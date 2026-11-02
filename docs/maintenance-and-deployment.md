# Maintenance and deployment

## Local setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_permissions
python manage.py setup_egypt_areas   # optional geography seed
python manage.py createsuperuser
python manage.py runserver
```

Login: `/auth/login/` (`LOGIN_URL`). After login: `/home/`.

Optional: `backfill_representative_resources`, `migrate_to_canonical_roles`, `seed_activities`, `import_excel_data`.

## Environment

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret. Required in production. Dev fallback is insecure. |
| `DJANGO_DEBUG` | `true`/`false`. Default true in this checkout if unset. |
| `GOOGLE_MAPS_API_KEY` | Geocoding; empty → Nominatim fallback |

Never commit real keys. `.env` is gitignored; there is no runtime dotenv loader unless you add one — set vars in the OS/service.

## Database

`DATABASES['default']` is SQLite `db.sqlite3`. Archived material mentions MySQL; **that is not wired in settings**. To use PostgreSQL/MySQL, change `DATABASES` and run migrations on that engine; re-test transfers and ledger totals.

```bash
python manage.py migrate
```

Back up `db.sqlite3` and `media/` before migrate in any shared environment. Rollback: restore backup; Django does not auto-reverse production migrations.

## Static and media

- Source assets: `static/` (currently JS).
- `STATIC_ROOT` = `staticfiles/` for `collectstatic`.
- Uploads: `MEDIA_ROOT` / `MEDIA_URL`. `config/urls.py` serves media in this project (including a redundant `re_path`); **do not** serve media that way behind a public production proxy without access control.

Tailwind and fonts load from CDNs in `base.html` (needs outbound HTTPS).

## Tests and lint

```bash
python manage.py test
python manage.py check
```

No project linter config (ruff/flake8) is checked in. Test labels: see [`testing-strategy.md`](testing-strategy.md).

## Production notes

This tree is **development-oriented** (`DEBUG` default, `ALLOWED_HOSTS = ['*']`, SQLite). A production rollout should at least:

1. Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, explicit `ALLOWED_HOSTS`.
2. Use a managed database and backups.
3. Serve static via `collectstatic` + web server; restrict media.
4. HTTPS, secure cookies (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`) — **not currently set**.
5. Do not expose `/admin/` without SuperAdmin discipline.

## Background work

No Celery. Management commands are manual. `settings/sync-data/` trigger currently updates timestamps only.

## Logging and monitoring

Python `logging` on `AuditLogService` failures. No APM config in-repo.

## Known environment differences

- UI language Arabic; Windows/PowerShell is fine; keep UTF-8.
- Google quota vs Nominatim rate limits on geocoding.
- Playwright scripts under `scratch/` need a browser install; they are optional.
