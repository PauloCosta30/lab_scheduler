# /home/ubuntu/lab_scheduler/src/models/entities.py

from ..extensions import db
from sqlalchemy.sql import func
import datetime

class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    
    bookings = db.relationship("Booking", backref="room", lazy=True)

    def __repr__(self):
        return f"<Room {self.name}>"

class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(120), nullable=False)
    user_email = db.Column(db.String(120), nullable=False) # Novo campo
    coordinator_name = db.Column(db.String(120), nullable=True) # Novo campo, pode ser opcional
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)
    booking_date = db.Column(db.Date, nullable=False)
    period = db.Column(db.String(20), nullable=False)  # "Manhã" ou "Tarde"
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Booking {self.user_name} ({self.user_email}) - Room: {self.room.name} on {self.booking_date} ({self.period}) - Coord: {self.coordinator_name}>"

