# auth/utils.py
from flask import url_for, session
from app.models import Business

def determine_redirect_url(user, next_param=None):
    """Centralized redirect logic used by all routes"""
    from flask import request
    
    # 1. Check safe 'next' parameter
    if next_param and is_safe_url(next_param):
        return next_param
        
    # 2. Role-based redirects
    if user.is_superadmin():
        return url_for('bhapos.superadmin_dashboard')
    elif user.is_tenant():
        business = Business.query.get(user.business_id)
        if business and not business.is_deleted:
            session['active_business_id'] = business.id
            return url_for('bhapos.tenant_dashboard')
    elif user.is_admin() and user.shop_id:
        session['active_shop_id'] = user.shop_id
        return url_for('admin.admin_dashboard', shop_id=user.shop_id)
    elif user.is_cashier() and user.shop_id:
        return url_for('sales.sales_screen', shop_id=user.shop_id)
        
    return url_for('home.index')

def is_safe_url(target):
    """Security check for redirect URLs"""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc