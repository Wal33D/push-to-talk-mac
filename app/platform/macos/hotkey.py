"""macOS global hotkey adapter implementation."""

from __future__ import annotations

import logging
import threading
from typing import Callable

try:
    from pynput import keyboard as pynput_keyboard

    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

try:
    import Quartz

    HAS_QUARTZ = True
except ImportError:
    HAS_QUARTZ = False

LOG = logging.getLogger("vtc")

# Fn/Globe key modifier flag on macOS.
_FN_FLAG = 0x800000  # NX_SECONDARYFNMASK / kCGEventFlagMaskSecondaryFn


class FnKeyMonitor:
    """Monitors the Fn/Globe key via Quartz modifier flag changes."""

    def __init__(self, on_press_cb, on_release_cb):
        self.on_press_cb = on_press_cb
        self.on_release_cb = on_release_cb
        self._fn_down = False
        self._tap = None
        self._source = None
        self._thread = None

    def start(self):
        if not HAS_QUARTZ or self._thread is not None:
            return
        self._fn_down = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._source is not None:
            try:
                Quartz.CFRunLoopSourceInvalidate(self._source)
            except Exception as exc:
                LOG.debug(f"Failed to invalidate Fn runloop source: {exc}")
        if self._tap is not None:
            try:
                Quartz.CGEventTapEnable(self._tap, False)
            except Exception as exc:
                LOG.debug(f"Failed to disable Fn event tap: {exc}")
        self._tap = None
        self._source = None
        self._thread = None
        self._fn_down = False

    def _callback(self, proxy, event_type, event, refcon):
        flags = Quartz.CGEventGetFlags(event)
        fn_now = bool(flags & _FN_FLAG)

        if fn_now and not self._fn_down:
            self._fn_down = True
            self.on_press_cb()
        elif not fn_now and self._fn_down:
            self._fn_down = False
            self.on_release_cb()

        return event

    def _run(self):
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
            self._callback,
            None,
        )
        if tap is None:
            print(
                "PTT: Could not create event tap for Fn key. "
                "Grant Accessibility permission and retry."
            )
            return

        self._tap = tap
        self._source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(loop, self._source, Quartz.kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(tap, True)
        Quartz.CFRunLoopRun()


class KeyListener:
    """Global hotkey listener for push-to-talk mode."""

    # Map config key names to pynput key objects.
    KEY_MAP = {
        "fn": None,  # Handled by FnKeyMonitor, not pynput.
        "right_option": "Key.alt_r",
        "right_command": "Key.cmd_r",
        "right_shift": "Key.shift_r",
        "left_option": "Key.alt",
        "f18": "Key.f18",
        "f19": "Key.f19",
        "f17": "Key.f17",
    }

    # Human-readable names for the menu.
    KEY_DISPLAY_NAMES = {
        "fn": "Fn (Globe)",
        "right_option": "Right Option",
        "right_command": "Right Command",
        "right_shift": "Right Shift",
        "left_option": "Left Option",
        "f18": "F18",
        "f19": "F19",
        "f17": "F17",
    }

    def __init__(self, key_name, on_press_cb, on_release_cb):
        self.key_name = key_name
        self.on_press_cb = on_press_cb
        self.on_release_cb = on_release_cb
        self.is_pressed = False
        self._listener = None  # pynput listener (non-Fn keys).
        self._fn_monitor = None  # Quartz Fn monitor.
        self._target_key = self._resolve_key(key_name)

    def _resolve_key(self, key_name):
        """Resolve a config key name to a pynput key object (None for Fn)."""
        if key_name == "fn":
            return None  # Fn uses FnKeyMonitor.
        if not HAS_PYNPUT:
            return None
        key_str = self.KEY_MAP.get(key_name, "Key.alt_r")
        try:
            return getattr(pynput_keyboard.Key, key_str.split(".")[-1])
        except AttributeError:
            return pynput_keyboard.Key.alt_r

    def set_key(self, key_name):
        """Change the PTT key. Restarts the listener if running."""
        was_running = self._listener is not None or self._fn_monitor is not None
        if was_running:
            self.stop()
        self.key_name = key_name
        self._target_key = self._resolve_key(key_name)
        if was_running:
            self.start()

    def start(self):
        """Start listening for the global hotkey."""
        if self._listener is not None or self._fn_monitor is not None:
            return
        self.is_pressed = False

        if self.key_name == "fn":
            # Use Quartz monitor for Fn key.
            if HAS_QUARTZ:
                self._fn_monitor = FnKeyMonitor(self.on_press_cb, self.on_release_cb)
                self._fn_monitor.start()
            else:
                print("PTT: Quartz not available for Fn key detection")
        else:
            # Use pynput for all other keys.
            if HAS_PYNPUT:
                self._listener = pynput_keyboard.Listener(
                    on_press=self._on_press,
                    on_release=self._on_release,
                )
                self._listener.daemon = True
                self._listener.start()

    def stop(self):
        """Stop the global hotkey listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._fn_monitor is not None:
            self._fn_monitor.stop()
            self._fn_monitor = None
        self.is_pressed = False

    def _on_press(self, key):
        """Handle key press event (pynput)."""
        if key == self._target_key and not self.is_pressed:
            self.is_pressed = True
            self.on_press_cb()

    def _on_release(self, key):
        """Handle key release event (pynput)."""
        if key == self._target_key and self.is_pressed:
            self.is_pressed = False
            self.on_release_cb()


class MacOSHotkeyProvider:
    """Protocol-friendly adapter around KeyListener."""

    KEY_DISPLAY_NAMES = KeyListener.KEY_DISPLAY_NAMES

    def __init__(
        self,
        key_name: str,
        on_press_cb: Callable[[], None] | None = None,
        on_release_cb: Callable[[], None] | None = None,
    ):
        self._key_name = key_name
        self._on_press_cb = on_press_cb or (lambda: None)
        self._on_release_cb = on_release_cb or (lambda: None)
        self._running = False
        self._listener = KeyListener(
            self._key_name,
            self._on_press_cb,
            self._on_release_cb,
        )

    def set_handlers(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        """Register callbacks and rebuild listener with new handlers."""
        self._on_press_cb = on_press
        self._on_release_cb = on_release
        was_running = self._running
        if was_running:
            self._listener.stop()
        self._listener = KeyListener(
            self._key_name,
            self._on_press_cb,
            self._on_release_cb,
        )
        if was_running:
            self._listener.start()

    def set_key(self, key_name: str) -> None:
        """Update the configured key."""
        self._key_name = key_name
        self._listener.set_key(key_name)

    def start(self) -> None:
        """Start hotkey monitoring."""
        self._listener.start()
        self._running = True

    def stop(self) -> None:
        """Stop hotkey monitoring."""
        self._listener.stop()
        self._running = False
