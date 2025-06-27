from flask import Blueprint, request, jsonify, current_app, render_template, make_response
from src.extensions import db
from src.models.entities import Room, Booking
from datetime import datetime, date, timedelta
from collections import defaultdict
from flask_mail import Message
from weasyprint import HTML
import re

bookings_bp = Blueprint("bookings_bp", __name__)

MAX_BOOKINGS_PER_DAY = 3

# Helper function to send confirmation email
def send_booking_confirmation_email(user_email, user_name, coordinator_name, observation, booked_slots_details):
    mail = current_app.extensions.get("mail")
    if not mail:
        current_app.logger.error("Flask-Mail (mail object) not found in current_app.extensions. Email not sent.")
        return False
        
    if not booked_slots_details:
        current_app.logger.info("No booking details to send in email.")
        return False

    subject = "Confirmação de Agendamento de Laboratório"
    sender = current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@example.com")
    recipients = [user_email]

    html_body = f"""\
    <p>Olá {user_name},</p>
    <p>Seu agendamento de laboratório foi confirmado com sucesso. Detalhes abaixo:</p>
    <ul>
    """
    for slot in booked_slots_details:
        booking_date_formatted = slot["booking_date"]
        if isinstance(slot["booking_date"], date):
            booking_date_formatted = slot["booking_date"].strftime("%d/%m/%Y")
        elif isinstance(slot["booking_date"], str):
            try:
                booking_date_formatted = datetime.strptime(slot["booking_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                pass

        html_body += f"<li>Sala: {slot['room_name']} - Data: {booking_date_formatted} - Período: {slot['period']}</li>"
    
    html_body += "</ul>"
    if coordinator_name:
        html_body += f"<p>Coordenador: {coordinator_name}</p>"
    if observation:
        html_body += f"<p>Observação: {observation}</p>"
    html_body += "<p>Obrigado!</p>"

    msg = Message(subject, sender=sender, recipients=recipients)
    msg.html = html_body

    try:
        mail.send(msg)
        current_app.logger.info(f"Email de confirmação enviado para {user_email}")
        return True
    except Exception as e:
        current_app.logger.error(f"Falha ao enviar email para {user_email}: {str(e)}")
        return False

# Helper function to check for conflicts
def check_booking_conflict(room_id, booking_date_obj, period):
    existing_booking = Booking.query.filter_by(
        room_id=room_id,
        booking_date=booking_date_obj,
        period=period
    ).first()
    return existing_booking is not None

# Helper function to sort rooms with custom logic for "Geral" rooms
def sort_rooms_custom(rooms):
    """Ordena salas colocando as 'Geral' em ordem numérica correta"""
    def room_sort_key(room):
        name = room.name
        # Se é uma sala "Geral", extrair o número para ordenação correta
        if name.startswith("Geral "):
            try:
                number = int(re.findall(r'\d+', name)[0])
                return (0, number)  # Prioridade 0 para salas Geral, ordenadas por número
            except (IndexError, ValueError):
                return (0, 999)  # Se não conseguir extrair número, coloca no final das Geral
        else:
            # Para outras salas, usar o ID original
            return (1, room.id)
    
    return sorted(rooms, key=room_sort_key)

@bookings_bp.route("/rooms", methods=["GET"])
def get_rooms():
    rooms = Room.query.all()
    sorted_rooms = sort_rooms_custom(rooms)
    return jsonify([{"id": room.id, "name": room.name} for room in sorted_rooms])

@bookings_bp.route("/bookings", methods=["POST"])
def create_booking():
    data = request.get_json()
    if not data:
        current_app.logger.debug("create_booking: No JSON data received.")
        return jsonify({"error": "Invalid input"}), 400

    user_name = data.get("user_name")
    user_email = data.get("user_email")
    coordinator_name = data.get("coordinator_name")
    observation = data.get("observation", "")
    slots_data = data.get("slots")

    current_app.logger.debug(f"create_booking: Received data for user {user_name}, email {user_email}, slots: {slots_data}")

    if not all([user_name, user_email, slots_data]):
        current_app.logger.debug("create_booking: Missing required fields.")
        return jsonify({"error": "Missing fields. Required: user_name, user_email, slots"}), 400
    
    if not isinstance(slots_data, list) or not slots_data:
        current_app.logger.debug("create_booking: Slots must be a non-empty list.")
        return jsonify({"error": "Slots must be a non-empty list"}), 400

    if "@" not in user_email or "." not in user_email.split("@")[-1]:
        current_app.logger.debug(f"create_booking: Invalid email format for {user_email}.")
        return jsonify({"error": "Invalid email format"}), 400

    processed_slots = []
    daily_new_bookings_count = defaultdict(int)

    for slot_input in slots_data:
        room_id = slot_input.get("room_id")
        booking_date_str = slot_input.get("booking_date")
        period = slot_input.get("period")

        if not all([room_id, booking_date_str, period]):
            current_app.logger.debug(f"create_booking: Invalid slot data: {slot_input}. Missing room_id, booking_date, or period.")
            return jsonify({"error": f"Invalid slot data: {slot_input}. Each slot needs room_id, booking_date, period"}), 400
        if period not in ["Manhã", "Tarde"]:
            current_app.logger.debug(f"create_booking: Invalid period '{period}' in slot: {slot_input}.")
            return jsonify({"error": f"Invalid period '{period}' in slot: {slot_input}. Must be 'Manhã' or 'Tarde'"}), 400
        try:
            booking_date_obj = datetime.strptime(booking_date_str, "%Y-%m-%d").date()
        except ValueError:
            current_app.logger.debug(f"create_booking: Invalid date format '{booking_date_str}' in slot: {slot_input}.")
            return jsonify({"error": f"Invalid date format '{booking_date_str}' in slot: {slot_input}. Use YYYY-MM-DD"}), 400
        
        # Use datetime.utcnow().date() for consistency with frontend UTC logic
        if booking_date_obj < datetime.utcnow().date():
            current_app.logger.debug(f"create_booking: Booking date {booking_date_str} in slot: {slot_input} is in the past (UTC: {datetime.utcnow().date()}).")
            return jsonify({"error": f"Booking date {booking_date_str} in slot: {slot_input} cannot be in the past"}), 400
        
        if booking_date_obj.weekday() >= 5: # 5 is Saturday, 6 is Sunday
            current_app.logger.debug(f"create_booking: Booking date {booking_date_str} in slot: {slot_input} is not a weekday.")
            return jsonify({"error": f"Bookings for date {booking_date_str} in slot: {slot_input} are only allowed on weekdays (Mon-Fri)"}), 400
        
        room = Room.query.get(room_id)
        if not room:
            current_app.logger.debug(f"create_booking: Room ID {room_id} in slot: {slot_input} not found.")
            return jsonify({"error": f"Room ID {room_id} in slot: {slot_input} not found"}), 404
        
        processed_slots.append({
            "room_id": room_id, "room_name": room.name,
            "booking_date_obj": booking_date_obj, "booking_date_str": booking_date_str,
            "period": period
        })
        daily_new_bookings_count[booking_date_obj] += 1

    # Validation for max 3 bookings per day per user
    for booking_date_obj, count_for_this_request in daily_new_bookings_count.items():
        existing_bookings_on_day = Booking.query.filter_by(user_name=user_name, booking_date=booking_date_obj).count()
        current_app.logger.debug(f"create_booking: User {user_name} has {existing_bookings_on_day} existing bookings on {booking_date_obj}. Request adds {count_for_this_request}.")
        if (existing_bookings_on_day + count_for_this_request) > MAX_BOOKINGS_PER_DAY:
            current_app.logger.debug(f"create_booking: Max bookings per day exceeded for user {user_name} on {booking_date_obj}.")
            return jsonify({
                "error": f"Limite de {MAX_BOOKINGS_PER_DAY} agendamentos por dia para o usuário '{user_name}' seria excedido no dia {booking_date_obj.strftime('%Y-%m-%d')}."
            }), 409

    # Validation for "Geral" rooms - only one per period per day per user
    for booking_date_obj, _ in daily_new_bookings_count.items():
        geral_periods_in_request = defaultdict(list)
        
        # Agrupar salas "Geral" por período neste request
        for slot in processed_slots:
            if slot['booking_date_obj'] == booking_date_obj and slot['room_name'].startswith("Geral "):
                geral_periods_in_request[slot['period']].append(slot['room_name'])
        
        # Verificar se há mais de uma sala "Geral" no mesmo período
        for period, geral_rooms in geral_periods_in_request.items():
            if len(geral_rooms) > 1:
                current_app.logger.debug(f"create_booking: Multiple 'Geral' rooms requested for period '{period}' on {booking_date_obj}.")
                return jsonify({
                    "error": f"Você só pode agendar uma sala da categoria 'Geral' por período. Tentativa de agendar múltiplas salas 'Geral' no período '{period}' do dia {booking_date_obj.strftime('%Y-%m-%d')}."
                }), 409
            
            # Verificar se já existe agendamento de sala "Geral" para este usuário neste período
            existing_geral_booking = Booking.query.join(Room).filter(
                Booking.user_name == user_name,
                Booking.booking_date == booking_date_obj,
                Booking.period == period,
                Room.name.startswith("Geral ")
            ).first()
            
            if existing_geral_booking:
                current_app.logger.debug(f"create_booking: Existing 'Geral' room booking for user {user_name} in period '{period}' on {booking_date_obj}.")
                return jsonify({
                    "error": f"Você já possui um agendamento para uma sala da categoria 'Geral' ({existing_geral_booking.room.name}) no período '{period}' do dia {booking_date_obj.strftime('%Y-%m-%d')}."
                }), 409

    # Validation for booking conflicts (slot already taken)
    for slot in processed_slots:
        if check_booking_conflict(slot["room_id"], slot["booking_date_obj"], slot["period"]):
            current_app.logger.debug(f"create_booking: Conflict detected for room {slot['room_name']} on {slot['booking_date_str']} in period {slot['period']}.")
            return jsonify({
                "error": f"A sala '{slot['room_name']}' já está reservada para o período '{slot['period']}' no dia {slot['booking_date_str']}."
            }), 409
    
    newly_created_bookings_details_for_email = []
    try:
        for slot in processed_slots:
            new_booking = Booking(
                user_name=user_name, 
                user_email=user_email, 
                coordinator_name=coordinator_name,
                observation=observation,
                room_id=slot["room_id"], 
                booking_date=slot["booking_date_obj"], 
                period=slot["period"]
            )
            db.session.add(new_booking)
            newly_created_bookings_details_for_email.append({
                "room_name": slot["room_name"],
                "booking_date": slot["booking_date_str"],
                "period": slot["period"]
            })
        db.session.commit()
        current_app.logger.info(f"create_booking: Successfully created {len(processed_slots)} booking(s) for user {user_name}.")
        
        email_sent_successfully = send_booking_confirmation_email(
            user_email, user_name, coordinator_name, observation, newly_created_bookings_details_for_email
        )
        
        response_message = "Agendamento(s) criado(s) com sucesso!"
        if not email_sent_successfully:
            response_message += " (Houve um problema ao enviar o e-mail de confirmação.)"
        
        return jsonify({
            "message": response_message,
            "bookings_created": newly_created_bookings_details_for_email
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Falha ao criar agendamento(s) no servidor: {str(e)}", exc_info=True)
        return jsonify({"error": "Falha ao criar agendamento(s) no servidor.", "details": str(e)}), 500

@bookings_bp.route("/bookings", methods=["GET"])
def get_bookings():
    target_date_str = request.args.get("date")
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    
    current_app.logger.debug(f"get_bookings: Received request with date={target_date_str}, start_date={start_date_str}, end_date={end_date_str}")

    # Usar join com Room e aplicar ordenação customizada
    query = Booking.query.join(Room).order_by(Booking.booking_date, Booking.period)
    
    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            query = query.filter(Booking.booking_date == target_date)
            current_app.logger.debug(f"get_bookings: Filtering by single date: {target_date}")
        except ValueError:
            current_app.logger.debug(f"get_bookings: Invalid date format for 'date': {target_date_str}")
            return jsonify({"error": "Invalid date format for 'date'. Use YYYY-MM-DD"}), 400
    elif start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            query = query.filter(Booking.booking_date.between(start_date, end_date))
            current_app.logger.debug(f"get_bookings: Filtering by date range: {start_date} to {end_date}")
        except ValueError:
            current_app.logger.debug(f"get_bookings: Invalid date format for 'start_date' or 'end_date': {start_date_str}, {end_date_str}")
            return jsonify({"error": "Invalid date format for 'start_date' or 'end_date'. Use YYYY-MM-DD"}), 400
    
    bookings = query.all()
    
    # Aplicar ordenação customizada aos resultados
    def booking_sort_key(booking):
        room_name = booking.room.name
        if room_name.startswith("Geral "):
            try:
                number = int(re.findall(r'\d+', room_name)[0])
                return (0, number)
            except (IndexError, ValueError):
                return (0, 999)
        else:
            return (1, booking.room.id)
    
    bookings.sort(key=booking_sort_key)
    
    result = []
    for booking in bookings:
        result.append({
            "id": booking.id, 
            "user_name": booking.user_name, 
            "user_email": booking.user_email,
            "coordinator_name": booking.coordinator_name, 
            "observation": booking.observation,
            "room_id": booking.room_id,
            "room_name": booking.room.name, 
            "booking_date": booking.booking_date.isoformat(),
            "period": booking.period, 
            "created_at": booking.created_at.isoformat() if booking.created_at else None
        })
    current_app.logger.debug(f"get_bookings: Returning {len(result)} bookings.")
    return jsonify(result)

@bookings_bp.route("/generate-pdf", methods=["GET"])
def generate_schedule_pdf():
    """Gera PDF da escala semanal com observações organizadas por usuário"""
    try:
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        
        current_app.logger.debug(f"generate_schedule_pdf: Received request for start_date={start_date_str}, end_date={end_date_str}")

        if not start_date_str or not end_date_str:
            current_app.logger.debug("generate_schedule_pdf: Missing start_date or end_date parameters.")
            return jsonify({"error": "Parâmetros start_date e end_date são obrigatórios"}), 400
        
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            current_app.logger.debug(f"generate_schedule_pdf: Parsed dates: {start_date} to {end_date}")
        except ValueError:
            current_app.logger.debug(f"generate_schedule_pdf: Invalid date format for start_date or end_date: {start_date_str}, {end_date_str}")
            return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400
        
        # Buscar agendamentos do período
        bookings = Booking.query.join(Room).filter(
            Booking.booking_date.between(start_date, end_date)
        ).order_by(Booking.booking_date, Booking.period).all()
        current_app.logger.debug(f"generate_schedule_pdf: Found {len(bookings)} bookings for the period.")
        
        # Buscar todas as salas e aplicar ordenação customizada
        rooms = Room.query.all()
        sorted_rooms = sort_rooms_custom(rooms)
        current_app.logger.debug(f"generate_schedule_pdf: Found {len(sorted_rooms)} rooms.")
        
        # Preparar dados da escala
        schedule_data = {}
        dates_of_week = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:  # Segunda a sexta
                date_str = current_date.isoformat()
                dates_of_week.append(date_str)
                schedule_data[date_str] = {
                    "Manhã": {room.name: "" for room in sorted_rooms},
                    "Tarde": {room.name: "" for room in sorted_rooms}
                }
            current_date += timedelta(days=1)
        
        # Preencher dados da escala
        for booking in bookings:
            date_str = booking.booking_date.isoformat()
            if date_str in schedule_data:
                room_name = booking.room.name
                if room_name in schedule_data[date_str][booking.period]:
                    schedule_data[date_str][booking.period][room_name] = booking.user_name
        
        # Organizar observações por usuário
        user_observations = defaultdict(lambda: {
            'email': '',
            'coordinator': '',
            'bookings': []
        })
        
        for booking in bookings:
            user_name = booking.user_name
            user_observations[user_name]['email'] = booking.user_email
            user_observations[user_name]['coordinator'] = booking.coordinator_name or ''
            user_observations[user_name]['bookings'].append({
                'room_name': booking.room.name,
                'date': booking.booking_date,
                'period': booking.period,
                'observation': booking.observation or ''
            })
        
        # Preparar dados para o template
        days_locale = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"]
        generation_date = datetime.now().strftime("%d/%m/%Y às %H:%M")
        
        # Renderizar HTML
        html_content = render_template(
            'schedule_pdf_template.html',
            rooms=sorted_rooms,
            dates_of_week=dates_of_week,
            days_locale=days_locale,
            schedule_data=schedule_data,
            user_observations=dict(user_observations),
            week_start_date_formatted=start_date.strftime("%d/%m/%Y"),
            week_end_date_formatted=end_date.strftime("%d/%m/%Y"),
            generation_date=generation_date,
            zip=zip
        )
        current_app.logger.debug("generate_schedule_pdf: HTML content rendered.")
        
        # Gerar PDF
        pdf_bytes = HTML(string=html_content).write_pdf()
        current_app.logger.debug("generate_schedule_pdf: PDF generated.")
        
        # Criar resposta
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=escala_agendamentos_{start_date_str}_a_{end_date_str}.pdf'
        
        return response
        
    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {str(e)}", exc_info=True)
        return jsonify({"error": "Erro interno ao gerar PDF", "details": str(e)}), 500

