"""Platform adapter interfaces."""

from __future__ import annotations

from typing import Callable, Protocol

from app.core.state import AppState


class UiShell(Protocol):
    """Platform UI surface (menu bar/tray, notifications, state indicators)."""

    def set_state(self, state: AppState, message: str | None = None) -> None:
        """Render a new app state and optional status message."""

    def show_notification(self, title: str, message: str) -> None:
        """Display a user notification."""


class GlobalHotkeyProvider(Protocol):
    """Global push-to-talk key press/release provider."""

    def set_handlers(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        """Register callbacks for press/release events."""

    def set_key(self, key_name: str) -> None:
        """Update the configured key and rebind listeners if needed."""

    def start(self) -> None:
        """Start hotkey monitoring."""

    def stop(self) -> None:
        """Stop hotkey monitoring."""


class OutputAutomation(Protocol):
    """Text output provider for paste/type/send behavior."""

    def paste_and_send(self, text: str, send_key: str, append: bool = False) -> bool:
        """Paste text then send."""

    def paste_only(self, text: str, append: bool = False) -> bool:
        """Paste text only."""

    def copy_only(self, text: str) -> bool:
        """Copy text to clipboard only."""

    def type_text(self, text: str) -> bool:
        """Type text as keystrokes."""

    def type_and_send(self, text: str, send_key: str) -> bool:
        """Type text then send."""


class AutoStartManager(Protocol):
    """Platform startup-on-login implementation."""

    def enable(self) -> None:
        """Enable startup."""

    def disable(self) -> None:
        """Disable startup."""

    def status(self) -> str:
        """Return startup status."""

