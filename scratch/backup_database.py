import os
import sqlite3
import datetime
import sys

def backup_sqlite():
    db_path = "db.sqlite3"
    if not os.path.exists(db_path):
        print(f"Error: {db_path} does not exist!")
        sys.exit(1)
        
    os.makedirs("backups", exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"backups/db_backup_{timestamp}.sqlite3"
    
    print(f"Backing up {db_path} to {backup_path} using SQLite native backup API...")
    src_conn = sqlite3.connect(db_path)
    dst_conn = sqlite3.connect(backup_path)
    
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    
    # Verify backup
    if not os.path.exists(backup_path):
        print("Error: Backup file was not created!")
        sys.exit(1)
        
    backup_size = os.path.getsize(backup_path)
    if backup_size == 0:
        print("Error: Backup file is empty (0 bytes)!")
        sys.exit(1)
        
    # Verify integrity of backup
    verify_conn = sqlite3.connect(backup_path)
    cursor = verify_conn.cursor()
    cursor.execute("PRAGMA integrity_check;")
    result = cursor.fetchone()
    verify_conn.close()
    
    if result and result[0] == "ok":
        print(f"SUCCESS: Backup verified and recoverable. Size: {backup_size:,} bytes. Integrity: {result[0]}")
        print(f"Backup location: {os.path.abspath(backup_path)}")
        return backup_path
    else:
        print(f"Error: Backup integrity check failed: {result}")
        sys.exit(1)

if __name__ == "__main__":
    backup_sqlite()
