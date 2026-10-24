import os, sys
sys.path.insert(0, r'C:\D\Cooding\GENERAL\cpp\ERP')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
import scratch.audit as a

for app, data in sorted(a.by_app.items()):
    t = data['total']
    p = data['perm']
    l = data['login_only']
    o = data['open']
    print(f"{app:15} | Total: {t:3d} | Perm: {p:3d} | LoginOnly: {l:3d} | Open: {o:3d}")
