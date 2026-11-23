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
| `DJANGO_SECRET_KEY` | Insecure fallback key (dev only) | **Mandatory** random 50+ char secret (startup fails if default when `DEBUG=False`) | Cryptographic signing key. |
| `DEBUG` | `True` | `False` | Disables debug stack traces and enables secure cookies/HSTS. |
| `ALLOWED_HOSTS` | `*` (when `DEBUG=True`) | Comma-separated hostnames (e.g. `erp.weapharma.com`) | Host header validation. |
| `CSRF_TRUSTED_ORIGINS` | None | Comma-separated origins (e.g. `https://erp.weapharma.com`) | Trusted origins for CSRF over HTTPS. |
| `GOOGLE_MAPS_API_KEY` | None (falls back to Nominatim) | Valid Google Maps API key | Geocoding and map tile services (authenticated users only). |

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
python manage.py seed_activities

# 6. Collect static files
python manage.py collectstatic --noinput

# 7. Start development server
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

## 6. Backup, Recovery & SQLite Safety on PythonAnywhere

- **CRITICAL — Never overwrite a live SQLite database with `git pull`:**
  - `db.sqlite3` is a live binary database. Pulling a modified `db.sqlite3` from Git while PythonAnywhere WSGI workers are running can corrupt the database (`database disk image is malformed`) or overwrite production data.
  - Keep `DATABASES['default']['OPTIONS']['timeout'] = 20` and leave SQLite in its default `DELETE` journal mode (`synchronous = FULL`). **Do not enable `WAL` mode on PythonAnywhere's networked filesystem (NFS).**
  - Before any deployment or schema migration on PythonAnywhere:
    1. Create an online consistent backup outside the repository:
       ```bash
       sqlite3 /home/<user>/ERP/db.sqlite3 ".backup '/home/<user>/backups/db_backup_$(date +%Y%m%d_%H%M%S).sqlite3'"
       sqlite3 /home/<user>/backups/db_backup_<timestamp>.sqlite3 "PRAGMA integrity_check;"
       ```
    2. Never commit local `db.sqlite3` changes when pushing code updates. If untrack-ing `db.sqlite3` from Git in the future, always back up the production `db.sqlite3` outside the repo first, run `git pull`, restore the backup if Git removed the tracked file, run `python manage.py migrate`, and then reload the web app.
- **HTTPS CSRF Configuration:**
  - Always set `CSRF_TRUSTED_ORIGINS=https://<your-domain>` (e.g. `https://projecting.pythonanywhere.com`) in production `.env` / WSGI environment alongside `ALLOWED_HOSTS`.
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




## Cloudflare R2 Media Storage Configuration

Set the following environment variables to enable Cloudflare R2 (`master_data.storage.CloudflareR2Storage`). When any required key is omitted, `config/settings.py` falls back to local `FileSystemStorage` for development:

- `CLOUDFLARE_R2_ACCESS_KEY`
- `CLOUDFLARE_R2_SECRET_KEY`
- `CLOUDFLARE_R2_BUCKET_NAME`
- `CLOUDFLARE_R2_ENDPOINT_URL`
- `CLOUDFLARE_R2_CUSTOM_DOMAIN` (optional)
- `MEDIA_MAX_UPLOAD_SIZE_MB` (default `10`)

Management commands for storage operations:
- `python manage.py cleanup_r2_storage` — retries queued deletions in `PendingStorageDeletion`.
- `python manage.py migrate_media_to_r2` — migrates existing local media files (`ERPAttachment`, `CompanyProfile.logo`, `Product.thumbnail`, `User.avatar`) to R2.
