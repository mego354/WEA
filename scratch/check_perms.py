import os, sys
sys.path.insert(0, r'C:\D\Cooding\GENERAL\cpp\ERP')
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import Permission
from accounts.models import Role, User

print(f"Total permissions in auth_permission: {Permission.objects.count()}")
print("Permissions per app:")
from django.db.models import Count
for row in Permission.objects.values('content_type__app_label').annotate(cnt=Count('id')).order_by('content_type__app_label'):
    print(f"  {row['content_type__app_label']}: {row['cnt']}")

print(f"\nTotal Roles in DB: {Role.objects.count()}")
for r in Role.objects.all():
    print(f"  Role ID={r.id}, name={r.name}, display_name={r.display_name}, users={r.users.count()}, perms={r.permissions.count()}")

print(f"\nTotal Users in DB: {User.objects.count()}")
for u in User.objects.all():
    print(f"  User ID={u.id}, username={u.username}, role={u.role}, is_superuser={u.is_superuser}")
