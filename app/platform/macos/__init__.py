"""macOS platform adapter implementations."""

from app.platform.macos.hotkey import HAS_PYNPUT, HAS_QUARTZ, KeyListener
from app.platform.macos.output import OutputHandler

__all__ = ["OutputHandler", "KeyListener", "HAS_PYNPUT", "HAS_QUARTZ"]
