import os
import sys
import logging

# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, send_from_directory, render_template
from src.extensions import db
from src.models.entities import Room, Booking
from src.routes.booking_routes import bookings_bp
from flask_mail import Mail
from datetime import datetime

# Configuração correta do Flask para servir arquivos estáticos
app = Flask(__name__, 
           static_folder=os.path.join(os.path.dirname(__file__), 'static'),
           template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'a_very_strong_random_secret_key_dev_123!@#')

# Configuração do banco de dados SQLite com volume persistente
if os.getenv('RENDER'):
    # Produção no Render - usar diretório persistente
    db_path = '/opt/render/project/data/lab_scheduler.db'
    # Criar diretório se não existir
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
else:
    # Desenvolvimento local
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(project_root, 'lab_scheduler.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Flask-Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'true').lower() in ['true', '1', 't']
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'false').lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'itvdslab@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'cast qddf bxby mwsl')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', ('LAB.ITV', 'noreply@gmail.com'))

mail = Mail(app)
db.init_app(app)

# Configuração de logging
app.logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

@app.template_filter('format_date')
def format_date_filter(date_value, fmt="%d/%m"):
    """Filtro para formatação de datas nos templates"""
    if isinstance(date_value, str):
        try:
            date_obj = datetime.strptime(date_value, "%Y-%m-%d").date()
            return date_obj.strftime(fmt)
        except ValueError:
            return date_value
    elif hasattr(date_value, 'strftime'):
        return date_value.strftime(fmt)
    else:
        return str(date_value)

def init_database():
    """Inicializa o banco de dados e cria as salas se não existirem"""
    try:
        app.logger.info(f"Initializing database at: {db_path}")
        db.create_all()
        
        if not Room.query.first():
            room_names = [
                "Geral 1", "Geral 2", "Geral 3", "Geral 4", "Geral 5", "Geral 6", "Geral 7", "Geral 8",
                "Geral 9", "Geral 10", "Geral 11", "Geral 12",
                "Citometria - Bancada", "Sala Clara - Lupa esquerda", "Sala Clara - Lupa direita",
                "Sala Clara - Lupa com Câmera", "Sala Clara - Microscópio", "Sala Escura - Axio Imager.M2", 
                "Sala Escura - Axio Scope.A1", "Sala Escura - Microscópio CONFOCAL-LMSN",
                "Microbiologia - Capela de Fluxo Laminar", "Microbiologia - Lupa", "Microbiologia - Equipamento",
                "Geologia 1", "Geologia Micrótomo", "Cultivo A1", "Cultivo A2", "Cultivo B1", "Cultivo B2"
            ]
            
            for name in room_names:
                room = Room(name=name)
                db.session.add(room)
            
            db.session.commit()
            app.logger.info("Database initialized and custom rooms created.")
        else:
            app.logger.info("Database already initialized with rooms.")
            
    except Exception as e:
        app.logger.error(f"Error initializing database: {str(e)}")
        db.session.rollback()
        raise

# Inicialização do banco de dados
with app.app_context():
    init_database()

# Registrar blueprint
app.register_blueprint(bookings_bp, url_prefix='/api')

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve arquivos estáticos explicitamente"""
    return send_from_directory(app.static_folder, filename)

@app.route('/')
def index():
    """Serve a página principal"""
    try:
        return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        return f"Erro ao carregar página: {str(e)}", 500

@app.route('/<path:path>')
def serve_spa(path):
    """Serve arquivos estáticos ou redireciona para index.html"""
    try:
        if os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        else:
            return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        return f"Erro ao servir arquivo: {str(e)}", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
