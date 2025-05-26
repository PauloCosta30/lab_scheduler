# /home/ubuntu/lab_scheduler/src/routes/booking_routes.py

from flask import Blueprint, request, jsonify, current_app
from src.extensions import db
from src.models.entities import Room, Booking
from datetime import datetime, date
from collections import defaultdict
from flask_mail import Message # Import Message for Flask-Mail
# It's better to get mail instance from current_app or pass it if not using current_app context directly in functions
# from src.main import mail # Avoid direct import from main if possible to prevent circular dependencies

bookings_bp = Blueprint("bookings_bp", __name__)

MAX_BOOKINGS_PER_DAY = 3

# Helper function to send confirmation email
def send_booking_confirmation_email(user_email, user_name, coordinator_name, booked_slots_details):
    mail = current_app.extensions.get("mail") # Get Mail instance from app context
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
        # Ensure date is formatted nicely if it's an object
        booking_date_formatted = slot["booking_date"]
        if isinstance(slot["booking_date"], date):
            booking_date_formatted = slot["booking_date"].strftime("%d/%m/%Y")
        elif isinstance(slot["booking_date"], str):
             # Assuming it's already YYYY-MM-DD, convert to DD/MM/YYYY
            try:
                booking_date_formatted = datetime.strptime(slot["booking_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                pass # Keep original string if parsing fails

        html_body += f"<li>Sala: {slot['room_name']} - Data: {booking_date_formatted} - Período: {slot['period']}</li>"
    
    html_body += "</ul>"
    if coordinator_name:
        html_body += f"<p>Coordenador: {coordinator_name}</p>"
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

# Helper function to check for conflicts (remains the same)
def check_booking_conflict(room_id, booking_date_obj, period):
    existing_booking = Booking.query.filter_by(
        room_id=room_id,
        booking_date=booking_date_obj,
        period=period
    ).first()
    return existing_booking is not None

@bookings_bp.route("/rooms", methods=["GET"])
def get_rooms():
    rooms = Room.query.all()
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
        return jsonify({"error": "Missing fields. Required: user_name, user_email, slots"}), 400
    
    if not isinstance(slots_data, list) or not slots_data:
        return jsonify({"error": "Slots must be a non-empty list"}), 400

    if "@" not in user_email or "." not in user_email.split("@")[-1]:
        return jsonify({"error": "Invalid email format"}), 400

    processed_slots = []
    daily_new_bookings_count = defaultdict(int)

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
        if booking_date_obj < date.today(): # Check against server's current date (UTC)
            return jsonify({"error": f"Booking date {booking_date_str} in slot: {slot_input} cannot be in the past"}), 400
        if booking_date_obj.weekday() >= 5:
            return jsonify({"error": f"Bookings for date {booking_date_str} in slot: {slot_input} are only allowed on weekdays (Mon-Fri)"}), 400
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

    # NEW VALIDATION: Limit of one "Geral" room category per day per user
    geral_rooms_requested_this_request_by_day = defaultdict(set)
    for slot in processed_slots:
        if slot['room_name'].startswith("Geral "):
            geral_rooms_requested_this_request_by_day[slot['booking_date_obj']].add(slot['room_id'])

    for booking_date_obj, geral_room_ids_in_request in geral_rooms_requested_this_request_by_day.items():
        # 1. Check if in the SAME REQUEST the user asked for more than one different "Geral" room for the same day
        if len(geral_room_ids_in_request) > 1:
            return jsonify({
                "error": f"Você só pode agendar uma sala da categoria 'Geral' por dia. Tentativa de agendar múltiplas salas 'Geral' diferentes no dia {booking_date_obj.strftime('%Y-%m-%d')}."
            }), 409

        # 2. For the "Geral" room(s) in this request, check if another "Geral" room is already booked in the DB for this user on this day
        for room_id_in_request in geral_room_ids_in_request: # Usually only one ID here due to the validation above
            existing_geral_booking_other_room = Booking.query.join(Room).filter(
                Booking.user_name == user_name,
                Booking.booking_date == booking_date_obj,
                Room.name.startswith("Geral "),
                Room.id != room_id_in_request # Checks for a DIFFERENT "Geral" room
            ).first()
            if existing_geral_booking_other_room:
                return jsonify({
                    "error": f"Você já possui um agendamento para outra sala da categoria 'Geral' ({existing_geral_booking_other_room.room.name}) no dia {booking_date_obj.strftime('%Y-%m-%d')}. Só é permitida uma sala 'Geral' por dia."
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
                user_name=user_name, user_email=user_email, coordinator_name=coordinator_name,
                room_id=slot["room_id"], booking_date=slot["booking_date_obj"], period=slot["period"]
            )
            db.session.add(new_booking)
            newly_created_bookings_details_for_email.append({
                "room_name": slot["room_name"],
                "booking_date": slot["booking_date_str"], # Use string for consistency in email
                "period": slot["period"]
            })
        db.session.commit()
        
        email_sent_successfully = send_booking_confirmation_email(
            user_email, user_name, coordinator_name, newly_created_bookings_details_for_email
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
    query = Booking.query.join(Room).order_by(Booking.booking_date, Booking.period, Room.id)
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
    result = []
    for booking in bookings:
        result.append({
            "id": booking.id, "user_name": booking.user_name, "user_email": booking.user_email,
            "coordinator_name": booking.coordinator_name, "room_id": booking.room_id,
            "room_name": booking.room.name, "booking_date": booking.booking_date.isoformat(),
            "period": booking.period, "created_at": booking.created_at.isoformat() if booking.created_at else None
        })
    return jsonify(result)

