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

---

## 7. Enterprise Data Migration (`execute_wea_migration`)

The repository includes an authoritative enterprise migration engine in `master_data/management/commands/execute_wea_migration.py`.

### Migration Overview & Safe Execution

The engine migrates 12 source Excel workbooks from `data_folder/` into the ERP database while strictly preserving protected system configuration and framework records:
- **Protected Records**: `VisitTemplate` (7 templates, 21 questions), `Role` (all canonical roles), `CompanyProfile`, `LocationSettings`, `SalesSettings`, `PurchaseSettings`, and Django Superusers (`wea.pharm2020@gmail.com`).
- **User Passwords**: All imported operational users receive the password `Wea@1111`.
- **System Archive Account**: `historical_archive@wea.com` (`is_active=False`) resolves transactions created by former representatives not present in `users.xlsx`.

### Command Usage

```bash
# 1. Validation & Dry-Run Simulation (No database modification)
python manage.py execute_wea_migration --phase=all --dry-run

# 2. Complete Enterprise Migration Execution
python manage.py execute_wea_migration --phase=all

# 3. Targeted Phase Execution (e.g. Phase 15 quantitative verification only)
python manage.py execute_wea_migration --phase=15
```

### Supported Migration Phases

| Phase | Description | Output & Core Integrity Verification |
|---|---|---|
| **0** | Safe Operational Cleanup | Bottom-up purge of legacy demo records; preserves all templates, roles, superusers. |
| **1** | Areas & Bricks Import | Synchronizes governorates and child bricks; reconciles missing bricks. |
| **2** | Roles & Users Import | Reconciles roles, creates `direct_sales_rep` and `historical_archive@wea.com`, imports 18 users with `Wea@1111` password. |
| **3** | Warehouses & Vaults | Provisions 10 corporate warehouses, 13 representative custody warehouses, and 14 cash treasuries. |
| **4 & 5** | Categories & Products | Upserts 2 product categories (`WEA`, `Packing materials`) and 11 catalog products (6 pharma, 5 packaging). |
| **6** | Inventory Balances & Lots | Provisions opening inventory memo, 194 stock lots, and establishes 143,076.00 on-hand units. |
| **7** | CRM Contacts & Addresses | Imports 8,963 contacts (8,962 from source + synthesized missing customer `شيماء البقشيشى`) and 8,706 addresses. |
| **8 & 9** | Financial Accounts | Imports 1,094 unique customer accounts (506,108.99 EGP balance) and 8 vendor accounts (192,388.52 EGP liabilities). |
| **10 & 11** | Sales Orders & Returns | Imports 7,276 sales order headers (9,470,852.35 EGP), 286 sales return orders (228,959.14 EGP), and 463 return items. |
| **12** | Purchase Orders & Returns | Imports 17 purchase orders (659,454.52 EGP) and 1 purchase return order (10,000.00 EGP). |
| **13** | Collections & Payments | Imports 6,856 collection receipts (8,515,866.91 EGP) and 31 vendor disbursements (402,338.00 EGP). |
| **14** | Vendor Ledger Journal | Imports 62 vendor financial ledger entries with sequential audit tracking. |
| **15** | Quantitative Verification | Executes 5 core quantitative assertions verifying exact counts, balances, and territorial coverage. |


