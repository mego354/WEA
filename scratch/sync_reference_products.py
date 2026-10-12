import django
import os
from decimal import Decimal

import sys
sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from catalog.models import Product, ProductCategory
from django.contrib.auth import get_user_model

User = get_user_model()
admin_user = User.objects.filter(is_superuser=True).first()

# 1. Categories
cat_wea, _ = ProductCategory.objects.get_or_create(
    code='WEA',
    defaults={'name': 'WEA', 'description': 'WEA products without specific categorization'}
)
cat_pack, _ = ProductCategory.objects.get_or_create(
    code='PACK',
    defaults={'name': 'Packing materials', 'description': 'Packing materials for production'}
)

PRODUCTS = [
    {"code": "GE1", "name": "Geron", "cat": cat_wea, "price": Decimal("140.00"), "sellable": True, "barcode": ""},
    {"code": "LE1", "name": "Legatonexx Spray", "cat": cat_wea, "price": Decimal("120.00"), "sellable": True, "barcode": ""},
    {"code": "PU1", "name": "Putalaxy gel", "cat": cat_wea, "price": Decimal("75.00"), "sellable": True, "barcode": ""},
    {"code": "SO1", "name": "Soriana V.D", "cat": cat_wea, "price": Decimal("75.00"), "sellable": True, "barcode": ""},
    {"code": "ST1", "name": "Steps", "cat": cat_wea, "price": Decimal("140.00"), "sellable": True, "barcode": ""},
    {"code": "UL1", "name": "Ultrahumudin Cream", "cat": cat_wea, "price": Decimal("105.00"), "sellable": True, "barcode": ""},
    {"code": "7000", "name": "تيوب الالترا هيوميدين", "cat": cat_pack, "price": Decimal("0.00"), "sellable": False, "barcode": ""},
    {"code": "4000", "name": "كرتون الترا هيوميدين", "cat": cat_pack, "price": Decimal("0.00"), "sellable": False, "barcode": ""},
    {"code": "3000", "name": "كرتون بيوتالاكسي", "cat": cat_pack, "price": Decimal("0.00"), "sellable": False, "barcode": ""},
    {"code": "6000", "name": "كرتون جيرون", "cat": cat_pack, "price": Decimal("0.00"), "sellable": False, "barcode": ""},
    {"code": "5000", "name": "كرتون ستيبس", "cat": cat_pack, "price": Decimal("0.00"), "sellable": False, "barcode": ""},
    {"code": "1000", "name": "كرتون سوريانا", "cat": cat_pack, "price": Decimal("0.00"), "sellable": False, "barcode": "1000"},
    {"code": "2000", "name": "كرتون ليجاتونيكس", "cat": cat_pack, "price": Decimal("0.00"), "sellable": False, "barcode": ""},
]

for p in PRODUCTS:
    prod, created = Product.objects.get_or_create(
        sku_code=p["code"],
        defaults={
            "name": p["name"],
            "category": p["cat"],
            "retail_price": p["price"],
            "tax_percentage": Decimal("0.00"),
            "sellable": p["sellable"],
            "barcode": p["barcode"],
            "created_by": admin_user,
        }
    )
    if not created:
        prod.name = p["name"]
        prod.category = p["cat"]
        prod.retail_price = p["price"]
        prod.sellable = p["sellable"]
        prod.barcode = p["barcode"]
        prod.save()

print(f"Total products in DB now: {Product.objects.count()}")
