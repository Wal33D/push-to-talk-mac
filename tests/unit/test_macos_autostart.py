import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.platform.macos.autostart import MacOSAutoStartManager


class MacOSAutoStartManagerTests(unittest.TestCase):
    def test_status_is_unavailable_when_script_missing(self):
        manager = MacOSAutoStartManager(script_path="/tmp/does-not-exist-autostart-sh")
        with self.assertLogs("dictator", level="WARNING") as logs:
            status = manager.status()
        self.assertEqual(status, "unavailable")
        self.assertTrue(any("autostart script not found" in line for line in logs.output))

    @patch("app.platform.macos.autostart.subprocess.run")
    def test_status_parses_enabled(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Autostart is enabled\n",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "autostart.sh"
            script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            manager = MacOSAutoStartManager(script_path=script)
            self.assertEqual(manager.status(), "enabled")

    @patch("app.platform.macos.autostart.subprocess.run")
    def test_status_parses_installed(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Autostart is installed but not running\n",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "autostart.sh"
            script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            manager = MacOSAutoStartManager(script_path=script)
            self.assertEqual(manager.status(), "installed")

    @patch("app.platform.macos.autostart.subprocess.run")
    def test_enable_invokes_script_with_enable_action(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "autostart.sh"
            script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            manager = MacOSAutoStartManager(script_path=script)
            manager.enable()

            called_cmd = mock_run.call_args.args[0]
            self.assertEqual(called_cmd[0], "bash")
            self.assertEqual(called_cmd[1], str(script))
            self.assertEqual(called_cmd[2], "enable")


if __name__ == "__main__":
    unittest.main()
