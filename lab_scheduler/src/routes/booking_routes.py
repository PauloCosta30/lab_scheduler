from flask import Blueprint, request, jsonify, current_app, render_template, make_response
from src.extensions import db
from src.models.entities import Room, Booking
from datetime import datetime, date, timedelta, time
from collections import defaultdict
from flask_mail import Message
import re
import pytz
from functools import wraps

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

bookings_bp = Blueprint("bookings_bp", __name__)
MAX_BOOKINGS_PER_DAY = 3
BRASILIA_TZ = pytz.timezone("America/Sao_Paulo")

def require_admin_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin_key = request.headers.get('X-Admin-Key') or request.args.get('admin_key')
        expected_key = current_app.config.get('ADMIN_KEY')
        if not expected_key:
            return jsonify({"error": "Configuração administrativa não encontrada"}), 500
        if not admin_key or admin_key != expected_key:
            return jsonify({"error": "Chave administrativa inválida ou ausente"}), 401
        return f(*args, **kwargs)
    return decorated_function

def send_general_observation_confirmation_email(user_email, user_name, coordinator_name, observation, week_start_date):
    try:
        mail = current_app.extensions.get("mail")
        if not mail: return False
        subject = "Confirmação de Recebimento de Observação"
        sender = current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@example.com")
        recipients = [user_email]
        week_start_formatted = week_start_date.strftime("%d/%m/%Y")
        html_body = f"""<p>Olá {user_name},</p><p>Recebemos sua observação para a semana que se inicia em <strong>{week_start_formatted}</strong>.</p><p><strong>Observação enviada:</strong></p><blockquote style="border-left: 2px solid #ccc; padding-left: 10px; margin-left: 5px; font-style: italic;">{observation}</blockquote>"""
        if coordinator_name: html_body += f"<p><strong>Coordenador:</strong> {coordinator_name}</p>"
        html_body += "<p>Obrigado! Sua observação foi registrada.</p>"
        msg = Message(subject, sender=sender, recipients=recipients)
        msg.html = html_body
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f"Falha ao enviar email de observação geral para {user_email}: {str(e)}")
        return False

def send_booking_confirmation_email(user_email, user_name, coordinator_name, observation, booked_slots_details):
    try:
        mail = current_app.extensions.get("mail")
        if not mail or not booked_slots_details: return False
        subject = "Confirmação de Agendamento de Laboratório"
        sender = current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@example.com")
        recipients = [user_email]
        html_body = f"""<p>Olá {user_name},</p><p>Seu agendamento de laboratório foi confirmado com sucesso. Detalhes abaixo:</p><ul>"""
        for slot in booked_slots_details:
            booking_date_formatted = slot["booking_date"]
            if isinstance(slot["booking_date"], date): booking_date_formatted = slot["booking_date"].strftime("%d/%m/%Y")
            elif isinstance(slot["booking_date"], str):
                try: booking_date_formatted = datetime.strptime(slot["booking_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
                except ValueError: pass
            html_body += f"<li>Sala: {slot['room_name']} - Data: {booking_date_formatted} - Período: {slot['period']}</li>"
        html_body += "</ul>"
        if coordinator_name: html_body += f"<p>Coordenador: {coordinator_name}</p>"
        if observation: html_body += f"<p>Observação: {observation}</p>"
        html_body += "<p>Obrigado! Observação: Em caso de dúvidas sobre a escala, entre em contato com Ana Correa pelo e-mail: ana.correa@itv.org</p>"
        msg = Message(subject, sender=sender, recipients=recipients)
        msg.html = html_body
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f"Falha ao enviar email para {user_email}: {str(e)}")
        return False

def check_booking_conflict(room_id, booking_date_obj, period):
    return Booking.query.filter_by(room_id=room_id, booking_date=booking_date_obj, period=period).first() is not None

def sort_rooms_custom(rooms):
    def room_sort_key(room):
        if room.name.startswith("Geral "):
            try: return (0, int(re.findall(r'\d+', room.name)[0]))
            except (IndexError, ValueError): return (0, 999)
        return (1, room.id)
    return sorted(rooms, key=room_sort_key)

def get_booking_window_status():
    now_brasilia = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(BRASILIA_TZ)
    today_brasilia = now_brasilia.date()
    current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
    next_week_monday = current_week_monday + timedelta(weeks=1)
    current_week_cutoff = BRASILIA_TZ.localize(datetime.combine(current_week_monday + timedelta(days=2), time(23, 59, 0)))
    next_week_open = BRASILIA_TZ.localize(datetime.combine(current_week_monday + timedelta(days=3), time(18, 0, 0)))
    next_week_cutoff = BRASILIA_TZ.localize(datetime.combine(next_week_monday + timedelta(days=2), time(23, 59, 0)))
    status = {"current_week": {"open": now_brasilia <= current_week_cutoff}, "next_week": {"open": next_week_open <= now_brasilia <= next_week_cutoff}}
    status["general_message"] = "As escolhas para a semana atual sempre serão encerradas às quartas-feiras, às 23:59, e a escala da próxima semana será liberada todas as quintas-feiras, às 18h."
    return status

@bookings_bp.route("/booking-window-status", methods=["GET"])
def booking_window_status():
    return jsonify(get_booking_window_status())

@bookings_bp.route("/rooms", methods=["GET"])
def get_rooms():
    return jsonify([{"id": r.id, "name": r.name} for r in sort_rooms_custom(Room.query.all())])

@bookings_bp.route("/bookings", methods=["POST"])
def create_booking():
    data = request.get_json()
    user_name, user_email, coordinator_name, observation, slots_data = data.get("user_name"), data.get("user_email"), data.get("coordinator_name"), data.get("observation", ""), data.get("slots")
    if not all([user_name, user_email]) or (not slots_data and not observation): return jsonify({"error": "Campos obrigatórios ausentes"}), 400
    if not slots_data and observation:
        today_brasilia = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(BRASILIA_TZ).date()
        week_start_date = today_brasilia - timedelta(days=today_brasilia.weekday())
        db.session.add(Booking(user_name=user_name, user_email=user_email, coordinator_name=coordinator_name, observation=f"OBSERVAÇÃO GERAL: {observation}", booking_date=week_start_date, period="Geral"))
        db.session.commit()
        send_general_observation_confirmation_email(user_email, user_name, coordinator_name, observation, week_start_date)
        return jsonify({"message": "Observação geral adicionada com sucesso!"}), 201
    
    booking_window = get_booking_window_status()
    today_brasilia = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(BRASILIA_TZ).date()
    current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
    next_week_monday = current_week_monday + timedelta(weeks=1)

    for slot in slots_data:
        booking_date_obj = datetime.strptime(slot["booking_date"], "%Y-%m-%d").date()
        if current_week_monday <= booking_date_obj < next_week_monday:
            if not booking_window["current_week"]["open"]: return jsonify({"error": "Agendamentos para a semana atual estão fechados."}), 403
        elif next_week_monday <= booking_date_obj < (next_week_monday + timedelta(weeks=1)):
            if not booking_window["next_week"]["open"]: return jsonify({"error": "Agendamentos para a próxima semana estão fechados."}), 403
        elif booking_date_obj < today_brasilia: return jsonify({"error": f"Agendamento para {slot['booking_date']} não pode ser no passado."}), 400
        else: return jsonify({"error": "Agendamentos só são permitidos para a semana atual ou próxima semana."}), 403
        if check_booking_conflict(slot["room_id"], booking_date_obj, slot["period"]): return jsonify({"error": f"A sala já está reservada."}), 409

    for slot in slots_data:
        db.session.add(Booking(user_name=user_name, user_email=user_email, coordinator_name=coordinator_name, observation=observation, room_id=slot["room_id"], booking_date=datetime.strptime(slot["booking_date"], "%Y-%m-%d").date(), period=slot["period"]))
    db.session.commit()
    send_booking_confirmation_email(user_email, user_name, coordinator_name, observation, [{"room_name": Room.query.get(s["room_id"]).name, "booking_date": s["booking_date"], "period": s["period"]} for s in slots_data])
    return jsonify({"message": "Agendamento(s) criado(s) com sucesso!"}), 201

@bookings_bp.route("/bookings", methods=["GET"])
def get_bookings():
    try:
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        query = Booking.query.outerjoin(Room)
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            query = query.filter(Booking.booking_date.between(start_date, end_date))
        
        bookings = query.all()
        sorted_rooms = sort_rooms_custom(Room.query.all())
        room_order = {room.id: index for index, room in enumerate(sorted_rooms)}

        def final_sort_key(booking):
            if not booking.room: return (999, booking.booking_date, 0 if booking.period == "Manhã" else 1)
            return (room_order.get(booking.room_id, 999), booking.booking_date, 0 if booking.period == "Manhã" else 1)
        bookings.sort(key=final_sort_key)

        result = [{"id": b.id, "user_name": b.user_name, "user_email": b.user_email, "coordinator_name": b.coordinator_name, "observation": b.observation, "room_id": b.room_id, "room_name": b.room.name if b.room else "Obs. Geral", "booking_date": b.booking_date.isoformat(), "period": b.period, "created_at": b.created_at.isoformat() if b.created_at else None} for b in bookings]
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar agendamentos: {str(e)}")
        return jsonify({"error": "Erro ao carregar agendamentos"}), 500

@bookings_bp.route("/generate-pdf", methods=["GET"])
def generate_schedule_pdf():
    # ... (código do PDF sem alterações)
    pass

@bookings_bp.route("/admin/clear-by-date", methods=["POST"])
@require_admin_key
def clear_bookings_by_date():
    # ... (código de limpar por data sem alterações)
    pass

@bookings_bp.route("/admin/booking", methods=["POST"])
@require_admin_key
def admin_create_or_update_booking():
    data = request.get_json()
    room_id, booking_date_str, period, user_name = data.get("room_id"), data.get("booking_date"), data.get("period"), data.get("user_name", "").strip()
    booking_date = datetime.strptime(booking_date_str, "%Y-%m-%d").date()
    existing_booking = Booking.query.filter_by(room_id=room_id, booking_date=booking_date, period=period).first()
    if not user_name:
        if existing_booking:
            db.session.delete(existing_booking)
            message = "Agendamento removido com sucesso"
        else:
            return jsonify({"message": "Nenhum agendamento para remover"}), 200
    elif existing_booking:
        existing_booking.user_name = user_name
        message = "Agendamento atualizado com sucesso"
    else:
        db.session.add(Booking(room_id=room_id, booking_date=booking_date, period=period, user_name=user_name, user_email="admin@edit.com", coordinator_name="Admin", observation="Editado pelo administrador"))
        message = "Agendamento criado com sucesso"
    db.session.commit()
    return jsonify({"message": message}), 201
