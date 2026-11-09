# Deployment & Maintenance Guide

This document provides instructions for deploying, configuring, and maintaining WEA Pharma ERP in local development and production hosting environments.

---

## 1. System Requirements

- **Python**: 3.12 or higher.
- **Operating System**: Windows / Linux / macOS.
- **Database**: SQLite (local development and small team hosting) or PostgreSQL (high concurrency production).
- **Web Server**: Gunicorn / uWSGI behind Nginx, or PythonAnywhere WSGI container.

---

## 2. Environment Configuration

The application reads configuration from environment variables with safe development defaults:

| Variable | Development Default | Production Requirement | Description |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | Insecure fallback key | **Mandatory** random 50+ char secret | Cryptographic signing key. |
| `DEBUG` | `True` | `False` | Disables debug stack traces in production. |
| `ALLOWED_HOSTS` | `*` | Specific hostnames (e.g. `erp.weapharma.com`) | Host header validation. |
| `GOOGLE_MAPS_API_KEY` | None (falls back to Nominatim) | Valid Google Maps API key | Geocoding and map tile services. |

---

## 3. Fresh Installation & Setup

```bash
# 1. Clone repository
git clone <repository_url>
cd ERP

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run database migrations
python manage.py migrate

# 5. Initialize roles, permissions, and territorial areas
python manage.py setup_permissions
python manage.py migrate_to_canonical_roles
python manage.py setup_egypt_areas

# 6. Seed initial demonstration data (optional)
python seed_initial_data.py
python seed_test_users.py

# 7. Collect static files
python manage.py collectstatic --noinput

# 8. Start development server
python manage.py runserver 0.0.0.0:8000
```

---

## 4. PythonAnywhere & Linux VPS Deployment

### WSGI Configuration (`/var/www/..._wsgi.py` or WSGI handler)
```python
import os
import sys

path = '/home/username/ERP'
if path not in sys.path:
    sys.path.append(path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['DEBUG'] = 'False'
os.environ['DJANGO_SECRET_KEY'] = 'your-secure-production-secret-key'
os.environ['ALLOWED_HOSTS'] = 'username.pythonanywhere.com'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

### Static & Media File Mapping
Configure web server static routing:
- **URL**: `/static/` ➔ **Directory**: `/home/username/ERP/staticfiles/`
- **URL**: `/media/` ➔ **Directory**: `/home/username/ERP/media/`

---

## 5. Security Hardening Checklist

When deploying to public production:
- [ ] Set `DEBUG = False`.
- [ ] Configure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
- [ ] Enable HTTPS with SSL/TLS certificate.
- [ ] Set `SECURE_SSL_REDIRECT = True`.
- [ ] Set `SESSION_COOKIE_SECURE = True` and `CSRF_COOKIE_SECURE = True`.
- [ ] Verify file permissions on SQLite database (`chmod 600 db.sqlite3`) and media folder (`chmod 755 media`).
- [ ] Ensure `SecurityAuditLog` is active and monitored.

---

## 6. Backup & Recovery

- **SQLite Database Backup**:
  ```bash
  sqlite3 db.sqlite3 ".backup 'backups/db_backup_$(date +%Y%m%d_%H%M%S).sqlite3'"
  ```
- **Media Assets Backup**:
  Archive the `media/` folder containing user-uploaded attachments and visit photo evidence.

