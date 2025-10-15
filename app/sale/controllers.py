from flask import request, jsonify, render_template
from flask.views import MethodView
from flask_login import login_required, current_user
from marshmallow import ValidationError
from decimal import Decimal, InvalidOperation, getcontext
from sqlalchemy import and_
from .repositories import ProductRepository, CategoryRepository, SaleRepository
from .services import (
    SalesService,

    ProductService,
    ReceiptService,
    CategoryService,
    PaymentService,
    TaxService
  
)
from .schemas import (
    CheckoutSchema,
    CartItemSchema,
    ProductSearchSchema,
    ReceiptSchema
    
)

from app import shop_access_required, role_required, csrf, db 
from app.models import Role, Shop, Category, Product, Sale, CartItem
import logging
logger = logging.getLogger(__name__)

class SalesController(MethodView):
    decorators = [login_required, shop_access_required]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """Render POS page (products/categories are loaded via API)"""
        try:
            shop = Shop.query.get_or_404(shop_id)
            return render_template('sales/pos.html', shop=shop.serialize())
        except Exception as e:
            logger.error(f"Failed to load POS UI: {str(e)}", exc_info=True)
            return render_template('sales/error.html', error="Failed to load POS page"), 500


class ProductAPIController(MethodView):
    decorators = [login_required, shop_access_required]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """API: Return products sorted by most sold"""
        try:
            products = ProductService.get_available_for_sale(shop_id)
            return jsonify(products)
        except Exception as e:
            logger.error(f"Failed to load products: {str(e)}", exc_info=True)
            return jsonify({'error': 'Failed to load products'}), 500


            
class ProductSearchAPIController(MethodView):
    decorators = [login_required, shop_access_required, csrf.exempt]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def post(self, shop_id):
        try:
            data = ProductSearchSchema().load(request.json)

            query = (data['query'] or '').strip()[:100]
            category_id = data.get('category_id')

            if not query:
                return jsonify([])

            products = ProductService.search(
                shop_id=shop_id,
                query=query,
                category_id=category_id,
                limit=20  # optional limit
            )

            return jsonify(products)

        except ValidationError as ve:
            return jsonify({'error': 'Invalid input', 'details': ve.messages}), 400
        except Exception as e:
            logger.exception("Product search error")
            return jsonify({'error': 'Search failed'}), 500




class CategoryAPIController(MethodView):
    decorators = [login_required, shop_access_required]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """API: Get active categories and their products"""
        try:
            categories = CategoryRepository.get_for_pos(shop_id)
            serialized = []
            
            for category in categories:
                cat_data = category.serialize()
                cat_data['products'] = [
                    p.serialize(for_pos=True) 
                    for p in sorted(category.products, key=lambda p: p.name)
                    if p.is_active and p.stock > 0
                ]
                serialized.append(cat_data)
                
            return jsonify(serialized)
        except Exception as e:
            logger.error(f"Failed to fetch categories: {str(e)}", exc_info=True)
            return jsonify({'error': 'Failed to load categories'}), 500



class TransactionController(MethodView):
    decorators = [login_required, shop_access_required, csrf.exempt]
    
    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id, transaction_id=None):
        try:
            if request.path.endswith('/recent'):
                limit = min(int(request.args.get('limit', 4)), 10)  
                transactions = self._get_recent_transactions(shop_id, limit)
                return self._format_recent_transactions(transactions)

            elif transaction_id:
                sale = self._get_sale_with_items(transaction_id, shop_id)
                if not sale:
                    return jsonify({'error': 'Sale not found'}), 404
                return self._format_sale_details(sale)

            return self._get_paginated_transactions(shop_id)

        except ValueError as e:
            logger.warning(f"Invalid request: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Failed to get transactions: {str(e)}", exc_info=True)
            return jsonify({'error': 'Failed to get transactions'}), 500

    def _get_recent_transactions(self, shop_id, limit):
        """Get recent transactions with optimized query"""
        return db.session.query(Sale)\
            .filter(Sale.shop_id == shop_id)\
            .order_by(Sale.date.desc())\
            .limit(limit)\
            .options(
                db.load_only(
                    Sale.id,
                    Sale.date,
                    Sale.total,
                    Sale.payment_method,
                    Sale.customer_name,
                    Sale.status
                )
            )\
            .all()

    def _get_sale_with_items(self, sale_id, shop_id):
        """Get complete sale data with items and product info"""
        return db.session.query(Sale)\
            .filter(and_(
                Sale.id == sale_id,
                Sale.shop_id == shop_id
            ))\
            .options(
                db.joinedload(Sale.cart_items)
                .joinedload(CartItem.product)
                .load_only(
                    Product.id,
                    Product.name,
                    Product.image_url,
                    Product.selling_price,
                    Product.combination_size,
                    Product.combination_price,
                    Product.combination_unit_price
                )
            )\
            .first()

    def _format_sale_details(self, sale):
        """Format detailed sale response with proper decimal handling"""
        getcontext().prec = 8  # Set decimal precision

        def decimal_to_float(value):
            """Safely convert Decimal to float"""
            return float(value) if value is not None else 0.0

        def calculate_item_subtotal(item, unit_price):
            """Calculate subtotal with proper decimal handling"""
            try:
                if isinstance(item.quantity, Decimal) and isinstance(unit_price, Decimal):
                    return decimal_to_float(item.quantity * unit_price)
                elif isinstance(item.quantity, Decimal):
                    return decimal_to_float(item.quantity * Decimal(str(unit_price)))
                elif isinstance(unit_price, Decimal):
                    return decimal_to_float(Decimal(str(item.quantity)) * unit_price)
                return float(item.quantity * unit_price)
            except Exception as e:
                logger.error(f"Error calculating subtotal: {str(e)}")
                return 0.0

        def get_item_price_details(item):
            product = item.product
            if not product:
                unit_price = Decimal(str(item.unit_price)) if item.unit_price else Decimal('0')
                return {
                    'unit_price': unit_price,
                    'is_combo': False,
                    'combo_details': None
                }
            
            if product.is_combo:
                combo_size = Decimal(str(product.combination_size))
                combo_price = Decimal(str(product.combination_price)) if product.combination_price else combo_size * Decimal(str(product.selling_price))
                unit_price = Decimal(str(product.combination_unit_price)) if product.combination_unit_price else Decimal(str(product.selling_price))
                
                quantity = Decimal(str(item.quantity))
                combo_units = (quantity // combo_size).to_integral_value()
                remainder = quantity % combo_size
                
                return {
                    'unit_price': unit_price,
                    'is_combo': True,
                    'combo_details': {
                        'size': decimal_to_float(combo_size),
                        'combo_price': decimal_to_float(combo_price),
                        'combo_units': decimal_to_float(combo_units),
                        'remainder_units': decimal_to_float(remainder),
                        'total_combo_price': decimal_to_float(combo_units * combo_price),
                        'remainder_price': decimal_to_float(remainder * unit_price)
                    }
                }
            else:
                return {
                    'unit_price': Decimal(str(product.selling_price)),
                    'is_combo': False,
                    'combo_details': None
                }

        items = []
        for item in sale.cart_items:
            price_details = get_item_price_details(item)
            subtotal = calculate_item_subtotal(item, price_details['unit_price'])
            
            items.append({
                'product_id': item.product.id if item.product else None,
                'name': item.product.name if item.product else 'Unknown Product',
                'quantity': decimal_to_float(item.quantity),
                'unit_price': decimal_to_float(price_details['unit_price']),
                'current_price': decimal_to_float(item.product.selling_price) if item.product else decimal_to_float(item.unit_price),
                'image_url': item.product.image_url if item.product else None,
                'subtotal': subtotal,
                'is_combo': price_details['is_combo'],
                'combo_details': price_details['combo_details'],
                'applied_discount': decimal_to_float(item.discount) if hasattr(item, 'discount') else 0.0
            })

        return jsonify({
            'id': sale.id,
            'date': sale.date.isoformat(),
            'total': decimal_to_float(sale.total),
            'payment_method': sale.payment_method,
            'status': sale.status.value,
            'customer_name': sale.customer_name or 'Walk-in',
            'customer_phone': sale.customer_phone,
            'items': items,
            'pricing_summary': {
                'subtotal': decimal_to_float(sale.subtotal) if hasattr(sale, 'subtotal') else None,
                'total_discount': decimal_to_float(sum(
                    Decimal(str(item['quantity'])) * Decimal(str(item['unit_price'])) * 
                    (Decimal(str(item['applied_discount'])) / Decimal('100'))
                    for item in items
                )),
                'total_tax': decimal_to_float(sale.tax) if hasattr(sale, 'tax') else None
            }
        })

    def _format_recent_transactions(self, transactions):
        """Format recent transactions response"""
        return jsonify([{
            'id': t.id,
            'date': t.date.isoformat(),
            'total': float(t.total),
            'payment_method': t.payment_method,
            'customer_name': t.customer_name or 'Walk-in',
            'status': t.status.value,
            'item_count': len(t.cart_items) if hasattr(t, 'cart_items') else 0,
            'contains_combos': any(
                item.product and item.product.is_combo 
                for item in t.cart_items
            ) if hasattr(t, 'cart_items') else False
        } for t in transactions])

    
    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def post(self, shop_id):
        """
        Process checkout - POST /shops/<shop_id>/transactions
        """
        try:
            checkout_data = CheckoutSchema().load(request.json)

            result = SalesService.process_checkout(
                shop_id=shop_id,
                user_id=current_user.id,
                cart_items=checkout_data['cart_items'], 
                payment_method=checkout_data['payment_method'],
                customer_data={
                    'name': checkout_data.get('customer_name'),
                    'phone': checkout_data.get('customer_phone')
                }
            )

            return jsonify({
                'success': True,
                'sale_id': result['sale_id'],
                'receipt': result['receipt'],
                'amount_paid': result['amount_paid']
            })

        except ValidationError as e:
            return jsonify({'error': e.messages}), 400
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Checkout failed: {str(e)}")
            return jsonify({'error': 'Checkout processing failed'}), 500


class ReceiptController(MethodView):
    decorators = [login_required, shop_access_required]
    
    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """
        Get receipt - GET /api/shops/<shop_id>/receipts
        """
        try:
            data = ReceiptSchema().load(request.args)
            receipt = ReceiptService.generate(
                sale_id=data['sale_id'],
                format=data['format']
            )
            return jsonify(receipt)
        except ValidationError as e:
            return jsonify({'error': e.messages}), 400
        except Exception as e:
            logger.error(f"Failed to generate receipt: {str(e)}")
            return jsonify({'error': 'Failed to generate receipt'}), 500
        
        
