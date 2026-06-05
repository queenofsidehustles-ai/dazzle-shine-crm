import os
from flask import Flask
from extensions import db
from blueprints.admin import admin_bp
from blueprints.bookings import bookings_bp
from blueprints.api import api_bp
from blueprints.settings import settings_bp
from blueprints.staff import staff_bp


def create_app():
    app = Flask(__name__)

    # Database
    db_url = os.environ.get('DATABASE_URL', '')
    # Fall back to SQLite if URL is missing or unresolved template
    if not db_url or db_url.startswith('$') or '://' not in db_url:
        db_url = 'sqlite:///dazzle.db'
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    if db_url.startswith('postgresql://') and '+psycopg2' not in db_url:
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

    db.init_app(app)

    app.register_blueprint(admin_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(staff_bp)

    with app.app_context():
        db.create_all()

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8001)), debug=True)
