"""macOS platform adapter implementations."""

from app.platform.macos.autostart import MacOSAutoStartManager
from app.platform.macos.hotkey import HAS_PYNPUT, HAS_QUARTZ, KeyListener, MacOSHotkeyProvider
from app.platform.macos.output import OutputHandler, MacOSOutputAutomation

__all__ = [
    "OutputHandler",
    "MacOSOutputAutomation",
    "KeyListener",
    "MacOSHotkeyProvider",
    "MacOSAutoStartManager",
    "HAS_PYNPUT",
    "HAS_QUARTZ",
]
