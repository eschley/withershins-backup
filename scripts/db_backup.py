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


def replicate_to_nas(backup_file: str) -> bool:
    """
    Replicates a backup file to secondary NAS storage (e.g. Synology DS410j)
    using rsync over SSH. Enforces remote retention policy.
    """
    nas_host = os.environ.get("NAS_HOST")
    if not nas_host:
        LOG.info("NAS_HOST not set. Skipping secondary offsite replication.")
        return False

    nas_user = os.environ.get("NAS_USER", "eschley")
    nas_path = os.environ.get("NAS_PATH", "/volume1/backups/withershins-db")
    nas_retention_days = int(os.environ.get("NAS_RETENTION_DAYS", "30"))
    ssh_key = os.environ.get("SSH_KEY_PATH", "/root/.ssh/id_rsa")

    ssh_cmd = (
        f"ssh -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa "
        f"-o HostKeyAlgorithms=+ssh-rsa -i {ssh_key}"
    )

    remote_dest = f"{nas_user}@{nas_host}:{nas_path}/"
    LOG.info(f"Replicating backup {os.path.basename(backup_file)} to NAS ({remote_dest})...")

    rsync_cmd = [
        "rsync",
        "-avz",
        "--timeout=300",
        "-e", ssh_cmd,
        backup_file,
        remote_dest,
    ]

    try:
        res = subprocess.run(rsync_cmd, capture_output=True, text=True, check=True)
        LOG.info("NAS replication completed successfully.")

        # Remote rotation logic
        cleanup_script = (
            f"find {nas_path} -name 'withershins_db_*.dump' -mtime +{nas_retention_days} -delete"
        )
        ssh_cleanup_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "PubkeyAcceptedKeyTypes=+ssh-rsa",
            "-o", "HostKeyAlgorithms=+ssh-rsa",
            "-i", ssh_key,
            f"{nas_user}@{nas_host}",
            cleanup_script,
        ]
        subprocess.run(ssh_cleanup_cmd, capture_output=True, text=True, check=False)
        LOG.info(f"Enforced {nas_retention_days}-day retention on NAS.")
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr or e.stdout or str(e)
        LOG.error(f"NAS replication failed: {err}")
        return False
    except Exception as e:
        LOG.error(f"Unexpected error during NAS replication: {e}")
        return False


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
    backup_schema = os.environ.get("DB_SCHEMA", "stock_data")

    pg_dump_cmd = [
        "pg_dump",
        "-h", db_host,
        "-p", db_port,
        "-U", db_user,
        "-d", db_name,
        "-F", "c",
    ]
    if backup_schema and backup_schema.lower() != "all":
        pg_dump_cmd.extend(["-n", backup_schema])

    backup_file = os.path.join(backup_dir, f"withershins_db_{timestamp}.dump")
    LOG.info(f"Starting backup of database {db_name} at {db_host}:{db_port}")

    try:
        with open(backup_file, "wb") as f:
            subprocess.run(pg_dump_cmd, stdout=f, stderr=subprocess.PIPE, check=True)
        LOG.info(f"Backup completed successfully: {backup_file}")

        file_size = os.path.getsize(backup_file)
        size_mb = file_size / (1024 * 1024)
        LOG.info(f"Backup size: {size_mb:.2f} MB")

        # Offsite secondary storage replication
        nas_replicated = replicate_to_nas(backup_file)
        nas_status_msg = (
            "✅ Replicated to Mimir NAS (`/volume1/backups/withershins-db`)"
            if nas_replicated
            else "⚠️ NAS replication skipped or pending"
        )

        send_discord_notification(
            webhook_url=discord_webhook,
            title="Database Backup Success",
            description=(
                f"Successfully backed up `{db_name}`.\n"
                f"File: `{os.path.basename(backup_file)}`\n"
                f"Size: `{size_mb:.2f} MB`\n"
                f"Secondary Storage: {nas_status_msg}"
            ),
            color=0x00FF00,
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode("utf-8") if e.stderr else str(e)
        LOG.error(f"Backup failed: {error_msg}")
        send_discord_notification(
            webhook_url=discord_webhook,
            title="Database Backup FAILED",
            description=f"Failed to backup `{db_name}`.\nError: ```\n{error_msg[:1000]}\n```",
            color=0xFF0000,
        )
        sys.exit(1)
    except Exception as e:
        LOG.exception("Unexpected error during backup.")
        sys.exit(1)

    # Rotation logic
    LOG.info(f"Enforcing retention policy of {retention_days} days on local storage...")
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

        LOG.info(f"Local retention cleanup finished. Deleted {deleted_count} files.")
    except Exception as e:
        LOG.error(f"Failed to clean up old backups: {e}")


if __name__ == "__main__":
    run_backup()
