from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail
import logging # Importar logging

db = SQLAlchemy()
migrate = Migrate()
mail = Mail()

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    # Configurar o nível de log para DEBUG
    app.logger.setLevel(logging.DEBUG) 

    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)

    from src.routes.booking_routes import bookings_bp
    app.register_blueprint(bookings_bp, url_prefix='/api')

    # Importar e registrar o blueprint de admin
    from src.routes.admin_routes import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    with app.app_context():
        db.create_all() # Cria as tabelas se não existirem
        # Inicializa as salas padrão se o banco de dados estiver vazio
        from src.models.entities import Room
        if Room.query.count() == 0:
            Room.initialize_default_rooms()
            app.logger.info("Database initialized and custom rooms created.")
    
    return app

