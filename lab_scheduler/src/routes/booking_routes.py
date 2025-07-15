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

@bookings_bp.route("/generate-pdf", methods=["GET"])
def generate_schedule_pdf():
    """Gera PDF da escala semanal com observações organizadas por usuário e observações gerais"""
    try:
        if not WEASYPRINT_AVAILABLE:
            current_app.logger.error("WeasyPrint não está disponível. Geração de PDF desabilitada.")
            return jsonify({"error": "WeasyPrint não está disponível. Geração de PDF desabilitada."}), 500
        
        # Obter parâmetros de data
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        
        if not start_date_str or not end_date_str:
            current_app.logger.error("start_date e end_date são obrigatórios para gerar PDF.")
            return jsonify({"error": "start_date e end_date são obrigatórios"}), 400
        
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            current_app.logger.error(f"Formato de data inválido: start_date={start_date_str}, end_date={end_date_str}")
            return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400
        
        # Buscar todas as salas do sistema e ordená-las
        all_rooms = Room.query.all()
        sorted_rooms = sort_rooms_custom(all_rooms)
        
        # Buscar TODOS os agendamentos no período (incluindo observações gerais)
        all_bookings = Booking.query.outerjoin(Room).filter(
            Booking.booking_date.between(start_date, end_date)
        ).order_by(Booking.booking_date, Booking.period).all()
        
        # --- INFO: Log de todos os bookings encontrados ---
        current_app.logger.info(f"INFO: Total de bookings encontrados para PDF: {len(all_bookings)}")
        for b in all_bookings:
            current_app.logger.info(f"INFO: Booking ID: {b.id}, User: {b.user_name}, Room: {b.room.name if b.room else 'N/A'}, Date: {b.booking_date}, Period: {b.period}, Obs: '{b.observation}'")
        # --- FIM INFO ---

        # Organizar dados por data e período para a tabela da escala
        schedule_data = defaultdict(lambda: defaultdict(list))
        user_observations = {}
        
        # Processar todos os agendamentos
        for booking in all_bookings:
            # Processar agendamentos normais para a tabela da escala
            # Apenas se tiver room_id (não é observação geral) e for dia útil
            if booking.room and booking.booking_date.weekday() < 5:
                date_str = booking.booking_date.strftime("%Y-%m-%d")
                
                # Adicionar à estrutura da escala
                schedule_data[date_str][booking.period].append({
                    "user_name": booking.user_name,
                    "coordinator_name": booking.coordinator_name,
                    "room_name": booking.room.name,
                    "observation": booking.observation
                })
            
            # Coletar todas as observações por usuário, incluindo as "Observação Geral"
            # Inicializar usuário se não existir
            if booking.user_name not in user_observations:
                user_observations[booking.user_name] = {
                    "email": booking.user_email,
                    "coordinator": booking.coordinator_name,
                    "bookings": [],
                    "has_observations": False # Flag para indicar se o usuário tem QUALQUER observação
                }
            
            # Adicionar o agendamento à lista do usuário
            # Para observações gerais, room_name será "Observação Geral"
            user_observations[booking.user_name]["bookings"].append({
                "room_name": booking.room.name if booking.room else "Observação Geral", # CORREÇÃO AQUI
                "date": booking.booking_date,
                "period": booking.period,
                "observation": booking.observation if booking.observation else ""
            })
            
            # Marcar se este usuário tem observações (incluindo as gerais)
            if booking.observation and booking.observation.strip():
                user_observations[booking.user_name]["has_observations"] = True
        
        # Filtrar apenas usuários que realmente têm observações (incluindo as gerais)
        filtered_user_observations = {
            user_name: user_data 
            for user_name, user_data in user_observations.items() 
            if user_data["has_observations"]
        }
        
        # Gerar lista de datas para os dias úteis da semana
        dates_of_week = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:  # Segunda a Sexta
                dates_of_week.append(current_date)
            current_date += timedelta(days=1)
        
        # Limitar a 5 dias úteis se necessário
        dates_of_week = dates_of_week[:5]

        # --- INFO: Log dos dados finais que serão passados para o template ---
        current_app.logger.info(f"INFO: Salas encontradas: {[room.name for room in sorted_rooms]}")
        current_app.logger.info(f"INFO: Datas da semana: {[d.strftime('%Y-%m-%d') for d in dates_of_week]}")
        current_app.logger.info(f"INFO: Dados da escala (schedule_data): {dict(schedule_data)}")
        current_app.logger.info(f"INFO: Observações de usuários (filtered_user_observations): {len(filtered_user_observations)} usuários com observações")
        for user_name, user_data in filtered_user_observations.items():
            current_app.logger.info(f"  INFO: Usuário {user_name}: {len(user_data['bookings'])} agendamentos")
            for booking in user_data['bookings']:
                if booking['observation']:
                    current_app.logger.info(f"    INFO: Agendamento com observação: {booking['room_name']} ({booking['date']}, {booking['period']}): '{booking['observation']}'")
        # --- FIM INFO ---
        
        # Obter timestamp atual para o cabeçalho
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_brasilia = now_utc.astimezone(BRASILIA_TZ)
        
        # Renderizar template HTML
        html_content = render_template(
            "schedule_pdf_template.html",
            schedule_data=dict(schedule_data),
            user_observations=filtered_user_observations,
            general_observations=[], # Passar vazio, pois agora tudo está em user_observations
            start_date=start_date,
            end_date=end_date,
            generated_at=now_brasilia,
            dates_of_week=dates_of_week,
            all_rooms=sorted_rooms,
            timedelta=timedelta
        )
        # Gerar PDF
        pdf = HTML(string=html_content).write_pdf()
        
        # Criar resposta
        response = make_response(pdf)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"attachment; filename=escala_{start_date_str}_a_{end_date_str}.pdf"
        
        return response
        
    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {str(e)}", exc_info=True)
        return jsonify({"error": "Erro ao gerar PDF", "details": str(e)}), 500

