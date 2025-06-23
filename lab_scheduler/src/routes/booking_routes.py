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
import re

bookings_bp = Blueprint("bookings_bp", __name__)

MAX_BOOKINGS_PER_DAY = 3

# --- Booking Window Configuration (Adjusted) ---
CUTOFF_WEEKDAY = 2 # Wednesday
# Use 21:00 UTC to represent 18:00 Brazil Time (UTC-3)
CUTOFF_TIME = time(21, 0, 0, tzinfo=timezone.utc)
RELEASE_WEEKDAY = 3 # Thursday
# Use 02:59 UTC (Friday) to represent 23:59 Brazil Time (Thursday UTC-3)
RELEASE_TIME = time(2, 59, 0, tzinfo=timezone.utc)
# ----------------------------------

# Função para ordenar salas de forma personalizada
def custom_room_sort_key(room):
    """
    Função para ordenar salas de forma personalizada:
    1. Salas "Geral" em ordem numérica (1-12)
    2. Outras salas em ordem alfabética
    """
    if room.name.startswith("Geral "):
        # Extrair o número após "Geral "
        try:
            number = int(re.search(r'Geral (\d+)', room.name).group(1))
            # Retornar uma tupla com 0 (para priorizar salas Geral) e o número
            return (0, number)
        except (ValueError, IndexError, AttributeError):
            # Se não conseguir extrair um número, usar valor alto
            return (0, 999)
    else:
        # Para salas não-Geral, usar 1 (para colocar após as salas Geral) e o nome
        return (1, room.name)

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

    html_body = f"""<p>Olá {user_name},</p><p>Seu agendamento foi confirmado:</p><ul>"""
    for slot in booked_slots_details:
        booking_date_formatted = slot["booking_date"]
        try:
            booking_date_formatted = datetime.strptime(slot["booking_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            pass
        # Use single quotes inside the f-string for dictionary keys
        html_body += f"<li>Sala: {slot['room_name']} - Data: {booking_date_formatted} - Período: {slot['period']}</li>"
    html_body += f"</ul><p>Coordenador: {coordinator_name}</p><p>Obrigado!</p>"""

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
    start_of_current_week = today_utc - timedelta(days=today_utc.weekday()) # Monday of current week
    start_of_next_week = start_of_current_week + timedelta(days=7) # Monday of next week
    end_of_current_week = start_of_current_week + timedelta(days=4) # Friday of current week (Reverted)
    end_of_next_week = start_of_next_week + timedelta(days=4) # Friday of next week (Reverted)

    # Cutoff for the *current* week is Wednesday 18:00 Brazil Time (21:00 UTC)
    cutoff_datetime_current_week = datetime.combine(start_of_current_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
    
    # Release for the *next* week is Thursday 23:59 Brazil Time (Friday 02:59 UTC)
    thursday_current_week = start_of_current_week + timedelta(days=RELEASE_WEEKDAY)
    release_datetime_for_next_week = datetime.combine(thursday_current_week, RELEASE_TIME)
    if RELEASE_TIME < time(0,0,0) or (RELEASE_TIME > time(0,0,0) and RELEASE_TIME < time(3,0,0)):
         release_datetime_for_next_week += timedelta(days=1)

    # Cutoff for the *next* week is Wednesday 18:00 Brazil Time (21:00 UTC) of that next week
    cutoff_datetime_next_week = datetime.combine(start_of_next_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)

    # Re-enable weekend check
    if booking_date_obj.weekday() >= 5:
        return False, f"Agendamentos só permitidos de Seg-Sex. Data: {booking_date_obj.strftime('%d/%m/%Y')} é fim de semana."
    
    # Removed past date check as requested by user
    # if booking_date_obj < today_utc:
    #     return False, f"Data de agendamento {booking_date_obj.strftime('%d/%m/%Y')} no passado."

    # Check booking date against windows (using Friday as end of week)
    if start_of_current_week <= booking_date_obj <= end_of_current_week: # Booking for current week (Mon-Fri)
        if now_utc >= cutoff_datetime_current_week:
            return False, f"Agendamento para semana atual ({start_of_current_week.strftime('%d/%m')}-{end_of_current_week.strftime('%d/%m')}) encerrou Qua 18:00 (Horário Local)."
        else:
            return True, "OK"
            
    elif start_of_next_week <= booking_date_obj <= end_of_next_week: # Booking for next week (Mon-Fri)
        if now_utc < release_datetime_for_next_week:
             return False, f"Agendamento para próxima semana ({start_of_next_week.strftime('%d/%m')}-{end_of_next_week.strftime('%d/%m')}) abre Qui 23:59 (Horário Local)."
        elif now_utc >= cutoff_datetime_next_week:
             return False, f"Agendamento para semana de {start_of_next_week.strftime('%d/%m')} já encerrou (Qua 18:00 Horário Local)."
        else:
             # It's after release time and before next week's cutoff
             return True, "OK"
             
    else: # Booking for weeks beyond the next one, or past weeks
        # Allow booking past dates based on previous user request
        if booking_date_obj < start_of_current_week:
             # Still need to check if the past date is a weekend
             if booking_date_obj.weekday() >= 5:
                 return False, f"Agendamentos só permitidos de Seg-Sex. Data: {booking_date_obj.strftime('%d/%m/%Y')} é fim de semana."
             else:
                 return True, "OK" 
        else: # Booking for week after next or later
            return False, f"Só é possível agendar para semana atual ou próxima. Data: {booking_date_obj.strftime('%d/%m/%Y')} fora do período permitido."

@bookings_bp.route("/rooms", methods=["GET"])
def get_rooms():
    try:
        rooms = Room.query.all()
        # Ordenar as salas usando a função de ordenação personalizada
        rooms.sort(key=custom_room_sort_key)
        room_list = [{"id": room.id, "name": room.name} for room in rooms]
        return jsonify(room_list)
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar salas: {str(e)}")
        return jsonify({"error": "Erro ao buscar salas"}), 500

@bookings_bp.route("/bookings", methods=["POST"])
def create_booking():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid input"}), 400

    user_name = data.get("user_name")
    user_email = data.get("user_email")
    coordinator_name = data.get("coordinator_name")
    slots_data = data.get("slots")

    if not all([user_name, user_email, slots_data]):
        return jsonify({"error": "Campos obrigatórios: user_name, user_email, slots"}), 400
    if not isinstance(slots_data, list) or not slots_data:
        return jsonify({"error": "Slots deve ser uma lista não vazia"}), 400
    if "@" not in user_email or "." not in user_email.split("@")[-1]:
        return jsonify({"error": "Formato de email inválido"}), 400

    processed_slots = []
    daily_new_bookings_count = defaultdict(int)

    for slot_input in slots_data:
        room_id = slot_input.get("room_id")
        booking_date_str = slot_input.get("booking_date")
        period = slot_input.get("period")

        if not all([room_id, booking_date_str, period]):
            # Use single quotes for keys inside f-string
            return jsonify({"error": f"Slot inválido: {slot_input}. Requer room_id, booking_date, period"}), 400
        if period not in ["Manhã", "Tarde"]:
            # Use single quotes for literals inside f-string
            return jsonify({"error": f"Período inválido '{period}'. Use 'Manhã' ou 'Tarde'"}), 400
        try:
            booking_date_obj = datetime.strptime(booking_date_str, "%Y-%m-%d").date()
        except ValueError:
            # Use single quotes for literals inside f-string
            return jsonify({"error": f"Formato de data inválido '{booking_date_str}'. Use YYYY-MM-DD"}), 400
        
        # Check booking window rules first (now includes weekend check)
        allowed, message = is_booking_allowed(booking_date_obj)
        if not allowed:
            return jsonify({"error": message}), 400

        room = Room.query.get(room_id)
        if not room:
            return jsonify({"error": f"Sala ID {room_id} não encontrada"}), 404
        
        processed_slots.append({
            "room_id": room_id, "room_name": room.name,
            "booking_date_obj": booking_date_obj, "booking_date_str": booking_date_str,
            "period": period
        })
        daily_new_bookings_count[booking_date_obj] += 1

    # --- Validation: Limit "Geral" room bookings per day per user based on periods --- 
    geral_slots_in_request_by_day = defaultdict(list)
    for slot in processed_slots:
        if slot["room_name"].startswith("Geral "):
            geral_slots_in_request_by_day[slot["booking_date_obj"]].append(
                {"room_id": slot["room_id"], "period": slot["period"]}
            )

    for booking_date_obj, requested_geral_slots in geral_slots_in_request_by_day.items():
        # Fetch existing Geral bookings for this user on this day
        existing_geral_bookings = Booking.query.join(Room).filter(
            Booking.user_name == user_name,
            Booking.booking_date == booking_date_obj,
            Room.name.startswith("Geral ")
        ).all()

        combined_geral_slots = []
        # Add existing bookings
        for booking in existing_geral_bookings:
            combined_geral_slots.append({"room_id": booking.room_id, "period": booking.period})
        # Add requested slots (avoiding duplicates if re-requesting same slot)
        existing_tuples = {(b.room_id, b.period) for b in existing_geral_bookings}
        for req_slot in requested_geral_slots:
             if (req_slot["room_id"], req_slot["period"]) not in existing_tuples:
                 combined_geral_slots.append(req_slot)

        geral_periods_booked = {slot["period"] for slot in combined_geral_slots}
        geral_rooms_booked_ids = {slot["room_id"] for slot in combined_geral_slots}

        num_geral_periods = len(geral_periods_booked)
        num_geral_rooms = len(geral_rooms_booked_ids)

        if num_geral_periods > 2:
            return jsonify({"error": f"Não é possível agendar mais de dois períodos ("Manhã" e "Tarde") em salas "Geral" no mesmo dia ({booking_date_obj.strftime(\"%Y-%m-%d\")})."}), 409

        if num_geral_periods == 2 and num_geral_rooms > 2:
             # This case implies booking 2 periods across 3+ different Geral rooms
             return jsonify({"error": f"Não é possível agendar mais de duas salas "Geral" diferentes no mesmo dia ({booking_date_obj.strftime(\"%Y-%m-%d\")})."}), 409
        
        # Also check if trying to book a third Geral room even if only one period is used so far
        if num_geral_periods == 1 and num_geral_rooms > 2:
             return jsonify({"error": f"Não é possível agendar mais de duas salas \"Geral\" diferentes no mesmo dia ({booking_date_obj.strftime(\"%Y-%m-%d\")})."}), 409

    # --- End of Geral Validation ---

    # Validation: Slot already taken (Keep this check)
    for slot in processed_slots:
        if check_booking_conflict(slot["room_id"], slot["booking_date_obj"], slot["period"]):
            # Use single quotes for literals inside f-string
            return jsonify({"error": f"Sala '{slot['room_name']}' já reservada para '{slot['period']}' em {slot['booking_date_str']}."}), 409
    
    newly_created_bookings_details_for_email = []
    try:
        for slot in processed_slots:
            new_booking = Booking(
                user_name=user_name, user_email=user_email, coordinator_name=coordinator_name,
                room_id=slot["room_id"], booking_date=slot["booking_date_obj"], period=slot["period"]
            )
            db.session.add(new_booking)
            # Use single quotes for keys inside f-string
            newly_created_bookings_details_for_email.append({
                "room_name": slot["room_name"], "booking_date": slot["booking_date_str"], "period": slot["period"]
            })
        db.session.commit()
        email_sent_successfully = send_booking_confirmation_email(user_email, user_name, coordinator_name, newly_created_bookings_details_for_email)
        response_message = "Agendamento(s) criado(s) com sucesso!"
        if not email_sent_successfully:
            response_message += " (Falha ao enviar e-mail de confirmação.)"
        return jsonify({"message": response_message, "bookings_created": newly_created_bookings_details_for_email}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Falha ao criar agendamento(s): {str(e)}")
        return jsonify({"error": "Falha ao criar agendamento(s) no servidor.", "details": str(e)}), 500

@bookings_bp.route("/bookings", methods=["GET"])
def get_bookings():
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    if not start_date_str or not end_date_str:
         return jsonify({"error": "Parâmetros start_date e end_date são obrigatórios"}), 400
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        # Query only Mon-Fri
        query = Booking.query.join(Room).filter(
            Booking.booking_date.between(start_date, end_date),
            Booking.booking_date.op("strftime")("%w").notin_(["0", "6"]) # Exclude Sunday (0) and Saturday (6)
        ).order_by(Booking.booking_date, Room.id, Booking.period)
    except ValueError:
        return jsonify({"error": "Formato de data inválido para start_date ou end_date. Use YYYY-MM-DD"}), 400
    
    bookings = query.all()
    result = []
    for booking in bookings:
        result.append({
            "id": booking.id, "user_name": booking.user_name, "user_email": booking.user_email,
            "coordinator_name": booking.coordinator_name, "room_id": booking.room_id,
            "room_name": booking.room.name, "booking_date": booking.booking_date.isoformat(),
            "period": booking.period, "created_at": booking.created_at.isoformat() if booking.created_at else None
        })
    return jsonify(result)

# Adjusted booking status endpoint (Reverted end dates to Friday)
@bookings_bp.route("/booking-status", methods=["GET"])
def get_booking_status():
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date()
    start_of_current_week = today_utc - timedelta(days=today_utc.weekday())
    start_of_next_week = start_of_current_week + timedelta(days=7)
    end_of_current_week = start_of_current_week + timedelta(days=4) # Friday (Reverted)
    end_of_next_week = start_of_next_week + timedelta(days=4) # Friday (Reverted)

    cutoff_datetime_current_week = datetime.combine(start_of_current_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
    
    thursday_current_week = start_of_current_week + timedelta(days=RELEASE_WEEKDAY)
    release_datetime_for_next_week = datetime.combine(thursday_current_week, RELEASE_TIME)
    if RELEASE_TIME < time(0,0,0) or (RELEASE_TIME > time(0,0,0) and RELEASE_TIME < time(3,0,0)):
         release_datetime_for_next_week += timedelta(days=1)
    
    cutoff_datetime_next_week = datetime.combine(start_of_next_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
    
    # Determine if current week is open for booking
    current_week_open = now_utc < cutoff_datetime_current_week
    
    # Determine if next week is open for booking
    next_week_open = now_utc >= release_datetime_for_next_week and now_utc < cutoff_datetime_next_week
    
    # Format dates for display
    current_week_range = f"{start_of_current_week.strftime('%d/%m')} - {end_of_current_week.strftime('%d/%m')}"
    next_week_range = f"{start_of_next_week.strftime('%d/%m')} - {end_of_next_week.strftime('%d/%m')}"
    
    # Hardcoded display times (local Brazil Time)
    display_cutoff_time = "18:00"
    display_release_time = "23:59"
    cutoff_day_display = "Quarta-feira" # Display Wednesday for cutoff
    release_day_display = "Quinta-feira" # Display Thursday for release
    
    response_data = {
        "current_week_open": current_week_open,
        "next_week_open": next_week_open,
        "current_week_range": current_week_range,
        "next_week_range": next_week_range,
        "cutoff_day": cutoff_day_display,
        "cutoff_time": display_cutoff_time,
        "release_day": release_day_display,
        "release_time": display_release_time
    }
    
    # Verificar parâmetro de override para testes
    override = request.args.get('admin_override')
    if override == 'open_all' and request.args.get('password') == 'lab_scheduler_admin':
        current_app.logger.info("Admin override: Forçando abertura de ambas as semanas")
        response_data["current_week_open"] = True
        response_data["next_week_open"] = True
    elif override == 'open_current' and request.args.get('password') == 'lab_scheduler_admin':
        current_app.logger.info("Admin override: Forçando abertura da semana atual")
        response_data["current_week_open"] = True
    elif override == 'open_next' and request.args.get('password') == 'lab_scheduler_admin':
        current_app.logger.info("Admin override: Forçando abertura da próxima semana")
        response_data["next_week_open"] = True
    
    return jsonify(response_data)

# Rota administrativa para limpar agendamentos
ADMIN_PASSWORD = "lab_scheduler_admin"

@bookings_bp.route("/admin/clear-bookings", methods=["POST"])
def clear_bookings():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid input"}), 400
    
    password = data.get("password")
    if password != ADMIN_PASSWORD:
        return jsonify({"error": "Senha administrativa incorreta"}), 401
    
    # Parâmetros opcionais para filtragem
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    room_id = data.get("room_id")
    period = data.get("period")
    
    # Construir a query base
    query = Booking.query
    
    # Aplicar filtros se fornecidos
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            if end_date_str:
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                query = query.filter(Booking.booking_date.between(start_date, end_date))
            else:
                query = query.filter(Booking.booking_date == start_date)
        except ValueError:
            return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400
    
    if room_id:
        query = query.filter(Booking.room_id == room_id)
    
    if period:
        if period not in ["Manhã", "Tarde"]:
            return jsonify({"error": "Período inválido. Use 'Manhã' ou 'Tarde'"}), 400
        query = query.filter(Booking.period == period)
    
    # Obter os agendamentos a serem removidos para log
    bookings_to_remove = query.all()
    booking_details = []
    
    for booking in bookings_to_remove:
        room = Room.query.get(booking.room_id)
        booking_details.append({
            "id": booking.id,
            "user_name": booking.user_name,
            "room_name": room.name if room else f"Sala ID {booking.room_id}",
            "booking_date": booking.booking_date.strftime("%Y-%m-%d"),
            "period": booking.period
        })
    
    # Remover os agendamentos
    count = query.delete()
    db.session.commit()
    
    return jsonify({
        "message": f"{count} agendamento(s) removido(s) com sucesso",
        "count": count,
        "details": booking_details
    })

# PDF Generation
@bookings_bp.route("/generate-schedule-pdf", methods=["GET"])
def generate_schedule_pdf():
    start_date_str = request.args.get("start_date")
    if not start_date_str:
        return jsonify({"error": "Parâmetro start_date é obrigatório"}), 400
    
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        # Ensure start_date is a Monday
        if start_date.weekday() != 0:
            # Adjust to previous Monday
            start_date = start_date - timedelta(days=start_date.weekday())
        
        # End date is Friday of the same week
        end_date = start_date + timedelta(days=4)
        
        # Query only Mon-Fri
        bookings = Booking.query.join(Room).filter(
            Booking.booking_date.between(start_date, end_date),
            Booking.booking_date.op("strftime")("%w").notin_(["0", "6"]) # Exclude Sunday (0) and Saturday (6)
        ).order_by(Booking.booking_date, Room.name, Booking.period).all()
        
        # Get all rooms
        rooms = Room.query.all()
        # Ordenar as salas usando a função de ordenação personalizada
        rooms.sort(key=custom_room_sort_key)
        
        # Organize bookings by date, room, and period
        schedule_data = {}
        for booking in bookings:
            date_str = booking.booking_date.strftime("%Y-%m-%d")
            if date_str not in schedule_data:
                schedule_data[date_str] = {
                    "date_display": booking.booking_date.strftime("%d/%m/%Y"),
                    "weekday": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"][booking.booking_date.weekday()],
                    "rooms": {}
                }
            
            if booking.room_id not in schedule_data[date_str]["rooms"]:
                schedule_data[date_str]["rooms"][booking.room_id] = {
                    "name": booking.room.name,
                    "morning": None,
                    "afternoon": None
                }
            
            if booking.period == "Manhã":
                schedule_data[date_str]["rooms"][booking.room_id]["morning"] = {
                    "user": booking.user_name,
                    "coordinator": booking.coordinator_name
                }
            else:  # "Tarde"
                schedule_data[date_str]["rooms"][booking.room_id]["afternoon"] = {
                    "user": booking.user_name,
                    "coordinator": booking.coordinator_name
                }
        
        # Sort dates
        sorted_dates = sorted(schedule_data.keys())
        
        # Prepare data for template
        template_data = {
            "week_range": f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}",
            "dates": [schedule_data[date] for date in sorted_dates],
            "rooms": [{"id": room.id, "name": room.name} for room in rooms]
        }
        
        # Load template
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template('schedule_pdf_template.html')
        
        # Render HTML
        html_content = template.render(**template_data)
        
        # Generate PDF
        pdf = HTML(string=html_content).write_pdf()
        
        # Create response
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=escala_{start_date_str}_{end_date.strftime("%Y-%m-%d")}.pdf'
        
        return response
        
    except ValueError:
        return jsonify({"error": "Formato de data inválido para start_date. Use YYYY-MM-DD"}), 400
    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {str(e)}")
        return jsonify({"error": "Erro ao gerar PDF", "details": str(e)}), 500

# Helper function to get Monday of a week
def get_monday_of_week(date_obj):
    """Return the Monday of the week for the given date."""
    return date_obj - timedelta(days=date_obj.weekday())
