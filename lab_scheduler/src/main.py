import os
import sys
import logging
import time
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, send_from_directory, render_template
from src.extensions import db
from src.models.entities import Room, Booking
from src.routes.booking_routes import bookings_bp
from flask_mail import Mail # Import Flask-Mail
from datetime import datetime

# Configuração correta do Flask para servir arquivos estáticos
app = Flask(__name__, 
           static_folder=os.path.join(os.path.dirname(__file__), 'static'),
           template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'a_very_strong_random_secret_key_dev_123!@#')

# Configuração do banco de dados com retry e fallback
def get_database_uri():
    """Obtém a URI do banco de dados com retry para PostgreSQL"""
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        app.logger.info(f"Tentando conectar ao PostgreSQL: {database_url[:50]}...")
        
        # Tentar conectar ao PostgreSQL com retry
        max_retries = 5
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # Testar a conexão
                engine = create_engine(database_url)
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                app.logger.info("Conexão PostgreSQL estabelecida com sucesso!")
                return database_url
            except OperationalError as e:
                app.logger.warning(f"Tentativa {attempt + 1}/{max_retries} falhou: {str(e)}")
                if attempt < max_retries - 1:
                    app.logger.info(f"Aguardando {retry_delay} segundos antes da próxima tentativa...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Backoff exponencial
                else:
                    app.logger.error("Todas as tentativas de conexão PostgreSQL falharam")
                    
        # Se chegou aqui, PostgreSQL falhou - usar SQLite como fallback
        app.logger.warning("Usando SQLite como fallback devido a falhas na conexão PostgreSQL")
    
    # Fallback para SQLite local
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(project_root, 'lab_scheduler.db')
    sqlite_uri = f"sqlite:///{db_path}"
    app.logger.info(f"Usando SQLite: {sqlite_uri}")
    return sqlite_uri

app.config['SQLALCHEMY_DATABASE_URI'] = get_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Flask-Mail configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'true').lower() in ['true', '1', 't']
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'false').lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'itvdslab@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'cast qddf bxby mwsl')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', ('LAB.ITV', 'noreply@gmail.com'))

mail = Mail(app) # Initialize Flask-Mail
db.init_app(app)

# --- INÍCIO DAS MODIFICAÇÕES PARA LOGGING ---
# Configurar o nível de log para INFO (ou DEBUG, se preferir mais detalhes)
app.logger.setLevel(logging.INFO) 

# Adicionar handler para enviar logs para a saída padrão (stdout)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)
# --- FIM DAS MODIFICAÇÕES PARA LOGGING ---


# Adicionar filtro de template para formatação de data
@app.template_filter('format_date')
def format_date_filter(date_value, fmt="%d/%m"):
    """Filtro para formatação de datas nos templates"""
    if isinstance(date_value, str):
        try:
            # Tentar converter string ISO para objeto date
            date_obj = datetime.strptime(date_value, "%Y-%m-%d").date()
            return date_obj.strftime(fmt)
        except ValueError:
            return date_value
    elif hasattr(date_value, 'strftime'):
        # Se já é um objeto date/datetime
        return date_value.strftime(fmt)
    else:
        return str(date_value)

# Inicialização do banco de dados com retry
def initialize_database():
    """Inicializa o banco de dados com retry"""
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            db.create_all()
            app.logger.info("Tabelas do banco de dados criadas com sucesso")
            
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
                app.logger.info("Salas padrão criadas no banco de dados")
            else:
                app.logger.info("Salas já existem no banco de dados")
            return True
            
        except Exception as e:
            app.logger.error(f"Tentativa {attempt + 1}/{max_retries} de inicialização do banco falhou: {str(e)}")
            if attempt < max_retries - 1:
                app.logger.info(f"Aguardando {retry_delay} segundos antes da próxima tentativa...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                app.logger.error("Falha na inicialização do banco de dados após todas as tentativas")
                return False

# Inicialização do banco de dados
with app.app_context():
    initialize_database()

# Registrar blueprint
app.register_blueprint(bookings_bp, url_prefix='/api')

# Rota para servir arquivos estáticos corretamente
@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve arquivos estáticos explicitamente"""
    return send_from_directory(app.static_folder, filename)

# Rota principal corrigida
@app.route('/')
def index():
    """Serve a página principal"""
    try:
        return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        return f"Erro ao carregar página: {str(e)}", 500

# Rota catch-all para SPA
@app.route('/<path:path>')
def serve_spa(path):
    """Serve arquivos estáticos ou redireciona para index.html"""
    try:
        # Primeiro, tenta servir o arquivo solicitado
        if os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        else:
            # Se não encontrar, serve o index.html (comportamento SPA)
            return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        return f"Erro ao servir arquivo: {str(e)}", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
