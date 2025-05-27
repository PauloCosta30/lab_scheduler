
from flask import Blueprint, request, jsonify, current_app, Response, make_response
from src.extensions import db
from src.models.entities import Room, Booking
from datetime import datetime, date, time, timedelta, timezone
from collections import defaultdict
from flask_mail import Message  # Import Message for Flask-Mail
# PDF Generation
from weasyprint import HTML, CSS
from jinja2 import Environment, FileSystemLoader
import os

bookings_bp = Blueprint("bookings_bp", __name__)

MAX_BOOKINGS_PER_DAY = 3

# --- Booking Window Configuration ---
CUTOFF_WEEKDAY = 2  # Wednesday
CUTOFF_TIME = time(18, 0, 0, tzinfo=timezone.utc)
RELEASE_WEEKDAY = 4  # Friday
RELEASE_TIME = time(0, 0, 0, tzinfo=timezone.utc)
# ----------------------------------

# Helper function to send confirmation email
def send_booking_confirmation_email(user_email, user_name, coordinator_name, booked_slots_details):
    mail = current_app.extensions.get("mail")
    if not mail:
        current_app.logger.error("Flask-Mail not found. Email not sent.")
        return False
    if not booked_slots_details:
        current_app.logger.info("No booking details for email.")
        return False

    subject = "Confirmação de Agendamento de Laboratório"
    sender = current_app.config.get("MAIL_DEFAULT_SENDER", "noreply@example.com")
    recipients = [user_email]

    html_body = f"""<p>Olá {user_name},</p><p>Seu agendamento foi confirmado:</p><ul>"""
    for slot in booked_slots_details:
        booking_date_formatted = slot["booking_date"]
        try:
            booking_date_formatted = datetime.strptime(slot["booking_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            pass
        html_body += f"<li>Sala: {slot['room_name']} - Data: {booking_date_formatted} - Período: {slot['period']}</li>"
    html_body += f"</ul><p>Coordenador: {coordinator_name}</p><p>Obrigado!</p>"

    msg = Message(subject, sender=sender, recipients=recipients)
    msg.html = html_body

    try:
        mail.send(msg)
        current_app.logger.info(f"Confirmation email sent to {user_email}")
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send email to {user_email}: {str(e)}")
        return False
