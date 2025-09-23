from flask_login import current_user
from datetime import datetime
from decimal import Decimal, ROUND_UP
from typing import List, Dict, Optional
from flask import request, session
from .. import db, socketio
from .repositories import ProductRepository, CategoryRepository, SaleRepository
from ..models import Shop, Sale, CartItem, Category, Product, Tax
from sqlalchemy.sql import bindparam
from app.utils.pricing import PricingUtil
import threading
from sqlalchemy.orm import joinedload, with_loader_criteria
from app.utils.time import get_kenya_today_range
from sqlalchemy import and_, func, case
import logging
import logging
import traceback
from functools import lru_cache




logger = logging.getLogger(__name__)


def run_checkout_tasks(sale_id: int, shop_id: int, user_id: int, total: float, item_count: int):
    try:
        # Generate receipt (safe access)
        receipt = ReceiptService.generate(sale_id)
        logger.info("Receipt generated successfully")

        
        # Emit real-time update
        socketio.emit('sale_completed', {
            'sale_id': sale_id,
            'shop_id': shop_id,
            'total': total,
            'items_count': item_count,
        }, room=f'pos_{shop_id}')

    except Exception as e:
        logger.error("Post-checkout task failed", extra={'sale_id': sale_id, 'error': str(e), 'trace': traceback.format_exc()})


# In services.py
class SalesService:
    @staticmethod
    def get_pos_data(shop_id: int) -> Dict:
        """
        Get all data needed to initialize the POS interface
        """
        try:
            shop = Shop.query.get_or_404(shop_id)

            return {
                'shop': {
                    'id': shop.id,
                    'name': shop.name,
                    'currency': shop.currency,
                    'logo_url': shop.logo_url
                },
                'categories': CategoryService.get_for_pos(shop_id),
                'products': [
                    p.serialize(for_pos=True)
                    for p in ProductRepository.get_available_for_sale(shop_id)
                ],
                'payment_methods': PaymentService.get_available_methods(shop_id),
                'tax_rates': TaxService.get_rates(shop_id)
                
            }
        except Exception as e:
            logger.error(f"Error getting POS data: {str(e)}", exc_info=True)
            raise ValueError("Failed to load POS data") from e

    
    @staticmethod
    def process_checkout(
        shop_id: int,
        user_id: int,
        cart_items: List[Dict],
        payment_method: str,
        customer_data: Optional[Dict] = None
    ) -> Dict:
        if not cart_items:
            raise ValueError("Cannot process empty sale")
        if not payment_method:
            raise ValueError("Payment method is required")

        # Normalize cart data (force Decimal quantity)
        cart_items = [
            {
                'product_id': int(item['product_id']),
                'quantity': Decimal(str(item['quantity']))
            }
            for item in cart_items
        ]

        try:
            # Preload all products in bulk
            product_ids = [item['product_id'] for item in cart_items]
            products = ProductRepository.get_bulk_for_sale(product_ids, shop_id)
            product_map = {p.id: p for p in products}

            tax_rate = Decimal(str(Tax.get_tax_rate(shop_id)))
            subtotal = Decimal('0')
            total_cost = Decimal('0')
            cart_item_data = []
            stock_updates = []

            def round_up_to_nearest_five(amount: Decimal) -> Decimal:
                return (amount / Decimal('5')).to_integral_value(rounding=ROUND_UP) * Decimal('5')

            for item in cart_items:
                product = product_map.get(item['product_id'])
                if not product:
                    raise ValueError(f"Product {item['product_id']} not found")

                quantity = item['quantity']
                if product.stock < quantity:
                    raise ValueError(f"Insufficient stock for '{product.name}'")

                # Calculate combo-aware subtotal
                if product.is_combo and product.combination_size and product.combination_size > 1:
                    combo_size = Decimal(str(product.combination_size))
                    combo_price = Decimal(str(product.combination_price))
                    unit_price = Decimal(str(product.selling_price))

                    combos = quantity // combo_size
                    remainder = quantity % combo_size
                    combo_total = combos * combo_price
                    remainder_total = min(remainder * unit_price, combo_price)
                    item_subtotal = combo_total + remainder_total
                else:
                    unit_price = Decimal(str(product.selling_price))
                    item_subtotal = quantity * unit_price

                item_subtotal = round_up_to_nearest_five(item_subtotal)

                cost_price = Decimal(str(product.cost_price))
                item_cost = quantity * cost_price

                subtotal += item_subtotal
                total_cost += item_cost

                cart_item_data.append({
                    'shop_id': shop_id,
                    'product_id': product.id,
                    'quantity': float(quantity),
                    'unit_price': float(unit_price),
                    'total_price': float(item_subtotal)
                })

                stock_updates.append({
                    'p_id': product.id,
                    'new_stock': float(Decimal(str(product.stock)) - quantity)
                })

            tax_amount = (subtotal * tax_rate).quantize(Decimal('0.01'))
            total = subtotal + tax_amount
            profit = subtotal - total_cost

            # Save sale record
            sale = Sale(
                shop_id=shop_id,
                user_id=user_id,
                subtotal=float(subtotal),
                tax=float(tax_amount),
                total=float(total),
                payment_method=payment_method,
                profit=float(profit)
            )
            db.session.add(sale)
            db.session.flush()  # Get sale.id

            # Bulk insert cart items
            if cart_item_data:
                db.session.execute(
                    CartItem.__table__.insert(),
                    [dict(item, sale_id=sale.id) for item in cart_item_data]
                )

            # Bulk update product stock
            if stock_updates:
                db.session.execute(
                    Product.__table__.update()
                    .where(Product.id == bindparam('p_id'))
                    .values(stock=bindparam('new_stock')),
                    stock_updates
                )

            db.session.commit()

            # Background receipt and notification tasks
            threading.Thread(
                target=run_checkout_tasks,
                args=(sale.id, shop_id, user_id, float(total), len(cart_items)),
                daemon=True
            ).start()

            return {
                'success': True,
                'sale_id': sale.id,
                'amount_paid': float(total),
                'change_due': 0.0,
                'receipt': None,
                'receipt_pending': True
            }

        except Exception as e:
            db.session.rollback()
            logger.error("Checkout failed", extra={
                'shop_id': shop_id,
                'error': str(e),
                'trace': traceback.format_exc()
            })
            raise ValueError(f"Checkout processing failed: {str(e)}")



            

    @staticmethod
    def get_recent_transactions(shop_id: int, limit: int = 3) -> List[Sale]:
        """Get recent sales with optimized query"""
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

    @staticmethod
    def get_sale_details(sale_id: int, shop_id: int) -> Optional[Sale]:
        """Get complete sale data with items"""
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
                    Product.price
                )
            )\
            .first()

    @staticmethod
    def get_daily_sales_summary(shop_id: int, days: int = 7) -> dict:
        """Get sales summary for dashboard"""
        date_threshold = datetime.utcnow() - timedelta(days=days)
        
        result = db.session.query(
            func.count(Sale.id).label('count'),
            func.sum(Sale.total).label('total'),
            func.date(Sale.date).label('day')
        )\
        .filter(and_(
            Sale.shop_id == shop_id,
            Sale.date >= date_threshold
        ))\
        .group_by(func.date(Sale.date))\
        .order_by(func.date(Sale.date).desc())\
        .all()
        
        return [{
            'date': r.day.strftime('%Y-%m-%d'),
            'count': r.count,
            'total': float(r.total) if r.total else 0
        } for r in result]

    @staticmethod
    def reorder_sale(sale_id: int, shop_id: int) -> dict:
        """Prepare sale data for reordering"""
        sale = SalesService.get_sale_details(sale_id, shop_id)
        if not sale:
            return None
            
        return {
            'items': [{
                'product_id': item.product.id,
                'quantity': float(item.quantity),
                'original_price': float(item.unit_price),
                'current_price': float(item.product.price)
            } for item in sale.cart_items],
            'original_total': float(sale.total),
            'estimated_total': sum(
                float(item.quantity) * float(item.product.price)
                for item in sale.cart_items
            )
        }

    

class ReceiptService:
    @staticmethod
    def generate(sale_id: int, format: str = 'json') -> Dict:
        """Generate receipt data using CartItem as sale items"""
        sale = Sale.query.get_or_404(sale_id)
        items = CartItem.query.filter_by(sale_id=sale_id).join(Product).all()
        
        receipt_data = {
            'id': sale.id,
            'date': sale.date.strftime('%Y-%m-%d %H:%M'),
            'shop': {
                'name': sale.shop.name,
                'location': sale.shop.location,
                'phone': sale.shop.phone,
                'tax_id': sale.shop.taxes[0].id if sale.shop.taxes else None

            },
            'items': [{
                'name': item.product.name,
                'quantity': item.quantity,
                'unit_price': item.product.selling_price,  # Current price at time of sale
                'total': item.quantity * item.product.selling_price
            } for item in items],
            'subtotal': sale.subtotal,
            'tax': sale.tax,
            'total': sale.total,
            'payment_method': sale.payment_method,
            'cashier': sale.user.username if sale.user else 'System',
            'customer': {
                'name': sale.customer_name,
                'phone': sale.customer_phone
            } if sale.customer_name else None
        }
        
        # Add barcode/QR code for receipt tracking
        receipt_data['barcode'] = f"RECEIPT-{sale.id}-{sale.date.strftime('%Y%m%d')}"
        
        return receipt_data


class ProductService:
    @staticmethod
    def search(shop_id: int, query: str, category_id: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        try:
            results = ProductRepository.search_available(
                shop_id=shop_id,
                query=query,
                category_id=category_id,
                limit=limit
            )

            return [{
                'id': p.id,
                'name': p.name,
                'price': float(p.selling_price),
                'image': p.image_url or '/static/images/product-placeholder.png',
                'category': p.category.name,
                'category_id': p.category.id,
                'stock': p.stock,
                'barcode': p.barcode or '',
                'unit': p.unit.name if hasattr(p.unit, "name") else p.unit,
                'minimum_unit': p.minimum_unit or 1,
                'is_combo': bool(p.combination_size and p.combination_size > 1),
                'combination_price': float(p.combination_price) if p.combination_price and p.combination_size and p.combination_size > 1 else None,
                'combination_size': p.combination_size if p.combination_size and p.combination_size > 1 else None,
            } for p in results]


        except Exception as e:
            logger.error(f"Product search failed for shop {shop_id}: {str(e)}")
            return []


    @staticmethod
    def get_available_for_sale(shop_id: int) -> List[Dict]:
        try:
            products = ProductRepository.get_available_for_sale(shop_id)
            return [{
                'id': p.id,
                'name': p.name,
                'price': float(p.selling_price),
                'image': p.image_url or '/static/images/product-placeholder.png',
                'category': p.category.name,
                'category_id': p.category.id,
                'stock': p.stock,
                'is_low_stock': p.stock < 10,
                'unit': p.unit.value if p.unit else None,
                'minimum_unit': p.minimum_unit or 1,
                'is_combo': bool(p.combination_size and p.combination_size > 1),
                'combination_price': float(p.combination_price) if p.combination_price and p.combination_size and p.combination_size > 1 else None,
                'combination_size': p.combination_size if p.combination_size and p.combination_size > 1 else None,
            } for p in products]

        except Exception as e:
            logger.error(f"Failed to get products for shop {shop_id}: {str(e)}")
            return []




class CategoryService:
    @staticmethod
    def get_for_pos(shop_id: int) -> List[Dict]:
        """
        Return serialized category list with their valid products for POS display.
        """
        categories = CategoryRepository.get_for_pos(shop_id)

        return [
            {
                'id': c.id,
                'name': c.name,
                'products': sorted([
                    {
                        'id': p.id,
                        'name': p.name,
                        'price': float(p.selling_price),
                        'image_url': p.image_url or '/static/images/product-placeholder.png',
                        'stock': p.stock,
                        'unit': p.unit.value if p.unit else None,
                        'minimum_unit': float(p.minimum_unit) if p.minimum_unit else 1.0,
                        'barcode': p.barcode,
                        'category_id': p.category_id,
                        'is_combo': bool(p.combination_size and p.combination_size > 1),
                        'combination_price': float(p.combination_price) if p.combination_price and p.combination_size and p.combination_size > 1 else None,
                        'combination_size': p.combination_size if p.combination_size and p.combination_size > 1 else None,
                    }
                    for p in c.products
                    if p.is_active and p.stock > 0
                ], key=lambda x: x['name'])
            }
            for c in categories
        ]



    @staticmethod
    def get_ranked(shop_id: int) -> List[Dict]:
        """Get top selling categories"""
        categories = CategoryRepository.get_ranked_categories(shop_id)
        return [{
            'id': c.id,
            'name': c.name,
            'sales_count': len(c.products)
        } for c in categories]


class PaymentService:
    @staticmethod
    def get_available_methods(shop_id: int) -> List[Dict]:
        """Get payment methods enabled for this shop"""
        # In real implementation, this would come from shop settings
        return [
            {'code': 'cash', 'name': 'Cash', 'needs_confirmation': False},
            {'code': 'card', 'name': 'Card', 'needs_confirmation': True},
            {'code': 'transfer', 'name': 'Bank Transfer', 'needs_confirmation': True}
        ]


class TaxService:
    @staticmethod
    def calculate_tax(subtotal: float, shop_id: int) -> float:
        tax = Tax.query.filter_by(shop_id=shop_id, is_active=True, is_deleted=False).first()
        if not tax:
            return 0.0
        return round(subtotal * tax.rate, 2)

    @staticmethod
    def get_rates(shop_id: int) -> List[Dict]:
        tax = Tax.query.filter_by(shop_id=shop_id, is_active=True, is_deleted=False).first()
        if not tax:
            return []
        return [{
            'name': tax.name,
            'rate': tax.rate,
            'inclusive': False,
            'description': tax.description,
            'kra_code': tax.kra_code
        }]

    @staticmethod
    @lru_cache(maxsize=32)
    def get_tax_rate(shop_id: int) -> float:
        tax = Tax.query.filter_by(shop_id=shop_id, is_active=True, is_deleted=False).first()
        return float(tax.rate if tax else 0.0)



