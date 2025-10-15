from flask import Blueprint, render_template, redirect, url_for, session, flash, request
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired
import logging
from app.models import Shop, User, Business
from app import db

# Define the Blueprint
home_bp = Blueprint('home', __name__)

# Create a logger instance
logger = logging.getLogger(__name__)

# Login Form for home.html
class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember me')
    submit = SubmitField('Sign In')

def get_shop_from_request():
    """
    Extract shop from subdomain, custom domain, or URL parameter.
    Returns the Shop object or None if no valid shop is found.
    """
    host = request.headers.get('Host', '')
    
    # Check for custom domain
    from app.models import ShopHomepageSettings
    homepage_settings = ShopHomepageSettings.query.filter_by(
        custom_domain=host, 
        is_active=True
    ).first()
    if homepage_settings:
        return homepage_settings.shop
    
    # Check for subdomain
    if '.' in host:
        subdomain = host.split('.')[0]
        if subdomain not in ['www', 'app', 'admin', 'api']:
            homepage_settings = ShopHomepageSettings.query.filter_by(
                subdomain=subdomain, 
                is_active=True
            ).first()
            if homepage_settings:
                return homepage_settings.shop
    
    # Check URL parameter for shop-specific access
    shop_id = request.args.get('shop_id')
    if shop_id:
        shop = Shop.query.get(shop_id)
        if shop and shop.shop_homepage_settings and shop.shop_homepage_settings.is_active:
            return shop
    
    # Check for shop slug-based access
    shop_slug = request.args.get('shop_slug')
    if shop_slug:
        shop = Shop.query.filter_by(slug=shop_slug, is_active=True).first()
        if shop:
            return shop
    
    return None

@home_bp.route('/')
def index():
    logger.debug(f"Accessing index route for user: {current_user.get_id() if current_user.is_authenticated else 'anonymous'}")
    
    form = LoginForm()  # Initialize login form for unauthenticated users

    # Check if this is a shop-specific homepage request
    requested_shop = get_shop_from_request()
    if requested_shop and not current_user.is_authenticated:
        logger.debug(f"Serving custom homepage for shop: {requested_shop.name}")
        return render_template('homepage/custom_shop.html', current_shop=requested_shop)

    # Initialize context for template
    context = {
        'current_shop': None,
        'business': None,
        'is_super_admin': False,
        'create_business': False,
        'select_shop': False,
        'form': form
    }

    if not current_user.is_authenticated:
        logger.debug("Unauthenticated user, rendering public homepage")
        return render_template('home.html', **context)

    # Handle authenticated users
    if current_user.is_superadmin():
        logger.debug(f"Super admin {current_user.id} accessing homepage")
        context['is_super_admin'] = True
        
    elif current_user.is_tenant():
        logger.debug(f"Tenant user {current_user.id} with business_id: {current_user.business_id}")
        if not current_user.business_id:
            logger.warning(f"Tenant {current_user.id} has no business_id")
            flash("Please create a business to continue.", "warning")
            context['create_business'] = True
        else:
            business = Business.query.get(current_user.business_id)
            if not business:
                logger.error(f"No business found for tenant {current_user.id} with business_id: {current_user.business_id}")
                flash("Invalid business. Please create a new one.", "error")
                context['create_business'] = True
            else:
                context['business'] = business
                if current_user.shop_id:
                    shop = Shop.query.get(current_user.shop_id)
                    if not shop:
                        logger.error(f"No shop found for tenant {current_user.id} with shop_id: {current_user.shop_id}")
                        flash("Invalid shop selected. Please choose a valid shop.", "error")
                        current_user.shop_id = None
                        db.session.commit()
                        context['select_shop'] = True
                    elif shop.business_id != business.id:
                        logger.error(f"Shop {shop.id} does not belong to business {current_user.business_id} for tenant {current_user.id}")
                        flash("Selected shop is not valid for your business. Please choose another.", "error")
                        current_user.shop_id = None
                        db.session.commit()
                        context['select_shop'] = True
                    else:
                        context['current_shop'] = shop
                        
    elif current_user.is_admin() or current_user.is_cashier():
        role = 'admin' if current_user.is_admin() else 'cashier'
        logger.debug(f"{role.capitalize()} user {current_user.id} with shop_id: {current_user.shop_id}")
        
        if not current_user.shop_id:
            logger.warning(f"{role.capitalize()} {current_user.id} has no shop_id")
            flash("Please select a shop to continue.", "warning")
            context['select_shop'] = True
        else:
            shop = Shop.query.get(current_user.shop_id)
            if not shop:
                logger.error(f"No shop found for {role} {current_user.id} with shop_id: {current_user.shop_id}")
                flash("Invalid shop selected. Please choose a valid shop.", "error")
                current_user.shop_id = None
                db.session.commit()
                context['select_shop'] = True
            else:
                context['current_shop'] = shop
                if shop.business_id:
                    business = Business.query.get(shop.business_id)
                    if business:
                        context['business'] = business
    else:
        logger.error(f"Unknown role configuration for user {current_user.id}")
        flash("Invalid user role. Please contact support.", "error")

    return render_template('home.html', **context)

@home_bp.route('/select-shop/<int:shop_id>')
def select_shop(shop_id):
    if not current_user.is_authenticated or not (current_user.is_admin() or current_user.is_cashier() or current_user.is_tenant()):
        logger.warning(f"Unauthorized attempt to select shop by user: {current_user.get_id() if current_user.is_authenticated else 'anonymous'}")
        flash("You are not authorized to select a shop.", "error")
        return redirect(url_for('home.index'))
    
    shop = Shop.query.get_or_404(shop_id)
    if current_user.business_id and shop.business_id != current_user.business_id:
        logger.error(f"Shop {shop_id} does not belong to business {current_user.business_id}")
        flash("Selected shop does not belong to your business.", "error")
        return redirect(url_for('home.index'))
    
    session['shop_id'] = shop_id
    current_user.shop_id = shop_id
    db.session.commit()
    logger.debug(f"User {current_user.id} selected shop {shop_id}")
    flash(f"Selected shop: {shop.name}", "success")
    return redirect(url_for('sales.sales_screen', shop_id=shop_id))

@home_bp.route('/shop/<int:shop_id>/homepage')
def shop_homepage(shop_id):
    """Public-facing shop homepage"""
    shop = Shop.query.get_or_404(shop_id)
    return render_template('homepage/custom_shop.html', current_shop=shop)

@home_bp.route('/shop/<shop_slug>/homepage')
def shop_homepage_by_slug(shop_slug):
    """Public-facing shop homepage by slug"""
    shop = Shop.query.filter_by(slug=shop_slug, is_active=True).first_or_404()
    return redirect(url_for('home.shop_homepage', shop_id=shop.id))