# /home/ubuntu/lab_scheduler/src/routes/booking_routes.py

from flask import Blueprint, request, jsonify, current_app, Response, make_response
from src.extensions import db
from src.models.entities import Room, Booking
from datetime import datetime, date, time, timedelta, timezone
from collections import defaultdict
from flask_mail import Message # Import Message for Flask-Mail
# PDF Generation
from weasyprint import HTML, CSS
from jinja2 import Environment, FileSystemLoader
import os
# *** ADDED: Import joinedload for eager loading ***
from sqlalchemy.orm import joinedload
# *** ADDED: Import func for SQL functions ***
from sqlalchemy import func

bookings_bp = Blueprint("bookings_bp", __name__)

# --- MODIFICADO: Limite de 3 períodos por dia ---
MAX_BOOKINGS_PER_DAY = 3

# --- Booking Window Configuration (Ajustado para os horários corretos) ---
CUTOFF_WEEKDAY = 2 # Wednesday
# Use 21:00 UTC to represent 18:00 Brazil Time (UTC-3)
CUTOFF_TIME = time(21, 0, 0, tzinfo=timezone.utc)
RELEASE_WEEKDAY = 3 # Thursday (alterado de 4/Friday para 3/Thursday)
# Use 02:59 UTC (Friday) to represent 23:59 Brazil Time (Thursday UTC-3)
RELEASE_TIME = time(2, 59, 0, tzinfo=timezone.utc) # Alterado de 2:00 para 2:59
# ----------------------------------

# --- Admin Configuration ---
ADMIN_PASSWORD = "lab_scheduler_admin" # Default password, should be overridden in config
# ----------------------------------

# Helper function to get Monday of a week containing the given date
def get_monday_of_week(input_date):
    # weekday() returns 0 for Monday, 1 for Tuesday, etc.
    # If it's Sunday (6), we want the next day (Monday)
    if input_date.weekday() == 6:  # Sunday
        return input_date + timedelta(days=1)
    else:
        # For all other days, go back to Monday of the same week
        return input_date - timedelta(days=input_date.weekday())

# Helper function to send confirmation email
def send_booking_confirmation_email(user_email, user_name, coordinator_name, booked_slots_details):
    mail = current_app.extensions.get("mail")
    if not mail:
        current_app.logger.error("Flask-Mail not found. Email not sent.")
        return False
    if not booked_slots_details:
        current_app.logger.info("No booking details for email.")
        return False

    subject = "Confirmação de Agendamento de Laboratório"
    sender = current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@example.com")
    recipients = [user_email]

    # Using single quotes for the main f-string to allow double quotes inside HTML easily
    html_body = f'''<p>Olá {user_name},</p><p>Seu agendamento foi confirmado:</p><ul>'''
    for slot in booked_slots_details:
        booking_date_formatted = slot["booking_date"] # Use double quotes here, it's fine inside single-quoted f-string
        try:
            booking_date_formatted = datetime.strptime(slot["booking_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            pass
        # Use double quotes for dictionary keys inside single-quoted f-string
        html_body += f'''<li>Sala: {slot["room_name"]} - Data: {booking_date_formatted} - Período: {slot["period"]}</li>'''
    html_body += f'''</ul><p>Coordenador: {coordinator_name}</p><p>Obrigado!</p>'''

    msg = Message(subject, sender=sender, recipients=recipients)
    msg.html = html_body

    try:
        mail.send(msg)
        current_app.logger.info(f"Confirmation email sent to {user_email}")
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send email to {user_email}: {str(e)}")
        return False

# Helper function to check for conflicts
def check_booking_conflict(room_id, booking_date_obj, period):
    return Booking.query.filter_by(room_id=room_id, booking_date=booking_date_obj, period=period).first() is not None

# Helper function to check booking window rules (Reverted to block weekends)
def is_booking_allowed(booking_date_obj):
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date()
    
    # CORREÇÃO: Garantir que a semana sempre comece na segunda-feira
    start_of_current_week = get_monday_of_week(today_utc)
    start_of_next_week = start_of_current_week + timedelta(days=7) # Monday of next week
    end_of_current_week = start_of_current_week + timedelta(days=4) # Friday of current week
    end_of_next_week = start_of_next_week + timedelta(days=4) # Friday of next week

    # Cutoff for the *current* week is Wednesday 18:00 Brazil Time (21:00 UTC)
    cutoff_datetime_current_week = datetime.combine(start_of_current_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
    
    # Release for the *next* week is Thursday 23:59 Brazil Time (Friday 02:59 UTC)
    thursday_current_week = start_of_current_week + timedelta(days=RELEASE_WEEKDAY)
    release_datetime_for_next_week = datetime.combine(thursday_current_week, RELEASE_TIME)
    
    # Make time objects timezone-aware for comparison
    time_midnight_utc = time(0, 0, 0, tzinfo=timezone.utc)
    time_3am_utc = time(3, 0, 0, tzinfo=timezone.utc)
    # Compare RELEASE_TIME (aware) with aware time objects
    if RELEASE_TIME < time_midnight_utc or (RELEASE_TIME >= time_midnight_utc and RELEASE_TIME < time_3am_utc):
         release_datetime_for_next_week += timedelta(days=1)

    # Cutoff for the *next* week is Wednesday 18:00 Brazil Time (21:00 UTC) of that next week
    cutoff_datetime_next_week = datetime.combine(start_of_next_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)

    # Re-enable weekend check
    if booking_date_obj.weekday() >= 5:
        # Use double quotes for f-string, single quotes inside
        return False, f"Agendamentos só permitidos de Seg-Sex. Data: {booking_date_obj.strftime('%d/%m/%Y')} é fim de semana."
    
    # Removed past date check as requested by user
    # if booking_date_obj < today_utc:
    #     return False, f"Data de agendamento {booking_date_obj.strftime('%d/%m/%Y')} no passado."

    # Check booking date against windows (using Friday as end of week)
    if start_of_current_week <= booking_date_obj <= end_of_current_week: # Booking for current week (Mon-Fri)
        if now_utc >= cutoff_datetime_current_week:
            # Use double quotes for f-string, single quotes inside
            return False, f"Agendamento para semana atual ({start_of_current_week.strftime('%d/%m')}-{end_of_current_week.strftime('%d/%m')}) encerrou Qua 18:00 (Horário Local)."
        else:
            return True, "OK"
            
    elif start_of_next_week <= booking_date_obj <= end_of_next_week: # Booking for next week (Mon-Fri)
        if now_utc < release_datetime_for_next_week:
             # Use double quotes for f-string, single quotes inside
             return False, f"Agendamento para próxima semana ({start_of_next_week.strftime('%d/%m')}-{end_of_next_week.strftime('%d/%m')}) abre Qui 23:59 (Horário Local)."
        elif now_utc >= cutoff_datetime_next_week:
             # Use double quotes for f-string, single quotes inside
             return False, f"Agendamento para semana de {start_of_next_week.strftime('%d/%m')} já encerrou (Qua 18:00 Horário Local)."
        else:
             # It's after release time and before next week's cutoff
             return True, "OK"
             
    else: # Booking for weeks beyond the next one, or past weeks
        # Allow booking past dates based on previous user request
        if booking_date_obj < start_of_current_week:
             # Still need to check if the past date is a weekend
             if booking_date_obj.weekday() >= 5:
                 # Use double quotes for f-string, single quotes inside
                 return False, f"Agendamentos só permitidos de Seg-Sex. Data: {booking_date_obj.strftime('%d/%m/%Y')} é fim de semana."
             else:
                 return True, "OK" 
        else: # Booking for week after next or later
            # Use double quotes for f-string, single quotes inside
            return False, f"Só é possível agendar para semana atual ou próxima. Data: {booking_date_obj.strftime('%d/%m/%Y')} fora do período permitido."

@bookings_bp.route("/rooms", methods=["GET"])
def get_rooms():
    try:
        current_app.logger.debug("Fetching rooms...")
        rooms = Room.query.order_by(Room.id).all()
        room_list = [{"id": room.id, "name": room.name} for room in rooms]
        current_app.logger.debug(f"Rooms fetched: {len(room_list)}")
        return jsonify(room_list)
    except Exception as e:
        current_app.logger.error(f"Error fetching rooms: {str(e)}", exc_info=True)
        return jsonify({"error": "Erro ao buscar salas"}), 500

@bookings_bp.route("/bookings", methods=["POST"])
def create_booking():
    current_app.logger.debug("Received booking request")
    data = request.get_json()
    if not data:
        current_app.logger.warning("Invalid input for booking: No data")
        return jsonify({"error": "Invalid input"}), 400

    user_name = data.get("user_name")
    user_email = data.get("user_email")
    coordinator_name = data.get("coordinator_name")
    slots_data = data.get("slots")
    current_app.logger.debug(f"Booking request data: User={user_name}, Email={user_email}, Slots={len(slots_data) if slots_data else 0}")

    if not all([user_name, user_email, slots_data]):
        current_app.logger.warning("Missing required fields for booking")
        return jsonify({"error": "Campos obrigatórios: user_name, user_email, slots"}), 400
    if not isinstance(slots_data, list) or not slots_data:
        current_app.logger.warning("Slots data is not a non-empty list")
        return jsonify({"error": "Slots deve ser uma lista não vazia"}), 400
    if "@" not in user_email or "." not in user_email.split("@")[-1]:
        current_app.logger.warning(f"Invalid email format: {user_email}")
        return jsonify({"error": "Formato de email inválido"}), 400

    processed_slots = []

    try: # Wrap slot processing in try/except
        for slot_input in slots_data:
            room_id = slot_input.get("room_id")
            booking_date_str = slot_input.get("booking_date")
            period = slot_input.get("period")
            current_app.logger.debug(f"Processing slot: Room={room_id}, Date={booking_date_str}, Period={period}")

            if not all([room_id, booking_date_str, period]):
                current_app.logger.warning(f"Invalid slot data: {slot_input}")
                return jsonify({"error": f"Slot inválido: {slot_input}. Requer room_id, booking_date, period"}), 400
            if period not in ["Manhã", "Tarde"]:
                current_app.logger.warning(f"Invalid period: {period}")
                # Simplified f-string: double quotes outside, single quotes inside
                return jsonify({"error": f"Período inválido '{period}'. Use 'Manhã' ou 'Tarde'"}), 400
            try:
                booking_date_obj = datetime.strptime(booking_date_str, "%Y-%m-%d").date()
            except ValueError:
                current_app.logger.warning(f"Invalid date format: {booking_date_str}")
                # Simplified f-string: double quotes outside, single quotes inside
                return jsonify({"error": f"Formato de data inválido '{booking_date_str}'. Use YYYY-MM-DD"}), 400
            
            # Check booking window rules first
            current_app.logger.debug(f"Checking booking window for {booking_date_obj}")
            allowed, message = is_booking_allowed(booking_date_obj)
            if not allowed:
                current_app.logger.info(f"Booking denied for {booking_date_obj}: {message}")
                return jsonify({"error": message}), 400
            current_app.logger.debug(f"Booking window check passed for {booking_date_obj}")

            room = Room.query.get(room_id)
            if not room:
                current_app.logger.warning(f"Room ID not found: {room_id}")
                return jsonify({"error": f"Sala ID {room_id} não encontrada"}), 404
            
            processed_slots.append({
                "room_id": room_id, "room_name": room.name,
                "booking_date_obj": booking_date_obj, "booking_date_str": booking_date_str,
                "period": period
            })

        # --- MODIFICADO: Validação de salas Geral para permitir períodos diferentes no mesmo dia ---
        current_app.logger.debug("Validating Geral room limits - MODIFIED to allow different periods")
        # Agrupar slots de salas Geral por dia e período
        geral_slots_by_day_and_period = defaultdict(lambda: defaultdict(list))
        
        for slot in processed_slots:
            if slot["room_name"].startswith("Geral "):
                # Agrupar por dia e período
                geral_slots_by_day_and_period[slot["booking_date_obj"]][slot["period"]].append({
                    "room_id": slot["room_id"], 
                    "room_name": slot["room_name"]
                })
        
        # Verificar agendamentos existentes de salas Geral
        for booking_date_obj, periods_data in geral_slots_by_day_and_period.items():
            date_str = booking_date_obj.strftime('%Y-%m-%d')
            
            # Verificar agendamentos existentes para cada período
            for period, slots in periods_data.items():
                # Verificar se o usuário já tem agendamento para este período em outra sala Geral
                existing_geral_bookings = Booking.query.join(Room).filter(
                    Booking.user_name == user_name,
                    Booking.booking_date == booking_date_obj,
                    Booking.period == period,
                    Room.name.startswith("Geral ")
                ).all()
                
                # Se já existe agendamento para este período e estamos tentando agendar outra sala Geral
                if existing_geral_bookings and len(slots) > 0:
                    existing_room_names = [b.room.name for b in existing_geral_bookings]
                    current_app.logger.info(f"User {user_name} already has Geral room booking for {date_str}, {period}: {existing_room_names}")
                    return jsonify({"error": f"Você já possui agendamento para sala '{existing_room_names[0]}' no período da '{period}' em {date_str}."}), 409
                
                # Verificar se estamos tentando agendar mais de uma sala Geral no mesmo período
                if len(slots) > 1:
                    room_names = [s["room_name"] for s in slots]
                    current_app.logger.info(f"User {user_name} trying to book multiple Geral rooms in same period: {room_names}")
                    return jsonify({"error": f"Não é possível agendar mais de uma sala 'Geral' no mesmo período ('{period}') em {date_str}."}), 409
        
        current_app.logger.debug("Geral room validation passed")
        # --- Fim da validação modificada de salas Geral ---

        # Validation: Slot already taken (Keep this check)
        current_app.logger.debug("Checking for booking conflicts")
        for slot in processed_slots:
            # Use double quotes for dictionary keys inside single-quoted f-string
            if check_booking_conflict(slot["room_id"], slot["booking_date_obj"], slot["period"]):
                current_app.logger.info(f"Booking conflict found: Room {slot['room_id']}, Date {slot['booking_date_str']}, Period {slot['period']}")
                # Simplified f-string: double quotes outside, single quotes inside
                return jsonify({"error": f"Sala '{slot['room_name']}' já reservada para '{slot['period']}' em {slot['booking_date_str']}."}), 409
        current_app.logger.debug("Conflict check passed")
        
        # All validations passed, create bookings
        current_app.logger.debug("All validations passed, creating bookings")
        new_bookings = []
        booked_slots_details = []
        for slot in processed_slots:
            # Use double quotes for dictionary keys inside single-quoted f-string
            new_booking = Booking(
                user_name=user_name,
                user_email=user_email,
                coordinator_name=coordinator_name,
                room_id=slot["room_id"],
                booking_date=slot["booking_date_obj"],
                period=slot["period"]
            )
            db.session.add(new_booking)
            new_bookings.append(new_booking)
            booked_slots_details.append({
                "room_name": slot["room_name"],
                "booking_date": slot["booking_date_str"],
                "period": slot["period"]
            })
        
        # Commit to database
        try:
            db.session.commit()
            current_app.logger.info(f"Successfully created {len(new_bookings)} bookings for {user_name}")
            
            # Send confirmation email
            email_sent = send_booking_confirmation_email(user_email, user_name, coordinator_name, booked_slots_details)
            if not email_sent:
                current_app.logger.warning(f"Booking created but email not sent to {user_email}")
            
            return jsonify({"message": "Agendamento(s) criado(s) com sucesso", "email_sent": email_sent})
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Database error during booking commit: {str(e)}", exc_info=True)
            return jsonify({"error": "Erro ao salvar agendamento(s) no banco de dados"}), 500
            
    except Exception as e:
        current_app.logger.error(f"Unexpected error during booking processing: {str(e)}", exc_info=True)
        return jsonify({"error": "Falha ao processar ou criar agendamento(s) no servidor.", "details": str(e)}), 500

@bookings_bp.route("/bookings", methods=["GET"])
def get_bookings():
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    current_app.logger.debug(f"Fetching bookings from {start_date_str} to {end_date_str}")
    if not start_date_str or not end_date_str:
         current_app.logger.warning("Missing start_date or end_date for fetching bookings")
         return jsonify({"error": "Parâmetros start_date e end_date são obrigatórios"}), 400
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        
        # CORREÇÃO: Garantir que a data de início seja uma segunda-feira
        if start_date.weekday() != 0:  # Se não for segunda-feira
            start_date = get_monday_of_week(start_date)
            start_date_str = start_date.strftime("%Y-%m-%d")
            current_app.logger.debug(f"Adjusted start_date to Monday: {start_date_str}")
        
        current_app.logger.debug(f"Querying bookings between {start_date} and {end_date}")
        # *** CORRECTED: Use func.extract('dow', ...) for PostgreSQL compatibility ***
        query = Booking.query.options(joinedload(Booking.room)).filter(
            Booking.booking_date.between(start_date, end_date),
            func.extract('dow', Booking.booking_date).notin_([0, 6]) # Exclude Sunday (0) and Saturday (6)
        ).order_by(Booking.booking_date, Booking.room_id, Booking.period)
    except ValueError:
        current_app.logger.warning(f"Invalid date format for fetching bookings: {start_date_str} or {end_date_str}")
        return jsonify({"error": "Formato de data inválido para start_date ou end_date. Use YYYY-MM-DD"}), 400
    except Exception as e:
        current_app.logger.error(f"Error during booking query setup: {str(e)}", exc_info=True)
        return jsonify({"error": "Erro ao preparar consulta de agendamentos"}), 500
    
    try:
        # Execute query and get all results at once
        bookings = query.all()
        current_app.logger.debug(f"Found {len(bookings)} bookings for the period")
        result = []
        # Access related data *before* the session might close implicitly
        for booking in bookings:
            # Check if room was loaded correctly
            room_name = booking.room.name if booking.room else "Sala Desconhecida"
            if not booking.room:
                 current_app.logger.warning(f"Booking ID {booking.id} has no associated room!")
                 
            result.append({
                "id": booking.id, "user_name": booking.user_name, "user_email": booking.user_email,
                "coordinator_name": booking.coordinator_name, "room_id": booking.room_id,
                "room_name": room_name, # Use the loaded room name
                "booking_date": booking.booking_date.isoformat(),
                "period": booking.period, "created_at": booking.created_at.isoformat() if booking.created_at else None
            })
        current_app.logger.debug("Successfully processed booking results")
        return jsonify(result)
    except Exception as e:
        # Log the specific error, which might be the DetachedInstanceError (f405)
        current_app.logger.error(f"Error processing booking results (potentially accessing detached instance): {str(e)}", exc_info=True)
        return jsonify({"error": "Erro ao buscar ou processar agendamentos"}), 500

# Adjusted booking status endpoint (Reverted end dates to Friday) with Logging
@bookings_bp.route("/booking-status", methods=["GET"])
def get_booking_status():
    current_app.logger.debug("--- Entering get_booking_status --- ")
    try:
        now_utc = datetime.now(timezone.utc)
        today_utc = now_utc.date()
        current_app.logger.debug(f"Current UTC time: {now_utc}, Today UTC: {today_utc}")

        # CORREÇÃO: Garantir que a semana sempre comece na segunda-feira
        start_of_current_week = get_monday_of_week(today_utc)
        start_of_next_week = start_of_current_week + timedelta(days=7)
        end_of_current_week = start_of_current_week + timedelta(days=4) # Friday
        end_of_next_week = start_of_next_week + timedelta(days=4) # Friday
        
        current_app.logger.debug(f"Current week: {start_of_current_week} to {end_of_current_week}")
        current_app.logger.debug(f"Next week: {start_of_next_week} to {end_of_next_week}")

        cutoff_datetime_current_week = datetime.combine(start_of_current_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
        current_app.logger.debug(f"Current week cutoff UTC: {cutoff_datetime_current_week}")
        
        thursday_current_week = start_of_current_week + timedelta(days=RELEASE_WEEKDAY)
        release_datetime_for_next_week = datetime.combine(thursday_current_week, RELEASE_TIME)
        
        # Make time objects timezone-aware for comparison
        time_midnight_utc = time(0, 0, 0, tzinfo=timezone.utc)
        time_3am_utc = time(3, 0, 0, tzinfo=timezone.utc)
        # Compare RELEASE_TIME (aware) with aware time objects
        if RELEASE_TIME < time_midnight_utc or (RELEASE_TIME >= time_midnight_utc and RELEASE_TIME < time_3am_utc):
             release_datetime_for_next_week += timedelta(days=1)
        current_app.logger.debug(f"Next week release UTC (adjusted if needed): {release_datetime_for_next_week}")
             
        cutoff_datetime_next_week = datetime.combine(start_of_next_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
        current_app.logger.debug(f"Next week cutoff UTC: {cutoff_datetime_next_week}")

        current_week_open = now_utc < cutoff_datetime_current_week
        next_week_open = now_utc >= release_datetime_for_next_week and now_utc < cutoff_datetime_next_week
        current_app.logger.debug(f"Calculated status: current_week_open={current_week_open}, next_week_open={next_week_open}")
            
        response_data = {
            "current_week_start": start_of_current_week.isoformat(),
            "current_week_end": end_of_current_week.isoformat(), # Now ends on Friday
            "current_week_open": current_week_open,
            "current_week_cutoff": cutoff_datetime_current_week.isoformat(),
            "next_week_start": start_of_next_week.isoformat(),
            "next_week_end": end_of_next_week.isoformat(), # Now ends on Friday
            "next_week_open": next_week_open,
            "next_week_release": release_datetime_for_next_week.isoformat(), # New release time
            "server_time_utc": now_utc.isoformat()
        }
        
        # Verificar parâmetro de override para testes
        override = request.args.get('admin_override')
        if override == 'open_all' and request.args.get('password') == ADMIN_PASSWORD:
            current_app.logger.info("Admin override: Forçando abertura de ambas as semanas")
            response_data["current_week_open"] = True
            response_data["next_week_open"] = True
        elif override == 'open_current' and request.args.get('password') == ADMIN_PASSWORD:
            current_app.logger.info("Admin override: Forçando abertura da semana atual")
            response_data["current_week_open"] = True
        elif override == 'open_next' and request.args.get('password') == ADMIN_PASSWORD:
            current_app.logger.info("Admin override: Forçando abertura da próxima semana")
            response_data["next_week_open"] = True
        
        current_app.logger.debug(f"--- Exiting get_booking_status with data: {response_data} --- ")
        return jsonify(response_data)
        
    except Exception as e:
        current_app.logger.error(f"!!! Error in get_booking_status: {str(e)} !!!", exc_info=True)
        return jsonify({"error": "Erro interno ao calcular status do agendamento"}), 500

# --- PDF Generation Route (Reverted to 5 days) --- 
@bookings_bp.route("/generate-pdf", methods=["GET"])
def generate_schedule_pdf():
    week_start_date_str = request.args.get("week_start_date")
    current_app.logger.debug(f"Generating PDF for week starting: {week_start_date_str}")
    if not week_start_date_str:
        current_app.logger.warning("Missing week_start_date for PDF generation")
        return jsonify({"error": "Parâmetro week_start_date é obrigatório"}), 400
    
    try:
        week_start_date = datetime.strptime(week_start_date_str, "%Y-%m-%d").date()
        
        # CORREÇÃO: Garantir que a data de início seja uma segunda-feira
        if week_start_date.weekday() != 0:  # Se não for segunda-feira
            week_start_date = get_monday_of_week(week_start_date)
            week_start_date_str = week_start_date.isoformat()
            current_app.logger.debug(f"Adjusted PDF start date to Monday: {week_start_date_str}")
             
        week_end_date = week_start_date + timedelta(days=4) # Changed back to 4 for Friday
        week_end_date_str = week_end_date.isoformat()
        current_app.logger.debug(f"PDF date range: {week_start_date_str} to {week_end_date_str}")
    except ValueError:
        current_app.logger.warning(f"Invalid date format for PDF generation: {week_start_date_str}")
        return jsonify({"error": "Formato de data inválido para week_start_date. Use YYYY-MM-DD"}), 400
    except Exception as e:
        current_app.logger.error(f"Error processing PDF date parameters: {str(e)}", exc_info=True)
        return jsonify({"error": "Erro ao processar datas para PDF"}), 500

    try:
        # Fetch data for the specified week (Mon-Fri)
        current_app.logger.debug("Fetching rooms and bookings for PDF")
        rooms = Room.query.order_by(Room.id).all()
        # *** CORRECTED: Use func.extract('dow', ...) for PostgreSQL compatibility ***
        bookings_query = Booking.query.options(joinedload(Booking.room)).filter(
            Booking.booking_date.between(week_start_date, week_end_date),
            func.extract('dow', Booking.booking_date).notin_([0, 6]) # Exclude Sunday (0) and Saturday (6)
        ).order_by(Booking.booking_date, Booking.room_id, Booking.period)
        bookings = bookings_query.all()
        current_app.logger.debug(f"Found {len(bookings)} bookings for PDF week")
        
        # Prepare data for template
        schedule_data = defaultdict(lambda: defaultdict(lambda: {"Manhã": None, "Tarde": None}))
        for booking in bookings:
            # Check if room was loaded correctly
            room_name = booking.room.name if booking.room else "Sala Desconhecida"
            if not booking.room:
                 current_app.logger.warning(f"Booking ID {booking.id} has no associated room for PDF!")
            schedule_data[booking.room_id][booking.booking_date.isoformat()][booking.period] = booking.user_name
            
        dates_of_week = [(week_start_date + timedelta(days=i)).isoformat() for i in range(5)] # Changed back to 5 days
        days_locale = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"] # Reverted to 5 days
        
        # Setup Jinja2 environment
        template_dir = os.path.join(current_app.root_path, current_app.template_folder or "templates")
        env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
        
        # Add a date formatting filter
        def format_date_filter(date_str, fmt="%d/%m"):
            try:
                return datetime.strptime(date_str, "%Y-%m-%d").strftime(fmt)
            except:
                return date_str
        env.filters["format_date"] = format_date_filter
        
        # Render HTML template (Template itself needs update for 5 days)
        current_app.logger.debug("Rendering PDF HTML template")
        template = env.get_template("schedule_pdf_template.html") 
        html_string = template.render(
            rooms=rooms,
            dates_of_week=dates_of_week,
            days_locale=days_locale,
            schedule_data=schedule_data,
            week_start_date_formatted=week_start_date.strftime("%d/%m/%Y"),
            week_end_date_formatted=week_end_date.strftime("%d/%m/%Y")
        )
        
        # Generate PDF
        current_app.logger.debug("Generating PDF bytes using WeasyPrint")
        pdf_bytes = HTML(string=html_string).write_pdf() # Removed explicit CSS, assuming it's in template or default
        current_app.logger.debug("PDF generated successfully")
        
        # Create response
        response = make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"attachment; filename=escala_semana_{week_start_date_str}.pdf"
        
        return response

    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF para semana {week_start_date_str}: {str(e)}", exc_info=True)
        return jsonify({"error": "Falha ao gerar PDF no servidor", "details": str(e)}), 500

# --- Admin Route to Download Database --- 
@bookings_bp.route("/admin/download-database", methods=["GET"])
def download_database():
    password = request.args.get("password")
    correct_password = current_app.config.get("ADMIN_PASSWORD", ADMIN_PASSWORD) # Get from env or use default
    
    if password != correct_password:
        current_app.logger.warning("Unauthorized attempt to download database")
        return jsonify({"error": "Unauthorized"}), 401
        
    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI")
    if not db_uri or not db_uri.startswith("sqlite:///"):
        current_app.logger.error("Database download requested, but not using SQLite")
        return jsonify({"error": "Database download only supported for SQLite"}), 400
        
    db_path = db_uri.replace("sqlite:///", "")
    
    if not os.path.exists(db_path):
        current_app.logger.error(f"SQLite database file not found at: {db_path}")
        return jsonify({"error": "Database file not found"}), 404
        
    try:
        current_app.logger.info(f"Admin download of database file: {db_path}")
        return Response(
            open(db_path, "rb"),
            mimetype="application/vnd.sqlite3",
            headers={"Content-Disposition": "attachment;filename=lab_scheduler.db"}
        )
    except Exception as e:
        current_app.logger.error(f"Error serving database file: {str(e)}", exc_info=True)
        return jsonify({"error": "Error serving database file"}), 500

# --- NOVA ROTA: Admin Route to Clear Bookings ---
@bookings_bp.route("/admin/clear-bookings", methods=["POST"])
def clear_bookings():
    data = request.get_json()
    if not data:
        current_app.logger.warning("Invalid input for clear bookings: No data")
        return jsonify({"error": "Invalid input"}), 400
        
    password = data.get("password")
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    room_id = data.get("room_id")
    period = data.get("period")
    
    # Verificar senha
    correct_password = current_app.config.get("ADMIN_PASSWORD", ADMIN_PASSWORD) # Get from env or use default
    if password != correct_password:
        current_app.logger.warning("Unauthorized attempt to clear bookings")
        return jsonify({"error": "Senha administrativa incorreta"}), 401
    
    try:
        # Construir a query base
        query = Booking.query
        
        # Aplicar filtros se fornecidos
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                query = query.filter(Booking.booking_date.between(start_date, end_date))
                current_app.logger.info(f"Filtering bookings to clear by date range: {start_date} to {end_date}")
            except ValueError:
                current_app.logger.warning(f"Invalid date format for clear bookings: {start_date_str} or {end_date_str}")
                return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400
        elif start_date_str:
            try:
                single_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                query = query.filter(Booking.booking_date == single_date)
                current_app.logger.info(f"Filtering bookings to clear by single date: {single_date}")
            except ValueError:
                current_app.logger.warning(f"Invalid date format for clear bookings: {start_date_str}")
                return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400
                
        if room_id:
            query = query.filter(Booking.room_id == room_id)
            current_app.logger.info(f"Filtering bookings to clear by room_id: {room_id}")
            
        if period and period in ["Manhã", "Tarde"]:
            query = query.filter(Booking.period == period)
            current_app.logger.info(f"Filtering bookings to clear by period: {period}")
            
        # Contar e obter os agendamentos a serem excluídos
        bookings_to_delete = query.all()
        count = len(bookings_to_delete)
        
        if count == 0:
            current_app.logger.info("No bookings found matching criteria for deletion")
            return jsonify({"message": "Nenhum agendamento encontrado com os critérios especificados", "count": 0}), 200
            
        # Registrar detalhes dos agendamentos a serem excluídos (para log)
        booking_details = []
        for booking in bookings_to_delete:
            booking_details.append({
                "id": booking.id,
                "user_name": booking.user_name,
                "room_id": booking.room_id,
                "booking_date": booking.booking_date.isoformat(),
                "period": booking.period
            })
            
        # Excluir os agendamentos
        for booking in bookings_to_delete:
            db.session.delete(booking)
            
        db.session.commit()
        current_app.logger.info(f"Successfully deleted {count} bookings")
        
        return jsonify({
            "message": f"{count} agendamento(s) removido(s) com sucesso",
            "count": count,
            "details": booking_details
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing bookings: {str(e)}", exc_info=True)
        return jsonify({"error": f"Erro ao limpar agendamentos: {str(e)}"}), 500
# --- Fim da Nova Rota ---
