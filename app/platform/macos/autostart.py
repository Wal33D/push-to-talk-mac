"""macOS autostart adapter using launchd helper script."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

LOG = logging.getLogger("dictator")


class MacOSAutoStartManager:
    """Enable/disable/status wrapper around autostart.sh."""

    def __init__(self, script_path: str | Path | None = None):
        if script_path is not None:
            self.script_path = Path(script_path)
        else:
            self.script_path = Path(__file__).resolve().parents[3] / "autostart.sh"

    def _run(self, action: str) -> subprocess.CompletedProcess[str] | None:
        if action not in {"enable", "disable", "status"}:
            raise ValueError(f"Unsupported autostart action: {action}")

        if not self.script_path.exists():
            LOG.warning(f"autostart script not found: {self.script_path}")
            return None

        try:
            return subprocess.run(
                ["bash", str(self.script_path), action],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except Exception as exc:
            LOG.error(f"autostart command failed: {exc}", exc_info=True)
            return None

    def enable(self) -> None:
        """Enable startup at login."""
        self._run("enable")

    def disable(self) -> None:
        """Disable startup at login."""
        self._run("disable")

    def status(self) -> str:
        """Return startup state for UI display."""
        result = self._run("status")
        if result is None:
            return "unavailable"

        output = f"{result.stdout}\n{result.stderr}".lower()
        if "enabled" in output:
            return "enabled"
        if "disabled" in output:
            return "disabled"
        if "installed but not running" in output:
            return "installed"
        return "unknown"

