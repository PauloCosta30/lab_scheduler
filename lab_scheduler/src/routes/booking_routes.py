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
        admin_key = request.headers.get('X-Admin-Key')
        expected_key = current_app.config.get('ADMIN_KEY')
        if not expected_key:
            return jsonify({"error": "Configuração administrativa não encontrada"}), 500
        if not admin_key or admin_key != expected_key:
            return jsonify({"error": "Chave administrativa inválida ou ausente"}), 401
        return f(*args, **kwargs)
    return decorated_function

# ... (Funções de e-mail e helpers não foram alteradas) ...
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
    try:
        data = request.get_json()
        user_name = data.get("user_name")
        user_email = data.get("user_email")
        coordinator_name = data.get("coordinator_name")
        observation = data.get("observation", "")
        slots_data = data.get("slots")
        week_start_date_str = data.get("week_start_date") # NOVO: Recebe a data do frontend

        if not all([user_name, user_email]):
            return jsonify({"error": "Nome e e-mail do usuário são obrigatórios."}), 400
        
        if not slots_data:
            if not observation:
                return jsonify({"error": "É necessário selecionar ao menos uma sala ou fornecer uma observação."}), 400
            
            # --- LÓGICA CORRIGIDA PARA OBSERVAÇÃO GERAL ---
            if week_start_date_str:
                week_start_date = datetime.strptime(week_start_date_str, "%Y-%m-%d").date()
            else:
                # Fallback, caso o frontend não envie a data
                today_brasilia = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(BRASILIA_TZ).date()
                week_start_date = today_brasilia - timedelta(days=today_brasilia.weekday())
            
            db.session.add(Booking(user_name=user_name, user_email=user_email, coordinator_name=coordinator_name, observation=f"OBSERVAÇÃO GERAL: {observation}", booking_date=week_start_date, period="Geral"))
            db.session.commit()
            send_general_observation_confirmation_email(user_email, user_name, coordinator_name, observation, week_start_date)
            return jsonify({"message": "Observação geral adicionada com sucesso!"}), 201
        # --- FIM DA CORREÇÃO ---

        booking_window = get_booking_window_status()
        today_brasilia = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(BRASILIA_TZ).date()
        current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
        
        processed_slots = []
        daily_new_bookings_count = defaultdict(int)

        for slot in slots_data:
            booking_date_obj = datetime.strptime(slot["booking_date"], "%Y-%m-%d").date()
            
            is_current_week = current_week_monday <= booking_date_obj < (current_week_monday + timedelta(weeks=1))
            is_next_week = (current_week_monday + timedelta(weeks=1)) <= booking_date_obj < (current_week_monday + timedelta(weeks=2))

            if is_current_week:
                if not booking_window["current_week"]["open"]: return jsonify({"error": "Agendamentos para a semana atual estão fechados."}), 403
            elif is_next_week:
                if not booking_window["next_week"]["open"]: return jsonify({"error": "Agendamentos para a próxima semana estão fechados."}), 403
            else:
                return jsonify({"error": "Agendamentos só são permitidos para a semana atual ou próxima semana."}), 403

            if Booking.query.filter_by(room_id=slot["room_id"], booking_date=booking_date_obj, period=slot["period"]).first():
                return jsonify({"error": f"A sala no dia {slot['booking_date']} ({slot['period']}) já está reservada."}), 409

            room = Room.query.get(slot["room_id"])
            if not room: return jsonify({"error": "Sala não encontrada."}), 404

            processed_slots.append({"room_id": room.id, "room_name": room.name, "booking_date": booking_date_obj, "period": slot["period"]})
            daily_new_bookings_count[booking_date_obj] += 1

        for b_date, count in daily_new_bookings_count.items():
            existing_count = Booking.query.filter_by(user_name=user_name, booking_date=b_date).count()
            if (existing_count + count) > MAX_BOOKINGS_PER_DAY:
                return jsonify({"error": f"Limite de {MAX_BOOKINGS_PER_DAY} agendamentos por dia seria excedido em {b_date.strftime('%d/%m/%Y')}."}), 409

        geral_slots_by_day_period = defaultdict(int)
        for slot in processed_slots:
            if slot["room_name"].startswith("Geral "):
                key = (slot["booking_date"], slot["period"])
                geral_slots_by_day_period[key] += 1
        
        for (b_date, period), count in geral_slots_by_day_period.items():
            if count > 1:
                return jsonify({"error": f"Não é permitido agendar mais de uma sala 'Geral' no mesmo período ({period} de {b_date.strftime('%d/%m/%Y')})."}), 409
            
            existing_geral = Booking.query.join(Room).filter(
                Booking.user_name == user_name,
                Booking.booking_date == b_date,
                Booking.period == period,
                Room.name.startswith("Geral ")
            ).first()
            if existing_geral:
                return jsonify({"error": f"Você já possui um agendamento na sala '{existing_geral.room.name}' para o período ({period} de {b_date.strftime('%d/%m/%Y')})."}), 409

        for slot in processed_slots:
            db.session.add(Booking(user_name=user_name, user_email=user_email, coordinator_name=coordinator_name, observation=observation, room_id=slot["room_id"], booking_date=slot["booking_date"], period=slot["period"]))
        
        db.session.commit()
        
        email_details = [{"room_name": s["room_name"], "booking_date": s["booking_date"].strftime('%Y-%m-%d'), "period": s["period"]} for s in processed_slots]
        send_booking_confirmation_email(user_email, user_name, coordinator_name, observation, email_details)
        
        return jsonify({"message": "Agendamento(s) criado(s) com sucesso!"}), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao criar agendamento: {str(e)}")
        return jsonify({"error": "Ocorreu um erro interno no servidor."}), 500

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
    try:
        if not WEASYPRINT_AVAILABLE:
            return jsonify({"error": "Geração de PDF não está disponível no servidor."}), 503
            
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        
        if not start_date_str or not end_date_str:
            return jsonify({"error": "Parâmetros start_date e end_date são obrigatórios."}), 400
        
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        
        bookings = Booking.query.outerjoin(Room).filter(Booking.booking_date.between(start_date, end_date)).all()
        all_rooms = sort_rooms_custom(Room.query.all())
        
        dates_of_week = []
        current_d = start_date
        while current_d <= end_date:
            if current_d.weekday() < 5:
                dates_of_week.append(current_d)
            current_d += timedelta(days=1)

        schedule_data = {d.isoformat(): {"Manhã": {}, "Tarde": {}} for d in dates_of_week}
        user_observations = defaultdict(lambda: {'email': '', 'coordinator': '', 'bookings': []})
        general_observations = []

        for b in bookings:
            if b.period == "Geral":
                general_observations.append({'user_name': b.user_name, 'observation': b.observation.replace("OBSERVAÇÃO GERAL: ", ""), 'date': b.booking_date})
                continue

            if b.room:
                date_str = b.booking_date.isoformat()
                if date_str in schedule_data:
                    schedule_data[date_str][b.period][b.room.name] = b.user_name
            
            if b.observation and b.observation.strip():
                user_name = b.user_name
                user_observations[user_name]['email'] = b.user_email
                user_observations[user_name]['coordinator'] = b.coordinator_name or ''
                user_observations[user_name]['bookings'].append({
                    'room_name': b.room.name if b.room else 'N/A',
                    'date': b.booking_date,
                    'period': b.period,
                    'observation': b.observation
                })

        now_brasilia = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(BRASILIA_TZ)
        
        template_data = {
            'all_rooms': all_rooms,
            'dates_of_week': dates_of_week,
            'schedule_data': schedule_data,
            'user_observations': dict(user_observations),
            'general_observations': general_observations,
            'start_date': start_date,
            'end_date': end_date,
            'generated_at': now_brasilia
        }
        
        html_content = render_template('schedule_pdf_template.html', **template_data)
        pdf_bytes = HTML(string=html_content).write_pdf()
        
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=escala_{start_date_str}_a_{end_date_str}.pdf'
        return response
        
    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": "Erro interno ao gerar PDF"}), 500

@bookings_bp.route("/admin/clear-by-date", methods=["POST"])
@require_admin_key
def clear_bookings_by_date():
    try:
        data = request.get_json()
        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")
        if not start_date_str or not end_date_str:
            return jsonify({"error": "start_date e end_date são obrigatórios"}), 400
        
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        
        num_deleted = db.session.query(Booking).filter(Booking.booking_date.between(start_date, end_date)).delete()
        db.session.commit()
        
        return jsonify({"message": f"{num_deleted} agendamentos entre {start_date_str} e {end_date_str} foram apagados."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Erro ao apagar agendamentos: {str(e)}"}), 500

@bookings_bp.route("/admin/booking", methods=["POST"])
@require_admin_key
def admin_create_or_update_booking():
    try:
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
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro na rota admin/booking: {str(e)}")
        return jsonify({"error": "Erro interno do servidor", "details": str(e)}), 500
