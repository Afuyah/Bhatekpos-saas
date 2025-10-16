from flask_sqlalchemy import SQLAlchemy
from flask import url_for
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from enum import Enum
from datetime import datetime, date
from sqlalchemy import func, Index, ForeignKey
from sqlalchemy.orm import validates, relationship
from sqlalchemy_utils.types import ScalarListType
from app import db
from decimal import Decimal
from sqlalchemy import event
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.ext.declarative import declared_attr
import enum
import logging
from sqlalchemy import Numeric, Integer, Float, ForeignKey, String, DateTime, JSON, Boolean, Text , text, Column
from sqlalchemy import and_
import sqlalchemy as sa
from sqlalchemy.sql import expression
from slugify import slugify 
import uuid
# Configure logging
logging.basicConfig(level=logging.DEBUG)


class ShopType(enum.Enum):
    pos = 'point of sale'
    pop ='point of purchase'


class AdjustmentType(enum.Enum):
    addition = "addition"  # Adding stock
    reduction = "reduction"
    returned = "returned"  
    inventory_adjustment = "inventory_adjustment"  
    damage = "damage" 

    def __str__(self):
        return self.value.capitalize() 
 

class BusinessStatus(str, Enum):
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    SUSPENDED = 'suspended'
    CLOSED = 'closed'
    PENDING = 'pending'


# User Roles Enum
class Role(Enum):
    SUPERADMIN = 'superadmin'
    TENANT = 'tenant'
    ADMIN = 'admin'
    CASHIER = 'cashier'


class SaleStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"





class BaseModel(db.Model):
    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,  server_default=sa.func.now(),  nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = db.Column(Boolean, default=False, server_default=expression.false(), nullable=True, index=True)

    def soft_delete(self):
        """Mark record as deleted without physical removal"""
        self.is_deleted = True
        db.session.add(self)
        return self

    def restore(self):
        """Restore a soft-deleted record"""
        self.is_deleted = False
        db.session.add(self)
        return self

    @classmethod
    def get_active(cls):
        """Get all non-deleted records"""
        return cls.query.filter_by(is_deleted=False)

    @classmethod
    def get_deleted(cls):
        """Get all deleted records"""
        return cls.query.filter_by(is_deleted=True)

    @classmethod
    def bulk_delete(cls, ids):
        """Soft delete multiple records"""
        return cls.query.filter(cls.id.in_(ids)).update(
            {'is_deleted': True},
            synchronize_session=False
        )

    def before_save(self):
        """Hook for pre-save operations"""
        pass

    def after_save(self):
        """Hook for post-save operations"""
        pass

    def save(self):
        """Save with hooks"""
        self.before_save()
        db.session.add(self)
        db.session.commit()
        self.after_save()
        return self

class BusinessScopedMixin:
    @declared_attr
    def business_id(cls):
        return db.Column(db.Integer, db.ForeignKey('businesses.id'), nullable=True)

    @declared_attr
    def business(cls):
        return db.relationship('Business', back_populates=cls.__tablename__, lazy='joined')

class ShopScopedMixin:
    @declared_attr
    def shop_id(cls):
        return db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=True)

    @declared_attr
    def shop(cls):
        return db.relationship('Shop', back_populates=cls.__tablename__, lazy='joined')



class Business(BaseModel):
    __tablename__ = 'businesses'
    
    # Core Business Information
    name = db.Column(db.String(150), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(150), nullable=True)
    description = db.Column(db.Text, nullable=True)
    
    # Contact Information
    email = db.Column(db.String(150), nullable=True, unique=True)
    phone = db.Column(db.String(20), nullable=True)
    secondary_phone = db.Column(db.String(20), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    
    # Location Information
    address = db.Column(db.Text, nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), default="Kenya")
    postal_code = db.Column(db.String(20), nullable=True)
    timezone = db.Column(db.String(50), default="Africa/Nairobi")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
    # Legal Information
    registration_number = db.Column(db.String(50), nullable=True, unique=True)
    tax_identification = db.Column(db.String(50), nullable=True, unique=True)
    business_type = db.Column(db.String(50), nullable=True)  # LLC, Sole Proprietorship, etc.
    
    # Financial Settings
    currency = db.Column(db.String(10), default="KES")
    fiscal_year_start = db.Column(db.Date, default=date(date.today().year, 1, 1))
    tax_rate = db.Column(db.Float, default=0.0)  # Default tax rate
    
    # Status and Approval
    status = db.Column(db.Enum(BusinessStatus), default=BusinessStatus.PENDING, index=True)
    is_approved = db.Column(db.Boolean, default=False, nullable=True, index=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approval_notes = db.Column(db.Text, nullable=True)
    # Media
    logo_url = db.Column(db.String(255), nullable=True)
    banner_url = db.Column(db.String(255), nullable=True)
    
    # Relationships
    
    shops = db.relationship('Shop', back_populates='business', cascade='all, delete-orphan')
    users = db.relationship(
        'User',
        back_populates='business',
        cascade='all, delete-orphan',
        foreign_keys='User.business_id'  # Disambiguates User ↔ Business
    )
    
    
    # Indexes
    __table_args__ = (
        db.Index('ix_business_status', 'status'),
        db.Index('ix_business_approved', 'is_approved'),
    )

    def approve(self, approved_by_user, notes=None):
        """Approve the business and set approval details"""
        self.is_approved = True
        self.status = BusinessStatus.ACTIVE
        self.approved_by = approved_by_user
        self.approved_at = datetime.utcnow()
        self.approval_notes = notes

    def reject(self, reason=None):
        """Reject the business application"""
        self.is_approved = False
        self.status = BusinessStatus.REJECTED
        if reason:
            self.rejection_reason = reason
        return self.save()

    def suspend(self, reason=None):
        """Suspend the business"""
        self.status = BusinessStatus.SUSPENDED
        if reason:
            self.suspension_reason = reason
        return self.save()

    def activate(self):
        """Activate a suspended business"""
        self.status = BusinessStatus.ACTIVE
        return self.save()

    def close(self, reason=None):
        """Close the business"""
        self.status = BusinessStatus.CLOSED
        if reason:
            self.closing_reason = reason
        return self.save()

    @property
    def tenant(self):
        """Get the primary tenant/admin user"""
        return next((u for u in self.users if u.role == Role.TENANT), None)

    @property
    def active_shops(self):
        """Get all non-deleted shops"""
        return [shop for shop in self.shops if not shop.is_deleted]

    @property
    def active_users(self):
        """Get all non-deleted users"""
        return [user for user in self.users if not user.is_deleted]

    def serialize(self, include_related=False):
        """Serialize business data for API responses"""
        data = {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'status': self.status.value if self.status else None,
            'email': self.email,
            'phone': self.phone,
            'address': self.address,
            'city': self.city,
            'country': self.country,
            'registration_number': self.registration_number,
            'tax_identification': self.tax_identification,
            'currency': self.currency,
            'logo_url': self.logo_url,
            'is_approved': self.is_approved,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'shop_count': len(self.active_shops),
            'user_count': len(self.active_users),
            'tenant': self.tenant.username if self.tenant else None
        }

        if include_related:
            data['shops'] = [shop.serialize() for shop in self.active_shops]
            data['users'] = [user.serialize() for user in self.active_users]

        return data



    def before_save(self):
        """Ensure display name defaults to name"""
        if not self.display_name:
            self.display_name = self.name


class Shop(BaseModel, BusinessScopedMixin):
    __tablename__ = 'shops'
    __table_args__ = (
        db.Index('ix_shops_business_id', 'business_id'),
        db.Index('ix_shops_name', 'name'),
        db.Index('ix_shops_phone', 'phone'),
        db.Index('ix_shops_is_active', 'is_active'),
    )

    name = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(20), nullable=True, unique=True)
    email = db.Column(db.String(150), nullable=True, unique=True)
    currency = db.Column(db.String(10), default="KES", nullable=True)
    slug = db.Column(db.String(100), unique=True, index=True)
    allow_registrations = db.Column(db.Boolean, default=True)
    logo_url = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    type = db.Column(SQLAlchemyEnum(ShopType), nullable=True)
    short_url_code = db.Column(db.String(10), unique=True, nullable=True)

    # Relationships
    register_sessions = db.relationship('RegisterSession', back_populates='shop', cascade='all, delete-orphan')
    users = db.relationship('User', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic')
    price_changes = db.relationship('PriceChange', back_populates='shop', cascade="all, delete-orphan")
    products = db.relationship('Product', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic', order_by='Product.name')
    sales = db.relationship('Sale', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic', order_by='Sale.created_at.desc()')
    categories = db.relationship('Category', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic', order_by='Category.name')
    cart_items = db.relationship('CartItem', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic')
    suppliers = db.relationship('Supplier', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic', order_by='Supplier.name')
    expenses = db.relationship('Expense', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic', order_by='Expense.date.desc()')
    user_addresses = db.relationship('UserAddress', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic')
    stock_logs = db.relationship('StockLog', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic', order_by='StockLog.created_at.desc()')
    taxes = db.relationship('Tax', back_populates='shop', cascade="all, delete-orphan", lazy='selectin', order_by='Tax.name')
    shop_homepage_settings = db.relationship(
        'ShopHomepageSettings',
        back_populates='shop',
        uselist=False,
        cascade='all, delete-orphan'
    )
    shop_adverts = db.relationship(  # Renamed from adverts to shop_adverts
        'ShopAdvert',
        back_populates='shop',
        cascade='all, delete-orphan',
        lazy='dynamic',
        order_by='ShopAdvert.display_order'
    )

    def __repr__(self):
        return f"<Shop {self.name} (ID: {self.id})>"

    @staticmethod
    def generate_unique_slug(name):
        """Generate a unique slug from the shop name"""
        base_slug = slugify(name)
        slug = base_slug
        while Shop.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
        return slug

    def get_registration_url(self):
        """Generate registration URL for the shop"""
        return url_for("auth.register_user", shop_slug=self.slug, _external=True)

    def serialize(self, include_relations=None):
        """Enhanced serialization with configurable relation inclusion"""
        data = {
            'id': self.id,
            'name': self.name,
            'location': self.location,
            'business_id': self.business_id,
            'phone': self.phone,
            'currency': self.currency,
            'logo_url': self.logo_url,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

        if include_relations:
            for relation in include_relations:
                if relation == 'taxes':
                    data['taxes'] = [tax.serialize() for tax in self.taxes]
                elif relation == 'categories':
                    data['categories'] = [c.serialize() for c in self.categories.all()]
                elif relation == 'stats':
                    data.update(self.get_business_stats())
                elif relation == 'shop_homepage_settings':
                    data['shop_homepage_settings'] = self.shop_homepage_settings.serialize() if self.shop_homepage_settings else None
                elif relation == 'shop_adverts':  # Updated to match relationship name
                    data['shop_adverts'] = [advert.serialize() for advert in self.shop_adverts]

        return data

    def get_business_stats(self):
        """Get key business statistics with optimized queries"""
        from sqlalchemy import func
        return {
            'product_count': self.products.count(),
            'active_product_count': self.products.filter_by(is_active=True).count(),
            'category_count': self.categories.count(),
            'sale_count': self.sales.count(),
            'revenue_30days': db.session.query(
                func.sum(Sale.total)
            ).filter(
                Sale.shop_id == self.id,
                Sale.created_at >= func.date_sub(func.now(), text('interval 30 days'))
            ).scalar() or 0
        }

    @classmethod
    def find_by_name(cls, business_id, name):
        """Find a shop by name and business_id"""
        return cls.query.filter(
            cls.business_id == business_id,
            func.lower(cls.name) == func.lower(name)
        ).first()

    @classmethod
    def search(cls, business_id, query, limit=10):
        """Full-text search for shops by name"""
        return cls.query.filter(
            cls.business_id == business_id,
            cls.name.ilike(f'%{query}%')
        ).limit(limit).all()

    def deactivate(self):
        """Soft deactivate the shop"""
        self.is_active = False
        return self.save()

    @validates('email')
    def validate_email(self, key, email):
        if email and '@' not in email:
            raise ValueError("Invalid email format")
        return email

    @validates('phone')
    def validate_phone(self, key, phone):
        if phone and not phone.replace('+', '').isdigit():
            raise ValueError("Phone must contain only digits and optional '+'")
        return phone

    def before_save(self):
        """Ensure slug is set before saving"""
        if not self.slug:
            self.slug = self.generate_unique_slug(self.name)

class ShopHomepageSettings(BaseModel, ShopScopedMixin):
    __tablename__ = 'shop_homepage_settings'
    
    # Branding
    shop_name = db.Column(db.String(200), nullable=False)
    tagline = db.Column(db.String(300))
    primary_color = db.Column(db.String(7), default='#10b981')
    secondary_color = db.Column(db.String(7), default='#059669')
    
    # Content
    hero_title = db.Column(db.Text)
    hero_description = db.Column(db.Text)
    announcement_text = db.Column(db.Text)
    special_offer = db.Column(db.Text)
    
    # Features
    feature_1_title = db.Column(db.String(100))
    feature_1_description = db.Column(db.Text)
    feature_2_title = db.Column(db.String(100))
    feature_2_description = db.Column(db.Text)
    
    # Stats
    customer_count = db.Column(db.String(50), default='400+')
    delivery_area = db.Column(db.String(100))
    dispatch_time = db.Column(db.String(50))
    
    # Media
    logo_url = db.Column(db.String(500))
    favicon_url = db.Column(db.String(500))
    
    # SEO
    meta_title = db.Column(db.String(200))
    meta_description = db.Column(db.Text)
    
    # URL Scoping
    subdomain = db.Column(db.String(100), unique=True, index=True)
    custom_domain = db.Column(db.String(255), unique=True, index=True)
    
    is_active = db.Column(db.Boolean, default=True)
    
    # Indexes
    __table_args__ = (
        db.Index('ix_homepage_subdomain', 'subdomain'),
        db.Index('ix_homepage_custom_domain', 'custom_domain'),
        db.Index('ix_homepage_shop_active', 'shop_id', 'is_active'),
    )

    def generate_subdomain(self):
        """Generate a unique subdomain from shop name"""
        if not self.subdomain and self.shop_name:
            base_subdomain = slugify(self.shop_name)
            subdomain = base_subdomain
            counter = 1
            
            while ShopHomepageSettings.query.filter_by(subdomain=subdomain).first():
                subdomain = f"{base_subdomain}-{counter}"
                counter += 1
            
            self.subdomain = subdomain
        return self.subdomain

    def serialize(self):
        """Serialize homepage settings for API responses"""
        return {
            'id': self.id,
            'shop_id': self.shop_id,
            'shop_name': self.shop_name,
            'tagline': self.tagline,
            'primary_color': self.primary_color,
            'secondary_color': self.secondary_color,
            'hero_title': self.hero_title,
            'hero_description': self.hero_description,
            'announcement_text': self.announcement_text,
            'special_offer': self.special_offer,
            'feature_1_title': self.feature_1_title,
            'feature_1_description': self.feature_1_description,
            'feature_2_title': self.feature_2_title,
            'feature_2_description': self.feature_2_description,
            'customer_count': self.customer_count,
            'delivery_area': self.delivery_area,
            'dispatch_time': self.dispatch_time,
            'logo_url': self.logo_url,
            'favicon_url': self.favicon_url,
            'meta_title': self.meta_title,
            'meta_description': self.meta_description,
            'subdomain': self.subdomain,
            'custom_domain': self.custom_domain,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class ShopAdvert(BaseModel, ShopScopedMixin):
    __tablename__ = 'shop_adverts'
    
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    button_text = db.Column(db.String(50))
    button_link = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)
    
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    
    # Indexes
    __table_args__ = (
        db.Index('ix_adverts_shop_active', 'shop_id', 'is_active'),
        db.Index('ix_adverts_dates', 'start_date', 'end_date'),
    )

    @property
    def is_currently_active(self):
        """Check if advert is currently active based on dates"""
        now = datetime.utcnow()
        if self.start_date and self.start_date > now:
            return False
        if self.end_date and self.end_date < now:
            return False
        return self.is_active

    def serialize(self):
        """Serialize advert for API responses"""
        return {
            'id': self.id,
            'shop_id': self.shop_id,
            'title': self.title,
            'content': self.content,
            'image_url': self.image_url,
            'button_text': self.button_text,
            'button_link': self.button_link,
            'is_active': self.is_active,
            'display_order': self.display_order,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'is_currently_active': self.is_currently_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class RegisterSession(BaseModel, ShopScopedMixin):
    __tablename__ = 'register_sessions'

    opened_at = db.Column(DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(DateTime, nullable=True)

    opening_cash = db.Column(Float, nullable=False)   
    closing_cash = db.Column(Float, nullable=True)    
    expected_cash = db.Column(Float, nullable=True)     
    discrepancy = db.Column(Float, nullable=True)       
    notes = db.Column(Text, nullable=True)

    opened_by_id = db.Column(Integer, db.ForeignKey('users.id'), nullable=False)
    closed_by_id = db.Column(Integer, db.ForeignKey('users.id'), nullable=True)

    opened_by = db.relationship('User', foreign_keys=[opened_by_id])
    closed_by = db.relationship('User', foreign_keys=[closed_by_id])

    sales = db.relationship('Sale', backref='register_session')

    __table_args__ = (
        db.Index('ix_register_shop_date', 'shop_id', 'opened_at'),
        db.Index('ix_register_shop_closed', 'shop_id', 'closed_at'),
        db.Index('ix_register_opened_by', 'opened_by_id'),
        db.Index('ix_register_closed_by', 'closed_by_id'),
        db.Index('ix_register_opened_at', 'opened_at'),
        db.Index('ix_register_closed_at', 'closed_at'),
    )


    def is_open(self):
        return self.closed_at is None

    def serialize(self):
        return {
            'id': self.id,
            'opened_at': self.opened_at.isoformat(),
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'opening_cash': self.opening_cash,
            'closing_cash': self.closing_cash,
            'expected_cash': self.expected_cash,
            'discrepancy': self.discrepancy,
            'notes': self.notes,
            'opened_by_id': self.opened_by_id,
            'closed_by_id': self.closed_by_id,
            'shop_id': self.shop_id
        }

    @property
    def duration(self):
        if self.closed_at:
            return (self.closed_at - self.opened_at).total_seconds()
        return None
        
    @property
    def status(self):
        return 'OPEN' if self.closed_at is None else 'CLOSED'



class Tax(BaseModel, ShopScopedMixin):
    __tablename__ = 'taxes'

    name = db.Column(db.String(100), nullable=False)
    rate = db.Column(db.Float, nullable=False) 
    description = db.Column(db.String(255), nullable=True)
    kra_code = db.Column(db.String(50), nullable=True) 
    is_active = db.Column(db.Boolean, default=True, nullable=False)


    __table_args__ = (
        db.UniqueConstraint('shop_id', 'name', name='uq_tax_name_per_shop'),
    )


    @staticmethod
    def get_tax_rate(shop_id: int) -> float:
        tax = Tax.query.filter_by(shop_id=shop_id, is_active=True, is_deleted=False).first()
        return float(tax.rate if tax else 0.0) 

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'rate': self.rate,
            'description': self.description,
            'kra_code': self.kra_code,
            'shop_id': self.shop_id
        }


# User Model with Role-based Access
class User(UserMixin, BaseModel, ShopScopedMixin, BusinessScopedMixin):
    __tablename__ = 'users'
    
    # Authentication
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), nullable=True, unique=True, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    last_password_change = db.Column(db.DateTime, nullable=True)
    login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    business_id = db.Column(db.Integer, db.ForeignKey('businesses.id'), nullable=True)
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=True)
    
    # Security
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    email_verification_token = db.Column(db.String(100), nullable=True)
    email_verified = db.Column(db.Boolean, default=False)
    
    # Profile
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(20), nullable=True)

    
    # Permissions
    role = db.Column(db.Enum(Role), nullable=False, index=True)
    permissions = db.Column(db.JSON, nullable=True)  
    
    # Relationships
    sales = db.relationship('Sale', back_populates='user')
    opened_sessions = db.relationship('RegisterSession', foreign_keys='RegisterSession.opened_by_id', back_populates='opened_by')
    closed_sessions = db.relationship('RegisterSession', foreign_keys='RegisterSession.closed_by_id', back_populates='closed_by')
    business = db.relationship(
        'Business',
        back_populates='users',
        foreign_keys=[business_id],
        lazy='joined'
    )

    shop = db.relationship(
        'Shop',
        back_populates='users',
        foreign_keys=[shop_id],
        lazy='joined'
    )
    # Indexes
    __table_args__ = (
        db.Index('ix_user_role', 'role'),
        db.Index('ix_user_business', 'business_id'),
        db.Index('ix_user_shop', 'shop_id'),
    )


    @property
    def is_active(self):
        return not self.is_locked()


    @property
    def has_address(self):
        """Check if user has at least one valid address"""
        return bool(self.addresses)
    
    @property
    def primary_address(self):
        """Get the user's primary address"""
        return next((addr for addr in self.addresses if addr.is_primary), None)
    
    def set_primary_address(self, address_id):
        """Set a specific address as primary"""
        for addr in self.addresses:
            addr.is_primary = (addr.id == address_id)
        db.session.commit()
        return self
    


    def needs_address(self):
        """Determine if this user role requires an address"""
        return not (self.is_superadmin() or self.is_tenant())


    def get_addresses(self):
        """Get all non-deleted addresses ordered by primary first"""
        return sorted(
            [addr for addr in self.addresses if not addr.is_deleted],
            key=lambda x: not x.is_primary
        )    


    def get_full_name(self):
        """Get user's full name"""
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.username

    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
        self.last_password_change = datetime.utcnow()
        return self

    def check_password(self, password):
        """Verify password"""
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self, expires_in=3600):
        """Generate password reset token"""
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.utcnow() + timedelta(seconds=expires_in)
        return self.save()

    def clear_reset_token(self):
        """Clear reset token"""
        self.reset_token = None
        self.reset_token_expires = None
        return self.save()

    def record_login(self):
        """Record successful login"""
        self.last_login = datetime.utcnow()
        self.login_attempts = 0
        self.locked_until = None
        return self.save()

    def record_failed_login(self):
        """Record failed login attempt"""
        self.login_attempts += 1
        if self.login_attempts >= current_app.config.get('MAX_LOGIN_ATTEMPTS', 5):
            self.locked_until = datetime.utcnow() + timedelta(
                minutes=current_app.config.get('LOCKOUT_MINUTES', 30)
            )
        return self.save()

    def is_locked(self):
        """Check if account is locked"""
        return self.locked_until and self.locked_until > datetime.utcnow()

    # Role checking methods
    def is_superadmin(self):
        return self.role == Role.SUPERADMIN

    def is_tenant(self):
        return self.role == Role.TENANT

    def is_admin(self):
        return self.role == Role.ADMIN

    def is_cashier(self):
        return self.role == Role.CASHIER

    def has_permission(self, permission):
        """Check if user has specific permission"""
        if self.is_superadmin():
            return True
        return permission in (self.permissions or [])

    def serialize(self, include_sensitive=False):
        """Serialize user data for API responses"""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.get_full_name(),
            'phone': self.phone,
            'role': self.role.value if self.role else None,
            'business_id': self.business_id,
            'shop_id': self.shop_id,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

        if include_sensitive:
            data['email_verified'] = self.email_verified
            data['is_locked'] = self.is_locked()

        return data

           
class Category(BaseModel, ShopScopedMixin):
    __tablename__ = 'categories'
    
    name = db.Column(String(100), nullable=False, index=True)
    is_active = db.Column(Boolean, default=True)
    position = db.Column(Integer, default=0)
    image_url = db.Column(String(255))
    
    # Relationship with explicit back_populates
    products = db.relationship('Product', back_populates='category', lazy='selectin')

    
    __table_args__ = (
        db.UniqueConstraint('shop_id', 'name', name='uq_category_shop_name'),
    )

    @property
    def active_products(self):
        return [p for p in self.products if p.is_active and p.stock > 0]

    @property
    def product_count(self):
        return len(self.active_products)


    def serialize(self, include_products=False):
        """Enhanced serialization with options"""
        data = {
            'id': self.id,
            'name': self.name,
            'position': self.position,
            'image_url': self.image_url,
            'product_count': self.product_count,
            'shop_id': self.shop_id
        }
        
        if include_products:
            data['products'] = [p.serialize() for p in self.active_products]
        
        return data

    @classmethod
    def get_for_shop(cls, shop_id, include_products=False):
        """Get all active categories for a shop with error handling"""
        try:
            query = cls.query.filter_by(
                shop_id=shop_id,
                is_active=True
            ).order_by(cls.position, cls.name)
            
            if include_products:
                query = query.options(
                    db.joinedload(cls.products).filter(
                        and_(
                            Product.is_active == True,
                            Product.stock > 0
                        )
                    ).load_only('id', 'name', 'price', 'image_url', 'stock')
                )
            
            return query.all()
        except Exception as e:
            current_app.logger.error(f"Error loading categories for shop {shop_id}: {str(e)}")
            raise ValueError("Failed to load categories") from e

    def __repr__(self):
        return f'<Category {self.id}: {self.name}>'

class Sale(BaseModel, ShopScopedMixin):
    __tablename__ = 'sales'

    date = db.Column(DateTime, default=datetime.utcnow, index=True)
    total = db.Column(Float, nullable=False)
    profit = db.Column(Float, nullable=True)
    payment_method = db.Column(String(50), nullable=False)
    customer_phone = db.Column(String(20), nullable=True)
    customer_name = db.Column(String(200), nullable=True)
    notes = db.Column(Text, nullable=True)
    status = db.Column(SQLAlchemyEnum(SaleStatus, name="sale_status"), default=SaleStatus.PENDING, index=True, nullable=False)

    is_paid = db.Column(db.Boolean, default=False, index=True)
    expected_delivery_date = db.Column(DateTime, nullable=True)

    subtotal = db.Column(Float, nullable=True)
    tax = db.Column(Float, nullable=True)
    register_session_id = db.Column(Integer, db.ForeignKey('register_sessions.id'), nullable=True)
    user_id = db.Column(Integer, db.ForeignKey('users.id'))

    # Relationships
    cart_items = relationship('CartItem', back_populates='sale')
    user = relationship('User')

    __table_args__ = (
        db.Index('ix_sale_total', 'total'),
        db.Index('ix_sale_date', 'date'),
        db.Index('ix_sale_shop_date', 'shop_id', 'date'),
        db.Index('ix_sale_session', 'register_session_id'),
        db.Index('ix_sale_user', 'user_id'),
        db.Index('ix_sale_payment', 'payment_method'),
        db.Index('ix_sale_shop_pay_date', 'shop_id', 'payment_method', 'date'),
        db.Index('ix_sale_status_paid', 'status', 'is_paid'),
    )

    @validates('payment_method')
    def validate_payment_method(self, key, value):
        # Update allowed methods to match your schema
        allowed_methods = ['cash', 'mobile', 'pay_on_delivery']  # ADD 'cash' and 'mobile'
        if value not in allowed_methods:
            raise ValueError(f"Invalid payment method: {value}")
        return value

    def serialize(self):
        """Serialize sale object for API response."""
        return {
            'id': self.id,
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'total': self.total,
            'profit': self.profit,
            'payment_method': self.payment_method,
            'status': self.status.value,
            'is_paid': self.is_paid,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'expected_delivery_date': self.expected_delivery_date.strftime("%Y-%m-%d") if self.expected_delivery_date else None,
            'notes': self.notes,
            'user': {
                'id': self.user.id if self.user else None,
                'username': self.user.username if self.user else None,
                'role': self.user.role.value if self.user else None
            },
            'items': [item.serialize() for item in self.cart_items],
        }

    @classmethod
    def create_sale(cls, total, profit, payment_method, customer_name, user_id=None):
        """Create a new sale instance."""
        return cls(
            date=datetime.utcnow(),
            total=total,
            profit=profit,
            payment_method=payment_method,
            customer_name=customer_name,
            user_id=user_id
        )

    def finalize_sale(self):
        """Finalize the sale by updating stock and committing to the database."""
        try:
            # Check stock availability for each cart item
            for item in self.cart_items:
                if item.product.stock < item.quantity:
                    raise ValueError(f"Not enough stock for {item.product.name}")

            # Update stock and finalize the sale
            for item in self.cart_items:
                item.product.stock -= item.quantity

            db.session.commit()  # Commit changes if everything is valid
        except Exception as e:
            db.session.rollback()  # Rollback in case of error
            raise ValueError(f"Error finalizing sale: {str(e)}")

    def __repr__(self):
        return f'<Sale id={self.id}, total={self.total}, date={self.date.strftime("%Y-%m-%d %H:%M:%S")}>'


class CartItem(BaseModel, ShopScopedMixin):
    __tablename__ = 'cart_items'

    product_id = db.Column(Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    quantity = db.Column(Numeric(12, 3), nullable=False)  # Changed to Numeric for fractional quantities
    sale_id = db.Column(Integer, db.ForeignKey('sales.id'), nullable=False, index=True)
    unit_price = db.Column(Numeric(12, 2), nullable=False)  # Price at time of sale
    discount = db.Column(Numeric(5, 2), default=0.0)  # Discount percentage applied
    total_price = db.Column(Numeric(12, 2), nullable=False)  # Calculated field

    # Relationships
    product = relationship('Product', back_populates='sale_items', lazy='select')
    sale = relationship('Sale', back_populates='cart_items')

    __table_args__ = (
        db.Index('ix_cartitem_product_sale', 'product_id', 'sale_id'),
        db.Index('ix_cartitem_sale_product', 'sale_id', 'product_id'),
        db.Index('ix_cartitem_shop_product', 'shop_id', 'product_id'),
        db.Index('ix_cartitem_shop_sale', 'shop_id', 'sale_id'),
        db.CheckConstraint('quantity > 0', name='check_positive_quantity'),
        db.CheckConstraint('unit_price >= 0', name='check_non_negative_price'),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calculate_total()

    @validates('quantity', 'unit_price', 'discount')
    def validate_values(self, key, value):
        if key == 'quantity' and value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if key in ('unit_price', 'total_price') and value < 0:
            raise ValueError("Price cannot be negative")
        if key == 'discount' and not (0 <= value <= 100):
            raise ValueError("Discount must be between 0 and 100")
        return value

    def calculate_total(self):
        """Calculate total price including discounts"""
        if self.unit_price is not None and self.quantity is not None:
            subtotal = self.unit_price * self.quantity
            self.total_price = subtotal * (1 - (self.discount / 100))
            return self.total_price
        return Decimal('0.00')

    def update_from_product(self, product):
        """Update prices from current product information"""
        if product:
            self.unit_price = product.selling_price
            self.calculate_total()
        return self

    def serialize(self, include_product=False):
        """Enhanced serialization with more details"""
        data = {
            'id': self.id,
            'product_id': self.product_id,
            'quantity': float(self.quantity),
            'unit_price': float(self.unit_price),
            'discount': float(self.discount),
            'total_price': float(self.total_price),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        
        if include_product and self.product:
            data['product'] = {
                'name': self.product.name,
                'image_url': self.product.image_url,
                'barcode': self.product.barcode,
                'current_price': float(self.product.selling_price)
            }
        
        return data

    def __repr__(self):
        return (f'<CartItem id={self.id} product={self.product_id} '
                f'qty={self.quantity} price={self.unit_price}>')



class UnitType(Enum):
    """Enumeration of possible product units"""
    PIECE = 'pcs'
    KILOGRAM = 'kg'
    GRAM = 'g'
    LITER = 'l'
    MILLILITER = 'ml'
    PACKET = 'packet'
    BOTTLE = 'bottle'
    BOX = 'box'
    METER = 'm'
    CENTIMETER = 'cm'

class Product(BaseModel, ShopScopedMixin):
    """Product model representing items in inventory"""
    __tablename__ = 'products'

    # Basic Information
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text)
    barcode = Column(String(50), unique=True, index=True)
    sku = Column(String(50), unique=True, index=True, nullable=True)

    
    # Pricing Information
    cost_price = Column(Numeric(10, 2), nullable=False, default=0.00, server_default=text("0.00"))
    selling_price = Column(Numeric(10, 2), nullable=False, default=0.00, server_default=text("0.00"))
    stock = Column(Integer, nullable=False, default=0, server_default=text("0"))
    low_stock_threshold = Column(Integer, default=10, server_default=text("10"))

    # Media
    image_url = Column(String(255))
    secondary_images = Column(ScalarListType(separator="|"))  # Stores multiple image URLs

    # Measurement
    unit = Column(SQLAlchemyEnum(UnitType), nullable=True)
    minimum_unit = Column(Numeric(3, 2), nullable=False, default=1.0, server_default=text("1.0"))

    # Relationships
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), index=True)
    category = relationship('Category', back_populates='products')
    supplier = relationship('Supplier', back_populates='products')
    sale_items = relationship('CartItem', back_populates='product', lazy='dynamic')
    

    # Combination Pricing
    combination_size = Column(Integer)  # e.g. 4 units
    combination_price = Column(Numeric(10, 2))
    combination_unit_price = Column(Numeric(10, 2))  # Optional override for unit pricing in combo

    # Status Flags
    is_active = Column(Boolean, default=True, server_default=text("true"))
    is_featured = Column(Boolean, default=False, server_default=text("false"))
    is_discountable = Column(Boolean, default=True, server_default=text("true"))

    # Indexes
    __table_args__ = (
        Index('ix_product_shop_category', 'shop_id', 'category_id'),
        Index('ix_product_name_shop', 'name', 'shop_id'),
        Index('ix_product_barcode_shop', 'barcode', 'shop_id'),
        Index('ix_product_sku_shop', 'sku', 'shop_id'),
        Index('ix_product_shop_supplier', 'shop_id', 'supplier_id'),
        Index('ix_product_shop_active', 'shop_id', 'is_active'),
        Index('ix_product_shop_stock', 'shop_id', 'stock'),
        Index('ix_product_shop_combo', 'shop_id', 'combination_size'),
        Index('ix_product_search', 'shop_id', 'name', 'barcode', 'sku'),
    )

    # === Validations ===
    @validates('name')
    def validate_name(self, key, name):
        if not name or len(name.strip()) < 2:
            raise ValueError("Product name must be at least 2 characters")
        return name.strip()

 

        


    @validates('cost_price', 'selling_price')
    def validate_prices(self, key, price):
        if price < 0:
            raise ValueError(f"{key.replace('_', ' ').title()} cannot be negative")
        if key == 'selling_price' and hasattr(self, 'cost_price') and price < self.cost_price:
            raise ValueError("Selling price cannot be less than cost price")
        return round(Decimal(price), 2)

    @validates('stock', 'low_stock_threshold')
    def validate_stock_values(self, key, value):
        if value < 0:
            raise ValueError(f"{key.replace('_', ' ').title()} cannot be negative")
        return value

    @validates('minimum_unit')
    def validate_minimum_unit(self, key, value):
        if value <= 0:
            raise ValueError("Minimum unit must be a positive number")
        if self.unit and self.unit in [UnitType.KILOGRAM, UnitType.LITER] and value > 10:
            raise ValueError("Minimum unit too large for this unit type")
        return round(Decimal(value), 2)

    @validates('barcode', 'sku')
    def validate_codes(self, key, value):
        if value and len(value) > 50:
            raise ValueError(f"{key.upper()} must be 50 characters or less")
        return value

    # === Hybrid Properties ===
    @hybrid_property
    def profit(self):
        """Calculate absolute profit per unit"""
        return self.selling_price - self.cost_price

    @hybrid_property
    def profit_margin(self):
        """Calculate profit margin percentage"""
        return (self.profit / self.selling_price * 100) if self.selling_price > 0 else 0.0

    @hybrid_property
    def is_low_stock(self):
        """Check if stock is below threshold"""
        return (self.stock or 0) < (self.low_stock_threshold or 0)

    @hybrid_property
    def is_combo(self):
        """Check if product has combination pricing"""
        return self.combination_size is not None and self.combination_size > 1

    @hybrid_property
    def display_price(self):
        """Get appropriate price based on combination settings"""
        if self.is_combo:
            return {
                'single': float(self.selling_price),
                'combination': float(self.combination_price or 0.0),
                'size': self.combination_size,
                'unit_price': float(self.combination_unit_price or self.selling_price)
            }
        return float(self.selling_price)

    @hybrid_property
    def total_value(self):
        """Calculate total inventory value"""
        return float(self.cost_price * Decimal(self.stock))

    # === Business Methods ===
    def update_stock(self, quantity, note=None, user_id=None):
        """Safely update stock with inventory logging"""
        new_stock = (self.stock or 0) + quantity
        if new_stock < 0:
            raise ValueError("Insufficient stock available")
        
        self.stock = new_stock
        
        # Create inventory log
        if user_id:
          
            log = StockLog(
                product_id=self.id,
                user_id=user_id,
                quantity=quantity,
                new_quantity=new_stock,
                note=note
            )
            db.session.add(log)
        
        return self

    def apply_discount(self, percentage):
        """Apply percentage discount to selling price"""
        if not 0 <= percentage <= 100:
            raise ValueError("Discount percentage must be between 0 and 100")
        self.selling_price = round(self.selling_price * (1 - percentage/100), 2)
        return self

    # === Serialization ===
    def serialize(self, for_pos=False, include_private=False):
        """Serialize product data for API responses"""
        data = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'price': float(self.selling_price),
            'cost_price': float(self.cost_price) if include_private else None,
            'stock': self.stock,
            'low_stock_threshold': self.low_stock_threshold,
            'image_url': self.image_url,
            'barcode': self.barcode,
            'sku': self.sku,
            'category_id': self.category_id,
            'supplier_id': self.supplier_id,
            
            'is_active': self.is_active,
            'is_featured': self.is_featured,
            'is_discountable': self.is_discountable,
            'unit': self.unit.value if self.unit else None,
            'minimum_unit': float(self.minimum_unit),
            'profit_margin': float(self.profit_margin),
            'is_combo': self.is_combo,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

        if for_pos:
            data.update({
                'display_price': self.display_price,
                'combination_size': self.combination_size,
                'combination_price': float(self.combination_price or 0.0),
                'combination_unit_price': float(self.combination_unit_price or 0.0),
                'category_name': self.category.name if self.category else None,
                'supplier_name': self.supplier.name if self.supplier else None
            })

        if include_private:
            data.update({
                'profit': float(self.profit),
                'total_value': self.total_value,
                'is_low_stock': self.is_low_stock
            })

        return data

    def __repr__(self):
        return f'<Product {self.id}: {self.name} (Shop: {self.shop_id})>'




class Supplier(BaseModel, ShopScopedMixin):
    __tablename__ = 'suppliers'
    
    
    name = db.Column(String(200), nullable=False)  # Removed unique=True
    phone = db.Column(String(20), nullable=True)
    
    products = db.relationship("Product", back_populates="supplier")
 

    def __repr__(self):
        return f'<Supplier {self.name}>'

    def serialize(self):
        """Serialize the supplier object."""
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'product_count': len(self.products),  # Include count of products for context
            'products': [product.serialize() for product in self.products]  # Serialize all products
        }


class Expense(BaseModel, ShopScopedMixin):
    __tablename__ = 'expenses'
 
    description = db.Column(String(200), nullable=False)
    amount = db.Column(Numeric(10, 2), nullable=False)  # Changed to Numeric for precision
    date = db.Column(DateTime, default=datetime.utcnow, index=True)
    category = db.Column(String(100), nullable=True, default="Daily Expenses")  # Default category
    product_id = db.Column(Integer, ForeignKey('products.id'), nullable=True)
    quantity = db.Column(Integer, nullable=True)

    __table_args__ = (
        Index('ix_expense_date_category', 'date', 'category'),  # Composite index
    )

    product = relationship('Product', backref='expenses', lazy='select')  # Changed to select for efficiency

    @validates('amount', 'quantity')
    def validate_amount_quantity(self, key, value):
        """Validate that the expense amount and quantity are positive."""
        if key == 'amount' and value <= 0:  # Allow zero only for quantity
            raise ValueError("Expense amount must be positive.")
        if key == 'quantity' and value <= 0:
            raise ValueError("Quantity must be positive.")
        return value

    def serialize(self):
        """Serialize the expense object."""
        return {
            'id': self.id,
            'description': self.description,
            'amount': str(self.amount),  # Convert to string for JSON serialization
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'category': self.category,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'product_name': self.product.name if self.product else None  # Optional product name
        }


class StockLog(BaseModel, ShopScopedMixin):
    __tablename__ = 'stock_logs'
    
    
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.DateTime, default=func.now())
    previous_stock = db.Column(db.Integer, nullable=False)
    new_stock = db.Column(db.Integer, nullable=False)
    adjustment_type = db.Column(SQLAlchemyEnum(AdjustmentType), nullable=False)  
    change_reason = db.Column(db.String(200), nullable=True)
    log_metadata = db.Column(JSON, nullable=True) 
    
    product = db.relationship('Product', back_populates='stock_logs')
    user = db.relationship('User', back_populates='stock_logs')
    
    def __repr__(self):
        return f"<StockLog(product_id={self.product_id}, previous_stock={self.previous_stock}, new_stock={self.new_stock})>"

# Adding stock_logs relationship to Product and User models
Product.stock_logs = db.relationship('StockLog', order_by=StockLog.date, back_populates='product')
User.stock_logs = db.relationship('StockLog', back_populates='user')        


class PriceChange(BaseModel, ShopScopedMixin):
    __tablename__ = 'price_changes'
    
   
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    change_type = db.Column(db.String(50), nullable=False)  
    old_price = db.Column(db.Numeric(10, 2), nullable=False)
    new_price = db.Column(db.Numeric(10, 2), nullable=False)
    old_combo_size = db.Column(db.Integer, nullable=True)
    old_combo_price = db.Column(db.Numeric(10, 2), nullable=True)
    new_combo_size = db.Column(db.Integer, nullable=True)
    new_combo_price = db.Column(db.Numeric(10, 2), nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship('Product', backref='price_changes')
    user = db.relationship('User', backref='price_changes')


    @classmethod
    def create_record(cls, product_id, user_id, change_type, old_price, new_price,
                     old_combo=None, new_combo=None):
        """Create and return a new price change record"""
        record = cls(
            product_id=product_id,
            user_id=user_id,
            change_type=change_type,
            old_price=old_price,
            new_price=new_price,
            old_combo_size=old_combo[0] if old_combo else None,
            old_combo_price=old_combo[1] if old_combo else None,
            new_combo_size=new_combo[0] if new_combo else None,
            new_combo_price=new_combo[1] if new_combo else None
        )
        db.session.add(record)
        return record
    
class County(BaseModel):
    __tablename__ = 'counties'
    
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(10), unique=True)
    
    # Relationship to SubCounties
    subcounties = db.relationship('SubCounty', backref='county', lazy=True)
    
    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code
        }

class SubCounty(BaseModel):
    __tablename__ = 'subcounties'
    
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(10), unique=True)
    county_id = db.Column(db.Integer, db.ForeignKey('counties.id'), nullable=False)  # New field
    
    # Relationship to Ward
    wards = db.relationship('Ward', backref='subcounty', lazy=True)
    
    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'county_id': self.county_id
        }



class Ward(BaseModel):
    __tablename__ = 'wards'
   
    name = db.Column(db.String(100), nullable=False)
    subcounty_id = db.Column(db.Integer, db.ForeignKey('subcounties.id'), nullable=False)

    def serialize(self):
        return {
        'id' : self.id,
        'name': self.name,
        'subcounty_id': self.subcounty_id
        }

class UserAddress(BaseModel, ShopScopedMixin):
    __tablename__ = 'user_addresses'
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    county_id = db.Column(db.Integer, db.ForeignKey('counties.id'), nullable=False)  
    subcounty_id = db.Column(db.Integer, db.ForeignKey('subcounties.id'), nullable=False)
    ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'), nullable=False)
    
    # Location details
    estate = db.Column(db.String(100))
    landmark = db.Column(db.String(100))
    building = db.Column(db.String(100))
    apartment = db.Column(db.String(50))
    house_number = db.Column(db.String(20))
    
    # Additional info
    notes = db.Column(db.Text)
    is_primary = db.Column(db.Boolean, default=False, server_default=expression.false())
    
    # Relationships
    user = db.relationship('User', backref=db.backref('addresses', lazy=True))
    subcounty = db.relationship('SubCounty')
    ward = db.relationship('Ward')
    
    # Indexes
    __table_args__ = (
        db.Index('ix_useraddress_user', 'user_id'),
        db.Index('ix_useraddress_primary', 'user_id', 'is_primary'),
        db.Index('ix_useraddress_subcounty', 'subcounty_id'),
        db.Index('ix_useraddress_ward', 'ward_id'),
    )
    
    def serialize(self):
        return {
            'id': self.id,
            'county': self.county.name if self.county else None,
            'county_id': self.county_id,
            'subcounty': self.subcounty.name if self.subcounty else None,
            'subcounty_id': self.subcounty_id,
            'ward': self.ward.name if self.ward else None,
            'ward_id': self.ward_id,
            'estate': self.estate,
            'landmark': self.landmark,
            'building': self.building,
            'apartment': self.apartment,
            'house_number': self.house_number,
            'notes': self.notes,
            'is_primary': self.is_primary,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def before_save(self):
        """Ensure only one primary address per user"""
        if self.is_primary:
            # Clear any existing primary address
            UserAddress.query.filter_by(
                user_id=self.user_id,
                is_primary=True
            ).update({'is_primary': False})



