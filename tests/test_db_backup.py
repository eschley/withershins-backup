import os
import sys
import unittest
from unittest.mock import patch, MagicMock, mock_open
import subprocess

# Add scripts directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))
import db_backup
import verify_backup


class TestDbBackup(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_send_discord_notification_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_urlopen.return_value.__enter__.return_value = mock_response
        db_backup.send_discord_notification(
            "http://webhook.local", "Test Title", "Test Desc", 0x00FF00
        )
        mock_urlopen.assert_called_once()

    def test_send_discord_notification_empty_url(self):
        # Should cleanly no-op
        db_backup.send_discord_notification("", "Title", "Desc", 0x00FF00)

    @patch("urllib.request.urlopen", side_effect=Exception("Network error"))
    def test_send_discord_notification_exception_handled(self, mock_urlopen):
        db_backup.send_discord_notification("http://fail.local", "Title", "Desc", 0xFF0000)

    @patch.dict(os.environ, {}, clear=True)
    def test_replicate_to_nas_no_host(self):
        res = db_backup.replicate_to_nas("/backup/test.dump")
        self.assertFalse(res)

    @patch.dict(os.environ, {
        "NAS_HOST": "192.168.1.100",
        "NAS_USER": "eschley",
        "NAS_PATH": "/volume1/backups",
        "NAS_RETENTION_DAYS": "30",
        "SSH_KEY_PATH": "/root/.ssh/id_rsa"
    })
    @patch("subprocess.run")
    def test_replicate_to_nas_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        res = db_backup.replicate_to_nas("/backup/test.dump")
        self.assertTrue(res)
        self.assertEqual(mock_run.call_count, 2)  # 1 for rsync, 1 for remote retention find

    @patch.dict(os.environ, {
        "NAS_HOST": "192.168.1.100",
        "NAS_USER": "eschley",
        "NAS_PATH": "/volume1/backups"
    })
    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["rsync"], stderr=b"Connection refused"))
    def test_replicate_to_nas_failure(self, mock_run):
        res = db_backup.replicate_to_nas("/backup/test.dump")
        self.assertFalse(res)

    @patch.dict(os.environ, {
        "DB_PASSWORD": "secret_password",
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "delirium",
        "DB_SCHEMA": "stock_data",
        "BACKUP_DIR": "/tmp/test_backup",
        "RETENTION_DAYS": "7"
    })
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.getsize", return_value=1024 * 1024 * 10)
    @patch("glob.glob", return_value=[])
    @patch("subprocess.run")
    @patch("db_backup.send_discord_notification")
    def test_run_backup_success(self, mock_discord, mock_subproc, mock_glob, mock_getsize, mock_file):
        mock_subproc.return_value = MagicMock(returncode=0)
        db_backup.run_backup()
        mock_subproc.assert_called_once()
        mock_discord.assert_called_once()
        self.assertIn("Database Backup Success", mock_discord.call_args[1]["title"])


class TestVerifyBackup(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_send_discord_notification_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_urlopen.return_value.__enter__.return_value = mock_response
        verify_backup.send_discord_notification("http://webhook.local", "Title", "Desc", 0x00FF00)
        mock_urlopen.assert_called_once()

    @patch.dict(os.environ, {"BACKUP_DIR": "/tmp/test_backup"})
    @patch("glob.glob", return_value=[])
    def test_verify_latest_backup_no_files(self, mock_glob):
        res = verify_backup.verify_latest_backup()
        self.assertFalse(res)

    @patch.dict(os.environ, {"BACKUP_DIR": "/tmp/test_backup"})
    @patch("glob.glob", return_value=["/tmp/test_backup/withershins_db_20260904_070003.dump"])
    @patch("os.path.getmtime", return_value=12345)
    @patch("os.path.getsize", return_value=1024 * 1024 * 100)
    @patch("subprocess.run")
    @patch("verify_backup.send_discord_notification")
    def test_verify_latest_backup_success(self, mock_discord, mock_subproc, mock_getsize, mock_getmtime, mock_glob):
        mock_subproc.return_value = MagicMock(
            returncode=0,
            stdout=(
                ";\n"
                "; Archive created\n"
                "1; TABLE stock_data daily_history_v2 alpha_user\n"
                "2; TABLE stock_data master_indicator_history alpha_user\n"
                "3; TABLE stock_data correlations alpha_user\n"
                "4; TABLE stock_data market_topology alpha_user\n"
                "5; TABLE stock_data alembic_version alpha_user\n"
            )
        )
        res = verify_backup.verify_latest_backup()
        self.assertTrue(res)
        mock_discord.assert_called_once()
        self.assertIn("PASSED", mock_discord.call_args[1]["title"])

    @patch.dict(os.environ, {"BACKUP_DIR": "/tmp/test_backup"})
    @patch("glob.glob", return_value=["/tmp/test_backup/withershins_db_20260904_070003.dump"])
    @patch("os.path.getmtime", return_value=12345)
    @patch("os.path.getsize", return_value=1024 * 1024 * 100)
    @patch("subprocess.run")
    @patch("verify_backup.send_discord_notification")
    def test_verify_latest_backup_missing_tables(self, mock_discord, mock_subproc, mock_getsize, mock_getmtime, mock_glob):
        mock_subproc.return_value = MagicMock(
            returncode=0,
            stdout=(
                "1; TABLE stock_data some_other_table alpha_user\n"
            )
        )
        res = verify_backup.verify_latest_backup()
        self.assertFalse(res)
        mock_discord.assert_called_once()
        self.assertIn("FAILED", mock_discord.call_args[1]["title"])


if __name__ == "__main__":
    unittest.main()
