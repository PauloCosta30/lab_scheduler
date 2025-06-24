import os
from datetime import datetime, timedelta, time, timezone
from flask import Blueprint, request, jsonify, current_app, send_file, Response, make_response
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, and_
from sqlalchemy.orm import joinedload

# PDF Generation (from your provided file)
from weasyprint import HTML, CSS
from jinja2 import Environment, FileSystemLoader
import io # Import io for BytesIO

# Assuming these are in src.extensions and src.models.entities
from src.extensions import db
from src.models.entities import Booking, Room, User # Assuming User is also defined

bookings_bp = Blueprint('bookings_bp', __name__)

# Constantes de configuração
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "lab_scheduler_admin")
# Horários em UTC
CUTOFF_WEEKDAY = 2  # Wednesday (0=Monday, 1=Tuesday, ..., 6=Sunday)
CUTOFF_TIME = time(21, 0, 0, tzinfo=timezone.utc)  # 18:00 Brasília = 21:00 UTC
RELEASE_WEEKDAY = 3  # Thursday
RELEASE_TIME = time(2, 59, 0, tzinfo=timezone.utc)  # 23:59 Brasília = 02:59 UTC (do dia seguinte)

# Helper function for custom room sorting
def custom_room_sort_key(room):
    name = room.name
    if "Geral" in name:
        try:
            # Extract the number from "Geral X"
            num_str = "".join(filter(str.isdigit, name))
            num = int(num_str) if num_str else float('inf') # Handle "Geral" without number
            return (0, num) # Prioritize "Geral" rooms and sort them numerically
        except ValueError:
            return (0, float('inf')) # Fallback for "Geral" rooms with non-numeric parts
    return (1, name) # Other rooms come after, sorted alphabetically

# Helper function to get Monday of a week containing the given date
def get_monday_of_week(input_date):
    """Retorna a segunda-feira da semana de uma data."""
    # weekday() returns 0 for Monday, 1 for Tuesday, etc.
    # If it's Sunday (6), we want the next day (Monday)
    if input_date.weekday() == 6:  # Sunday
        return input_date + timedelta(days=1)
    else:
        # For all other days, go back to Monday of the same week
        return input_date - timedelta(days=input_date.weekday())

# Helper function to get Brazilian time (UTC-3)
def get_brazilian_time(dt_utc):
    """Converte um datetime UTC para o horário de Brasília (UTC-3)."""
    if dt_utc.tzinfo is None:
        # Se não tiver timezone, assume UTC
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    
    brazil_timezone = timezone(timedelta(hours=-3))
    return dt_utc.astimezone(brazil_timezone)

# Helper function to check booking window rules (Reverted to block weekends)
def is_booking_allowed(booking_date_obj):
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date()
    
    # CORREÇÃO: Garantir que a semana sempre comece na segunda-feira
    start_of_current_week = get_monday_of_week(today_utc)
    next_week_monday = start_of_current_week + timedelta(days=7) # Monday of next week
    
    # Define o fim da semana (sexta-feira)
    end_of_current_week = start_of_current_week + timedelta(days=4) # Friday of current week
    end_of_next_week = next_week_monday + timedelta(days=4) # Friday of next week

    # Cutoff for the *current* week is Wednesday 18:00 Brazil Time (21:00 UTC)
    cutoff_datetime_current_week = datetime.combine(start_of_current_week + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)
    
    # Release for the *next* week is Thursday 23:59 Brazil Time (Friday 02:59 UTC)
    thursday_current_week = start_of_current_week + timedelta(days=RELEASE_WEEKDAY)
    release_datetime_next_week = datetime.combine(thursday_current_week, RELEASE_TIME)
    
    # Make time objects timezone-aware for comparison
    time_midnight_utc = time(0, 0, 0, tzinfo=timezone.utc)
    time_3am_utc = time(3, 0, 0, tzinfo=timezone.utc)
    # Compare RELEASE_TIME (aware) with aware time objects
    if RELEASE_TIME < time_midnight_utc or (RELEASE_TIME >= time_midnight_utc and RELEASE_TIME < time_3am_utc):
         release_datetime_next_week += timedelta(days=1)

    # Cutoff for the *next* week is Wednesday 18:00 Brazil Time (21:00 UTC) of that next week
    cutoff_datetime_next_week = datetime.combine(next_week_monday + timedelta(days=CUTOFF_WEEKDAY), CUTOFF_TIME)

    # Re-enable weekend check
    if booking_date_obj.weekday() >= 5:
        return False, f"Agendamentos só permitidos de Seg-Sex. Data: {booking_date_obj.strftime('%d/%m/%Y')} é fim de semana."
    
    # Check booking date against windows (using Friday as end of week)
    if start_of_current_week <= booking_date_obj <= end_of_current_week: # Booking for current week (Mon-Fri)
        if now_utc >= cutoff_datetime_current_week:
            return False, f"Agendamento para semana atual ({start_of_current_week.strftime('%d/%m')}-{end_of_current_week.strftime('%d/%m')}) encerrou Qua 18:00 (Horário Local)."
        else:
            return True, "OK"
            
    elif next_week_monday <= booking_date_obj <= end_of_next_week: # Booking for next week (Mon-Fri)
        if now_utc < release_datetime_next_week:
             return False, f"Agendamento para próxima semana ({next_week_monday.strftime('%d/%m')}-{end_of_next_week.strftime('%d/%m')}) abre Qui 23:59 (Horário Local)."
        elif now_utc >= cutoff_datetime_next_week:
             return False, f"Agendamento para semana de {next_week_monday.strftime('%d/%m')} já encerrou (Qua 18:00 Horário Local)."
        else:
             # It's after release time and before next week's cutoff
             return True, "OK"
             
    else: # Booking for weeks beyond the next one, or past weeks
        # Allow booking past dates based on previous user request
        if booking_date_obj < start_of_current_week:
             # Still need to check if the past date is a weekend
             if booking_date_obj.weekday() >= 5:
                 return False, f"Agendamentos só permitidos de Seg-Sex. Data: {booking_date_obj.strftime('%d/%m/%Y')} é fim de semana."
             else:
                 return True, "OK" 
        else: # Booking for week after next or later
            return False, f"Só é possível agendar para semana atual ou próxima. Data: {booking_date_obj.strftime('%d/%m/%Y')} fora do período permitido."

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
        current_app.logger.debug("Fetching rooms...")
        rooms = Room.query.all() # Fetch all rooms
        
        # Apply custom sorting
        sorted_rooms = sorted(rooms, key=custom_room_sort_key)
        
        room_list = [{"id": room.id, "name": room.name} for room in sorted_rooms]
        current_app.logger.debug(f"Rooms fetched: {len(room_list)}")
        return jsonify(room_list)
    except Exception as e:
        current_app.logger.error(f"Error fetching rooms: {str(e)}", exc_info=True)
        return jsonify({"error": "Erro ao buscar salas"}), 500

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

        # Fetch data for the specified week (Mon-Fri)
        current_app.logger.debug("Fetching rooms and bookings for PDF")
        rooms = Room.query.all() # Fetch all rooms
        
        # Apply custom sorting to rooms for PDF
        sorted_rooms = sorted(rooms, key=custom_room_sort_key)
        
        bookings_query = db.session.query(Booking).options(joinedload(Booking.room), joinedload(Booking.user)).filter(
            Booking.booking_date.between(monday_of_week, friday_of_week),
            func.extract('dow', Booking.booking_date).notin_([0, 6]) # Exclude Sunday (0) and Saturday (6)
        ).order_by(Booking.booking_date, Booking.room_id, Booking.period)
        bookings = bookings_query.all()
        current_app.logger.debug(f"Found {len(bookings)} bookings for PDF week")
        
        # Prepare data for template
        schedule_data = {}
        for i in range(5): # Monday to Friday
            current_date = monday_of_week + timedelta(days=i)
            schedule_data[current_date.isoformat()] = {
                "Manhã": {room.name: "" for room in sorted_rooms},
                "Tarde": {room.name: "" for room in sorted_rooms}
            }

        for booking in bookings:
            room_name = booking.room.name if booking.room else "Sala Desconhecida"
            user_name = booking.user.name if booking.user else "Desconhecido"
            
            date_iso = booking.booking_date.isoformat()
            if date_iso in schedule_data and booking.period in schedule_data[date_iso] and room_name in schedule_data[date_iso][booking.period]:
                schedule_data[date_iso][booking.period][room_name] = user_name
            
        dates_of_week = [(monday_of_week + timedelta(days=i)).isoformat() for i in range(5)] # Changed back to 5 days
        days_locale = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"] # Reverted to 5 days
        
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
        
        # Render HTML template (Template itself needs update for 5 days)
        current_app.logger.debug("Rendering PDF HTML template")
        template = env.get_template("schedule_pdf_template.html") 
        html_string = template.render(
            rooms=sorted_rooms, # Use sorted rooms here
            dates_of_week=dates_of_week,
            days_locale=days_locale,
            schedule_data=schedule_data,
            week_start_date_formatted=monday_of_week.strftime("%d/%m/%Y"),
            week_end_date_formatted=friday_of_week.strftime("%d/%m/%Y")
        )
        
        # Generate PDF
        current_app.logger.debug("Generating PDF bytes using WeasyPrint")
        pdf_bytes = HTML(string=html_string).write_pdf() # Removed explicit CSS, assuming it's in template or default
        current_app.logger.debug("PDF generated successfully")
        
        # Create response
        response = make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"attachment; filename=escala_semana_{monday_of_week.strftime('%Y-%m-%d')}.pdf"
        
        return response

    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF para semana {monday_of_week.strftime('%Y-%m-%d')}: {e}", exc_info=True)
        return jsonify({"error": "Falha ao gerar PDF no servidor", "details": str(e)}), 500

# --- Admin Route to Download Database --- 
@bookings_bp.route("/admin/download-database", methods=["GET"])
def download_database():
    password = request.args.get("password")
    correct_password = current_app.config.get("ADMIN_PASSWORD", ADMIN_PASSWORD) # Get from env or use default
    
    if password != correct_password:
        current_app.logger.warning("Unauthorized attempt to download database")
        return jsonify({"error": "Unauthorized"}), 401
        
    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI")
    if not db_uri or not db_uri.startswith("sqlite:///"):
        current_app.logger.error("Database download requested, but not using SQLite")
        return jsonify({"error": "Database download only supported for SQLite"}), 400
        
    db_path = db_uri.replace("sqlite:///", "")
    
    if not os.path.exists(db_path):
        current_app.logger.error(f"SQLite database file not found at: {db_path}")
        return jsonify({"error": "Database file not found"}), 404
        
    try:
        current_app.logger.info(f"Admin download of database file: {db_path}")
        return Response(
            open(db_path, "rb"),
            mimetype="application/vnd.sqlite3",
            headers={"Content-Disposition": "attachment;filename=lab_scheduler.db"}
        )
    except Exception as e:
        current_app.logger.error(f"Error serving database file: {str(e)}", exc_info=True)
        return jsonify({"error": "Error serving database file"}), 500

# --- NOVA ROTA: Admin Route to Clear Bookings ---
@bookings_bp.route("/admin/clear-bookings", methods=["POST"])
def clear_bookings():
    data = request.get_json()
    if not data:
        current_app.logger.warning("Invalid input for clear bookings: No data")
