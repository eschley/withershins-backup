import os
import subprocess
import datetime
import glob
import json
import urllib.request
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOG = logging.getLogger("withershins-backup")

def send_discord_notification(webhook_url: str, title: str, description: str, color: int):
    if not webhook_url:
        return
    try:
        payload = {
            "embeds": [{
                "title": title,
                "description": description,
                "color": color
            }]
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            LOG.info("Discord notification sent.")
    except Exception as e:
        LOG.error(f"Failed to send Discord notification: {e}")

def run_backup():
    db_host = os.environ.get("DB_HOST", "withershins-db-cluster")
    db_port = os.environ.get("DB_PORT", "5432")
    db_user = os.environ.get("DB_USER", "postgres")
    db_name = os.environ.get("DB_NAME", "withershins")
    db_pass = os.environ.get("DB_PASSWORD", "")
    
    backup_dir = os.environ.get("BACKUP_DIR", "/backup")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    retention_days = int(os.environ.get("RETENTION_DAYS", "7"))

    if not db_pass:
        LOG.error("DB_PASSWORD environment variable is required.")
        sys.exit(1)

    os.environ["PGPASSWORD"] = db_pass

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"withershins_db_{timestamp}.sql.gz")

    LOG.info(f"Starting backup of database {db_name} at {db_host}:{db_port}")
    
    pg_dump_cmd = [
        "pg_dump",
        "-h", db_host,
        "-p", db_port,
        "-U", db_user,
        "-d", db_name,
        "-F", "c"  # Custom format (compressed by default, but we'll gzip it anyway or let pg_restore handle it. pg_dump -F c is already compressed)
    ]
    
    # Actually, pg_dump -F c produces a compressed binary format natively, no need to pipe to gzip.
    # We will output directly to the backup_file (without .gz, we'll use .dump)
    backup_file = os.path.join(backup_dir, f"withershins_db_{timestamp}.dump")
    
    try:
        with open(backup_file, "wb") as f:
            result = subprocess.run(pg_dump_cmd, stdout=f, stderr=subprocess.PIPE, check=True)
        LOG.info(f"Backup completed successfully: {backup_file}")
        
        file_size = os.path.getsize(backup_file)
        size_mb = file_size / (1024 * 1024)
        LOG.info(f"Backup size: {size_mb:.2f} MB")
        
        send_discord_notification(
            webhook_url=discord_webhook,
            title="Database Backup Success",
            description=f"Successfully backed up `{db_name}`.\nFile: `{os.path.basename(backup_file)}`\nSize: `{size_mb:.2f} MB`",
            color=0x00FF00 # Green
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode("utf-8") if e.stderr else str(e)
        LOG.error(f"Backup failed: {error_msg}")
        send_discord_notification(
            webhook_url=discord_webhook,
            title="Database Backup FAILED",
            description=f"Failed to backup `{db_name}`.\nError: ```\n{error_msg[:1000]}\n```",
            color=0xFF0000 # Red
        )
        sys.exit(1)
    except Exception as e:
        LOG.exception("Unexpected error during backup.")
        sys.exit(1)

    # Rotation logic
    LOG.info(f"Enforcing retention policy of {retention_days} days...")
    try:
        now = datetime.datetime.now().timestamp()
        pattern = os.path.join(backup_dir, "withershins_db_*.dump")
        files = glob.glob(pattern)
        
        deleted_count = 0
        for file in files:
            file_mtime = os.path.getmtime(file)
            age_days = (now - file_mtime) / (24 * 3600)
            if age_days > retention_days:
                LOG.info(f"Deleting old backup: {file} (Age: {age_days:.1f} days)")
                os.remove(file)
                deleted_count += 1
                
        LOG.info(f"Retention cleanup finished. Deleted {deleted_count} files.")
    except Exception as e:
        LOG.error(f"Failed to clean up old backups: {e}")

if __name__ == "__main__":
    run_backup()
