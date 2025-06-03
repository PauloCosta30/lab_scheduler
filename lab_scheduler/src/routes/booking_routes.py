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
CUTOFF_TIME = time(21, 0, 0, tzinfo=timezone.utc)
RELEASE_WEEKDAY = 4 # Friday
RELEASE_TIME = time(3, 0, 0, tzinfo=timezone.utc)
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
        # Use single quotes inside the f-string for dictionary keys
        html_body += f"<li>Sala: {slot['room_name']} - Data: {booking_date_formatted} - Período: {slot['period']}</li>"
    html_body += f"</ul><p>Coordenador: {coordinator_name}</p><p>Obrigado! Observação: Em caso de dúvidas sobre a escala, entre em contato com Ana Correa pelo e-mail: ana.correa@itv.org</p>"""

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
    #if booking_date_obj < today_utc:
        #return False, f"Data de agendamento {booking_date_obj.strftime('%d/%m/%Y')} no passado."#

    if start_of_current_week <= booking_date_obj < start_of_next_week:
        if now_utc >= cutoff_datetime:
            # Corrected f-string with balanced parentheses
            return False, f"Agendamento para semana atual ({start_of_current_week.strftime('%d/%m')}-{(start_of_current_week + timedelta(days=4)).strftime('%d/%m')}) encerrou Qua 18:00 UTC."
        else:
            return True, "OK"
    elif start_of_next_week <= booking_date_obj <= end_of_next_week:
        if now_utc < release_datetime:
             # Corrected f-string with balanced parentheses
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
        existing_bookings_on_day = Booking.query.filter_by(user_name=user_name, booking_date=booking_date_obj).count()
        if (existing_bookings_on_day + count_for_this_request) > MAX_BOOKINGS_PER_DAY:
            # Use single quotes for literals inside f-string
            return jsonify({"error": f"Limite de {MAX_BOOKINGS_PER_DAY} agendamentos/dia para '{user_name}' excedido em {booking_date_obj.strftime('%Y-%m-%d')}."}), 409

    # Validation: Limit one "Geral" room per day per user
    geral_rooms_requested_this_request_by_day = defaultdict(set)
    for slot in processed_slots:
        # Use single quotes for keys inside f-string
        if slot['room_name'].startswith("Geral "):
            geral_rooms_requested_this_request_by_day[slot['booking_date_obj']].add(slot['room_id'])

    for booking_date_obj, geral_room_ids_in_request in geral_rooms_requested_this_request_by_day.items():
        if len(geral_room_ids_in_request) > 1:
            # Use single quotes for literals inside f-string
            return jsonify({"error": f"Só pode agendar uma sala 'Geral' por dia. Tentativa múltipla em {booking_date_obj.strftime('%Y-%m-%d')}."}), 409
        for room_id_in_request in geral_room_ids_in_request:
            existing_geral_booking_other_room = Booking.query.join(Room).filter(
                Booking.user_name == user_name, Booking.booking_date == booking_date_obj,
                Room.name.startswith("Geral "), Room.id != room_id_in_request
            ).first()
            if existing_geral_booking_other_room:
                # Use single quotes for literals inside f-string
                return jsonify({"error": f"Já possui agendamento para outra sala 'Geral' ({existing_geral_booking_other_room.room.name}) em {booking_date_obj.strftime('%Y-%m-%d')}."}), 409

    # Validation: Slot already taken
    for slot in processed_slots:
        # *** CORRECTED THIS F-STRING ***
        if check_booking_conflict(slot['room_id'], slot['booking_date_obj'], slot['period']):
            return jsonify({"error": f"Sala '{slot['room_name']}' já reservada para '{slot['period']}' em {slot['booking_date_str']}."}), 409
    
    newly_created_bookings_details_for_email = []
    try:
        for slot in processed_slots:
            new_booking = Booking(
                user_name=user_name, user_email=user_email, coordinator_name=coordinator_name,
                room_id=slot['room_id'], booking_date=slot['booking_date_obj'], period=slot['period']
            )
            db.session.add(new_booking)
            # Use single quotes for keys inside f-string
            newly_created_bookings_details_for_email.append({
                "room_name": slot['room_name'], "booking_date": slot['booking_date_str'], "period": slot['period']
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
        query = Booking.query.join(Room).filter(Booking.booking_date.between(start_date, end_date)).order_by(Booking.booking_date, Room.id, Booking.period)
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

@bookings_bp.route("/booking-status", methods=["GET"])
def get_booking_status():
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date()
    start_of_current_week = today_utc - timedelta(days=today_utc.weekday())
    start_of_next_week = start_of_current_week + timedelta(days=7)
    end_of_next_week = start_of_next_week + timedelta(days=4)
    cutoff_datetime = datetime.combine(start_of_current_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
    release_datetime = datetime.combine(start_of_current_week + timedelta(days=RELEASE_WEEKDAY), RELEASE_TIME)
    cutoff_next_week = datetime.combine(start_of_next_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)

    current_week_open = now_utc < cutoff_datetime
    next_week_open = now_utc >= release_datetime and now_utc < cutoff_next_week
        
    return jsonify({
        "current_week_start": start_of_current_week.isoformat(),
        "current_week_end": (start_of_current_week + timedelta(days=4)).isoformat(),
        "current_week_open": current_week_open,
        "current_week_cutoff": cutoff_datetime.isoformat(),
        "next_week_start": start_of_next_week.isoformat(),
        "next_week_end": end_of_next_week.isoformat(),
        "next_week_open": next_week_open,
        "next_week_release": release_datetime.isoformat(),
        "server_time_utc": now_utc.isoformat()
    })

# --- NEW: PDF Generation Route --- 
@bookings_bp.route("/generate-pdf", methods=["GET"])
def generate_schedule_pdf():
    week_start_date_str = request.args.get("week_start_date")
    if not week_start_date_str:
        return jsonify({"error": "Parâmetro week_start_date é obrigatório"}), 400
    
    try:
        week_start_date = datetime.strptime(week_start_date_str, "%Y-%m-%d").date()
        # Ensure it's a Monday
        if week_start_date.weekday() != 0:
             week_start_date -= timedelta(days=week_start_date.weekday())
             week_start_date_str = week_start_date.isoformat()
             
        week_end_date = week_start_date + timedelta(days=4)
        week_end_date_str = week_end_date.isoformat()
    except ValueError:
        return jsonify({"error": "Formato de data inválido para week_start_date. Use YYYY-MM-DD"}), 400

    try:
        # Fetch data for the specified week
        rooms = Room.query.order_by(Room.id).all()
        bookings_query = Booking.query.join(Room).filter(
            Booking.booking_date.between(week_start_date, week_end_date)
        ).order_by(Booking.booking_date, Room.id, Booking.period)
        bookings = bookings_query.all()
        
        # Prepare data for template
        schedule_data = defaultdict(lambda: defaultdict(lambda: {"Manhã": None, "Tarde": None}))
        for booking in bookings:
            schedule_data[booking.room_id][booking.booking_date.isoformat()][booking.period] = booking.user_name
            
        dates_of_week = [(week_start_date + timedelta(days=i)).isoformat() for i in range(5)]
        days_locale = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"]
        
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
        
        # Render HTML template
        template = env.get_template("schedule_pdf_template.html")
        html_string = template.render(
            rooms=rooms,
            dates_of_week=dates_of_week,
            days_locale=days_locale,
            schedule_data=schedule_data,
            week_start_date_formatted=week_start_date.strftime("%d/%m/%Y"),
            week_end_date_formatted=week_end_date.strftime("%d/%m/%Y")
        )
        
        # Define CSS for the PDF
        css_string = """
            body { font-family: sans-serif; font-size: 10px; }
            h1, h2 { text-align: center; color: #333; }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; }
            th, td { border: 1px solid #ccc; padding: 4px; text-align: center; }
            th { background-color: #f2f2f2; font-weight: bold; }
            td.booked { background-color: #f8d7da; color: #721c24; font-style: italic; }
            td.room-name { text-align: left; font-weight: bold; }
            thead th { vertical-align: middle; }
            tbody td { height: 30px; vertical-align: middle; }
        """
        css = CSS(string=css_string)
        
        # Generate PDF
        pdf_bytes = HTML(string=html_string).write_pdf(stylesheets=[css])
        
        # Create response
        response = make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"attachment; filename=escala_semana_{week_start_date_str}.pdf"
        
        return response

    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF para semana {week_start_date_str}: {str(e)}")
        return jsonify({"error": "Falha ao gerar PDF no servidor", "details": str(e)}), 500
# --- End of PDF Route ---
