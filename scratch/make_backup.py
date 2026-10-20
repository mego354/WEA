import sqlite3
import os
import shutil
import datetime

os.makedirs('backups', exist_ok=True)
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = f"backups/db_pre_replacement_{timestamp}.sqlite3"

src_conn = sqlite3.connect('db.sqlite3')
dst_conn = sqlite3.connect(backup_path)
src_conn.backup(dst_conn)
dst_conn.close()
src_conn.close()

verify_conn = sqlite3.connect(backup_path)
cur = verify_conn.cursor()
cur.execute("PRAGMA integrity_check;")
res = cur.fetchone()
verify_conn.close()

size = os.path.getsize(backup_path)
print(f"Verified Backup Created: {backup_path}")
print(f"Size: {size:,} bytes")
print(f"Integrity check: {res}")
