import os
import sys
import django
import inspect

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, r'C:\D\Cooding\GENERAL\new\ERP')
django.setup()

from django.urls import get_resolver
from accounts.models import User, Role, RoleTag
from django.contrib.auth.models import Permission

resolver = get_resolver()

by_app = {}
routes_list = []

def analyze(patterns, prefix=''):
    for p in patterns:
        if hasattr(p, 'url_patterns'):
            analyze(p.url_patterns, prefix + str(p.pattern))
        else:
            cb = getattr(p, 'callback', None)
            name = getattr(p, 'name', '')
            full_pattern = prefix + str(p.pattern)
            if not cb:
                continue
            module = cb.__module__
            app = module.split('.')[0]
            
            src = ''
            try:
                fn = cb
                while hasattr(fn, '__wrapped__'):
                    fn = fn.__wrapped__
                src = inspect.getsource(fn)
            except Exception:
                pass
            
            has_login = '@login_required' in src or 'LoginRequiredMixin' in src
            has_perm = '@require_permission' in src or 'RequirePermissionMixin' in src
            
            if app not in by_app:
                by_app[app] = {'total': 0, 'perm': 0, 'login_only': 0, 'open': 0}
            
            by_app[app]['total'] += 1
            if has_perm:
                by_app[app]['perm'] += 1
                status = 'PERM_PROTECTED'
            elif has_login:
                by_app[app]['login_only'] += 1
                status = 'LOGIN_ONLY'
            else:
                by_app[app]['open'] += 1
                status = 'OPEN'
            
            routes_list.append({
                'app': app,
                'pattern': full_pattern,
                'name': name,
                'view': f"{module}.{cb.__name__}",
                'status': status,
            })

analyze(resolver.url_patterns)

print("=== APP PERMISSION SUMMARY ===")
for app, data in sorted(by_app.items()):
    print(f"{app:15} | Total: {data['total']:3d} | PermProtected: {data['perm']:3d} | LoginOnly: {data['login_only']:3d} | Open: {data['open']:3d}")

print(f"\nTotal routes: {len(routes_list)}")

print("\n=== OPEN (UNAUTHENTICATED) ROUTES ===")
for r in routes_list:
    if r['status'] == 'OPEN':
        print(f"[{r['app']}] {r['pattern']} -> {r['view']} ({r['name']})")

print("\n=== LOGIN-ONLY (NO PERMISSION CHECK) ROUTES ===")
for r in routes_list:
    if r['status'] == 'LOGIN_ONLY':
        print(f"[{r['app']}] {r['pattern']} -> {r['view']} ({r['name']})")
