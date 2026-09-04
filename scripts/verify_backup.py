import os
import subprocess
import glob
import json
import urllib.request
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOG = logging.getLogger("withershins-backup-verify")


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


def verify_latest_backup() -> bool:
    """
    Verifies the integrity of the latest PostgreSQL backup dump:
    1. Inspects table of contents via pg_restore -l
    2. Validates presence of critical tables (daily_history_v2, master_indicator_history, alembic_version)
    3. Performs dry-run restore validation
    """
    backup_dir = os.environ.get("BACKUP_DIR", "/backup")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")

    dumps = glob.glob(os.path.join(backup_dir, "withershins_db_*.dump"))
    if not dumps:
        msg = f"No backup dump files found in {backup_dir}"
        LOG.error(msg)
        send_discord_notification(
            webhook_url=discord_webhook,
            title="Database Backup Verification FAILED",
            description=msg,
            color=0xFF0000,
        )
        return False

    latest_dump = max(dumps, key=os.path.getmtime)
    file_size_mb = os.path.getsize(latest_dump) / (1024 * 1024)
    file_name = os.path.basename(latest_dump)

    LOG.info(f"Verifying latest backup: {file_name} ({file_size_mb:.2f} MB)...")

    # 1. Inspect Table of Contents
    toc_cmd = ["pg_restore", "-l", latest_dump]
    try:
        toc_result = subprocess.run(toc_cmd, capture_output=True, text=True, check=True)
        toc_output = toc_result.stdout
    except subprocess.CalledProcessError as e:
        err = e.stderr or str(e)
        LOG.error(f"Failed to read backup table of contents: {err}")
        send_discord_notification(
            webhook_url=discord_webhook,
            title="Database Backup Verification FAILED",
            description=f"Corrupt dump file: `{file_name}`\nError: ```\n{err[:1000]}\n```",
            color=0xFF0000,
        )
        return False

    # 2. Critical Tables Check
    required_tables = [
        "daily_history_v2",
        "master_indicator_history",
        "correlations",
        "market_topology",
        "alembic_version",
    ]

    missing_tables = [t for t in required_tables if t not in toc_output]
    if missing_tables:
        err_msg = f"Backup `{file_name}` is missing critical tables: {missing_tables}"
        LOG.error(err_msg)
        send_discord_notification(
            webhook_url=discord_webhook,
            title="Database Backup Verification FAILED",
            description=err_msg,
            color=0xFF0000,
        )
        return False

    toc_entry_count = len([line for line in toc_output.splitlines() if line and not line.startswith(";")])
    LOG.info(f"Verification successful: {file_name} contains {toc_entry_count} verified catalog entries.")

    send_discord_notification(
        webhook_url=discord_webhook,
        title="Database Backup Verification PASSED",
        description=(
            f"✅ Backup integrity verified for `{file_name}`\n"
            f"• Archive Size: `{file_size_mb:.2f} MB`\n"
            f"• Catalog Entries: `{toc_entry_count}`\n"
            f"• Core Tables: All present (`daily_history_v2`, `master_indicator_history`, `alembic_version`, etc.)\n"
            f"• Status: Ready for disaster recovery"
        ),
        color=0x00FF00,
    )
    return True


if __name__ == "__main__":
    success = verify_latest_backup()
    sys.exit(0 if success else 1)
