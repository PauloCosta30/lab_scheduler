# /home/ubuntu/lab_scheduler/src/routes/booking_routes.py

from flask import Blueprint, request, jsonify, current_app, render_template, make_response
from src.extensions import db
from src.models.entities import Room, Booking
from datetime import datetime, date, timedelta, time
from collections import defaultdict
from flask_mail import Message
import re
import pytz
from functools import wraps

# Importação condicional do weasyprint
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    # Usar try-except para evitar erro se current_app não estiver disponível durante importação
    try:
        current_app.logger.warning("WeasyPrint não está disponível. Geração de PDF desabilitada.")
    except RuntimeError:
        print("WeasyPrint não está disponível. Geração de PDF desabilitada.")

bookings_bp = Blueprint("bookings_bp", __name__)

MAX_BOOKINGS_PER_DAY = 3

# Definir o fuso horário de Brasília
BRASILIA_TZ = pytz.timezone("America/Sao_Paulo")

def rate_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function

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
        slots_data = data.get("slots", [])

        # Validação básica
        if not all([user_name, user_email, coordinator_name]):
            return jsonify({
                "error": "Missing fields. Required: user_name, user_email, coordinator_name"
            }), 400

        # Validação de email
        if "@" not in user_email or "." not in user_email.split("@")[-1]:
            return jsonify({"error": "Invalid email format"}), 400

        # Se não há slots, criar apenas uma entrada de observação geral
        if not slots_data:
            today = datetime.now(BRASILIA_TZ).date()
            
            # Verificar se o modelo Booking suporta os campos necessários
            general_booking = Booking(
                user_name=user_name,
                user_email=user_email,
                observation=f"[SEM SALA SELECIONADA] {observation}",
                date=today,
                created_at=datetime.now(BRASILIA_TZ)
            )
            
            # Adicionar campos opcionais se existirem no modelo
            if hasattr(Booking, 'coordinator_name'):
                general_booking.coordinator_name = coordinator_name
            if hasattr(Booking, 'start_time'):
                general_booking.start_time = time(0, 0)
            if hasattr(Booking, 'end_time'):
                general_booking.end_time = time(0, 0)
            if hasattr(Booking, 'room_id'):
                general_booking.room_id = None
            if hasattr(Booking, 'status'):
                general_booking.status = "info_only"
            
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
            
            if not all([room_id, date_str, start_time_str, end_time_str]):
                return jsonify({"error": "Missing slot information"}), 400
            
            # Verificar se a sala existe
            room = Room.query.get(room_id)
            if not room:
                return jsonify({"error": f"Room with ID {room_id} not found"}), 404
            
            # Converter strings para objetos datetime
            try:
                booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                start_time_obj = datetime.strptime(start_time_str, "%H:%M").time()
                end_time_obj = datetime.strptime(end_time_str, "%H:%M").time()
            except ValueError as e:
                return jsonify({"error": f"Invalid date/time format: {str(e)}"}), 400
            
            # Verificar se a data não é no passado
            today = datetime.now(BRASILIA_TZ).date()
            if booking_date < today:
                return jsonify({"error": "Cannot book rooms for past dates"}), 400
            
            # Verificar conflitos (simplificado para compatibilidade)
            conflicting_booking = Booking.query.filter(
                Booking.room_id == room_id,
                Booking.date == booking_date
            ).first()
            
            if conflicting_booking:
                # Verificação mais detalhada de conflito se os campos existirem
                if (hasattr(Booking, 'start_time') and hasattr(Booking, 'end_time') and
                    conflicting_booking.start_time and conflicting_booking.end_time):
                    # Lógica de verificação de conflito de horário
                    if not (end_time_obj <= conflicting_booking.start_time or 
                           start_time_obj >= conflicting_booking.end_time):
                        return jsonify({
                            "error": f"Time slot conflict for room {room.name} on {date_str}"
                        }), 409
            
            # Criar o booking
            booking = Booking(
                user_name=user_name,
                user_email=user_email,
                observation=observation,
                room_id=room_id,
                date=booking_date,
                created_at=datetime.now(BRASILIA_TZ)
            )
            
            # Adicionar campos opcionais
            if hasattr(Booking, 'coordinator_name'):
                booking.coordinator_name = coordinator_name
            if hasattr(Booking, 'start_time'):
                booking.start_time = start_time_obj
            if hasattr(Booking, 'end_time'):
                booking.end_time = end_time_obj
            if hasattr(Booking, 'status'):
                booking.status = "confirmed"
            
            db.session.add(booking)
            bookings_created.append({
                "room_name": room.name,
                "date": date_str,
                "start_time": start_time_str,
                "end_time": end_time_str
            })
        
        db.session.commit()
        
        # Tentar enviar email (opcional)
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
        return jsonify({"error": "Internal server error"}), 500

def send_booking_confirmation_email(user_email, user_name, bookings, observation):
    """Envia email de confirmação para o usuário"""
    try:
        from src.extensions import mail
        
        if not bookings:
            subject = "Informações Registradas - Sistema de Agendamento"
            body = f"""
            Olá {user_name},
            
            Suas informações foram registradas em nosso sistema.
            
            Observação: {observation}
            
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
                body += f"\nObservação: {observation}"
            
            body += "\n\nAtenciosamente,\nEquipe de Agendamentos"
        
        msg = Message(
            subject=subject,
            recipients=[user_email],
            body=body
        )
        
        mail.send(msg)
        
    except Exception as e:
        current_app.logger.error(f"Error sending email: {str(e)}")
        raise

@bookings_bp.route("/bookings", methods=["GET"])
def get_bookings():
    try:
        date_param = request.args.get("date")
        room_id = request.args.get("room_id")
        user_email = request.args.get("user_email")
        include_info_only = request.args.get("include_info_only", "false").lower() == "true"
        
        query = Booking.query
        
        if date_param:
            try:
                filter_date = datetime.strptime(date_param, "%Y-%m-%d").date()
                query = query.filter(Booking.date == filter_date)
            except ValueError:
                return jsonify({"error": "Invalid date format"}), 400
        
        if room_id:
            query = query.filter(Booking.room_id == room_id)
        
        if user_email:
            query = query.filter(Booking.user_email == user_email)
        
        if not include_info_only and hasattr(Booking, 'status'):
            query = query.filter(Booking.status != "info_only")
        
        bookings = query.order_by(Booking.date).all()
        
        bookings_data = []
        for booking in bookings:
            booking_data = {
                "id": booking.id,
                "user_name": booking.user_name,
                "user_email": booking.user_email,
                "observation": booking.observation,
                "date": booking.date.strftime("%Y-%m-%d"),
                "room_id": booking.room_id
            }
            
            # Adicionar campos opcionais se existirem
            if hasattr(booking, 'coordinator_name'):
                booking_data["coordinator_name"] = booking.coordinator_name
            if hasattr(booking, 'start_time') and booking.start_time:
                booking_data["start_time"] = booking.start_time.strftime("%H:%M")
            if hasattr(booking, 'end_time') and booking.end_time:
                booking_data["end_time"] = booking.end_time.strftime("%H:%M")
            if hasattr(booking, 'status'):
                booking_data["status"] = booking.status
            if hasattr(booking, 'created_at') and booking.created_at:
                booking_data["created_at"] = booking.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if booking.room:
                booking_data["room_name"] = booking.room.name
            
            bookings_data.append(booking_data)
        
        return jsonify({
            "bookings": bookings_data,
            "total": len(bookings_data)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching bookings: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# Adicione outras rotas conforme necessário...
