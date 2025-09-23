import logging
from flask import Flask, render_template, request, g, abort, session, current_app, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_socketio import SocketIO
from flask_caching import Cache
from flask_wtf import CSRFProtect
from logging.handlers import RotatingFileHandler
from functools import wraps
from datetime import datetime
import pytz
from config import Config

# App extensions
db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO()
login_manager = LoginManager()
cache = Cache()
csrf = CSRFProtect()

# -----------------------
# Access Control Helpers
# -----------------------
from .models import User, Shop, SubCounty, Ward, County
def role_required(*roles):
    def wrapper(view_func):
        @wraps(view_func)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)
        return decorated_view
    return wrapper

def shop_access_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        from flask import current_app

        if not current_user.is_authenticated:
            return login_manager.unauthorized()

        shop_id = kwargs.get('shop_id')
        if not shop_id:
            abort(400, "Missing shop_id in route")

        shop = Shop.query.get_or_404(shop_id)

        if current_user.is_tenant():
            if shop.business_id != current_user.business_id:
                current_app.logger.warning(
                    f"[ACCESS DENIED] Tenant {current_user.username} tried to access shop {shop_id} not in their business."
                )
                abort(403, "You don't have access to this shop.")
        elif current_user.is_admin():
            if current_user.shop_id != shop.id:
                current_app.logger.warning(
                    f"[ACCESS DENIED] Admin {current_user.username} tried to access shop {shop_id} not assigned to them."
                )
                abort(403, "Admin is not assigned to this shop.")
        elif current_user.is_cashier():
            if current_user.shop_id != shop.id:
                current_app.logger.warning(
                    f"[ACCESS DENIED] Cashier {current_user.username} tried to access shop {shop_id} not assigned to them."
                )
                abort(403, "Cashier is not assigned to this shop.")
        else:
            current_app.logger.warning(
                f"[ACCESS DENIED] Unauthorized role {current_user.role} tried to access shop {shop_id}."
            )
            abort(403, "Unauthorized role.")

        g.current_shop = shop
        return view_func(*args, **kwargs)
    return wrapped



def business_access_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        business_id = kwargs.get('business_id')
        if not business_id:
            abort(400, "Missing business_id in route")

        if not current_user.is_tenant():
            abort(403, "Only tenants can access business-level views")

        if current_user.business_id != business_id:
            abort(403, "Access denied for this business")

        return view_func(*args, **kwargs)
    return wrapped


# -----------------------
# App Factory
# -----------------------

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # -----------------------
    # Secure Config
    # -----------------------
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['TIME_ZONE'] = 'Africa/Nairobi'
    app.config['POPULATE_LOCATIONS'] = app.debug  # Auto-populate in dev

    # -----------------------
    # Logging Setup
    # -----------------------
    if not app.debug:
        handler = RotatingFileHandler('app.log', maxBytes=10240, backupCount=10)
        handler.setLevel(logging.WARNING)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        app.logger.addHandler(handler)
        app.logger.info('Application startup')

    # -----------------------
    # Initialize Extensions
    # -----------------------
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, 
                 cors_allowed_origins=['https://yourdomain.com', 'http://127.0.0.1:5000'],
                 async_mode='threading')
    login_manager.init_app(app)
    cache.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'

    # -----------------------
    # Load User
    # -----------------------
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # -----------------------
    # Address Management Setup
    # -----------------------
    def populate_location_data():
        """Initialize county location data (Mombasa complete, Kilifi partial)"""
        from pathlib import Path
        import json
        
        data_path = Path(app.root_path) / 'data' / 'county_locations.json'
        
        try:
            with open(data_path) as f:
                data = json.load(f)
                
            with db.session.begin_nested():
                # Process each county
                for county_data in data["counties"]:
                    # Create or get county
                    county = County.query.filter_by(name=county_data["name"]).first()
                    if not county:
                        county = County(name=county_data["name"], code=county_data["code"])
                        db.session.add(county)
                        db.session.flush()
                    
                    # Process subcounties
                    for sc_data in county_data["subcounties"]:
                        subcounty = SubCounty.query.filter_by(
                            name=sc_data["name"], 
                            county_id=county.id
                        ).first()
                        
                        if not subcounty:
                            subcounty = SubCounty(
                                name=sc_data["name"],
                                code=sc_data["code"],
                                county_id=county.id
                            )
                            db.session.add(subcounty)
                            db.session.flush()
                        
                        # Process wards
                        for ward_name in sc_data["wards"]:
                            if not Ward.query.filter_by(
                                name=ward_name, 
                                subcounty_id=subcounty.id
                            ).first():
                                db.session.add(Ward(
                                    name=ward_name,
                                    subcounty_id=subcounty.id
                                ))
            
            db.session.commit()
            app.logger.info("Location data populated successfully")
            app.logger.info(f"Mombasa: 6 subcounties, 30 wards")
            app.logger.info(f"Kilifi: 1 subcounty (Mtwapa), 3 wards")
            return True
            
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to populate location data: {str(e)}", exc_info=True)
            return False

    # -----------------------
    # Request Handlers
    # -----------------------
    @app.before_request
    def set_tenant_context():
        g.business = None
        g.shop = None

        if current_user.is_authenticated:
            g.business = current_user.business
            g.shop = current_user.shop

            # Store shop_id from URL if present
            if 'shops' in request.path:
                try:
                    shop_id = int(request.path.split('/shops/')[1].split('/')[0])
                    session['shop_id'] = shop_id
                except (IndexError, ValueError):
                    pass

    @app.before_request
    def enforce_address_completion():
        if current_user.is_authenticated:
            # Only enforce for users who actually need an address
            if current_user.needs_address() and not current_user.has_address:

                # Exempt specific endpoints (e.g., setting address, auth routes, static)
                exempt_routes = {
                    'auth.set_address',
                    'auth.logout',
                    'home.index',
                    'auth.register',
                    'static'
                }

                # Also allow any endpoint explicitly starting with 'static' or 'auth.'
                if request.endpoint and (
                    request.endpoint in exempt_routes
                    or request.endpoint.startswith('auth.')
                    or request.endpoint.startswith('static')
                ):
                    return  # Allow these routes

                # Otherwise, redirect to set address
                return redirect(url_for('auth.set_address', next=request.url))

    # -----------------------
    # Template Context
    # -----------------------
    @app.context_processor
    def inject_now():
        tz = pytz.timezone(app.config['TIME_ZONE'])
        return {'now': datetime.now(tz)}


    @app.context_processor
    def inject_globals():
        from sqlalchemy.exc import SQLAlchemyError
        shops = []
        business = None

        try:
            if current_user.is_authenticated:
                if current_user.is_tenant():
                    shops = Shop.query.filter_by(
                        business_id=current_user.business_id,
                        is_deleted=False
                    ).all()
                    business = current_user.business
                elif current_user.is_admin() and current_user.shop:
                    shops = [current_user.shop]
                    business = current_user.shop.business
        except SQLAlchemyError as e:
            db.session.rollback()  # ✅ this is crucial
            shops = []
            business = None
            current_app.logger.error(f"inject_globals failed: {e}", exc_info=True)

        return {
            'shops': shops,
            'business': business
        }



    @app.context_processor
    def inject_current_shop():
        from flask import session
        current_shop = None

        try:
            shop_id = session.get("shop_id")
            if shop_id:
                current_shop = db.session.get(Shop, shop_id)
                if current_shop and current_shop.is_deleted:
                    current_shop = None  # Don't expose deleted shops
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"inject_current_shop error: {e}", exc_info=True)

        return dict(current_shop=current_shop)

    
    # -----------------------
    # Template Filters
    # -----------------------
    @app.template_filter('number_format')
    def number_format(value, decimals=2):
        try:
            return f"{float(value):,.{decimals}f}"
        except (TypeError, ValueError):
            return f"{0:.{decimals}f}"

    @app.template_filter('format_datetime')
    def format_datetime(value, format='%d %b %Y, %I:%M %p'):
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        if isinstance(value, datetime):
            return value.strftime(format)
        return value

    # -----------------------
    # Error Handlers
    # -----------------------
    @app.errorhandler(404)
    def not_found_error(error):
        app.logger.warning(f"404 at {request.url}")
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"500 Error: {error}")
        return render_template('500.html'), 500




    # Jinja filter to get product image URL
    def product_image_url(image_path):
        if image_path:
            filename = image_path.split('/')[-1]
            return url_for('serve_product_image', filename=filename)
        else:
            return url_for('static', filename='products/placeholder.jpg')

    # Register the filter globally
    app.jinja_env.filters['product_image_url'] = product_image_url

    # Route to serve uploaded product images
    @app.route('/products/image/<filename>')
    def serve_product_image(filename):
        return send_from_directory('static/products', filename)
            

        # -----------------------
    # Initial Data Population
    # -----------------------
    with app.app_context():
        try:
            if app.config['POPULATE_LOCATIONS'] and not SubCounty.query.first():
                if not populate_location_data():
                    app.logger.warning("Failed to populate initial location data")
        except Exception as e:
            app.logger.error(f"Initialization error: {e}")

    # -----------------------
    # Register Blueprints
    # -----------------------
    from .auth.routes import auth_bp
    from .inventory.routes import inventory_bp
    from .sale import sales_bp, api_bp
    from .home.routes import home_bp
    from .expense.routes import expense_bp
    from .supplier.routes import supplier_bp
    from .reports.routes import reports_bp
    from .bhapos.routes import bhapos_bp
    from .admin.routes import admin_bp
    from .price.routes import price_bp

    blueprints = [
        (auth_bp, '/auth'),
        (home_bp, ''),
        (inventory_bp, '/inventory'),
        (sales_bp, ''),
        (api_bp, '/api'),
        (expense_bp, '/expense'),
        (supplier_bp, '/supplier'),
        (reports_bp, '/reports'),
        (price_bp, '/price'),
        (admin_bp, '/admin'),
        (bhapos_bp, '/bhapos')
    ]

    for bp, url_prefix in blueprints:
        app.register_blueprint(bp, url_prefix=url_prefix)

    return app