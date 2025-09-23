import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    # Basic App Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'you-will-never-guess')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Redis Cache Settings
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_URL = os.getenv('REDIS_URL')
    CACHE_DEFAULT_TIMEOUT = 300

    # Session Security Configuration
    SESSION_COOKIE_SECURE = True  
    SESSION_COOKIE_HTTPONLY = True  
    SESSION_COOKIE_SAMESITE = 'Lax'  
    PERMANENT_SESSION_LIFETIME = 3600 
    REMEMBER_COOKIE_DURATION = 2592000  # 30 days in seconds
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = True  

    # Additional Security Headers (Flask-Talisman compatible)
    SECURITY_HEADERS = {
        'Strict-Transport-Security': 'max-age=63072000; includeSubDomains; preload',
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'SAMEORIGIN',
        'X-XSS-Protection': '1; mode=block',
        'Content-Security-Policy': "default-src 'self'",
        'Referrer-Policy': 'strict-origin-when-cross-origin'
    }

    

    @staticmethod
    def init_app(app):
        # Apply security headers
        if os.getenv('FLASK_ENV') == 'production':
            from flask_talisman import Talisman
            Talisman(
                app,
                **app.config['SECURITY_HEADERS']
            )