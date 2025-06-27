# /home/ubuntu/lab_scheduler/src/routes/booking_routes.py

from flask import Blueprint, request, jsonify, current_app, render_template, make_response
from src.extensions import db
from src.models.entities import Room, Booking
from datetime import datetime, date, timedelta, time
from collections import defaultdict
from flask_mail import Message
import re
import pytz # Importar pytz para lidar com fusos horários
from functools import wraps

# Importação condicional do weasyprint
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    current_app.logger.warning("WeasyPrint não está disponível. Geração de PDF desabilitada.")

bookings_bp = Blueprint("bookings_bp", __name__)

MAX_BOOKINGS_PER_DAY = 3

# Definir o fuso horário de Brasília
BRASILIA_TZ = pytz.timezone("America/Sao_Paulo")

# Decorator para verificar chave administrativa
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

# Helper function to send confirmation email
def send_booking_confirmation_email(user_email, user_name, coordinator_name, observation, booked_slots_details):
    try:
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

        mail.send(msg)
        current_app.logger.info(f"Email de confirmação enviado para {user_email}")
        return True
    except Exception as e:
        current_app.logger.error(f"Falha ao enviar email para {user_email}: {str(e)}")
        return False

# Helper function to check for conflicts
def check_booking_conflict(room_id, booking_date_obj, period):
    try:
        existing_booking = Booking.query.filter_by(
            room_id=room_id,
            booking_date=booking_date_obj,
            period=period
        ).first()
        return existing_booking is not None
    except Exception as e:
        current_app.logger.error(f"Erro ao verificar conflito de agendamento: {str(e)}")
        return False

# Helper function to sort rooms with custom logic for "Geral" rooms
def sort_rooms_custom(rooms):
    """Ordena salas colocando as 'Geral' em ordem numérica correta"""
    def room_sort_key(room):
        try:
            name = room.name
            if name.startswith("Geral "):
                try:
                    number = int(re.findall(r'\d+', name)[0])
                    return (0, number)
                except (IndexError, ValueError):
                    return (0, 999)
            else:
                return (1, room.id)
        except Exception:
            return (999, 999)
    
    return sorted(rooms, key=room_sort_key)

# Função para determinar o status da janela de agendamento
def get_booking_window_status():
    try:
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
    except Exception as e:
        current_app.logger.error(f"Erro ao obter status da janela de agendamento: {str(e)}")
        return {
            "current_week": {"open": False, "message": "Erro no sistema"},
            "next_week": {"open": False, "message": "Erro no sistema"}
        }

@bookings_bp.route("/booking-window-status", methods=["GET"])
def booking_window_status():
    try:
        status = get_booking_window_status()
        return jsonify(status)
    except Exception as e:
        current_app.logger.error(f"Erro na rota booking-window-status: {str(e)}")
        return jsonify({"error": "Erro interno do servidor"}), 500

@bookings_bp.route("/rooms", methods=["GET"])
def get_rooms():
    try:
        rooms = Room.query.all()
        sorted_rooms = sort_rooms_custom(rooms)
        return jsonify([{"id": room.id, "name": room.name} for room in sorted_rooms])
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar salas: {str(e)}")
        return jsonify({"error": "Erro ao carregar salas"}), 500

@bookings_bp.route("/bookings", methods=["POST"])
def create_booking():
    try:
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
    try:
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
            try:
                room_name = booking.room.name
                if room_name.startswith("Geral "):
                    try:
                        number = int(re.findall(r'\d+', room_name)[0])
                        return (0, number)
                    except (IndexError, ValueError):
                        return (0, 999)
                else:
                    return (1, booking.room.id)
            except Exception:
                return (999, 999)
        
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
    
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar agendamentos: {str(e)}")
        return jsonify({"error": "Erro ao carregar agendamentos"}), 500

@bookings_bp.route("/generate-pdf", methods=["GET"])
def generate_schedule_pdf():
    """Gera PDF da escala semanal com observações organizadas por usuário"""
    try:
        if not WEASYPRINT_AVAILABLE:
            return jsonify({"error": "Geração de PDF não está disponível no servidor"}), 503
            
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
    try:
        status = get_booking_window_status()
        return jsonify(status)
    except Exception as e:
        current_app.logger.error(f"Erro na rota get-booking-status: {str(e)}")
        return jsonify({"error": "Erro interno do servidor"}), 500

# ===============================
# ROTAS ADMINISTRATIVAS
# ===============================

@bookings_bp.route("/admin/database/status", methods=["GET"])
@require_admin_key
def admin_database_status():
    """Retorna estatísticas do banco de dados"""
    try:
        bookings_count = Booking.query.count()
        rooms_count = Room.query.count()
        
        # Estatísticas por período
        bookings_by_period = db.session.query(
            Booking.period, 
            db.func.count(Booking.id)
        ).group_by(Booking.period).all()
        
        # Agendamentos por mês
        bookings_by_month = db.session.query(
            db.func.strftime('%Y-%m', Booking.booking_date),
            db.func.count(Booking.id)
        ).group_by(db.func.strftime('%Y-%m', Booking.booking_date)).all()
        
        # Usuários únicos
        unique_users = db.session.query(Booking.user_name).distinct().count()
        
        # Agendamentos futuros
        today = datetime.now().date()
        future_bookings = Booking.query.filter(Booking.booking_date >= today).count()
        
        return jsonify({
            "total_bookings": bookings_count,
            "total_rooms": rooms_count,
            "unique_users": unique_users,
            "future_bookings": future_bookings,
            "bookings_by_period": dict(bookings_by_period),
            "bookings_by_month": dict(bookings_by_month)
        })
    except Exception as e:
        current_app.logger.error(f"Erro ao obter status do banco: {str(e)}")
        return jsonify({"error": "Erro ao obter estatísticas do banco de dados"}), 500

@bookings_bp.route("/admin/bookings/delete", methods=["DELETE"])
@require_admin_key
def admin_delete_bookings():
    """
    Apaga agendamentos com filtros opcionais:
    - date: data específica (YYYY-MM-DD)
    - start_date/end_date: intervalo de datas
    - user_name: agendamentos de usuário específico
    - room_id: agendamentos de sala específica
    - before_date: agendamentos antes de uma data
    - all: apagar todos os agendamentos (requer confirmação)
    """
    try:
        # Parâmetros de filtro
        target_date_str = request.args.get("date")
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        user_name = request.args.get("user_name")
        room_id = request.args.get("room_id")
        before_date_str = request.args.get("before_date")
        delete_all = request.args.get("all", "").lower() == "true"
        confirm = request.args.get("confirm", "").lower() == "true"
        
        query = Booking.query
        
        # Aplicar filtros
        if delete_all:
            if not confirm:
                return jsonify({
                    "error": "Para apagar todos os agendamentos, adicione '&confirm=true' à URL"
                }), 400
        else:
            filters_applied = False
            
            if target_date_str:
                try:
                    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
                    query = query.filter(Booking.booking_date == target_date)
                    filters_applied = True
                except ValueError:
                    return jsonify({"error": "Formato de data inválido para 'date'. Use YYYY-MM-DD"}), 400
            
            if start_date_str and end_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                    query = query.filter(Booking.booking_date.between(start_date, end_date))
                    filters_applied = True
                except ValueError:
                    return jsonify({"error": "Formato de data inválido para 'start_date' ou 'end_date'. Use YYYY-MM-DD"}), 400
            
            if before_date_str:
                try:
                    before_date = datetime.strptime(before_date_str, "%Y-%m-%d").date()
                    query = query.filter(Booking.booking_date < before_date)
                    filters_applied = True
                except ValueError:
                    return jsonify({"error": "Formato de data inválido para 'before_date'. Use YYYY-MM-DD"}), 400
            
            if user_name:
                query = query.filter(Booking.user_name == user_name)
                filters_applied = True
            
            if room_id:
                try:
                    room_id_int = int(room_id)
                    query = query.filter(Booking.room_id == room_id_int)
                    filters_applied = True
                except ValueError:
                    return jsonify({"error": "room_id deve ser um número inteiro"}), 400
            
            if not filters_applied:
                return jsonify({
                    "error": "Pelo menos um filtro deve ser especificado (date, start_date/end_date, user_name, room_id, before_date, ou all=true)"
                }), 400
        
        # Contar agendamentos que serão deletados
        bookings_to_delete = query.all()
        count_to_delete = len(bookings_to_delete)
        
        if count_to_delete == 0:
            return jsonify({
                "message": "Nenhum agendamento encontrado com os filtros especificados",
                "deleted_count": 0
            })
        
        # Criar log dos agendamentos que serão deletados
        deleted_bookings_log = []
        for booking in bookings_to_delete:
            deleted_bookings_log.append({
                "id": booking.id,
                "user_name": booking.user_name,
                "user_email": booking.user_email,
                "room_name": booking.room.name,
                "booking_date": booking.booking_date.isoformat(),
                "period": booking.period,
                "created_at": booking.created_at.isoformat() if booking.created_at else None
            })
        
        # Deletar agendamentos
        for booking in bookings_to_delete:
            db.session.delete(booking)
        
        db.session.commit()
        
        current_app.logger.warning(f"ADMIN: {count_to_delete} agendamentos deletados. Filtros utilizados: "
                                 f"date={target_date_str}, start_date={start_date_str}, end_date={end_date_str}, "
                                 f"user_name={user_name}, room_id={room_id}, before_date={before_date_str}, all={delete_all}")
        
        return jsonify({
            "message": f"{count_to_delete} agendamento(s) deletado(s) com sucesso",
            "deleted_count": count_to_delete,
            "deleted_bookings": deleted_bookings_log
        })
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao deletar agendamentos: {str(e)}")
        return jsonify({"error": "Erro ao deletar agendamentos", "details": str(e)}), 500

@bookings_bp.route("/admin/bookings/delete/<int:booking_id>", methods=["DELETE"])
@require_admin_key
def admin_delete_booking_by_id(booking_id):
    """Apaga um agendamento específico pelo ID"""
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({"error": f"Agendamento com ID {booking_id} não encontrado"}), 404
        
        booking_info = {
            "id": booking.id,
            "user_name": booking.user_name,
            "user_email": booking.user_email,
            "room_name": booking.room.name,
            "booking_date": booking.booking_date.isoformat(),
            "period": booking.period
        }
        
        db.session.delete(booking)
        db.session.commit()
        
        current_app.logger.warning(f"ADMIN: Agendamento ID {booking_id} deletado: {booking_info}")
        
        return jsonify({
            "message": f"Agendamento ID {booking_id} deletado com sucesso",
            "deleted_booking": booking_info
        })
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao deletar agendamento ID {booking_id}: {str(e)}")
        return jsonify({"error": "Erro ao deletar agendamento", "details": str(e)}), 500

@bookings_bp.route("/admin/database/clear", methods=["DELETE"])
@require_admin_key
def admin_clear_database():
    """Limpa completamente o banco de dados (apenas agendamentos, mantém salas)"""
    try:
        confirm = request.args.get("confirm", "").lower() == "true"
        
        if not confirm:
            return jsonify({
                "error": "Esta operação apagará TODOS os agendamentos do banco de dados. "
                        "Para confirmar, adicione '&confirm=true' à URL"
            }), 400
        
        # Contar agendamentos antes de deletar
        total_bookings = Booking.query.count()
        
        # Deletar todos os agendamentos
        Booking.query.delete()
        db.session.commit()
        
        current_app.logger.warning(f"ADMIN: Banco de dados limpo. {total_bookings} agendamentos deletados.")
        
        return jsonify({
            "message": "Banco de dados limpo com sucesso",
            "deleted_bookings_count": total_bookings,
            "remaining_rooms": Room.query.count()
        })
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao limpar banco de dados: {str(e)}")
        return jsonify({"error": "Erro ao limpar banco de dados", "details": str(e)}), 500

@bookings_bp.route("/admin/bookings/cleanup", methods=["DELETE"])
@require_admin_key
def admin_cleanup_old_bookings():
    """Remove agendamentos antigos (por padrão, mais de 30 dias)"""
    try:
        days_ago = request.args.get("days", "30")
        confirm = request.args.get("confirm", "").lower() == "true"
        
        try:
            days_int = int(days_ago)
        except ValueError:
            return jsonify({"error": "Parâmetro 'days' deve ser um número inteiro"}), 400
        
        if not confirm:
            return jsonify({
                "error": f"Esta operação apagará agendamentos com mais de {days_int} dias. "
                        "Para confirmar, adicione '&confirm=true' à URL"
            }), 400
        
        cutoff_date = datetime.now().date() - timedelta(days=days_int)
        
        old_bookings = Booking.query.filter(Booking.booking_date < cutoff_date).all()
        count_to_delete = len(old_bookings)
        
        if count_to_delete == 0:
            return jsonify({
                "message": f"Nenhum agendamento encontrado com mais de {days_int} dias",
                "deleted_count": 0
            })
        
        # Log dos agendamentos que serão deletados
        deleted_bookings_log = []
        for booking in old_bookings:
            deleted_bookings_log.append({
                "id": booking.id,
                "user_name": booking.user_name,
                "room_name": booking.room.name,
                "booking_date": booking.booking_date.isoformat(),
                "period": booking.period
            })
            db.session.delete(booking)
        
        db.session.commit()
        
        current_app.logger.info(f"ADMIN: Limpeza automática executada. {count_to_delete} agendamentos "
                               f"com mais de {days_int} dias foram deletados.")
        
        return jsonify({
            "message": f"{count_to_delete} agendamento(s) antigo(s) deletado(s) com sucesso",
            "deleted_count": count_to_delete,
            "cutoff_date": cutoff_date.isoformat(),
            "deleted_bookings": deleted_bookings_log
        })
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro na limpeza de agendamentos antigos: {str(e)}")
        return jsonify({"error": "Erro na limpeza de agendamentos antigos", "details": str(e)}), 500

@bookings_bp.route("/admin/rooms", methods=["POST"])
@require_admin_key
def admin_create_room():
    """Cria uma nova sala"""
    try:
        data = request.get_json()
        if not data or not data.get("name"):
            return jsonify({"error": "Nome da sala é obrigatório"}), 400
        
        room_name = data["name"].strip()
        
        # Verificar se a sala já existe
        existing_room = Room.query.filter_by(name=room_name).first()
        if existing_room:
            return jsonify({"error": f"Sala '{room_name}' já existe"}), 409
        
        new_room = Room(name=room_name)
        db.session.add(new_room)
        db.session.commit()
        
        current_app.logger.info(f"ADMIN: Nova sala criada: {room_name} (ID: {new_room.id})")
        
        return jsonify({
            "message": f"Sala '{room_name}' criada com sucesso",
            "room": {"id": new_room.id, "name": new_room.name}
        }), 201
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao criar sala: {str(e)}")
        return jsonify({"error": "Erro ao criar sala", "details": str(e)}), 500

@bookings_bp.route("/admin/rooms/<int:room_id>", methods=["DELETE"])
@require_admin_key
def admin_delete_room(room_id):
    """Deleta uma sala (e todos os seus agendamentos)"""
    try:
        room = Room.query.get(room_id)
        if not room:
            return jsonify({"error": f"Sala com ID {room_id} não encontrada"}), 404
        
        # Contar agendamentos associados
        bookings_count = Booking.query.filter_by(room_id=room_id).count()
        
        # Deletar agendamentos associados
        Booking.query.filter_by(room_id=room_id).delete()
        
        room_name = room.name
        db.session.delete(room)
        db.session.commit()
        
        current_app.logger.warning(f"ADMIN: Sala '{room_name}' (ID: {room_id}) deletada junto com "
                                 f"{bookings_count} agendamento(s) associado(s)")
        
        return jsonify({
            "message": f"Sala '{room_name}' deletada com sucesso",
            "deleted_bookings_count": bookings_count
        })
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao deletar sala ID {room_id}: {str(e)}")
        return jsonify({"error": "Erro ao deletar sala", "details": str(e)}), 500

@bookings_bp.route("/admin/export/bookings", methods=["GET"])
@require_admin_key
def admin_export_bookings():
    """Exporta todos os agendamentos em formato JSON"""
    try:
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        
        query = Booking.query.join(Room).order_by(Booking.booking_date, Booking.period)
        
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                query = query.filter(Booking.booking_date.between(start_date, end_date))
            except ValueError:
                return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400
        
        bookings = query.all()
        
        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "total_bookings": len(bookings),
            "date_range": {
                "start": start_date_str,
                "end": end_date_str
            } if start_date_str and end_date_str else None,
            "bookings": []
        }
        
        for booking in bookings:
            export_data["bookings"].append({
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
        
        response = make_response(jsonify(export_data))
        filename = f"bookings_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        return response
    
    except Exception as e:
        current_app.logger.error(f"Erro ao exportar agendamentos: {str(e)}")
        return jsonify({"error": "Erro ao exportar agendamentos", "details": str(e)}), 500
