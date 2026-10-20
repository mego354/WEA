import os, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.apps import apps

for app_config in apps.get_app_configs():
    if not app_config.name.startswith('django.'):
        print(f"\nApp: {app_config.name}")
        for model in app_config.get_models():
            field_names = [f.name for f in model._meta.get_fields()]
            print(f"  Model: {model.__name__} (Table: {model._meta.db_table}, Records: {model.objects.count()})")
            print(f"    Fields: {field_names[:15]} ... (total {len(field_names)})")
