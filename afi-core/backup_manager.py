import asyncio
import datetime
import os
import subprocess

RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "onedrive:/AFI_Backups")
DB_HOST = os.getenv("DB_HOST", "afi_db")
DB_USER = os.getenv("DB_USER", "afi_user")
DB_NAME = os.getenv("DB_NAME", "afi_brain")
DB_PASS = os.getenv("DB_PASS") or os.getenv("POSTGRES_PASSWORD") or ""
BACKUP_DIR = os.getenv("BACKUP_DIR", "/app/backups")


async def run_backup():
    """Ejecuta pg_dump comprimido y sube a OneDrive vía rclone."""
    print("📦 Iniciando Backup...")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"afi_backup_{timestamp}.sql.gz"
    local_path = os.path.join(BACKUP_DIR, filename)

    dump_cmd = f"PGPASSWORD='{DB_PASS}' pg_dump -h {DB_HOST} -U {DB_USER} -d {DB_NAME} | gzip > {local_path}"
    upload_cmd = f"rclone copy {local_path} {RCLONE_REMOTE}"
    try:
        subprocess.run(dump_cmd, shell=True, check=True, executable="/bin/bash")
        print(f"✅ Dump generado en {local_path}")
        subprocess.run(upload_cmd, shell=True, check=True, executable="/bin/bash")
        print(f"☁️ Backup subido a {RCLONE_REMOTE}")
    except Exception as e:
        print(f"❌ Error crítico en Backup: {e}")
