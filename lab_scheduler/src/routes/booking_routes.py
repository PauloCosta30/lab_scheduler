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

bookings_bp = Blueprint("bookings_bp", __name__)

MAX_BOOKINGS_PER_DAY = 3

# --- Booking Window Configuration ---
CUTOFF_WEEKDAY = 2 # Wednesday
CUTOFF_TIME = time(18, 0, 0, tzinfo=timezone.utc)
RELEASE_WEEKDAY = 4 # Friday
RELEASE_TIME = time(0, 0, 0, tzinfo=timezone.utc)
# ----------------------------------

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

# Helper function to check booking window rules
def is_booking_allowed(booking_date_obj):
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date()
    start_of_current_week = today_utc - timedelta(days=today_utc.weekday())
    start_of_next_week = start_of_current_week + timedelta(days=7)
    end_of_next_week = start_of_next_week + timedelta(days=4)
    cutoff_datetime = datetime.combine(start_of_current_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
    release_datetime = datetime.combine(start_of_current_week + timedelta(days=RELEASE_WEEKDAY), RELEASE_TIME)

    if booking_date_obj.weekday() >= 5:
        return False, f"Agendamentos só permitidos de Seg-Sex. Data: {booking_date_obj.strftime('%d/%m/%Y')} é fim de semana."
    if booking_date_obj < today_utc:
        return False, f"Data de agendamento {booking_date_obj.strftime('%d/%m/%Y')} no passado."

    if start_of_current_week <= booking_date_obj < start_of_next_week:
        if now_utc >= cutoff_datetime:
            return False, f"Agendamento para semana atual ({start_of_current_week.strftime('%d/%m')}-{(start_of_current_week + timedelta(days=4)).strftime('%d/%m')}) encerrou Qua 18:00 UTC."
        else:
            return True, "OK"
    elif start_of_next_week <= booking_date_obj <= end_of_next_week:
        if now_utc < release_datetime:
            return False, f"Agendamento para próxima semana ({start_of_next_week.strftime('%d/%m')}-{end_of_next_week.strftime('%d/%m')}) abre Sex 00:00 UTC."
        else:
            cutoff_next_week = datetime.combine(start_of_next_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
            if now_utc >= cutoff_next_week:
                return False, f"Agendamento para semana de {start_of_next_week.strftime('%d/%m')} já encerrou."
            else:
                return True, "OK"
    else:
        return False, f"Só é possível agendar para semana atual ou próxima. Data: {booking_date_obj.strftime('%d/%m/%Y')} fora do período."


@bookings_bp.route("/rooms", methods=["GET"])
def get_rooms():
    rooms = Room.query.order_by(Room.id).all()
    return jsonify([{"id": room.id, "name": room.name} for room in rooms])

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
            return jsonify({"error": f"Slot inválido: {slot_input}. Requer room_id, booking_date, period"}), 400
        if period not in ["Manhã", "Tarde"]:
            return jsonify({"error": f"Período inválido '{period}'. Use 'Manhã' ou 'Tarde'"}), 400
        try:
            booking_date_obj = datetime.strptime(booking_date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": f"Formato de data inválido '{booking_date_str}'. Use YYYY-MM-DD"}), 400
        
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

    # Validation: max 3 bookings per day per user
    for booking_date_obj, count_for_this_request in daily_new_bookings_count.items():
        existing_bookings_on_day = Booking.query.filter_by(
            user_name=user_name, booking_date=booking_date_obj
        ).count()
        if (existing_bookings_on_day + count_for_this_request) > MAX_BOOKINGS_PER_DAY:
            return jsonify({
                "error": f"Limite de {MAX_BOOKINGS_PER_DAY} agendamentos/dia para '{user_name}' excedido em {booking_date_obj.strftime('%Y-%m-%d')}."
            }), 409


    # Validation: Limit one "Geral" room per day per user
    geral_rooms_requested_this_request_by_day = defaultdict(set)
    for slot in processed_slots:
        if slot["room_name"].startswith("Geral "):
            geral_rooms_requested_this_request_by_day[slot["booking_date_obj"]].add(slot["room_id"])

    for booking_date_obj, geral_room_ids_in_request in geral_rooms_requested_this_request_by_day.items():
        if len(geral_room_ids_in_request) > 1:
            return jsonify({"error": f"Só pode agendar uma sala 'Geral' por dia. Tentativa múltipla em {booking_date_obj.strftime('%Y-%m-%d')}."}), 409
        for room_id_in_request in geral_room_ids_in_request:
            existing_geral_booking_other_room = Booking.query.join(Room).filter(
                Booking.user_name == user_name, Booking.booking_date == booking_date_obj,
                Room.name.startswith("Geral "), Room.id != room_id_in_request
            ).first()
            if existing_geral_booking_other_room:
                return jsonify({"error": f"Já possui agendamento para outra sala 'Geral' ({existing_geral_booking_other_room.room.name}) em {booking_date_obj.strftime('%Y-%m-%d')}."}), 409

    # Validation: Slot already taken
    for slot in processed_slots:
        if check_booking_conflict(slot["room_id"], slot["booking_date_obj"], slot["period"]):
            return jsonify({"error": f"Sala '{slot['room_name']}' já reservada para '{slot['period']}' em {slot['booking_date_str']}."}), 409
    
    newly_created_bookings_details_for_email = []
    try:
        for slot in processed_slots:
            booking = Booking(
                room_id=slot["room_id"],
                booking_date=slot["booking_date_obj"],
                period=slot["period"],
                user_name=user_name,
                user_email=user_email,
                coordinator_name=coordinator_name,
                created_at=datetime.utcnow()
            )
            db.session.add(booking)
            newly_created_bookings_details_for_email.append({
                "room_name": slot["room_name"],
                "booking_date": slot["booking_date_str"],
                "period": slot["period"]
            })
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Erro ao salvar agendamento: {str(e)}"}), 500

    # Send confirmation email
    send_booking_confirmation_email(user_email, user_name, coordinator_name, newly_created_bookings_details_for_email)

    return jsonify({"message": "Agendamento(s) criado(s) com sucesso."})

@bookings_bp.route("/bookings/pdf", methods=["POST"])
def generate_bookings_pdf():
    data = request.get_json()
    if not data or "bookings" not in data:
        return jsonify({"error": "Dados de agendamento ausentes."}), 400
    
    bookings = data["bookings"]
    if not isinstance(bookings, list) or not bookings:
        return jsonify({"error": "Lista de agendamentos inválida."}), 400

    # Carregar template Jinja2
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "../../templates")))
    template = env.get_template("bookings_pdf_template.html")

    # Renderizar HTML
    rendered_html = template.render(bookings=bookings)

    # Gerar PDF com WeasyPrint
    css_path = os.path.join(os.path.dirname(__file__), "../../static/css/pdf_style.css")
    css = CSS(filename=css_path)
    pdf = HTML(string=rendered_html).write_pdf(stylesheets=[css])

    # Responder PDF para download
    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=agendamentos.pdf"
    return response
