import os
import sys
import logging
import time
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, DisconnectionError
from sqlalchemy.pool import QueuePool

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

# Configuração do banco de dados - MELHORADA para reconexão automática
database_url = os.getenv('DATABASE_URL')
if database_url:
    # Configurações otimizadas para PostgreSQL no Render
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,          # Verifica conexão antes de usar
        'pool_recycle': 300,            # Recicla conexões a cada 5 minutos
        'pool_timeout': 20,             # Timeout para obter conexão do pool
        'max_overflow': 0,              # Sem conexões extras
        'echo': False,                  # Desabilita logs SQL em produção
        'connect_args': {
            'connect_timeout': 10,      # Timeout de conexão
            'options': '-c statement_timeout=30000'  # Timeout de query
        }
    }
else:
    # Fallback para SQLite local para desenvolvimento
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

# Configurar logging
app.logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

# Função para executar operações no banco com retry
def execute_with_retry(operation, max_retries=3, delay=2):
    """Executa operação no banco com retry automático"""
    for attempt in range(max_retries):
        try:
            return operation()
        except (OperationalError, DisconnectionError) as e:
            app.logger.warning(f"Tentativa {attempt + 1} falhou: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(delay)
                # Tenta recriar a conexão
                try:
                    db.session.remove()
                    db.engine.dispose()
                except:
                    pass
            else:
                app.logger.error(f"Todas as tentativas falharam: {str(e)}")
                raise e

# Adicionar filtro de template para formatação de data
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

# Função para inicializar o banco de dados
def init_database():
    """Inicializa o banco de dados com retry"""
    def create_tables():
        db.create_all()
        app.logger.info("Tabelas do banco de dados criadas com sucesso")
        return True
    
    def create_default_rooms():
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
    
    try:
        execute_with_retry(create_tables)
        execute_with_retry(create_default_rooms)
    except Exception as e:
        app.logger.error(f"Erro ao inicializar banco de dados: {str(e)}")
        # Não falha a aplicação, apenas registra o erro

# Middleware para reconexão automática
@app.before_request
def before_request():
    """Verifica conexão com banco antes de cada requisição"""
    try:
        # Teste simples de conectividade
        db.session.execute('SELECT 1')
        db.session.commit()
    except (OperationalError, DisconnectionError):
        try:
            db.session.remove()
            db.engine.dispose()
        except:
            pass

# Inicialização do banco de dados
with app.app_context():
    init_database()

# Registrar blueprint
app.register_blueprint(bookings_bp, url_prefix='/api')

# Rota de health check
@app.route('/health')
def health_check():
    """Verifica saúde da aplicação"""
    try:
        def check_db():
            db.session.execute('SELECT 1')
            return True
        
        execute_with_retry(check_db)
        return {
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.now().isoformat()
        }, 200
    except Exception as e:
        return {
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }, 500

# Rota para servir arquivos estáticos
@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve arquivos estáticos explicitamente"""
    return send_from_directory(app.static_folder, filename)

# Rota principal
@app.route('/')
def index():
    """Serve a página principal"""
    try:
        return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        app.logger.error(f"Erro ao servir index.html: {str(e)}")
        return f"Erro ao carregar página: {str(e)}", 500

# Rota catch-all para SPA
@app.route('/<path:path>')
def serve_spa(path):
    """Serve arquivos estáticos ou redireciona para index.html"""
    try:
        if os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        else:
            return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        app.logger.error(f"Erro ao servir {path}: {str(e)}")
        return f"Erro ao servir arquivo: {str(e)}", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
