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
from datetime import datetime, date, timedelta, time

# Importação condicional do weasyprint
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    current_app.logger.warning("WeasyPrint não está disponível. Geração de PDF desabilitada.")

bookings_bp = Blueprint("bookings_bp", __name__)


# REGISTRO DO FILTRO date_from_string
@bookings_bp.app_template_filter('date_from_string')
def date_from_string_filter(date_str):
    try:
        if isinstance(date_str, str):
            for fmt in ['%Y-%m-%d', '%d/%m/%Y']:
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        elif isinstance(date_str, date):
            return date_str
        elif isinstance(date_str, datetime):
            return date_str.date()
    except Exception:
        pass
    return None

# REGISTRO DO FILTRO format_weekday
@bookings_bp.app_template_filter('format_weekday')
def format_weekday_filter(date_obj):
    weekdays = {
        0: 'Segunda-feira', 1: 'Terça-feira', 2: 'Quarta-feira',
        3: 'Quinta-feira', 4: 'Sexta-feira', 5: 'Sábado', 6: 'Domingo'
    }
    if isinstance(date_obj, str):
        date_obj = date_from_string_filter(date_obj)
    if date_obj:
        return weekdays.get(date_obj.weekday(), '')
    return ''

# REGISTRO DA FUNÇÃO zip para templates
@bookings_bp.app_template_global('zip')
def zip_template(*args):
    return zip(*args)


MAX_BOOKINGS_PER_DAY = 3

# Definir o fuso horário de Brasília
BRASILIA_TZ = pytz.timezone("America/Sao_Paulo")

# Decorator para verificar chave administrativa
def require_admin_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin_key = request.headers.get("X-Admin-Key") or request.args.get("admin_key")
        expected_key = current_app.config.get("ADMIN_KEY")
        
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
            
        # Permitir envio de email mesmo sem slots específicos de sala
        if not booked_slots_details and not observation:
            current_app.logger.info("No booking details or observation to send in email.")
            return False

        subject = "Confirmação de Agendamento de Laboratório"
        sender = current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@example.com")
        recipients = [user_email]

        html_body = f"""\
        <p>Olá {user_name},</p>
        """
        
        if booked_slots_details:
            html_body += "<p>Seu agendamento de laboratório foi confirmado com sucesso. Detalhes abaixo:</p><ul>"
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
        
        if observation:
            html_body += f"<p><strong>Observação registrada:</strong> {observation}</p>"
        
        if coordinator_name:
            html_body += f"<p>Coordenador: {coordinator_name}</p>"
            
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

# Rota de debug temporária - remover em produção
@bookings_bp.route("/debug-booking-window", methods=["GET"])
@require_admin_key
def debug_booking_window():
    try:
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_brasilia = now_utc.astimezone(BRASILIA_TZ)
        
        today_brasilia = now_brasilia.date()
        current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
        next_week_monday = current_week_monday + timedelta(weeks=1)
        
        current_week_cutoff_date = current_week_monday + timedelta(days=2)
        current_week_cutoff_datetime = BRASILIA_TZ.localize(datetime.combine(current_week_cutoff_date, time(23, 59, 59)))
        
        next_week_open_date = current_week_monday + timedelta(days=4)
        next_week_open_datetime = BRASILIA_TZ.localize(datetime.combine(next_week_open_date, time(18, 0, 0)))
        
        next_week_cutoff_date = next_week_monday + timedelta(days=2)
        next_week_cutoff_datetime = BRASILIA_TZ.localize(datetime.combine(next_week_cutoff_date, time(23, 59, 59)))
        
        return jsonify({
            "agora_brasilia": now_brasilia.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "hoje_brasilia": today_brasilia.strftime("%Y-%m-%d"),
            "segunda_semana_atual": current_week_monday.strftime("%Y-%m-%d"),
            "segunda_proxima_semana": next_week_monday.strftime("%Y-%m-%d"),
            "cutoff_semana_atual": current_week_cutoff_datetime.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "abertura_proxima_semana": next_week_open_datetime.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "cutoff_proxima_semana": next_week_cutoff_datetime.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "comparacoes": {
                "agora_antes_cutoff_atual": now_brasilia <= current_week_cutoff_datetime,
                "agora_depois_abertura_proxima": now_brasilia >= next_week_open_datetime,
                "agora_antes_cutoff_proxima": now_brasilia <= next_week_cutoff_datetime
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Função para determinar o status da janela de agendamento
# Função para determinar o status da janela de agendamento (CORRIGIDA)
def get_booking_window_status():
    try:
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_brasilia = now_utc.astimezone(BRASILIA_TZ)
        
        # Encontrar a segunda-feira da semana atual
        today_brasilia = now_brasilia.date()
        current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
        
        # Encontrar a segunda-feira da próxima semana
        next_week_monday = current_week_monday + timedelta(weeks=1)
        
        # CORREÇÃO: Definir os pontos de corte para a semana atual
        # Cutoff: Quarta-feira às 23:59:59
        current_week_cutoff_date = current_week_monday + timedelta(days=2)  # Quarta-feira
        current_week_cutoff_datetime = BRASILIA_TZ.localize(
            datetime.combine(current_week_cutoff_date, time(23, 59, 59))
        )

        # CORREÇÃO: Definir os pontos de abertura e corte para a próxima semana
        # Abertura: Sexta-feira às 18:00
        next_week_open_date = current_week_monday + timedelta(days=4)  # Sexta-feira
        next_week_open_datetime = BRASILIA_TZ.localize(
            datetime.combine(next_week_open_date, time(18, 0, 0))
        )

        # Cutoff próxima semana: Quarta-feira da próxima semana às 23:59:59
        next_week_cutoff_date = next_week_monday + timedelta(days=2)  # Quarta-feira da próxima semana
        next_week_cutoff_datetime = BRASILIA_TZ.localize(
            datetime.combine(next_week_cutoff_date, time(23, 59, 59))
        )

        status = {
            "current_week": {"open": False, "message": "Fechado"},
            "next_week": {"open": False, "message": "Fechado"},
            "general_message": "As escolhas para a semana atual sempre serão encerradas às 23:59 de quarta-feira, e a escala da próxima semana será liberada todas as sextas-feiras, às 18h."
        }

        # DEBUG: Log para verificar os valores
        current_app.logger.info(f"Agora (Brasília): {now_brasilia}")
        current_app.logger.info(f"Cutoff semana atual: {current_week_cutoff_datetime}")
        current_app.logger.info(f"Abertura próxima semana: {next_week_open_datetime}")
        current_app.logger.info(f"Cutoff próxima semana: {next_week_cutoff_datetime}")

        # CORREÇÃO: Regra para a semana atual - deve estar ABERTA até quarta-feira 23:59
        if now_brasilia <= current_week_cutoff_datetime:
            status["current_week"]["open"] = True
            status["current_week"]["message"] = f"Aberto até quarta-feira ({current_week_cutoff_date.strftime('%d/%m')}) às 23:59"
        else:
            status["current_week"]["message"] = f"Fechado (após quarta-feira {current_week_cutoff_date.strftime('%d/%m')} 23:59)"

        # CORREÇÃO: Regra para a próxima semana
        if now_brasilia >= next_week_open_datetime and now_brasilia <= next_week_cutoff_datetime:
            status["next_week"]["open"] = True
            status["next_week"]["message"] = f"Aberto até quarta-feira ({next_week_cutoff_date.strftime('%d/%m')}) às 23:59"
        elif now_brasilia < next_week_open_datetime:
            status["next_week"]["message"] = f"Abre na sexta-feira ({next_week_open_date.strftime('%d/%m')}) às 18:00"
        else:
            status["next_week"]["message"] = f"Fechado (após quarta-feira {next_week_cutoff_date.strftime('%d/%m')} 23:59)"

        return status
    except Exception as e:
        current_app.logger.error(f"Erro ao obter status da janela de agendamento: {str(e)}")
        return {
            "current_week": {"open": False, "message": "Erro no sistema"},
            "next_week": {"open": False, "message": "Erro no sistema"},
            "general_message": "As escolhas para a semana atual sempre serão encerradas às 23:59 de quarta-feira, e a escala da próxima semana será liberada todas as sextas-feiras, às 18h."
        }

@bookings_bp.route("/booking-window-status", methods=["GET"])
def get_booking_window_status_api():
    try:
        # Obter timezone do Brasil
        brasil_tz = pytz.timezone('America/Sao_Paulo')
        now_brasilia = datetime.now(brasil_tz)
        
        # Normalizar microssegundos para evitar problemas de comparação
        now_brasilia = now_brasilia.replace(microsecond=0)
        
        # CORREÇÃO: Encontrar a próxima quarta-feira às 23:59
        today = now_brasilia.date()
        days_until_wednesday = (2 - today.weekday()) % 7  # 2 = quarta-feira (0=segunda, 1=terça, 2=quarta)
        
        # CORREÇÃO: Se hoje É quarta-feira, verificar se ainda não passou das 23:59
        if days_until_wednesday == 0:  # Hoje é quarta-feira
            if now_brasilia.time() <= time(23, 59, 59):
                # Ainda está dentro do prazo de hoje (quarta-feira)
                current_week_cutoff = today
            else:
                # Já passou das 23:59 de quarta-feira, próxima quarta-feira
                days_until_wednesday = 7
                current_week_cutoff = today + timedelta(days=days_until_wednesday)
        else:
            # Não é quarta-feira, calcular próxima quarta-feira
            current_week_cutoff = today + timedelta(days=days_until_wednesday)
        
        current_week_cutoff_datetime = brasil_tz.localize(
            datetime.combine(current_week_cutoff, time(23, 59, 59))
        ).replace(microsecond=0)
        
        # CORREÇÃO: Encontrar próxima sexta-feira às 18:00 para abertura da próxima semana
        days_until_friday = (4 - today.weekday()) % 7  # 4 = sexta-feira
        if days_until_friday == 0 and now_brasilia.time() >= time(18, 0, 0):
            # É sexta-feira e já passou das 18:00, próxima sexta-feira
            days_until_friday = 7
        elif days_until_friday == 0:
            # É sexta-feira mas ainda não são 18:00
            pass
        
        next_opening = today + timedelta(days=days_until_friday)
        next_opening_datetime = brasil_tz.localize(
            datetime.combine(next_opening, time(18, 0, 0))
        ).replace(microsecond=0)
        
        # Log para debug
        current_app.logger.info(f"Debug API - Agora: {now_brasilia}")
        current_app.logger.info(f"Debug API - Cutoff: {current_week_cutoff_datetime}")
        current_app.logger.info(f"Debug API - Comparação (aberto?): {now_brasilia <= current_week_cutoff_datetime}")
        
        # CORREÇÃO: Verificar se está dentro da janela de agendamento
        is_open = now_brasilia <= current_week_cutoff_datetime
        
        return jsonify({
            'is_open': is_open,
            'current_time': now_brasilia.strftime('%Y-%m-%d %H:%M:%S'),
            'closes_at': current_week_cutoff_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            'reopens_at': next_opening_datetime.strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro na verificação da janela de agendamento: {e}")
        return jsonify({
            'is_open': False,
            'error': 'Erro interno no sistema'
        }), 500


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
        coordinator_name = data.get("coordinator_name", "")
        observation = data.get("observation", "")
        slots_data = data.get("slots", [])

        # Primeiro, verificar se há slots OU observação. Se não houver nenhum, é um erro.
        if not slots_data and not observation.strip(): # Usar .strip() para considerar observações vazias
            return jsonify({"error": "É necessário selecionar pelo menos uma sala ou fornecer uma observação."}), 400

        # Agora, validar user_name e user_email, que são obrigatórios para qualquer tipo de agendamento/observação.
        if not all([user_name, user_email]):
            return jsonify({"error": "Missing fields. Required: user_name, user_email"}), 400
        
        if not re.match(r"[^@]+@[^@]+\.[^@]+", user_email):
            return jsonify({"error": "Invalid email format"}), 400

        processed_slots = []
        daily_new_bookings_count = defaultdict(int)
        booking_window = get_booking_window_status()

        # Processar slots apenas se existirem
        if slots_data:
            if not isinstance(slots_data, list):
                return jsonify({"error": "Slots must be a list"}), 400

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
                    return jsonify({"error": f"Limite de {MAX_BOOKINGS_PER_DAY} agendamentos por dia para o usuário '{user_name}' seria excedido no dia {booking_date_obj.strftime('%Y-%m-%d')}."}), 409

            # Validation for "Geral" rooms - only one per period per day per user
            for booking_date_obj, _ in daily_new_bookings_count.items():
                geral_periods_in_request = defaultdict(list)
                
                for slot in processed_slots:
                    if slot["booking_date_obj"] == booking_date_obj and slot["room_name"].startswith("Geral "):
                        geral_periods_in_request[slot["period"]].append(slot["room_name"])
                
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
        
        # Criar agendamentos para slots específicos
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
        
        # Se não há slots mas há observação, criar um registro de observação geral
        if not processed_slots and observation.strip():
            # Determinar a data da semana atual para a observação geral
            now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
            now_brasilia = now_utc.astimezone(BRASILIA_TZ)
            today_brasilia = now_brasilia.date()
            current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
            
            general_observation_booking = Booking(
                user_name=user_name,
                user_email=user_email,
                coordinator_name=coordinator_name,
                observation=observation,
                room_id=None,  # Sem sala específica
                booking_date=current_week_monday,  # Data da segunda-feira da semana atual
                period="Observação Geral"  # Período especial para observações gerais
            )
            db.session.add(general_observation_booking)
        
        db.session.commit()
        
        email_sent_successfully = send_booking_confirmation_email(
            user_email, user_name, coordinator_name, observation, newly_created_bookings_details_for_email
        )
        
        if processed_slots:
            response_message = "Agendamento(s) criado(s) com sucesso!"
        elif observation.strip():
            response_message = "Observação registrada com sucesso!"
        else:
            response_message = "Nenhuma ação realizada." # Caso não haja slots nem observação (já validado antes)
            
        if not email_sent_successfully:
            response_message += " (Houve um problema ao enviar o e-mail de confirmação.)"
        
        return jsonify({
            "message": response_message,
            "bookings_created": newly_created_bookings_details_for_email,
            "observation_saved": bool(observation.strip() and not processed_slots)
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
                # Observações gerais vão por último
                if booking.period == "Observação Geral":
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
            return jsonify({"error": "WeasyPrint não está disponível. Geração de PDF desabilitada."}), 500
        
        # Obter parâmetros de data
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        
        if not start_date_str or not end_date_str:
            return jsonify({"error": "start_date e end_date são obrigatórios"}), 400
        
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400
        
        # Buscar todas as salas do sistema e ordená-las
        all_rooms = Room.query.all()
        sorted_rooms = sort_rooms_custom(all_rooms)
        
        # Buscar agendamentos no período (excluindo fins de semana e observações gerais)
        bookings = Booking.query.outerjoin(Room).filter(
            Booking.booking_date.between(start_date, end_date),
            Booking.period != "Observação Geral"  # Excluir observações gerais da tabela principal
        ).order_by(Booking.booking_date, Booking.period).all()
        
        # Organizar dados por data e período para a tabela da escala
        schedule_data = defaultdict(lambda: defaultdict(list))
        user_observations = {}
        
        # Processar agendamentos normais
        for booking in bookings:
            if booking.room and booking.booking_date.weekday() < 5:  # Segunda a Sexta apenas
                date_str = booking.booking_date.strftime("%Y-%m-%d")
                
                # Adicionar à estrutura da escala
                schedule_data[date_str][booking.period].append({
                    "user_name": booking.user_name,
                    "coordinator_name": booking.coordinator_name,
                    "room_name": booking.room.name,
                    "observation": booking.observation
                })
            
            # Coletar observações específicas por usuário (se houver observação)
            if booking.observation and booking.observation.strip():
                if booking.user_name not in user_observations:
                    user_observations[booking.user_name] = {
                        "email": booking.user_email,
                        "coordinator": booking.coordinator_name,
                        "bookings": []
                    }

                user_observations[booking.user_name]["bookings"].append({
                    "room_name": booking.room.name if booking.room else "N/A",
                    "date": booking.booking_date,
                    "period": booking.period,
                    "observation": booking.observation
                })
        
        # Buscar observações gerais separadamente
        general_observations_query = Booking.query.filter(
            Booking.booking_date.between(start_date, end_date),
            Booking.period == "Observação Geral"
        ).order_by(Booking.booking_date).all()
        
        general_observations = []
        for obs_booking in general_observations_query:
            general_observations.append({
                "user_name": obs_booking.user_name,
                "coordinator_name": obs_booking.coordinator_name,
                "observation": obs_booking.observation,
                "booking_date": obs_booking.booking_date
            })
        
        # Gerar lista de datas para os dias úteis da semana
        dates_of_week = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:  # Segunda a Sexta
                dates_of_week.append(current_date)
            current_date += timedelta(days=1)
        
        # Limitar a 5 dias úteis se necessário
        dates_of_week = dates_of_week[:5]
        
        # Obter timestamp atual para o cabeçalho
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_brasilia = now_utc.astimezone(BRASILIA_TZ)
        
        # Debug: Log dos dados que estão sendo passados para o template
        current_app.logger.info(f"Salas encontradas: {[room.name for room in sorted_rooms]}")
        current_app.logger.info(f"Datas da semana: {[d.strftime('%Y-%m-%d') for d in dates_of_week]}")
        current_app.logger.info(f"Dados da escala: {dict(schedule_data)}")
        current_app.logger.info(f"Observações de usuários: {len(user_observations)} usuários")
        current_app.logger.info(f"Observações gerais: {len(general_observations)} observações")
        
        # Renderizar template HTML
        html_content = render_template(
            "schedule_pdf_template.html",
            schedule_data=dict(schedule_data),
            user_observations=dict(user_observations),
            general_observations=general_observations,
            start_date=start_date,
            end_date=end_date,
            generated_at=now_brasilia,
            dates_of_week=dates_of_week,
            all_rooms=sorted_rooms,  # Adicionar todas as salas para o template
            timedelta=timedelta  # Disponibilizar timedelta para o template
        )
        
        # Gerar PDF
        pdf = HTML(string=html_content).write_pdf()
        
        # Criar resposta
        response = make_response(pdf)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"attachment; filename=escala_{start_date_str}_a_{end_date_str}.pdf"
        
        return response
        
    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {str(e)}")
        return jsonify({"error": "Erro ao gerar PDF", "details": str(e)}), 500
