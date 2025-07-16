# /src/routes/booking_routes.py

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
        html_body += "<p>Obrigado! Observação: Em caso de dúvidas sobre a escala, entre em contato com Ana Correa pelo e-mail: ana.correa@itv.org</p>"

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
        
        today_brasilia = now_brasilia.date()
        current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
        
        next_week_monday = current_week_monday + timedelta(weeks=1)
        
        current_week_cutoff_date = current_week_monday + timedelta(days=2) # Quarta-feira
        current_week_cutoff_time = time(18, 0, 0) # 18:00
        current_week_cutoff_datetime = BRASILIA_TZ.localize(datetime.combine(current_week_cutoff_date, current_week_cutoff_time))

        next_week_open_date = current_week_monday + timedelta(days=4) # Sexta-feira
        next_week_open_time = time(18, 0, 0) # 18:00
        next_week_open_datetime = BRASILIA_TZ.localize(datetime.combine(next_week_open_date, next_week_open_time))

        next_week_cutoff_date = next_week_monday + timedelta(days=2) # Quarta-feira da próxima semana
        next_week_cutoff_time = time(18, 0, 0) # 18:00
        next_week_cutoff_datetime = BRASILIA_TZ.localize(datetime.combine(next_week_cutoff_date, next_week_cutoff_time))

        status = {
            "current_week": {"open": False, "message": "Fechado"},
            "next_week": {"open": False, "message": "Fechado"},
            "general_message": "As escolhas para a semana atual sempre serão encerradas às quartas-feiras, às 18h, e a escala da próxima semana será liberada todas as sextas-feiras, às 18h."
        }

        if now_brasilia <= current_week_cutoff_datetime:
            status["current_week"]["open"] = True
            status["current_week"]["message"] = "Aberto até quarta-feira às 18:00"
        else:
            status["current_week"]["message"] = "Fechado (após quarta-feira 18:00)"

        if now_brasilia >= next_week_open_datetime and now_brasilia <= next_week_cutoff_datetime:
            status["next_week"]["open"] = True
            status["next_week"]["message"] = "Aberto para a próxima semana"
        elif now_brasilia < next_week_open_datetime:
            status["next_week"]["message"] = f"Abre na sexta-feira às 18:00 ({next_week_open_date.strftime('%d/%m')})"
        else:
            status["next_week"]["message"] = "Fechado (após quarta-feira 18:00 da próxima semana)"

        return status
    except Exception as e:
        current_app.logger.error(f"Erro ao obter status da janela de agendamento: {str(e)}")
        return {
            "current_week": {"open": False, "message": "Erro no sistema"},
            "next_week": {"open": False, "message": "Erro no sistema"},
            "general_message": "As escolhas para a semana atual sempre serão encerradas às quartas-feiras, às 18h, e a escala da próxima semana será liberada todas as sextas-feiras, às 18h."
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

        if not all([user_name, user_email]):
            return jsonify({"error": "Missing fields. Required: user_name, user_email, slots"}), 400
        
        if not slots_data and not observation:
            return jsonify({"error": "Missing fields. Required: slots or observation"}), 400

        if not slots_data and observation:
            today_brasilia = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(BRASILIA_TZ).date()
            general_obs_booking = Booking(
                user_name=user_name,
                user_email=user_email,
                coordinator_name=coordinator_name,
                observation=f"OBSERVAÇÃO GERAL: {observation}",
                room_id=None,
                booking_date=today_brasilia,
                period="Geral"
            )
            db.session.add(general_obs_booking)
            db.session.commit()
            return jsonify({
                "message": "Observação geral adicionada com sucesso!",
                "observation": observation
            }), 201

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
            
            now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
            now_brasilia = now_utc.astimezone(BRASILIA_TZ)
            today_brasilia = now_brasilia.date()
            current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
            next_week_monday = current_week_monday + timedelta(weeks=1)

            if booking_date_obj.weekday() >= 5:
                return jsonify({"error": f"Agendamentos para {booking_date_str} são permitidos apenas de segunda a sexta-feira."}), 400

            if booking_date_obj < today_brasilia:
                return jsonify({"error": f"Agendamento para {booking_date_str} não pode ser no passado."}), 400
            
            if current_week_monday <= booking_date_obj < next_week_monday:
                if not booking_window["current_week"]["open"]:
                    return jsonify({"error": f"Agendamentos para a semana atual estão fechados. {booking_window['current_week']['message']}"}), 403
            elif next_week_monday <= booking_date_obj < (next_week_monday + timedelta(weeks=1)):
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

        for booking_date_obj, count_for_this_request in daily_new_bookings_count.items():
            existing_bookings_on_day = Booking.query.filter_by(user_name=user_name, booking_date=booking_date_obj).count()
            if (existing_bookings_on_day + count_for_this_request) > MAX_BOOKINGS_PER_DAY:
                return jsonify({
                    "error": f"Limite de {MAX_BOOKINGS_PER_DAY} agendamentos por dia para o usuário '{user_name}' seria excedido no dia {booking_date_obj.strftime('%Y-%m-%d')}."
                }), 409

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

@bookings_bp.route("/general-observation", methods=["POST"])
def add_general_observation():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid input"}), 400

        user_name = data.get("user_name")
        user_email = data.get("user_email")
        observation = data.get("observation", "")
        week_start_date_str = data.get("week_start_date")

        if not all([user_name, user_email, observation, week_start_date_str]):
            return jsonify({"error": "Missing fields. Required: user_name, user_email, observation, week_start_date"}), 400

        if "@" not in user_email or "." not in user_email.split("@")[-1]:
            return jsonify({"error": "Invalid email format"}), 400

        try:
            week_start_date = datetime.strptime(week_start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date format for week_start_date. Use YYYY-MM-DD"}), 400

        general_obs_booking = Booking(
            user_name=user_name,
            user_email=user_email,
            coordinator_name="",
            observation=f"OBSERVAÇÃO GERAL: {observation}",
            room_id=None,
            booking_date=week_start_date,
            period="Geral"
        )
        
        db.session.add(general_obs_booking)
        db.session.commit()

        return jsonify({
            "message": "Observação geral adicionada com sucesso!",
            "observation": observation
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Falha ao adicionar observação geral: {str(e)}")
        return jsonify({"error": "Falha ao adicionar observação geral.", "details": str(e)}), 500

@bookings_bp.route("/bookings", methods=["GET"])
def get_bookings():
    try:
        target_date_str = request.args.get("date")
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        
        query = Booking.query.outerjoin(Room).order_by(Booking.booking_date, Booking.period)
        
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
                if booking.period == "Geral":
                    return (999, 999)
                
                if booking.room:
                    room_name = booking.room.name
                    if room_name.startswith("Geral "):
                        try:
                            number = int(re.findall(r'\d+', room_name)[0])
                            return (0, number)
                        except (IndexError, ValueError):
                            return (0, 999)
                    else:
                        return (1, booking.room.id)
                else:
                    return (999, 999)
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
                "room_name": booking.room.name if booking.room else "Observação Geral", 
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
    """Gera PDF da escala semanal com observações organizadas por usuário e observações gerais"""
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
        
        current_app.logger.info(f"Gerando PDF para período: {start_date} a {end_date}")
        
        bookings = Booking.query.outerjoin(Room).filter(
            Booking.booking_date.between(start_date, end_date)
        ).order_by(Booking.booking_date, Booking.period).all()
        
        current_app.logger.info(f"Encontrados {len(bookings)} agendamentos")
        
        rooms = Room.query.all()
        sorted_rooms = sort_rooms_custom(rooms)
        
        def ensure_date(date_input):
            if isinstance(date_input, date): return date_input
            if isinstance(date_input, datetime): return date_input.date()
            if isinstance(date_input, str):
                try: return datetime.strptime(date_input, "%Y-%m-%d").date()
                except ValueError:
                    try: return datetime.fromisoformat(date_input.replace('Z', '+00:00')).date()
                    except ValueError: return None
            return None

        dates_of_week = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:
                dates_of_week.append(current_date)
            current_date += timedelta(days=1)

        schedule_data = {}
        for d in dates_of_week:
            date_str = d.isoformat()
            schedule_data[date_str] = {
                "Manhã": {room.name: "" for room in sorted_rooms},
                "Tarde": {room.name: "" for room in sorted_rooms}
            }
        
        # <<< INÍCIO DA LÓGICA CORRIGIDA PARA OBSERVAÇÕES >>>
        
        user_info = defaultdict(lambda: {
            'email': '',
            'coordinator': '',
            'observation': '', # Campo para a observação principal do usuário
            'bookings': []
        })
        
        general_observations = []

        for booking in bookings:
            booking_date = ensure_date(booking.booking_date)
            if not booking_date: continue

            # Processa observações gerais (sem sala)
            if booking.period == "Geral":
                general_observations.append({
                    'user_name': booking.user_name,
                    'observation': booking.observation.replace("OBSERVAÇÃO GERAL: ", ""),
                    'date': booking_date
                })
                continue

            # Processa agendamentos normais
            user_name = booking.user_name
            user_info[user_name]['email'] = booking.user_email
            user_info[user_name]['coordinator'] = booking.coordinator_name or ''
            
            # Captura a observação do primeiro agendamento do usuário como a principal
            if booking.observation and not user_info[user_name]['observation']:
                 user_info[user_name]['observation'] = booking.observation

            # Adiciona o agendamento à lista do usuário
            if booking.room:
                user_info[user_name]['bookings'].append({
                    'room_name': booking.room.name,
                    'date': booking_date,
                    'period': booking.period
                })
                
                # Preenche a tabela da escala
                date_str = booking_date.isoformat()
                if date_str in schedule_data:
                    schedule_data[date_str][booking.period][booking.room.name] = user_name

        # <<< FIM DA LÓGICA CORRIGIDA >>>

        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_brasilia = now_utc.astimezone(BRASILIA_TZ)
        
        current_app.logger.info("Preparando dados para o template HTML")
        
        template_data = {
            'all_rooms': sorted_rooms,
            'dates_of_week': dates_of_week,
            'schedule_data': schedule_data,
            'user_info': dict(user_info), # <<< ALTERAÇÃO: Passa a nova estrutura de dados
            'general_observations': general_observations,
            'start_date': start_date,
            'end_date': end_date,
            'generated_at': now_brasilia,
            'zip': zip
        }
        
        html_content = render_template('schedule_pdf_template.html', **template_data)
        
        current_app.logger.info("Template HTML renderizado, gerando PDF")
        
        pdf_bytes = HTML(string=html_content).write_pdf(presentational_hints=True)
        
        current_app.logger.info("PDF gerado com sucesso")
        
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=escala_agendamentos_{start_date_str}_a_{end_date_str}.pdf'
        
        return response
        
    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {str(e)}")
        import traceback
        current_app.logger.error(f"Traceback completo: {traceback.format_exc()}")
        return jsonify({"error": "Erro interno ao gerar PDF", "details": str(e)}), 500


