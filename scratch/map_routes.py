import os, sys
sys.path.insert(0, r'C:\D\Cooding\GENERAL\cpp\ERP')
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.urls import get_resolver
resolver = get_resolver()

def extract_routes(patterns, prefix=''):
    routes = []
    for p in patterns:
        if hasattr(p, 'url_patterns'):
            routes.extend(extract_routes(p.url_patterns, prefix + str(p.pattern)))
        else:
            cb = getattr(p, 'callback', None)
            if not cb: continue
            name = getattr(p, 'name', '') or ''
            routes.append((prefix + str(p.pattern), name, cb.__module__, cb.__name__))
    return routes

routes = extract_routes(resolver.url_patterns)
by_app = {}
for pattern, name, mod, func in routes:
    app = mod.split('.')[0]
    by_app.setdefault(app, []).append((pattern, name, func))

for app, app_routes in sorted(by_app.items()):
    print(f"\n=== App: {app} ({len(app_routes)} routes) ===")
    for pattern, name, func in app_routes:
        print(f"  {pattern:65} | {name:32} | {func}")
