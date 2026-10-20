import os
import sys
import json
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

with open('scratch/views_inventory.json', 'r', encoding='utf-8') as f:
    views = json.load(f)

print("=== CURRENTLY PAGINATED VIEWS ===")
for k, v in views.items():
    if v['has_paginator']:
        print(f"{k:<45} | select_related: {v['has_select_related']} | prefetch: {v['has_prefetch_related']}")

print("\n=== TEMPLATES USED BY LIST VIEWS ===")
for k, v in views.items():
    if v['has_paginator'] or ('list' in v['view_name']):
        print(f"{k:<45} -> {v['templates']}")
