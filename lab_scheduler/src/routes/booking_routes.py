# /home/ubuntu/lab_scheduler/src/routes/booking_routes.py

from flask import Blueprint, request, jsonify, current_app, render_template, make_response
from src.extensions import db
from src.models.entities import Room, Booking
from datetime import datetime, date, timedelta, time
from collections import defaultdict
from flask_mail import Message
from weasyprint import HTML
import re
import pytz # Importar pytz para lidar com fusos horários

bookings_bp = Blueprint("bookings_bp", __name__)

MAX_BOOKINGS_PER_DAY = 3

# Definir o fuso horário de Brasília
BRASILIA_TZ = pytz.timezone("America/Sao_Paulo")

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
        if name.startswith("Geral "):
            try:
                number = int(re.findall(r'\d+', name)[0])
                return (0, number)
            except (IndexError, ValueError):
                return (0, 999)
        else:
            return (1, room.id)
    
    return sorted(rooms, key=room_sort_key)

# Função para determinar o status da janela de agendamento
def get_booking_window_status():
    now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
    now_brasilia = now_utc.astimezone(BRASILIA_TZ)
    
    # Encontrar a segunda-feira da semana atual
    today_brasilia = now_brasilia.date()
    current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
    
    # Encontrar a segunda-feira da próxima semana
    next_week_monday = current_week_monday + timedelta(weeks=1)
    
    # Definir os pontos de corte para a semana atual
    current_week_cutoff_date = current_week_monday + timedelta(days=2) # Quarta-feira
    current_week_cutoff_time = time(18, 0, 0) # 18:00
    current_week_cutoff_datetime = BRASILIA_TZ.localize(datetime.combine(current_week_cutoff_date, current_week_cutoff_time))

    # Definir os pontos de corte para a próxima semana
    next_week_open_date = current_week_monday + timedelta(days=3) # Quinta-feira
    next_week_open_time = time(23, 59, 0) # 23:59
    next_week_open_datetime = BRASILIA_TZ.localize(datetime.combine(next_week_open_date, next_week_open_time))

    next_week_cutoff_date = next_week_monday + timedelta(days=2) # Quarta-feira da próxima semana
    next_week_cutoff_time = time(18, 0, 0) # 18:00
    next_week_cutoff_datetime = BRASILIA_TZ.localize(datetime.combine(next_week_cutoff_date, next_week_cutoff_time))

    status = {
        "current_week": {"open": False, "message": "Fechado"},
        "next_week": {"open": False, "message": "Fechado"}
    }

    # Regra para a semana atual
    if now_brasilia <= current_week_cutoff_datetime:
        status["current_week"]["open"] = True
        status["current_week"]["message"] = "Aberto até quarta-feira às 18:00"
    else:
        status["current_week"]["message"] = "Fechado (após quarta-feira 18:00)"

    # Regra para a próxima semana
    if now_brasilia >= next_week_open_datetime and now_brasilia <= next_week_cutoff_datetime:
        status["next_week"]["open"] = True
        status["next_week"]["message"] = "Aberto para a próxima semana"
    elif now_brasilia < next_week_open_datetime:
        status["next_week"]["message"] = f"Abre na quinta-feira às 23:59 ({next_week_open_date.strftime('%d/%m')})"
    else:
        status["next_week"]["message"] = "Fechado (após quarta-feira 18:00 da próxima semana)"

    return status

@bookings_bp.route("/booking-window-status", methods=["GET"])
def booking_window_status():
    status = get_booking_window_status()
    return jsonify(status)

@bookings_bp.route("/rooms", methods=["GET"])
def get_rooms():
    rooms = Room.query.all()
    sorted_rooms = sort_rooms_custom(rooms)
    return jsonify([{"id": room.id, "name": room.name} for room in sorted_rooms])

@bookings_bp.route("/bookings", methods=["POST"])
def create_booking():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid input"}), 400

    user_name = data.get("user_name")
    user_email = data.get("user_email")
    coordinator_name = data.get("coordinator_name")
    observation = data.get("observation", "")
    slots_data = data.get("slots")

    if not all([user_name, user_email, slots_data]):
        return jsonify({"error": "Missing fields. Required: user_name, user_email, slots"}), 400
    
    if not isinstance(slots_data, list) or not slots_data:
        return jsonify({"error": "Slots must be a non-empty list"}), 400

    if "@" not in user_email or "." not in user_email.split("@")[-1]:
        return jsonify({"error": "Invalid email format"}), 400

    processed_slots = []
    daily_new_bookings_count = defaultdict(int)

    booking_window = get_booking_window_status()

    for slot_input in slots_data:
        room_id = slot_input.get("room_id")
        booking_date_str = slot_input.get("booking_date")
        period = slot_input.get("period")

        if not all([room_id, booking_date_str, period]):
            return jsonify({"error": f"Invalid slot data: {slot_input}. Each slot needs room_id, booking_date, period"}), 400
        if period not in ["Manhã", "Tarde"]:
            return jsonify({"error": f"Invalid period '{period}' in slot: {slot_input}. Must be 'Manhã' or 'Tarde'"}), 400
        try:
            booking_date_obj = datetime.strptime(booking_date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": f"Invalid date format '{booking_date_str}' in slot: {slot_input}. Use YYYY-MM-DD"}), 400
        
        # Validação da janela de agendamento
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_brasilia = now_utc.astimezone(BRASILIA_TZ)
        today_brasilia = now_brasilia.date()
        current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
        next_week_monday = current_week_monday + timedelta(weeks=1)

        if booking_date_obj.weekday() >= 5: # Sábado ou Domingo
            return jsonify({"error": f"Agendamentos para {booking_date_str} são permitidos apenas de segunda a sexta-feira."}), 400

        if booking_date_obj < today_brasilia:
            return jsonify({"error": f"Agendamento para {booking_date_str} não pode ser no passado."}), 400
        
        if booking_date_obj >= current_week_monday and booking_date_obj < next_week_monday:
            # Agendamento para a semana atual
            if not booking_window["current_week"]["open"]:
                return jsonify({"error": f"Agendamentos para a semana atual estão fechados. {booking_window['current_week']['message']}"}), 403
        elif booking_date_obj >= next_week_monday and booking_date_obj < (next_week_monday + timedelta(weeks=1)):
            # Agendamento para a próxima semana
            if not booking_window["next_week"]["open"]:
                return jsonify({"error": f"Agendamentos para a próxima semana estão fechados. {booking_window['next_week']['message']}"}), 403
        else:
            return jsonify({"error": f"Agendamentos só são permitidos para a semana atual ou próxima semana."}), 403

        room = Room.query.get(room_id)
        if not room:
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
        if (existing_bookings_on_day + count_for_this_request) > MAX_BOOKINGS_PER_DAY:
            return jsonify({
                "error": f"Limite de {MAX_BOOKINGS_PER_DAY} agendamentos por dia para o usuário '{user_name}' seria excedido no dia {booking_date_obj.strftime('%Y-%m-%d')}."
            }), 409

    # Validation for "Geral" rooms - only one per period per day per user
    for booking_date_obj, _ in daily_new_bookings_count.items():
        geral_periods_in_request = defaultdict(list)
        
        for slot in processed_slots:
            if slot['booking_date_obj'] == booking_date_obj and slot['room_name'].startswith("Geral "):
                geral_periods_in_request[slot['period']].append(slot['room_name'])
        
        for period, geral_rooms in geral_periods_in_request.items():
            if len(geral_rooms) > 1:
                return jsonify({
                    "error": f"Você só pode agendar uma sala da categoria 'Geral' por período. Tentativa de agendar múltiplas salas 'Geral' no período '{period}' do dia {booking_date_obj.strftime('%Y-%m-%d')}."
                }), 409
            
            existing_geral_booking = Booking.query.join(Room).filter(
                Booking.user_name == user_name,
                Booking.booking_date == booking_date_obj,
                Booking.period == period,
                Room.name.startswith("Geral ")
            ).first()
            
            if existing_geral_booking:
                return jsonify({
                    "error": f"Você já possui um agendamento para uma sala da categoria 'Geral' ({existing_geral_booking.room.name}) no período '{period}' do dia {booking_date_obj.strftime('%Y-%m-%d')}."
                }), 409

    # Validation for booking conflicts (slot already taken)
    for slot in processed_slots:
        if check_booking_conflict(slot["room_id"], slot["booking_date_obj"], slot["period"]):
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
        current_app.logger.error(f"Falha ao criar agendamento(s) no servidor: {str(e)}")
        return jsonify({"error": "Falha ao criar agendamento(s) no servidor.", "details": str(e)}), 500

@bookings_bp.route("/bookings", methods=["GET"])
def get_bookings():
    target_date_str = request.args.get("date")
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    
    query = Booking.query.join(Room).order_by(Booking.booking_date, Booking.period)
    
    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            query = query.filter(Booking.booking_date == target_date)
        except ValueError:
            return jsonify({"error": "Invalid date format for 'date'. Use YYYY-MM-DD"}), 400
    elif start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            query = query.filter(Booking.booking_date.between(start_date, end_date))
        except ValueError:
            return jsonify({"error": "Invalid date format for 'start_date' or 'end_date'. Use YYYY-MM-DD"}), 400
    
    bookings = query.all()
    
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
    return jsonify(result)

@bookings_bp.route("/generate-pdf", methods=["GET"])
def generate_schedule_pdf():
    """Gera PDF da escala semanal com observações organizadas por usuário"""
    try:
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        
        if not start_date_str or not end_date_str:
            return jsonify({"error": "Parâmetros start_date e end_date são obrigatórios"}), 400
        
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400
        
        bookings = Booking.query.join(Room).filter(
            Booking.booking_date.between(start_date, end_date)
        ).order_by(Booking.booking_date, Booking.period).all()
        
        rooms = Room.query.all()
        sorted_rooms = sort_rooms_custom(rooms)
        
        schedule_data = {}
        dates_of_week = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:
                date_str = current_date.isoformat()
                dates_of_week.append(date_str)
                schedule_data[date_str] = {
                    "Manhã": {room.name: "" for room in sorted_rooms},
                    "Tarde": {room.name: "" for room in sorted_rooms}
                }
            current_date += timedelta(days=1)
        
        for booking in bookings:
            date_str = booking.booking_date.isoformat()
            if date_str in schedule_data:
                room_name = booking.room.name
                if room_name in schedule_data[date_str][booking.period]:
                    schedule_data[date_str][booking.period][room_name] = booking.user_name
        
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
        
        days_locale = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"]
        generation_date = datetime.now().strftime("%d/%m/%Y às %H:%M")
        
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
        
        pdf_bytes = HTML(string=html_content).write_pdf()
        
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=escala_agendamentos_{start_date_str}_a_{end_date_str}.pdf'
        
        return response
        
    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {str(e)}")
        return jsonify({"error": "Erro interno ao gerar PDF", "details": str(e)}), 500


# Rota para verificar o status do agendamento (para o frontend)
@bookings_bp.route("/get-booking-status", methods=["GET"])
def get_booking_status():
    status = get_booking_window_status()
    return jsonify(status)
