# Database Schema Migrations & Historical Data Preservation

**Project:** WEA Pharma ERP  
**Module:** Activities Subsystem (`activities`)  
**Specification:** Migration 0012, Data Preservation & Rollback Procedures  

---

## 1. Pre-Migration Verification & Database Backup

Before applying any schema modifications, a full snapshot of the development SQLite database was created:

- **Backup Path:** `backups/db_backup_pre_visit_standardization_20261027.sqlite3`
- **Integrity Check:**
  - `VisitTemplate` records prior to migration: **6 templates**
  - `Visit` records prior to migration: **19 visits**
  - Questionnaire answers, timestamps, and GPS coordinates: **100% verified intact**

---

## 2. Schema Changes & Migration 0012

### Migration File
`activities/migrations/0012_remove_obsolete_visittemplate_settings.py`

### Operations Executed
1. `RemoveField(model_name='visittemplate', name='mode')`: Removed obsolete check-in/out mode setting.
2. `RemoveField(model_name='visittemplate', name='visit_outcome_mode')`: Removed obsolete configurable outcome setting.
3. `RemoveField(model_name='visittemplate', name='auto_approve_unplanned')`: Removed automatic unplanned approval toggle.
4. `RemoveField(model_name='visittemplate', name='auto_end_visit')`: Removed automatic end-visit toggle.

### Migration Status
```bash
python manage.py showmigrations activities
 [X] 0001_initial
 ...
 [X] 0011_visittemplate_suggested_products_and_more
 [X] 0012_remove_obsolete_visittemplate_settings
```

---

## 3. Historical Data Preservation

- **Visit Records (`activities.Visit`):**
  - Historical visit answers (`questionnaire_answers`), duration (`duration`), check-in (`started_at`), and check-out (`ended_at`) timestamps were **not modified or truncated**.
  - Historical visit outcomes stored on `visit.visit_outcome` and `visit.is_successful` were preserved for reporting, analytics, and performance KPIs.
  - GPS verification coordinates (`latitude`, `longitude`, `customer_latitude_snapshot`, `distance`) and location photos remain fully accessible.
- **Audit Logs (`ApprovalAuditLog`):**
  - All existing status changes, approval timestamps, actor IDs, and IP addresses remain intact.

---

## 4. Rollback & Disaster Recovery Procedures

In the unlikely event a rollback is required:

1. **Reverting Migration:**
   ```bash
   python manage.py migrate activities 0011_visittemplate_suggested_products_and_more
   ```
2. **Restoring from SQLite Backup:**
   If database restoration is required:
   ```bash
   # Stop server
   cp backups/db_backup_pre_visit_standardization_20261027.sqlite3 db.sqlite3
   # Restart server
   ```
