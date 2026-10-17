import os
import django
import time
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.db import connection
from accounts.models import User
from contacts.models import Contact
from activities.models import Visit, PlannedVisitDay, PlannedVisitItem, Agreement

def audit_views_performance():
    print("=" * 70)
    print("PERFORMANCE & QUERY COUNT AUDIT (MEASURED DATA)")
    print("=" * 70)

    client = Client()
    superadmin = User.objects.filter(is_superuser=True).first()
    client.force_login(superadmin)

    endpoints = [
        ("Dashboard", "/home/"),
        ("Visits List", "/visits/"),
        ("Visit Create Form", "/visits/create/"),
        ("Planned Visits List", "/planned-visits/"),
        ("Agreements List", "/agreements/"),
        ("Contacts List", "/contacts/"),
        ("Customer Search API (Empty query)", "/contacts/api/search/?q="),
        ("Customer Search API (Specific term)", "/contacts/api/search/?q=%D8%A3%D9%85%D9%84"),
        ("Visit Templates API", "/activities/api/templates/"),
        ("Catalog List", "/catalog/"),
        ("Purchases List", "/purchases/"),
        ("Sales List", "/sales/"),
        ("Treasury Payments", "/treasury/payments/"),
        ("Location Settings", "/settings/location/"),
    ]

    results = []

    for name, url in endpoints:
        # Measure query count
        with CaptureQueriesContext(connection) as queries:
            start_time = time.perf_counter()
            response = client.get(url)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        query_count = len(queries)
        status_code = response.status_code
        payload_size_kb = len(response.content) / 1024.0

        results.append({
            "name": name,
            "url": url,
            "status": status_code,
            "queries": query_count,
            "elapsed_ms": round(elapsed_ms, 2),
            "payload_kb": round(payload_size_kb, 2)
        })

        print(f"[{status_code}] {name:<35} | {query_count:>2} queries | {elapsed_ms:>6.2f} ms | {payload_size_kb:>6.2f} KB")

    print("\nDetailed Query Analysis for Key Endpoints:")
    for ep in ["/visits/", "/planned-visits/", "/contacts/api/search/?q="]:
        with CaptureQueriesContext(connection) as queries:
            client.get(ep)
        print(f"\n--- Queries for {ep} ({len(queries)} queries) ---")
        for i, q in enumerate(queries.captured_queries, 1):
            sql = q['sql'].strip().replace('"', '')
            sql_preview = (sql[:120] + '...') if len(sql) > 120 else sql
            print(f"  {i}. [{q['time']}s] {sql_preview}")

if __name__ == "__main__":
    audit_views_performance()
