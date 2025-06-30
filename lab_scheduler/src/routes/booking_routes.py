# /home/ubuntu/lab_scheduler/src/routes/booking_routes.py

from flask import Blueprint, request, jsonify, current_app, render_template, make_response
from src.extensions import db
from src.models.entities import Room, Booking
from datetime import datetime, date, timedelta, time
from collections import defaultdict
from flask_mail import Message
import re
import pytz  # Importar pytz para lidar com fusos horários
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

# Decorator para verificação de rate limiting (se necessário)
def rate_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Implementar lógica de rate limiting se necessário
        return f(*args, **kwargs)
    return decorated_function

# ROTA PRINCIPAL MODIFICADA - create_booking
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

        # Validação básica - apenas campos obrigatórios do usuário
        if not all([user_name, user_email, coordinator_name]):
            return jsonify({
                "error": "Missing fields. Required: user_name, user_email, coordinator_name"
            }), 400

        # Validação de email
        if "@" not in user_email or "." not in user_email.split("@")[-1]:
            return jsonify({"error": "Invalid email format"}), 400

        # Se não há slots, criar apenas uma entrada de observação geral
        if not slots_data:
            # Encontrar o próximo slot disponível ou criar um registro especial
            today = datetime.now(BRASILIA_TZ).date()
            
            # Criar um booking especial para salvar as informações do usuário
            general_booking = Booking(
                user_name=user_name,
                user_email=user_email,
                coordinator_name=coordinator_name,
                observation=f"[SEM SALA SELECIONADA] {observation}",
                date=today,
                start_time=time(0, 0),  # Horário especial para indicar "sem horário"
                end_time=time(0, 0),
                room_id=None,  # Sem sala selecionada
                status="info_only",  # Status especial para indicar apenas informações
                created_at=datetime.now(BRASILIA_TZ)
            )
            
            db.session.add(general_booking)
            db.session.commit()
            
            return jsonify({
                "message": "Informações do usuário salvas com sucesso (sem agendamento de sala)",
                "booking_id": general_booking.id,
                "user_info": {
                    "user_name": user_name,
                    "user_email": user_email,
                    "coordinator_name": coordinator_name,
                    "observation": observation,
                    "status": "info_saved"
                }
            }), 201

        # Processar slots normalmente quando há seleção de salas
        bookings_created = []
        
        for slot in slots_data:
            room_id = slot.get("room_id")
            date_str = slot.get("date")
            start_time_str = slot.get("start_time")
            end_time_str = slot.get("end_time")
            
            # Validar dados do slot
            if not all([room_id, date_str, start_time_str, end_time_str]):
                return jsonify({
                    "error": "Missing slot information"
                }), 400
            
            # Verificar se a sala existe
            room = Room.query.get(room_id)
            if not room:
                return jsonify({
                    "error": f"Room with ID {room_id} not found"
                }), 404
            
            # Converter strings para objetos datetime
            try:
                booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                start_time_obj = datetime.strptime(start_time_str, "%H:%M").time()
                end_time_obj = datetime.strptime(end_time_str, "%H:%M").time()
            except ValueError as e:
                return jsonify({
                    "error": f"Invalid date/time format: {str(e)}"
                }), 400
            
            # Verificar se a data não é no passado
            today = datetime.now(BRASILIA_TZ).date()
            if booking_date < today:
                return jsonify({
                    "error": "Cannot book rooms for past dates"
                }), 400
            
            # Verificar conflitos de horário
            conflicting_booking = Booking.query.filter(
                Booking.room_id == room_id,
                Booking.date == booking_date,
                Booking.status != "cancelled"
            ).filter(
                db.or_(
                    db.and_(
                        Booking.start_time <= start_time_obj,
                        Booking.end_time > start_time_obj
                    ),
                    db.and_(
                        Booking.start_time < end_time_obj,
                        Booking.end_time >= end_time_obj
                    ),
                    db.and_(
                        Booking.start_time >= start_time_obj,
                        Booking.end_time <= end_time_obj
                    )
                )
            ).first()
            
            if conflicting_booking:
                return jsonify({
                    "error": f"Time slot conflict for room {room.name} on {date_str} from {start_time_str} to {end_time_str}"
                }), 409
            
            # Criar o booking
            booking = Booking(
                user_name=user_name,
                user_email=user_email,
                coordinator_name=coordinator_name,
                observation=observation,
                room_id=room_id,
                date=booking_date,
                start_time=start_time_obj,
                end_time=end_time_obj,
                status="confirmed",
                created_at=datetime.now(BRASILIA_TZ)
            )
            
            db.session.add(booking)
            bookings_created.append({
                "room_name": room.name,
                "date": date_str,
                "start_time": start_time_str,
                "end_time": end_time_str
            })
        
        # Confirmar todas as operações
        db.session.commit()
        
        # Enviar email de confirmação
        try:
            send_booking_confirmation_email(user_email, user_name, bookings_created, observation)
        except Exception as email_error:
            current_app.logger.error(f"Failed to send confirmation email: {str(email_error)}")
        
        return jsonify({
            "message": "Bookings created successfully",
            "bookings": bookings_created,
            "user_info": {
                "user_name": user_name,
                "user_email": user_email,
                "coordinator_name": coordinator_name
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating booking: {str(e)}")
        return jsonify({
            "error": "Internal server error"
        }), 500

# Função auxiliar para envio de email
def send_booking_confirmation_email(user_email, user_name, bookings, observation):
    """Envia email de confirmação para o usuário"""
    try:
        from src.extensions import mail
        
        if not bookings:
            subject = "Informações Registradas - Sistema de Agendamento"
            body = f"""
            Olá {user_name},
            
            Suas informações foram registradas em nosso sistema:
            
            Observação: {observation}
            
            Caso precise agendar uma sala posteriormente, entre em contato conosco.
            
            Atenciosamente,
            Equipe de Agendamentos
            """
        else:
            subject = "Confirmação de Agendamento - Laboratório"
            body = f"""
            Olá {user_name},
            
            Seu agendamento foi confirmado com sucesso!
            
            Detalhes do agendamento:
            """
            
            for booking in bookings:
                body += f"""
            - Sala: {booking['room_name']}
            - Data: {booking['date']}
            - Horário: {booking['start_time']} às {booking['end_time']}
            """
            
            if observation:
                body += f"""
            
            Observação: {observation}
            """
            
            body += """
            
            Atenciosamente,
            Equipe de Agendamentos
            """
        
        msg = Message(
            subject=subject,
            recipients=[user_email],
            body=body
        )
        
        mail.send(msg)
        
    except Exception as e:
        current_app.logger.error(f"Error sending email: {str(e)}")
        raise

# Rota para buscar bookings
@bookings_bp.route("/bookings", methods=["GET"])
def get_bookings():
    try:
        # Parâmetros de consulta
        date_param = request.args.get("date")
        room_id = request.args.get("room_id")
        user_email = request.args.get("user_email")
        include_info_only = request.args.get("include_info_only", "false").lower() == "true"
        
        # Construir query base
        query = Booking.query
        
        # Filtrar por data se fornecida
        if date_param:
            try:
                filter_date = datetime.strptime(date_param, "%Y-%m-%d").date()
                query = query.filter(Booking.date == filter_date)
            except ValueError:
                return jsonify({"error": "Invalid date format"}), 400
        
        # Filtrar por sala se fornecida
        if room_id:
            query = query.filter(Booking.room_id == room_id)
        
        # Filtrar por email do usuário se fornecido
        if user_email:
            query = query.filter(Booking.user_email == user_email)
        
        # Incluir ou excluir registros apenas informativos
        if not include_info_only:
            query = query.filter(Booking.status != "info_only")
        
        # Ordenar por data e horário
        bookings = query.order_by(Booking.date, Booking.start_time).all()
        
        # Converter para JSON
        bookings_data = []
        for booking in bookings:
            booking_data = {
                "id": booking.id,
                "user_name": booking.user_name,
                "user_email": booking.user_email,
                "coordinator_name": booking.coordinator_name,
                "observation": booking.observation,
                "date": booking.date.strftime("%Y-%m-%d"),
                "start_time": booking.start_time.strftime("%H:%M") if booking.start_time else None,
                "end_time": booking.end_time.strftime("%H:%M") if booking.end_time else None,
                "room_name": booking.room.name if booking.room else None,
                "room_id": booking.room_id,
                "status": booking.status,
                "created_at": booking.created_at.strftime("%Y-%m-%d %H:%M:%S") if booking.created_at else None
            }
            bookings_data.append(booking_data)
        
        return jsonify({
            "bookings": bookings_data,
            "total": len(bookings_data)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching bookings: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# Rota para buscar apenas informações de usuários (sem agendamento)
@bookings_bp.route("/user-info", methods=["GET"])
def get_user_info():
    try:
        # Buscar apenas registros com status "info_only"
        info_bookings = Booking.query.filter(
            Booking.status == "info_only"
        ).order_by(Booking.created_at.desc()).all()
        
        user_info_data = []
        for booking in info_bookings:
            user_info_data.append({
                "id": booking.id,
                "user_name": booking.user_name,
                "user_email": booking.user_email,
                "coordinator_name": booking.coordinator_name,
                "observation": booking.observation.replace("[SEM SALA SELECIONADA] ", ""),
                "created_at": booking.created_at.strftime("%Y-%m-%d %H:%M:%S") if booking.created_at else None
            })
        
        return jsonify({
            "user_info": user_info_data,
            "total": len(user_info_data)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching user info: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# Rota para gerar PDF incluindo informações de usuários
@bookings_bp.route("/generate-pdf", methods=["POST"])
def generate_pdf():
    if not WEASYPRINT_AVAILABLE:
        return jsonify({
            "error": "PDF generation not available"
        }), 503
    
    try:
        data = request.get_json()
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        include_user_info = data.get("include_user_info", True)
        
        if not start_date or not end_date:
            return jsonify({
                "error": "start_date and end_date are required"
            }), 400
        
        # Converter datas
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date format"}), 400
        
        # Buscar agendamentos com salas
        bookings = Booking.query.filter(
            Booking.date >= start_date_obj,
            Booking.date <= end_date_obj,
            Booking.status != "info_only"
        ).order_by(Booking.date, Booking.start_time).all()
        
        # Buscar informações de usuários sem agendamento
        user_info = []
        if include_user_info:
            user_info = Booking.query.filter(
                Booking.created_at >= datetime.combine(start_date_obj, time.min),
                Booking.created_at <= datetime.combine(end_date_obj, time.max),
                Booking.status == "info_only"
            ).order_by(Booking.created_at).all()
        
        # Renderizar HTML
        html_content = render_template(
            "booking_report.html",
            bookings=bookings,
            user_info=user_info,
            start_date=start_date,
            end_date=end_date,
            include_user_info=include_user_info
        )
        
        # Gerar PDF
        pdf = HTML(string=html_content).write_pdf()
        
        # Retornar PDF
        response = make_response(pdf)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"attachment; filename=relatorio_{start_date}_{end_date}.pdf"
        
        return response
        
    except Exception as e:
        current_app.logger.error(f"Error generating PDF: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# Rota para cancelar booking
@bookings_bp.route("/bookings/<int:booking_id>", methods=["DELETE"])
def cancel_booking(booking_id):
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({"error": "Booking not found"}), 404
        
        booking.status = "cancelled"
        db.session.commit()
        
        return jsonify({"message": "Booking cancelled successfully"}), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error cancelling booking: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# Rota para buscar salas disponíveis
@bookings_bp.route("/available-rooms", methods=["GET"])
def get_available_rooms():
    try:
        date_param = request.args.get("date")
        start_time_param = request.args.get("start_time")
        end_time_param = request.args.get("end_time")
        
        if not all([date_param, start_time_param, end_time_param]):
            return jsonify({
                "error": "date, start_time, and end_time are required"
            }), 400
        
        # Converter parâmetros
        try:
            check_date = datetime.strptime(date_param, "%Y-%m-%d").date()
            start_time = datetime.strptime(start_time_param, "%H:%M").time()
            end_time = datetime.strptime(end_time_param, "%H:%M").time()
        except ValueError:
            return jsonify({"error": "Invalid date/time format"}), 400
        
        # Buscar salas ocupadas no horário especificado
        occupied_rooms = db.session.query(Booking.room_id).filter(
            Booking.date == check_date,
            Booking.status != "cancelled",
            db.or_(
                db.and_(
                    Booking.start_time <= start_time,
                    Booking.end_time > start_time
                ),
                db.and_(
                    Booking.start_time < end_time,
                    Booking.end_time >= end_time
                ),
                db.and_(
                    Booking.start_time >= start_time,
                    Booking.end_time <= end_time
                )
            )
        ).subquery()
        
        # Buscar salas disponíveis
        available_rooms = Room.query.filter(
            ~Room.id.in_(occupied_rooms)
        ).all()
        
        rooms_data = [
            {
                "id": room.id,
                "name": room.name,
                "capacity": room.capacity,
                "description": room.description
            }
            for room in available_rooms
        ]
        
        return jsonify({
            "available_rooms": rooms_data,
            "total": len(rooms_data)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching available rooms: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
