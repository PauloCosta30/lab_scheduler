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
            
        # Permitir envio de email mesmo sem slots se houver observação
        if not booked_slots_details and not observation:
            current_app.logger.info("No booking details or observation to send in email.")
            return False

        subject = "Confirmação de Agendamento de Laboratório"
        sender = current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@example.com")
        recipients = [user_email]

        html_body = f"<p>Olá {user_name},</p>"
        
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
            if booked_slots_details:
                html_body += f"<p>Observação: {observation}</p>"
            else:
                html_body += "<p>Sua observação foi registrada com sucesso.</p>"
                html_body += f"<p>Observação: {observation}</p>"
        
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
        next_week_open_date = current_week_monday + timedelta(days=3) # Sexta-feira
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
        slots_data = data.get("slots", [])  # Permitir lista vazia

        # Validação básica - requer pelo menos nome, email e (slots OU observação)
        if not user_name or not user_email:
            return jsonify({"error": "Missing fields. Required: user_name, user_email"}), 400
        
        # Validar se há pelo menos slots ou observação
        if not slots_data and not observation.strip():
            return jsonify({"error": "É necessário fornecer pelo menos slots para agendamento ou uma observação"}), 400
        
        # Validar formato do email
        if "@" not in user_email or "." not in user_email.split("@")[-1]:
            return jsonify({"error": "Invalid email format"}), 400

        # Validar slots apenas se fornecidos
        if slots_data and not isinstance(slots_data, list):
            return jsonify({"error": "Slots must be a list"}), 400

        processed_slots = []
        daily_new_bookings_count = defaultdict(int)

        booking_window = get_booking_window_status()

        # Processar slots apenas se fornecidos
        if slots_data:
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

            # Validações adicionais apenas se há slots
            if processed_slots:
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
        
        # CORREÇÃO: Se não há slots mas há observação, criar um registro de observação geral
        if not processed_slots and observation.strip():
            # Determinar a data da semana atual para a observação geral
            now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
            now_brasilia = now_utc.astimezone(BRASILIA_TZ)
            today_brasilia = now_brasilia.date()
            current_week_monday = today_brasilia - timedelta(days=today_brasilia.weekday())
            
            # Verificar se já existe uma observação geral para este usuário nesta semana
            existing_general_observation = Booking.query.filter_by(
                user_name=user_name,
                booking_date=current_week_monday,
                period="Observação Geral"
            ).first()
            
            if existing_general_observation:
                # Atualizar a observação existente
                existing_general_observation.observation = observation
                existing_general_observation.coordinator_name = coordinator_name
                existing_general_observation.user_email = user_email
                current_app.logger.info(f"Observação geral atualizada para {user_name} na semana de {current_week_monday}")
            else:
                # Criar nova observação geral
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
                current_app.logger.info(f"Nova observação geral criada para {user_name} na semana de {current_week_monday}")
        
        db.session.commit()
        
        # CORREÇÃO: Debug - Verificar se as observações foram salvas
        if not processed_slots and observation.strip():
            saved_observation = Booking.query.filter_by(
                user_name=user_name,
                period="Observação Geral"
            ).first()
            if saved_observation:
                current_app.logger.info(f"Observação geral confirmada no banco: {saved_observation.observation}")
            else:
                current_app.logger.error(f"Observação geral NÃO foi salva para {user_name}")
        
        email_sent_successfully = send_booking_confirmation_email(
            user_email, user_name, coordinator_name, observation, newly_created_bookings_details_for_email
        )
        
        if processed_slots:
            response_message = "Agendamento(s) criado(s) com sucesso!"
        elif observation.strip():
            response_message = "Observação registrada com sucesso!"
        else:
            response_message = "Nenhuma ação realizada."
            
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
async function generatePdf() {
        if (!currentWeekStartDate) {
            showScheduleMessage("Carregue uma escala primeiro antes de gerar o PDF.", "error");
            return;
        }

        const startDate = currentWeekStartDate.toISOString().split("T")[0];
        const endDate = new Date(currentWeekStartDate.valueOf());
        endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
        const endDateStr = endDate.toISOString().split("T")[0];

        // Desabilitar o botão durante a geração
        if (generatePdfButton) {
            generatePdfButton.disabled = true;
            generatePdfButton.textContent = "Gerando PDF...";
        }

        showScheduleMessage("Gerando PDF...", "");
        
        try {
            console.log(`Solicitando PDF para período: ${startDate} até ${endDateStr}`);
            
            const response = await fetch(`${API_BASE_URL}/generate-pdf?start_date=${startDate}&end_date=${endDateStr}`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/pdf',
                    'Cache-Control': 'no-cache'
                }
            });
            
            console.log(`Response status: ${response.status}`);
            console.log(`Response headers:`, response.headers);
            
            if (!response.ok) {
                let errorMessage = `Erro ${response.status}: ${response.statusText}`;
                
                try {
                    // Tentar ler como JSON para obter mensagem de erro detalhada
                    const contentType = response.headers.get('content-type');
                    if (contentType && contentType.includes('application/json')) {
                        const errorData = await response.json();
                        errorMessage = errorData.error || errorData.message || errorMessage;
                    } else {
                        // Se não for JSON, ler como texto
                        const errorText = await response.text();
                        if (errorText.trim()) {
                            errorMessage = errorText;
                        }
                    }
                } catch (parseError) {
                    console.error("Erro ao fazer parse da resposta de erro:", parseError);
                }
                
                throw new Error(errorMessage);
            }

            // Verificar se a resposta é realmente um PDF
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/pdf')) {
                console.warn(`Tipo de conteúdo inesperado: ${contentType}`);
            }

            const blob = await response.blob();
            
            // Verificar se o blob tem conteúdo
            if (blob.size === 0) {
                throw new Error("PDF gerado está vazio");
            }
            
            console.log(`PDF blob criado com tamanho: ${blob.size} bytes`);

            // Criar URL para download
            const url = window.URL.createObjectURL(blob);
            
            // Criar elemento de download
            const a = document.createElement("a");
            a.style.display = "none";
            a.href = url;
            
            // Nome do arquivo com data formatada
            const startDateFormatted = new Date(startDate).toLocaleDateString('pt-BR').replace(/\//g, '-');
            const endDateFormatted = new Date(endDateStr).toLocaleDateString('pt-BR').replace(/\//g, '-');
            a.download = `escala_agendamentos_${startDateFormatted}_a_${endDateFormatted}.pdf`;
            
            // Adicionar ao DOM, clicar e remover
            document.body.appendChild(a);
            a.click();
            
            // Limpar recursos
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            showScheduleMessage("PDF gerado e baixado com sucesso!", "success");
            console.log("PDF baixado com sucesso");
            
        } catch (error) {
            console.error("Falha ao gerar PDF:", error);
            
            let userMessage = "Não foi possível gerar o PDF.";
            
            if (error.message.includes('Failed to fetch')) {
                userMessage = "Erro de conexão: Não foi possível conectar ao servidor para gerar o PDF.";
            } else if (error.message.includes('NetworkError')) {
                userMessage = "Erro de rede: Verifique sua conexão com a internet.";
            } else if (error.message.includes('timeout')) {
                userMessage = "Timeout: A geração do PDF demorou muito tempo. Tente novamente.";
            } else if (error.message) {
                userMessage = `Erro: ${error.message}`;
            }
            
            showScheduleMessage(userMessage, "error");
            
        } finally {
            // Re-habilitar o botão
            if (generatePdfButton) {
                generatePdfButton.disabled = false;
                generatePdfButton.textContent = "Gerar PDF";
            }
        }
    }

    // Função auxiliar para debug do endpoint PDF
    async function testPdfEndpoint() {
        if (!currentWeekStartDate) {
            console.error("Nenhuma data de semana definida");
            return;
        }

        const startDate = currentWeekStartDate.toISOString().split("T")[0];
        const endDate = new Date(currentWeekStartDate.valueOf());
        endDate.setUTCDate(currentWeekStartDate.getUTCDate() + 4);
        const endDateStr = endDate.toISOString().split("T")[0];
        
        const testUrl = `${API_BASE_URL}/generate-pdf?start_date=${startDate}&end_date=${endDateStr}`;
        
        console.log("=== TESTE DO ENDPOINT PDF ===");
        console.log(`URL: ${testUrl}`);
        console.log(`Período: ${startDate} até ${endDateStr}`);
        
        try {
            const response = await fetch(testUrl, {
                method: 'HEAD' // Usar HEAD para testar sem baixar o conteúdo
            });
            
            console.log(`Status: ${response.status}`);
            console.log(`Status Text: ${response.statusText}`);
            console.log(`Headers:`, [...response.headers.entries()]);
            
            if (response.ok) {
                console.log("✅ Endpoint PDF está respondendo corretamente");
            } else {
                console.log("❌ Endpoint PDF retornou erro");
            }
            
        } catch (error) {
            console.error("❌ Erro ao testar endpoint PDF:", error);
        }
    }

    // --- Booking Creation ---
    async function createBooking(formData) {
        console.log("=== DEBUG: Iniciando createBooking ===");
        
        // Debug: Listar todos os campos do FormData
        console.log("Campos do FormData:");
        for (let [key, value] of formData.entries()) {
            console.log(`  ${key}: "${value}"`);
        }

        const userName = formData.get("userName");
        const userEmail = formData.get("userEmail");
        const coordinatorName = formData.get("coordinatorName") || "";
        const observation = formData.get("observation") || "";

        console.log("Valores extraídos:");
        console.log(`  userName: "${userName}"`);
        console.log(`  userEmail: "${userEmail}"`);
        console.log(`  coordinatorName: "${coordinatorName}"`);
        console.log(`  observation: "${observation}"`);
        console.log(`  selectedSlots: ${selectedSlots.length} slots`);

        // Validação de campos obrigatórios no frontend
        if (!userName || userName.trim() === "") {
            showModalMessage("Nome é obrigatório para o agendamento.", "error");
            return;
        }

        if (!userEmail || userEmail.trim() === "") {
            showModalMessage("E-mail é obrigatório para o agendamento.", "error");
            return;
        }

        // Validação de formato de e-mail no frontend
        const emailTrimmed = userEmail.trim();
        if (!emailTrimmed.includes("@") || !emailTrimmed.includes(".")) {
            showModalMessage("Por favor, insira um e-mail válido.", "error");
            return;
        }

        // REMOVIDA A VALIDAÇÃO QUE IMPEDIA AGENDAMENTOS SEM SLOTS
        // Agora permite agendamentos somente com observação
        if (selectedSlots.length === 0 && !observation.trim()) {
            showModalMessage("É necessário fornecer uma observação quando não há salas selecionadas (ex: solicitação de encaixe).", "error");
            return;
        }

        const bookingData = {
            slots: selectedSlots.map(slot => ({
                room_id: slot.roomId,
                booking_date: slot.date,
                period: slot.period
            })),
            user_name: userName.trim(),
            user_email: emailTrimmed,
            coordinator_name: coordinatorName.trim(),
            observation: observation.trim()
        };

        console.log("=== DEBUG: Dados finais do agendamento ===");
        console.log(JSON.stringify(bookingData, null, 2));
        console.log(`URL da requisição: ${API_BASE_URL}/bookings`);

        // Mostrar mensagem diferente para agendamentos somente observação
        if (selectedSlots.length === 0) {
            showModalMessage("Enviando solicitação de encaixe...", "");
        } else {
            showModalMessage("Enviando agendamento...", "");
        }

        try {
            console.log("=== DEBUG: Fazendo requisição POST ===");
            const response = await fetch(`${API_BASE_URL}/bookings`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(bookingData)
            });

            console.log(`=== DEBUG: Response Status: ${response.status} ===`);
            console.log(`=== DEBUG: Response OK: ${response.ok} ===`);

            let result;
            try {
                result = await response.json();
                console.log("=== DEBUG: Response JSON ===");
                console.log(JSON.stringify(result, null, 2));
            } catch (jsonError) {
                console.error("=== DEBUG: Erro ao fazer parse do JSON ===", jsonError);
                const textResponse = await response.text();
                console.log("=== DEBUG: Response Text ===", textResponse);
                throw new Error(`Resposta inválida do servidor (Status: ${response.status})`);
            }

            if (response.ok) {
                if (selectedSlots.length === 0) {
                    showModalMessage("Solicitação de encaixe registrada com sucesso!", "success");
                } else {
                    showModalMessage("Agendamento realizado com sucesso!", "success");
                }
                
                // Limpar slots selecionados e atualizar a tabela após o sucesso
                selectedSlots.forEach(slot => {
                    if (slot.cellRef) {
                        slot.cellRef.classList.remove("selected");
                        slot.cellRef.classList.add("booked");
                        slot.cellRef.textContent = userName.trim();
                        slot.cellRef.removeEventListener("click", handleSlotClick);
                        slot.cellRef.style.cursor = "default";
                        slot.cellRef.title = `Reservado por: ${userName.trim()}`;
                    }
                });
                
                selectedSlots = [];
                updateSelectedSlotsSummary();
                updateButtonStates(); // Atualizar texto do botão
                modalBookingForm.reset();
                
                // Recarregar a escala para garantir consistência
                setTimeout(() => {
                    loadScheduleData(currentWeekStartDate.toISOString().split("T")[0]);
                }, 1000);
                
            } else {
                // Tratar diferentes tipos de erro do servidor
                let errorMessage = "Erro desconhecido do servidor";
                
                if (result && result.error) {
                    errorMessage = result.error;
                } else if (result && result.message) {
                    errorMessage = result.message;
                } else if (result && result.detail) {
                    errorMessage = result.detail;
                } else {
                    errorMessage = `Erro ${response.status}: ${response.statusText}`;
                }
                
                console.error("=== DEBUG: Erro do servidor ===", {
                    status: response.status,
                    statusText: response.statusText,
                    result: result,
                    errorMessage: errorMessage
                });
                
                showModalMessage(`Falha ao criar agendamento: ${errorMessage}`, "error");
            }
        } catch (error) {
            console.error("=== DEBUG: Erro na requisição ===", error)
            
            if (error.name === 'TypeError' && error.message.includes('fetch')) {
                showModalMessage("Erro de conexão: Não foi possível conectar ao servidor. Verifique sua conexão.", "error");
            } else if (error.message.includes('JSON')) {
                showModalMessage("Erro de comunicação: Resposta inválida do servidor.", "error");
            } else {
                showModalMessage(`Erro de conexão: ${error.message}`, "error");
            }
        }
    }

    // --- Modal and Form Handling ---
    if (proceedToBookingButton) {
        proceedToBookingButton.addEventListener("click", () => {
            updateSelectedSlotsSummary();
            bookingModal.style.display = "block";
            
            // Focar no campo de observação se não há slots selecionados
            if (selectedSlots.length === 0) {
                setTimeout(() => {
                    const observationField = document.querySelector('#modalBookingForm textarea[name="observation"]');
                    if (observationField) {
                        observationField.focus();
                        observationField.placeholder = "Descreva sua solicitação de encaixe (ex: 'Preciso de uma sala na sexta à tarde para reunião urgente')";
                    }
                }, 100);
            }
        });
    }

    if (closeModalButton) {
        closeModalButton.addEventListener("click", () => {
            bookingModal.style.display = "none";
            if (modalFormMessage) {
                modalFormMessage.textContent = "";
                modalFormMessage.className = "message";
            }
        });
    }

    window.addEventListener("click", (event) => {
        if (event.target === bookingModal) {
            bookingModal.style.display = "none";
            if (modalFormMessage) {
                modalFormMessage.textContent = "";
                modalFormMessage.className = "message";
            }
        }
    });

    if (modalBookingForm) {
        modalBookingForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            console.log("=== DEBUG: Form submit ===");
            
            // Debug: Verificar se o formulário existe e tem elementos
            console.log("Form encontrado:", modalBookingForm);
            console.log("Elementos do form:", modalBookingForm.elements);
            
            const formData = new FormData(modalBookingForm);
            await createBooking(formData);
        });
    }

    function updateSelectedSlotsSummary() {
        if (!selectedSlotsSummaryList) return;
        
        selectedSlotsSummaryList.innerHTML = "";
        if (selectedSlots.length === 0) {
            const li = document.createElement("li");
            li.innerHTML = "<em>Nenhum horário selecionado - Agendamento somente observação</em>";
            li.style.color = "#666";
            selectedSlotsSummaryList.appendChild(li);
            return;
        }
        selectedSlots.forEach(slot => {
            const li = document.createElement("li");
            li.textContent = `${slot.roomName} - ${slot.date} - ${slot.period}`;
            selectedSlotsSummaryList.appendChild(li);
        });
    }

    // --- Event Listeners ---
    if (weekSelector) {
        weekSelector.value = new Date().toISOString().split("T")[0];
    }
    
    if (loadScheduleButton) {
        loadScheduleButton.addEventListener("click", () => {
            const selectedDate = weekSelector ? weekSelector.value : null;
            loadScheduleData(selectedDate);
        });
    }
    
    if (generatePdfButton) {
        generatePdfButton.addEventListener("click", generatePdf);
    }

    // --- Initialization ---
    console.log("Inicializando aplicação...");
    
    // Carregar status da janela de agendamento primeiro
    fetchBookingWindowStatus().then(() => {
        // Depois carregar a escala
        loadScheduleData();
    });
});


