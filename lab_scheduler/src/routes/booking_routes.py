import os
from datetime import datetime, timedelta, time, timezone
from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, and_
from sqlalchemy.orm import joinedload
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import io

from src.extensions import db
from src.models.entities import Booking, Room, User

bookings_bp = Blueprint('bookings_bp', __name__)

# Constantes de configuração
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "lab_scheduler_admin")
# Horários em UTC
CUTOFF_WEEKDAY = 2  # Wednesday (0=Monday, 1=Tuesday, ..., 6=Sunday)
CUTOFF_TIME = time(21, 0, 0, tzinfo=timezone.utc)  # 18:00 Brasília = 21:00 UTC
RELEASE_WEEKDAY = 3  # Thursday
RELEASE_TIME = time(2, 59, 0, tzinfo=timezone.utc)  # 23:59 Brasília = 02:59 UTC (do dia seguinte)

def get_monday_of_week(date_obj):
    """Retorna a segunda-feira da semana de uma data."""
    # Ajusta para garantir que o dia da semana 0 seja segunda-feira para cálculo
    # Python's weekday() returns 0 for Monday, 6 for Sunday.
    # We want to calculate difference from Monday (0).
    day_of_week = date_obj.weekday() # 0 for Monday, 6 for Sunday
    
    # Se a data for domingo, ajusta para a segunda-feira seguinte
    if day_of_week == 6: # Sunday
        # Se for domingo, queremos a segunda-feira seguinte
        return date_obj + timedelta(days=1)
    else:
        # Para outros dias, subtrai para chegar na segunda-feira da mesma semana
        return date_obj - timedelta(days=day_of_week)

def get_brazilian_time(dt_utc):
    """Converte um datetime UTC para o horário de Brasília (UTC-3)."""
    if dt_utc.tzinfo is None:
        # Se não tiver timezone, assume UTC
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    
    brazil_timezone = timezone(timedelta(hours=-3))
    return dt_utc.astimezone(brazil_timezone)

@bookings_bp.route('/api/booking-status', methods=['GET'])
def get_booking_status():
    try:
        current_utc_dt = datetime.now(timezone.utc)
        current_brazil_dt = get_brazilian_time(current_utc_dt)

        current_week_monday = get_monday_of_week(current_brazil_dt.date())
        next_week_monday = current_week_monday + timedelta(days=7)

        # Determinar o status da semana atual
        current_week_open = True
        cutoff_dt_current_week = datetime.combine(current_week_monday + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME).replace(tzinfo=timezone.utc)
        
        if current_utc_dt >= cutoff_dt_current_week:
            current_week_open = False

        # Determinar o status da próxima semana
        next_week_open = False
        release_dt_next_week = datetime.combine(next_week_monday + timedelta(days=RELEASE_WEEKDAY), RELEASE_TIME).replace(tzinfo=timezone.utc)
        
        if current_utc_dt >= release_dt_next_week:
            next_week_open = True

        # Mensagens de status para o frontend
        status_message = ""
        if current_week_open and next_week_open:
            status_message = "Escala aberta para a semana atual e próxima semana."
        elif current_week_open and not next_week_open:
            status_message = f"Escala aberta para a semana atual. A escala da próxima semana abre na {get_brazilian_time(release_dt_next_week).strftime('%A, %H:%M')}."
        elif not current_week_open and next_week_open:
            status_message = f"Escala da semana atual fechada (encerrou na {get_brazilian_time(cutoff_dt_current_week).strftime('%A, %H:%M')}). Escala da próxima semana aberta."
        else: # not current_week_open and not next_week_open
            status_message = f"Escala da semana atual fechada (encerrou na {get_brazilian_time(cutoff_dt_current_week).strftime('%A, %H:%M')}). A escala da próxima semana abre na {get_brazilian_time(release_dt_next_week).strftime('%A, %H:%M')}."

        response_data = {
            "current_week_open": current_week_open,
            "next_week_open": next_week_open,
            "status_message": status_message,
            "current_time_utc": current_utc_dt.isoformat(),
            "current_time_brazil": current_brazil_dt.isoformat(),
            "cutoff_time_current_week_utc": cutoff_dt_current_week.isoformat(),
            "release_time_next_week_utc": release_dt_next_week.isoformat()
        }

        # Verificar parâmetro de override para testes
        override = request.args.get('admin_override')
        if override == 'open_all' and request.args.get('password') == ADMIN_PASSWORD:
            current_app.logger.info("Admin override: Forçando abertura de ambas as semanas")
            response_data["current_week_open"] = True
            response_data["next_week_open"] = True
            response_data["status_message"] = "Admin override: Escala aberta para ambas as semanas (apenas para testes)."
        elif override == 'open_current' and request.args.get('password') == ADMIN_PASSWORD:
            current_app.logger.info("Admin override: Forçando abertura da semana atual")
            response_data["current_week_open"] = True
            response_data["status_message"] = "Admin override: Escala aberta para a semana atual (apenas para testes)."
        elif override == 'open_next' and request.args.get('password') == ADMIN_PASSWORD:
            current_app.logger.info("Admin override: Forçando abertura da próxima semana")
            response_data["next_week_open"] = True
            response_data["status_message"] = "Admin override: Escala aberta para a próxima semana (apenas para testes)."

        return jsonify(response_data)

    except Exception as e:
        current_app.logger.error(f"Erro ao verificar status do agendamento: {e}", exc_info=True)
        return jsonify({"error": "Não foi possível verificar o status do agendamento. Tente novamente mais tarde."}), 500

@bookings_bp.route('/api/bookings', methods=['GET'])
def get_bookings():
    try:
        selected_date_str = request.args.get('date')
        if not selected_date_str:
            current_app.logger.warning("Data não fornecida na requisição de agendamentos.")
            return jsonify({"error": "Data não fornecida."}), 400

        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        
        # Garante que a semana sempre comece na segunda-feira
        monday_of_week = get_monday_of_week(selected_date)
        
        # Define o fim da semana (sexta-feira)
        friday_of_week = monday_of_week + timedelta(days=4) # Monday (0) + 4 days = Friday (4)

        current_app.logger.info(f"Buscando agendamentos para a semana de {monday_of_week} a {friday_of_week}")

        bookings = db.session.query(Booking).options(joinedload(Booking.room), joinedload(Booking.user)).filter(
            Booking.booking_date >= monday_of_week,
            Booking.booking_date <= friday_of_week,
            func.extract('dow', Booking.booking_date).notin_([0, 6]) # Exclui Sábado (6) e Domingo (0)
        ).order_by(Booking.booking_date, Booking.period, Booking.room_id).all()

        bookings_data = []
        for booking in bookings:
            bookings_data.append({
                "id": booking.id,
                "user_name": booking.user.name if booking.user else "Desconhecido",
                "room_name": booking.room.name if booking.room else "Desconhecido",
                "booking_date": booking.booking_date.strftime('%Y-%m-%d'),
                "period": booking.period
            })
        current_app.logger.info(f"Agendamentos encontrados: {len(bookings_data)}")
        return jsonify(bookings_data)
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar agendamentos: {e}", exc_info=True)
        return jsonify({"error": "Erro ao buscar agendamentos."}), 500

@bookings_bp.route('/api/bookings', methods=['POST'])
def create_booking():
    try:
        data = request.get_json()
        user_name = data.get('user_name')
        slots = data.get('slots')

        if not user_name or not slots:
            current_app.logger.warning("Dados incompletos para criar agendamento.")
            return jsonify({"error": "Nome de usuário e slots são obrigatórios."}), 400

        user = User.query.filter_by(name=user_name).first()
        if not user:
            user = User(name=user_name)
            db.session.add(user)
            db.session.commit()
            current_app.logger.info(f"Novo usuário criado: {user_name}")

        new_bookings = []
        for slot in slots:
            room_name = slot.get('room_name')
            booking_date_str = slot.get('booking_date')
            period = slot.get('period')

            if not room_name or not booking_date_str or not period:
                current_app.logger.warning(f"Slot com dados incompletos: {slot}")
                return jsonify({"error": "Dados do slot incompletos."}), 400

            room = Room.query.filter_by(name=room_name).first()
            if not room:
                current_app.logger.warning(f"Sala não encontrada: {room_name}")
                return jsonify({"error": f"Sala '{room_name}' não encontrada."}), 404

            booking_date_obj = datetime.strptime(booking_date_str, '%Y-%m-%d').date()
            
            # Verificar se a data é sábado (6) ou domingo (0)
            if booking_date_obj.weekday() == 5 or booking_date_obj.weekday() == 6: # 5=Saturday, 6=Sunday
                current_app.logger.warning(f"Tentativa de agendar em fim de semana: {booking_date_obj}")
                return jsonify({"error": "Não é possível agendar em sábados ou domingos."}), 400

            # Verificar conflito de agendamento
            existing_booking = Booking.query.filter_by(
                room_id=room.id,
                booking_date=booking_date_obj,
                period=period
            ).first()

            if existing_booking:
                current_app.logger.warning(f"Conflito de agendamento: Sala '{room_name}' já reservada para {booking_date_str} no período da {period}.")
                return jsonify({"error": f"Sala '{room_name}' já reservada para {booking_date_str} no período da {period}."}), 409
            
            # Regra para salas "Geral": não permite agendar a mesma sala Geral no mesmo período
            if "Geral" in room.name:
                # Verifica se o usuário já tem outra sala "Geral" agendada no mesmo período do mesmo dia
                # Esta validação foi removida conforme solicitado para permitir múltiplos agendamentos "Geral"
                # A única restrição é que a mesma sala não pode ser agendada duas vezes no mesmo slot.
                pass # A validação de conflito acima já cobre isso.

            new_booking = Booking(
                user_id=user.id,
                room_id=room.id,
                booking_date=booking_date_obj,
                period=period
            )
            new_bookings.append(new_booking)

        db.session.add_all(new_bookings)
        db.session.commit()
        current_app.logger.info(f"{len(new_bookings)} agendamento(s) criado(s) com sucesso para {user_name}.")
        return jsonify({"message": "Agendamento(s) criado(s) com sucesso!"}), 201

    except IntegrityError as e:
        db.session.rollback()
        current_app.logger.error(f"Erro de integridade ao criar agendamento: {e}", exc_info=True)
        return jsonify({"error": "Erro de banco de dados. Verifique os dados e tente novamente."}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro inesperado ao criar agendamento: {e}", exc_info=True)
        return jsonify({"error": "Erro interno ao criar agendamento."}), 500

@bookings_bp.route('/api/bookings/<int:booking_id>', methods=['DELETE'])
def delete_booking(booking_id):
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            current_app.logger.warning(f"Agendamento não encontrado para exclusão: ID {booking_id}")
            return jsonify({"error": "Agendamento não encontrado."}), 404

        db.session.delete(booking)
        db.session.commit()
        current_app.logger.info(f"Agendamento ID {booking_id} excluído com sucesso.")
        return jsonify({"message": "Agendamento excluído com sucesso."}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao excluir agendamento ID {booking_id}: {e}", exc_info=True)
        return jsonify({"error": "Erro ao excluir agendamento."}), 500

@bookings_bp.route('/api/admin/clear-bookings', methods=['POST'])
def admin_clear_bookings():
    try:
        data = request.get_json()
        password = data.get('password')
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        room_id = data.get('room_id')
        period = data.get('period')

        if password != ADMIN_PASSWORD:
            current_app.logger.warning("Tentativa de acesso não autorizado à função de limpeza de agendamentos.")
            return jsonify({"error": "Senha administrativa incorreta."}), 403

        query = Booking.query

        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query = query.filter(Booking.booking_date >= start_date)
            current_app.logger.info(f"Filtro de data inicial: {start_date}")

        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            query = query.filter(Booking.booking_date <= end_date)
            current_app.logger.info(f"Filtro de data final: {end_date}")

        if room_id:
            query = query.filter(Booking.room_id == room_id)
            current_app.logger.info(f"Filtro de sala: ID {room_id}")

        if period:
            query = query.filter(Booking.period == period)
            current_app.logger.info(f"Filtro de período: {period}")

        bookings_to_delete = query.all()
        count = len(bookings_to_delete)
        details = []

        for booking in bookings_to_delete:
            details.append({
                "id": booking.id,
                "user_id": booking.user_id,
                "room_id": booking.room_id,
                "booking_date": booking.booking_date.strftime('%Y-%m-%d'),
                "period": booking.period
            })
            db.session.delete(booking)

        db.session.commit()
        current_app.logger.info(f"{count} agendamento(s) removido(s) pela administração.")
        return jsonify({
            "message": f"{count} agendamento(s) removido(s) com sucesso",
            "count": count,
            "details": details
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao limpar agendamentos: {e}", exc_info=True)
        return jsonify({"error": "Erro ao limpar agendamentos."}), 500

@bookings_bp.route('/api/rooms', methods=['GET'])
def get_rooms():
    try:
        rooms = Room.query.order_by(Room.id).all() # Busca todas as salas
        
        # Função de chave de ordenação personalizada
        def custom_room_sort_key(room):
            name = room.name
            if "Geral" in name:
                try:
                    # Extrai o número da sala Geral
                    num = int("".join(filter(str.isdigit, name)))
                    return (0, num) # Prioriza salas "Geral" e as ordena numericamente
                except ValueError:
                    return (0, float('inf')) # Para "Geral" sem número, coloca no final das Gerais
            return (1, name) # Outras salas vêm depois, ordenadas alfabeticamente

        # Aplica a ordenação personalizada
        sorted_rooms = sorted(rooms, key=custom_room_sort_key)

        rooms_data = [{"id": room.id, "name": room.name} for room in sorted_rooms]
        current_app.logger.info(f"Salas encontradas: {len(rooms_data)}")
        return jsonify(rooms_data)
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar salas: {e}", exc_info=True)
        return jsonify({"error": "Erro ao buscar salas."}), 500

@bookings_bp.route('/api/generate-pdf', methods=['GET'])
def generate_schedule_pdf():
    try:
        selected_date_str = request.args.get('date')
        if not selected_date_str:
            current_app.logger.warning("Data não fornecida para geração de PDF.")
            return jsonify({"error": "Data não fornecida."}), 400

        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        monday_of_week = get_monday_of_week(selected_date)
        friday_of_week = monday_of_week + timedelta(days=4)

        current_app.logger.info(f"Gerando PDF para a semana de {monday_of_week} a {friday_of_week}")

        bookings = db.session.query(Booking).options(joinedload(Booking.room), joinedload(Booking.user)).filter(
            Booking.booking_date >= monday_of_week,
            Booking.booking_date <= friday_of_week,
            func.extract('dow', Booking.booking_date).notin_([0, 6]) # Exclui Sábado (6) e Domingo (0)
        ).order_by(Booking.booking_date, Booking.period, Booking.room_id).all()

        rooms = Room.query.all()
        
        # Função de chave de ordenação personalizada (duplicada para consistência no PDF)
        def custom_room_sort_key(room):
            name = room.name
            if "Geral" in name:
                try:
                    num = int("".join(filter(str.isdigit, name)))
                    return (0, num)
                except ValueError:
                    return (0, float('inf'))
            return (1, name)

        sorted_rooms = sorted(rooms, key=custom_room_sort_key)
        room_names = [room.name for room in sorted_rooms]

        # Organizar dados para o PDF
        schedule_data = {}
        for i in range(5): # Segunda a Sexta
            current_date = monday_of_week + timedelta(days=i)
            schedule_data[current_date] = {
                "Manhã": {room_name: "" for room_name in room_names},
                "Tarde": {room_name: "" for room_name in room_names}
            }

        for booking in bookings:
            date = booking.booking_date
            period = booking.period
            room_name = booking.room.name if booking.room else "Desconhecido"
            user_name = booking.user.name if booking.user else "Desconhecido"
            
            if date in schedule_data and period in schedule_data[date] and room_name in schedule_data[date][period]:
                schedule_data[date][period][room_name] = user_name

        # Gerar PDF
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        # Título
        c.setFont("Helvetica-Bold", 16)
        c.drawString(inch, height - inch, f"Escala de Agendamentos - Semana de {monday_of_week.strftime('%d/%m/%Y')}")

        # Cabeçalho da tabela
        y_start = height - 1.5 * inch
        x_start = inch
        col_width = (width - 2 * inch) / (len(room_names) + 1) # +1 para a coluna de Período/Dia
        row_height = 0.3 * inch

        # Desenhar cabeçalho de salas
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x_start + col_width, y_start, "Período/Dia")
        for i, room_name in enumerate(room_names):
            c.drawString(x_start + (i + 1) * col_width + col_width/2 - c.stringWidth(room_name, "Helvetica-Bold", 8)/2, y_start, room_name)

        y_position = y_start - row_height

        # Desenhar linhas da tabela
        c.setFont("Helvetica", 7)
        days_of_week_pt = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira"]

        for i in range(5):
            current_date = monday_of_week + timedelta(days=i)
            day_name = days_of_week_pt[i]
            
            # Linha da Manhã
            c.drawString(x_start + col_width, y_position, f"{day_name} - Manhã")
            for j, room_name in enumerate(room_names):
                text = schedule_data[current_date]["Manhã"][room_name]
                c.drawString(x_start + (j + 1) * col_width + col_width/2 - c.stringWidth(text, "Helvetica", 7)/2, y_position, text)
            y_position -= row_height

            # Linha da Tarde
            c.drawString(x_start + col_width, y_position, f"{day_name} - Tarde")
            for j, room_name in enumerate(room_names):
                text = schedule_data[current_date]["Tarde"][room_name]
                c.drawString(x_start + (j + 1) * col_width + col_width/2 - c.stringWidth(text, "Helvetica", 7)/2, y_position, text)
            y_position -= row_height

        c.save()
        buffer.seek(0)
        current_app.logger.info("PDF gerado com sucesso.")
        return send_file(buffer, as_attachment=True, download_name=f"escala_{monday_of_week.strftime('%Y-%m-%d')}.pdf", mimetype='application/pdf')

    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {e}", exc_info=True)
        return jsonify({"error": "Erro ao gerar PDF da escala."}), 500


