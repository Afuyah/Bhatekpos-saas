
from marshmallow import Schema, fields, validate, validates_schema, ValidationError, post_load, validates
from datetime import datetime
from enum import Enum

class AdjustmentType(Enum):
    SALE = 'sale'
    RESTOCK = 'restock'
    DAMAGED = 'damaged'
    RETURN = 'return'




def validate_quantity(value):
    if value <= 0:
        raise ValidationError("Quantity must be greater than zero.")
    if value > 999:
        raise ValidationError("Quantity exceeds maximum allowed (999).")

class CartItemSchema(Schema):
    product_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1),
        metadata={"description": "ID of the product being purchased"}
    )
    quantity = fields.Float(
        required=True,
        validate=validate_quantity,
        metadata={"description": "Quantity being purchased (can be fractional)"}
    )
    price = fields.Float( 
        required=True,
        validate=validate.Range(min=0),
        metadata={"description": "Price of the product at time of sale"}
    )


class CheckoutSchema(Schema):
    payment_mode = fields.String(
        required=True,
        validate=validate.OneOf(['pay_now', 'pay_later']),
        metadata={"description": "Payment mode: pay_now or pay_later"}
    )

    payment_method = fields.String(
        allow_none=True,
        validate=validate.OneOf(['cash', 'mobile', 'pay_on_delivery']),
        metadata={"description": "Payment method based on payment mode"}
    )

    customer_name = fields.String(
        allow_none=True,
        metadata={"description": "Customer name required for pay_later sales"}
    )

    customer_phone = fields.String(
        allow_none=True,
        validate=validate.Length(max=20),
        metadata={"description": "Optional customer phone number"}
    )

    discount_code = fields.String(
        allow_none=True,
        metadata={"description": "Optional discount code"}
    )

    cart_items = fields.List(
        fields.Nested(CartItemSchema),
        required=True,
        validate=validate.Length(min=1),
        metadata={"description": "List of items in cart"}
    )

    @validates_schema
    def validate_payment_fields(self, data, **kwargs):
        """Ensure required fields match payment mode logic"""
        payment_mode = data.get('payment_mode')
        payment_method = data.get('payment_method')
        customer_name = data.get('customer_name')

        # Pay Now flow validation
        if payment_mode == 'pay_now':
            if not payment_method:
                raise ValidationError("Payment method is required when payment mode is 'pay_now'.")
            if payment_method not in ['cash', 'mobile']:
                raise ValidationError("For pay_now mode, payment method must be either 'cash' or 'mobile'.")
            # Customer name is optional for pay_now

        # Pay Later flow validation
        elif payment_mode == 'pay_later':
            if not customer_name:
                raise ValidationError("Customer name is required for 'pay_later' sales.")
            if payment_method and payment_method != 'pay_on_delivery':
                raise ValidationError("For pay_later mode, payment method should be 'pay_on_delivery' or not provided.")
            
            # Auto-set payment_method to pay_on_delivery for pay_later if not provided
            if not payment_method:
                data['payment_method'] = 'pay_on_delivery'

    @post_load
    def set_default_payment_method(self, data, **kwargs):
        """Set default payment method for pay_later if not provided"""
        if data.get('payment_mode') == 'pay_later' and not data.get('payment_method'):
            data['payment_method'] = 'pay_on_delivery'
        return data



class ProductSearchSchema(Schema):
    """
    Schema for product search in POS
    """
    query = fields.String(
        required=True,
        validate=validate.Length(min=1, max=100),
        metadata={"description": "Search term for products"}
    )
    category_id = fields.Integer(
        allow_none=True,
        metadata={"description": "Optional category filter"}
    )
    in_stock_only = fields.Boolean(
        load_default=True, 
        metadata={"description": "Only show products in stock"}
    )

class ReceiptSchema(Schema):
    """
    Schema for receipt generation requests
    """
    sale_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1),
        metadata={"description": "ID of the sale to generate receipt for"}
    )
    format = fields.String(
        validate=validate.OneOf(['thermal', 'pdf', 'email', 'sms']),
        load_default='thermal',  # Changed from 'missing' to 'load_default'
        metadata={"description": "Output format for the receipt"}
    )
    include_tax_details = fields.Boolean(
        load_default=False, 
        metadata={"description": "Include detailed tax information"}
    )

class PaymentProcessingSchema(Schema):
    """
    Schema for payment processing data
    """
    amount = fields.Float(
        required=True,
        validate=validate.Range(min=0.01),
        metadata={"description": "Amount to be processed"}
    )
    payment_note = fields.String(
        allow_none=True,
        validate=validate.Length(max=100),
        metadata={"description": "Optional note for the payment"}
    )

class RefundSchema(Schema):
    """
    Schema for processing refunds
    """
    sale_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1),
        metadata={"description": "Original sale ID for the refund"}
    )
    items = fields.List(
        fields.Nested(CartItemSchema),
        required=True,
        metadata={"description": "List of items to refund"}
    )
    reason = fields.String(
        required=True,
        validate=validate.Length(max=200),
        metadata={"description": "Reason for the refund"}
    )


class SaleItemSchema(Schema):
    product_id = fields.Int(required=True)
    quantity = fields.Int(
        required=True,
        validate=validate.Range(min=1, error="Quantity must be at least 1")
    )
    price = fields.Float(
        required=True,
        validate=validate.Range(min=0, error="Price must be positive")
    )

class SaleSchema(Schema):
    id = fields.Int(dump_only=True)
    date = fields.DateTime(dump_only=True)
    total = fields.Float(required=True)
    profit = fields.Float(allow_none=True)
    
    # Payment mode field - this is new logic we're adding
    payment_mode = fields.Str(
        required=True,
        validate=validate.OneOf(['pay_now', 'pay_later']),
        metadata={"description": "Payment mode: pay_now or pay_later"}
    )
    
    # Updated payment method validation to include both old and new methods
    payment_method = fields.Str(
        required=True,
        validate=validate.OneOf(['cash', 'mobile', 'pay_on_delivery']),
        metadata={"description": "Payment method used for the sale"}
    )
    
    customer_name = fields.Str(allow_none=True)
    customer_phone = fields.Str(allow_none=True)
    notes = fields.Str(allow_none=True)
    status = fields.Str(dump_only=True)
    is_paid = fields.Bool(dump_only=True)
    expected_delivery_date = fields.DateTime(allow_none=True)
    subtotal = fields.Float(allow_none=True)
    tax = fields.Float(allow_none=True)
    
    # Relationships
    items = fields.Nested('SaleItemSchema', many=True, required=True)
    user = fields.Nested('UserSchema', dump_only=True)
    
    @validates('payment_method')
    def validate_payment_method_based_on_mode(self, value, **kwargs):
        """Validate payment method based on payment mode"""
        payment_mode = self.context.get('payment_mode')
        
        if payment_mode == 'pay_now':
            if value not in ['cash', 'mobile']:
                raise ValidationError('For pay_now mode, payment method must be either "cash" or "mobile"')
        elif payment_mode == 'pay_later':
            if value != 'pay_on_delivery':
                raise ValidationError('For pay_later mode, payment method must be "pay_on_delivery"')
    
    @validates('customer_name')
    def validate_customer_name(self, value, **kwargs):
        """Validate customer name based on payment mode"""
        payment_mode = self.context.get('payment_mode')
        
        if payment_mode == 'pay_later' and not value:
            raise ValidationError('Customer name is required when payment_mode is "pay_later"')

    @validates_schema
    def validate_payment_flow(self, data, **kwargs):
        """Validate the complete payment flow logic"""
        payment_mode = data.get('payment_mode')
        payment_method = data.get('payment_method')
        customer_name = data.get('customer_name')
        
        # Pay Now flow validation
        if payment_mode == 'pay_now':
            if payment_method not in ['cash', 'mobile']:
                raise ValidationError({
                    'payment_method': ['For pay_now mode, payment method must be either cash or mobile']
                })
            # For pay_now, we don't require customer_name but can still accept it
        
        # Pay Later flow validation  
        elif payment_mode == 'pay_later':
            if payment_method != 'pay_on_delivery':
                raise ValidationError({
                    'payment_method': ['For pay_later mode, payment method must be pay_on_delivery']
                })
            if not customer_name:
                raise ValidationError({
                    'customer_name': ['Customer name is required for pay_later mode']
                })