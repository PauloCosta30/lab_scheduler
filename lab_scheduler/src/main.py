import os
import sys
import logging

# Configurar o path para encontrar os módulos
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)
sys.path.insert(0, current_dir)

# Agora importar com try/except para debug
try:
    from flask import Flask, send_from_directory, render_template
    from flask_mail import Mail
    from datetime import datetime
    
    # Tentar importar os módulos locais
    from src.extensions import db
    from src.models.entities import Room, Booking
    from src.routes.booking_routes import bookings_bp
    
    print("Todos os módulos importados com sucesso!")
    
except ImportError as e:
    print(f"Erro de importação: {e}")
    print(f"Diretório atual: {current_dir}")
    print(f"Diretório pai: {parent_dir}")
    print(f"Conteúdo do diretório atual: {os.listdir(current_dir)}")
    if os.path.exists(os.path.join(current_dir, 'src')):
        print(f"Conteúdo do diretório src: {os.listdir(os.path.join(current_dir, 'src'))}")
    sys.exit(1)

# Configuração do Flask
app = Flask(__name__, 
           static_folder=os.path.join(current_dir, 'static'),
           template_folder=os.path.join(current_dir, 'templates'))

app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'a_very_strong_random_secret_key_dev_123!@#')

# Configuração do banco de dados
database_url = os.getenv('DATABASE_URL')
if database_url:
    # Produção - PostgreSQL
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.logger.info("Usando PostgreSQL em produção")
else:
    # Desenvolvimento - SQLite
    db_path = os.path.join(parent_dir, 'lab_scheduler.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
    app.logger.info("Usando SQLite em desenvolvimento")

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

# Configurar logging
app.logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

# Filtro de template para formatação de data
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
    """Inicializa o banco de dados com as salas padrão"""
    with app.app_context():
        try:
            db.create_all()
            app.logger.info("Tabelas criadas com sucesso")
            
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
                app.logger.info("Salas criadas com sucesso")
            else:
                app.logger.info("Salas já existem no banco")
                
        except Exception as e:
            app.logger.error(f"Erro ao inicializar banco: {str(e)}")
            db.session.rollback()

# Inicializar banco
init_database()

# Registrar blueprint
app.register_blueprint(bookings_bp, url_prefix='/api')

# Rotas
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(app.static_folder, filename)

@app.route('/')
def index():
    try:
        return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        return f"Erro ao carregar página: {str(e)}", 500

@app.route('/<path:path>')
def serve_spa(path):
    try:
        if os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        else:
            return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        return f"Erro ao servir arquivo: {str(e)}", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
