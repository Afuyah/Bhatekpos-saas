from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, current_app, g, Response, abort
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import func
from app.models import User,  Role, Sale, Product, Category, StockLog, CartItem, Shop, Business, SubCounty, County, Ward, UserAddress
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta, datetime
from sqlalchemy.exc import SQLAlchemyError
from app.utils.render import render_htmx
from .forms import RegistrationForm, AddressForm
from urllib.parse import urlparse, urljoin
import logging
from app import db, csrf, role_required, shop_access_required, business_access_required
from .schemas import RegistrationSchema
from urllib.parse import urljoin
from app.utils.helpers import generate_short_code, slugify  
from app import cache 
from sqlalchemy.exc import IntegrityError

auth_bp = Blueprint('auth', __name__)

# Create a logger instance
logger = logging.getLogger(__name__)



def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (
        test_url.scheme in ('http', 'https') and
        ref_url.netloc == test_url.netloc
    )

def _handle_login_error(message, is_json=False, field=None, status_code=401):
    """Handle login errors consistently"""
    if is_json:
        response = {'success': False, 'message': message}
        if field:
            response['field'] = field
        return jsonify(response), status_code
    flash(message, 'error')
    return redirect(url_for('home.index', login_error=message, field=field))

def _handle_login_success(redirect_url, user, is_json=False):
    """Handle successful logins with validation"""
    if not redirect_url:
        logger.warning("Empty redirect URL, using fallback")
        redirect_url = url_for('home.index')
    
    try:
        if is_json:
            return jsonify({
                'success': True,
                'redirect_url': redirect_url,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'role': user.role.value,
                    'has_address': user.has_address
                }
            }), 200
        return redirect(redirect_url)
    except Exception as e:
        logger.error(f"Redirect failed: {str(e)}")
        return redirect(url_for('home.index'))


def _determine_redirect_url(user, next_param=None):
    """Determine the appropriate redirect URL after login or registration."""

    # 1. If a safe 'next' param is provided, use it directly
    if next_param and is_safe_url(next_param):
        redirect_url = next_param
    else:
        # 2. Role-based default redirect
        try:
            if user.is_superadmin():
                redirect_url = url_for('bhapos.superadmin_dashboard')

            elif user.is_tenant():
                # Only allow tenants with a valid business
                business = Business.query.filter_by(id=user.business_id, is_deleted=False).first()
                redirect_url = url_for('bhapos.tenant_dashboard') if business else url_for('home.index')

            elif user.is_admin():
                if user.shop_id:
                    redirect_url = url_for('admin.admin_dashboard', shop_id=user.shop_id)
                else:
                    redirect_url = url_for('home.index')

            elif user.is_cashier():
                if user.shop_id:
                    redirect_url = url_for('sales.sales_screen', shop_id=user.shop_id)
                else:
                    redirect_url = url_for('home.index')

            else:
                redirect_url = url_for('home.index')

        except Exception as e:
            logger.error(f"[Redirect Error] Could not determine URL: {str(e)}")
            redirect_url = url_for('home.index')

    # 3. Check if user must set their address first
    if user.needs_address() and not user.has_address:
        return url_for('auth.set_address', next=redirect_url)  # Preserve intended final destination

    return redirect_url



def create_cashier_user(data, shop):
    """Create a new cashier user with validated data"""
    return User(
        username=data['username'].lower().strip(),
        email=data.get('email', '').lower().strip() or None,
        first_name=data.get('first_name', '').strip(),
        last_name=data.get('last_name', '').strip(),
        phone=data.get('phone', '').strip(),
        shop_id=shop.id,
        business_id=shop.business_id,
        role=Role.CASHIER
    ).set_password(data['password'])


def handle_registration_success(user, shop):
    """Handle successful registration"""
    login_user(user)
    user.record_login()
    db.session.commit()

    flash('Registration successful! Welcome.', 'success')
    return redirect(_determine_redirect_url(user))


def handle_registration_error(message, shop, form=None):
    """Handle registration errors"""
    db.session.rollback()

    if isinstance(message, dict):
        for field_errors in message.values():
            for err in field_errors:
                flash(err, 'error')
    else:
        flash(message, 'error')

    return render_template(
        'auth/register.html',
        shop=shop,
        form=form or RegistrationForm()
    )


def _determine_redirect_url(user, next_url=None):
    """Determine redirect URL based on user role"""
    if next_url and is_safe_url(next_url):
        return next_url
    if user.is_superadmin():
        return url_for('bhapos.superadmin_dashboard')
    elif user.is_tenant() and user.business_id:
        return url_for('bhapos.tenant_dashboard', business_id=user.business_id)
    elif (user.is_admin() or user.is_cashier()) and user.shop_id:
        return url_for('sales.sales_screen', shop_id=user.shop_id)
    return url_for('home.index')


def _handle_login_error(message, is_json, field=None):
    """Handle login errors"""
    logger.warning(f"Login error: {message}")
    if is_json:
        return jsonify({'success': False, 'error': message, 'field': field}), 400

    flash(message, 'error')
    return redirect(url_for('auth.login'))


def _handle_login_success(redirect_url, user, is_json):
    """Handle successful login"""
    logger.info(f"Redirecting user {user.id} to {redirect_url}")
    if is_json:
        return jsonify({
            'success': True,
            'redirect': redirect_url,
            'user': user.serialize()
        })
    return redirect(redirect_url)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login"""
    logger.info("Login request received")

    if request.method == 'POST':
        # Extract credentials
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')

        if not username or not password:
            return _handle_login_error("Username and password are required", request.is_json, 'username')

        username = username.strip().lower()
        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            return _handle_login_error("Invalid credentials", request.is_json, 'password')

        if user.is_deleted:
            return _handle_login_error("Account is disabled", request.is_json)

        login_user(user, remember=True)
        logger.info(f"User {user.username} logged in successfully")

        redirect_url = _determine_redirect_url(user, request.args.get('next'))
        return _handle_login_success(redirect_url, user, request.is_json)

    # GET request: show login form
    return render_template('home.html')


@auth_bp.route('/register/<shop_slug>', methods=['GET', 'POST'])
def register_user(shop_slug):
    """Handle user registration"""
    shop = Shop.query.filter_by(slug=shop_slug, is_active=True, is_deleted=False).first()
    if not shop:
        flash('Invalid or inactive shop.', 'error')
        return redirect(url_for('home.index'))

    if not shop.allow_registrations:
        flash('Registrations are disabled for this shop.', 'error')
        return redirect(url_for('home.index'))

    if request.method == 'GET':
        logger.debug(f"Rendering registration form for shop: {shop_slug}")
        return render_template(
            'auth/register.html',
            shop=shop,
            form=RegistrationForm()
        )

    form = RegistrationForm(request.form)
    if not form.validate():
        return handle_registration_error(form.errors, shop, form)

    try:
        user = create_cashier_user(form.data, shop)
        db.session.add(user)
        db.session.commit()
        return handle_registration_success(user, shop)

    except IntegrityError:
        return handle_registration_error('Username or email already exists.', shop, form)
    except Exception as e:
        logger.exception(f"Registration error: {str(e)}")
        return handle_registration_error('Something went wrong. Please try again.', shop, form)


@auth_bp.route('/api/shops/<int:shop_id>/registration-link', methods=['GET'])
@login_required
def get_registration_link(shop_id):
    """
    Generates a permanent registration link and temporary short URL for a given shop.
    Only shop owners or admins of the shop can access this endpoint.
    """
    shop = Shop.query.get_or_404(shop_id)

    # Permission: tenant owner or assigned shop admin
    is_owner = current_user.is_tenant() and current_user.tenant_id == shop.tenant_id
    is_admin = current_user.is_admin() and current_user.shop_id == shop.id

    if not (is_owner or is_admin):
        return jsonify({'success': False, 'error': 'Not authorized.'}), 403

    # Permanent registration URL
    registration_url = url_for('auth.register_user', shop_slug=shop.slug, _external=True)

    # Temporary short URL using random short code (24hr cache)
    short_code = generate_short_code()
    short_url = urljoin(request.host_url, f'r/{short_code}')
    cache.set(f'short_code:{short_code}', shop.slug, timeout=86400)

    # Optional: QR Code
    qr_code_url = f'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={registration_url}'

    return jsonify({
        'success': True,
        'registration_url': registration_url,
        'short_url': short_url,
        'qr_code_url': qr_code_url,
        'shop': {
            'id': shop.id,
            'name': shop.name,
            'slug': shop.slug
        }
    })

@csrf.exempt
@auth_bp.route("/shops/<int:shop_id>/generate-short-url", methods=["POST"])
@login_required
def generate_short_url(shop_id):
    shop = Shop.query.get_or_404(shop_id)

    if not current_user.is_tenant() or shop.business_id != current_user.business_id:
        flash("Unauthorized", "error")
        return redirect(url_for("auth.dashboard"))

    shop.short_url_code = generate_short_code()
    db.session.commit()

    # Re-render the settings section only (HTMX target)
    return render_template("bhapos/tenants/url_settings.html", shop=shop)


@auth_bp.route("/register/<string:code>", methods=["GET"])
def short_register(code):
    shop = Shop.query.filter_by(short_url_code=code).first_or_404()

    # Redirect to the full registration page
    return redirect(url_for("auth.show_register_page", shop_slug=shop.slug))


@auth_bp.route('/shop/<int:shop_id>/url-settings')
@login_required
def url_settings_partial(shop_id):
    shop = Shop.query.get_or_404(shop_id)
    return render_template('bhapos/tenants/url_settings.html', shop=shop)


@auth_bp.route('/set-address', methods=['GET', 'POST'])
@login_required
def set_address():
    form = AddressForm()

    # Always populate county choices
    form.county.choices = [('', 'Select County')] + [(c.id, c.name) for c in County.query.order_by('name').all()]

    # Get selected values early from request/form
    selected_county = request.form.get('county') or form.county.data
    selected_subcounty = request.form.get('subcounty') or form.subcounty.data

    # Populate subcounty choices dynamically before validation
    if selected_county:
        form.subcounty.choices = [('', 'Select Subcounty')] + [
            (s.id, s.name) for s in SubCounty.query.filter_by(county_id=selected_county).order_by('name').all()
        ]
    else:
        form.subcounty.choices = [('', 'Select Subcounty')]

    # Populate ward choices dynamically before validation
    if selected_subcounty:
        form.ward.choices = [('', 'Select Ward')] + [
            (w.id, w.name) for w in Ward.query.filter_by(subcounty_id=selected_subcounty).order_by('name').all()
        ]
    else:
        form.ward.choices = [('', 'Select Ward')]

    # Now validation will work properly
    if form.validate_on_submit():
        try:
            is_primary = not current_user.has_address
            address = UserAddress(
                user_id=current_user.id,
                county_id=form.county.data,
                subcounty_id=form.subcounty.data,
                ward_id=form.ward.data,
                estate=form.estate.data,
                landmark=form.landmark.data,
                building=form.building.data,
                apartment=form.apartment.data,
                house_number=form.house_number.data,
                notes=form.notes.data,
                is_primary=is_primary
            )
            db.session.add(address)
            db.session.commit()
            logger.info(f"Address saved for user {current_user.id}: {address}")
            next_url = request.args.get('next') or _determine_redirect_url(current_user)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'redirect_url': next_url})
            return redirect(next_url)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Address save error: {str(e)}")
            flash('Error saving address. Please try again.', 'error')

    elif request.method == 'POST':
        logger.error(f"Form validation failed: {form.errors}")
        flash(f"Form validation failed: {form.errors}", 'error')

    return render_template('auth/set_address.html', form=form)



@auth_bp.route('/addresses', methods=['GET', 'POST'])
@login_required
def manage_addresses():
    """Manage all user addresses with dynamic location loading"""
    form = AddressForm()
    form.county.choices = [('', 'Select County')] + [(c.id, c.name) for c in County.query.order_by('name').all()]
    
    if form.validate_on_submit():
        try:
            # Clear any existing primary if setting new primary
            if form.is_primary.data:
                UserAddress.query.filter_by(user_id=current_user.id, is_primary=True).update({'is_primary': False})
            
            address = UserAddress(
                user_id=current_user.id,
                county_id=form.county.data,
                subcounty_id=form.subcounty.data,
                ward_id=form.ward.data,
                estate=form.estate.data,
                landmark=form.landmark.data,
                building=form.building.data,
                apartment=form.apartment.data,
                house_number=form.house_number.data,
                notes=form.notes.data,
                is_primary=form.is_primary.data,
                business_id=current_user.business_id,
                shop_id=current_user.shop_id
            )
            db.session.add(address)
            db.session.commit()
            flash('Address saved successfully!', 'success')
            return redirect(url_for('auth.manage_addresses'))
            
        except Exception as e:
            db.session.rollback()
            flash('Error saving address. Please try again.', 'error')
            logger.error(f"Address save error: {str(e)}")

    return render_template('auth/addresses.html',
                         form=form,
                         addresses=current_user.get_addresses())


@auth_bp.route('/api/counties')
def get_counties():
    """Get all counties (JSON)"""
    counties = County.query.order_by('name').all()
    return jsonify([c.serialize() for c in counties])

@auth_bp.route('/api/subcounties/<int:county_id>')
@login_required
def get_subcounties(county_id):
    """Get subcounties for a county (JSON)"""
    try:
        subcounties = SubCounty.query.filter_by(county_id=county_id).order_by('name').all()
        return jsonify([{
            'id': sc.id,
            'name': sc.name,
            'code': sc.code
        } for sc in subcounties])
    except Exception as e:
        current_app.logger.error(f"Error fetching subcounties: {str(e)}")
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/api/wards/<int:subcounty_id>')
@login_required
def get_wards(subcounty_id):
    """Get wards for a subcounty (JSON)"""
    try:
        wards = Ward.query.filter_by(subcounty_id=subcounty_id).order_by('name').all()
        return jsonify([{
            'id': w.id,
            'name': w.name,
            
        } for w in wards])
    except Exception as e:
        current_app.logger.error(f"Error fetching wards: {str(e)}")
        return jsonify({'error': str(e)}), 500   





@csrf.exempt
@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    logger.info("Change password route accessed.")
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        # Validate current password
        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', category='error')
            logger.warning(f"User {current_user.username} provided incorrect current password.")
            return render_template('auth/fragments/_admin_change_password.html')

        if new_password != confirm_password:
            flash('New passwords do not match.', category='error')
            logger.warning("New password confirmation did not match.")
            return render_template('auth/fragments/_admin_change_password.html')

        if len(new_password) < 5:
            flash('New password must be at least 5 characters long.', category='error')
            logger.warning("New password length is insufficient.")
            return render_template('auth/fragments/_admin_change_password.html')

        current_user.set_password(new_password)
        db.session.commit()
        flash('Your password has been updated successfully!', category='success')
        logger.info(f"User {current_user.username} updated their password.")

        # After successful password update, redirect or return a success partial
        return render_template('auth/fragments/_admin_change_password.html')

    # For GET request, render the form fragment
    template_name = 'auth/fragments/_admin_change_password.html'
    return render_template(template_name)


@auth_bp.route('/user_management/<int:shop_id>', methods=['GET'])
@login_required
@shop_access_required 
@role_required(Role.ADMIN, Role.TENANT) 
def user_management(shop_id):
    logger.info(f"User management accessed by user {current_user.username}.")

    # Get the current shop from g (set by shop_access_required)
    shop = g.current_shop

    # Fetch users belonging only to this shop
    users = User.query.filter_by(shop_id=shop.id, is_deleted=False).all()

    if request.headers.get('HX-Request'):
        logger.info(f"[HTMX] Fragment request for user management by {current_user.username}")
        return render_template('auth/fragments/_user_management_fragment.html', users=users,)

    return render_template(
        'auth/admin_dashboard.html',
        fragment_template='auth/fragments/_user_management_fragment.html',
        users=users
    )

@csrf.exempt
@auth_bp.route('/shops/<int:shop_id>/add_user', methods=['GET', 'POST'])
@login_required
@role_required(Role.ADMIN, Role.TENANT)
@shop_access_required  # Ensures the shop belongs to the current admin or tenant
def add_user(shop_id):
    shop = g.current_shop
    logger.info(f"Add user route accessed by user {current_user.username} for shop {shop.id}.")

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password')
        role = request.form.get('role')

        # --- Validations ---
        if username.isdigit():
            return render_template('auth/fragments/add_user_fragment.html', error="Username cannot be only numbers.", shop=shop)

        if role.upper() not in Role.__members__:
            return render_template('auth/fragments/add_user_fragment.html', error="Invalid role selected.", shop=shop)

        if User.query.filter_by(username=username).first():
            return render_template('auth/fragments/add_user_fragment.html', error="Username already exists.", shop=shop)

        # --- Create new user ---
        new_user = User(
            username=username,
            role=Role[role.upper()],
            shop_id=shop.id,
            business_id=shop.business_id  # ensure scoped correctly
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        logger.info(f"User {username} created for shop {shop.name}.")

        return Response(headers={"HX-Redirect": url_for('auth.user_management', shop_id=shop.id)})

    return render_template('auth/fragments/add_user_fragment.html', shop=shop)



@auth_bp.route('/logout')
@login_required
def logout():
    logger.info(f"User {current_user.username} logged out.")
    
    # Clear the session (including cart data)
    session.clear()
    
    logout_user()  # Log out the user
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home.index'))


@auth_bp.route('/api/auth/current-user')
@login_required
def current_user_info():
    return jsonify({
        'id': current_user.id,
        'name': current_user.username,
        
        'role': current_user.role.value
    })
