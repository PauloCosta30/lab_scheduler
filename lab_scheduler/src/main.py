import os
import sys
# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, send_from_directory, send_file, jsonify, request
from src.extensions import db
from src.models.entities import Room, Booking
from src.routes.booking_routes import bookings_bp
from flask_mail import Mail # Import Flask-Mail
import datetime
import shutil

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'a_very_strong_random_secret_key_dev_123!@#')

# Configuração do banco de dados com suporte a PostgreSQL para produção
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(project_root, 'lab_scheduler.db')

# Usar variável de ambiente DATABASE_URL se disponível, caso contrário usar SQLite local
database_url = os.getenv('DATABASE_URL', f"sqlite:///{db_path}")

# Ajustar URL do PostgreSQL se necessário (Render fornece URLs começando com postgres://)
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Flask-Mail configuration - Replace with your actual SMTP server details in production
# For development, you might use a local SMTP debugging server or a service like Mailtrap
# IMPORTANT: Use environment variables for sensitive information in production!
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'true').lower() in ['true', '1', 't']
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'false').lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'paulo.henriquee30@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'almz rukj tayw nsup')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', ('LAB.ITV', 'noreply@gmail.com'))

# For local testing without a real SMTP server, you can suppress sending or use a console mail server.
# app.config['MAIL_SUPPRESS_SEND'] = True # Uncomment to suppress emails during testing if no SMTP server is configured
#app.config['MAIL_SUPPRESS_SEND'] = True # Suppress emails for current testing phase

mail = Mail(app) # Initialize Flask-Mail
db.init_app(app)

# Exemplo de modificação em src/main.py
# ... (outras importações e configurações) ...
from src.models.entities import Room, Booking # Certifique-se que Room está importado
# ...
with app.app_context():
    db.create_all()
    if not Room.query.first():
        room_names = ["Geral 1", "Geral 2", "Geral 3", "Geral 4", "Geral 5","Geral 6","Geral 7","Geral 8","Citometria - Bancada", "Sala Clara - Lupa esquerda", "Sala Clara - Lupa direita","Sala Clara - Lupa com Câmera","Sala Clara - Microscópio","Sala Escura - Axio Imager.M2", "Sala Escura - Axio Scope.A1","Sala Escura - Microscópio CONFOCAL-LMSN","Microbiologia - Capela de Fluxo Laminar","Microbiologia - Lupa", "Microbiologia - Equipamento","Geologia 1", "Geologia Micrótomo", "Cultivo A1","Cultivo A2","Cultivo B1","Cultivo B2"]
        # Certifique-se de ter 10 nomes se o range(1,11) for mantido, ou ajuste o loop
        for name in room_names: # Ou use um loop com índice se preferir
            room = Room(name=name)
            db.session.add(room)
        db.session.commit()
        print("Database initialized and custom rooms created.")


app.register_blueprint(bookings_bp, url_prefix='/api')

# Rota para download do banco de dados
@app.route('/admin/download-database')
def download_database():
    # Verificar senha de administrador (básica para demonstração)
    admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
    password = request.args.get('password', '')
    
    if password != admin_password:
        return jsonify({"error": "Acesso não autorizado"}), 401
    
    # Se estiver usando SQLite
    if database_url.startswith('sqlite'):
        # Criar uma cópia do banco para download
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"lab_scheduler_backup_{timestamp}.db"
        download_path = os.path.join(project_root, download_filename)
        
        # Copiar o arquivo do banco de dados
        shutil.copy2(db_path, download_path)
        
        # Enviar o arquivo para download
        return send_file(
            download_path,
            as_attachment=True,
            download_name=download_filename,
            mimetype='application/octet-stream'
        )
    else:
        # Para PostgreSQL ou outros bancos, informar que download direto não é suportado
        return jsonify({
            "error": "Download direto não disponível para PostgreSQL",
            "message": "Para PostgreSQL, use ferramentas como pg_dump para backup"
        }), 400

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    static_folder_path = app.static_folder
    if static_folder_path is None:
            return "Static folder not configured", 404

    if path != "" and os.path.exists(os.path.join(static_folder_path, path)):
        return send_from_directory(static_folder_path, path)
    else:
        index_path = os.path.join(static_folder_path, 'index.html')
        if os.path.exists(index_path):
            return send_from_directory(static_folder_path, 'index.html')
        else:
            return "index.html not found in static folder. Please create it.", 404

if __name__ == '__main__':
    # For local testing, you might want to set MAIL_SUPPRESS_SEND to True if SMTP is not set up
    # Example: app.config['MAIL_SUPPRESS_SEND'] = True
    app.run(host='0.0.0.0', port=5000, debug=True)
