"""macOS output automation adapter."""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import pyperclip

LOG = logging.getLogger("pusha")


def _save_clipboard():
    """Save current clipboard text content. Returns saved text or None if non-text."""
    try:
        result = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=2
        )
        text = result.stdout
        # If pbpaste returns empty, clipboard likely has non-text content (images, etc.)
        return text if text else None
    except Exception as exc:
        LOG.debug(f"Failed to save clipboard: {exc}")
        return None


def _restore_clipboard(saved):
    """Restore clipboard after a short delay. Runs in background thread."""
    if saved is None:
        return
    def _do_restore():
        time.sleep(0.15)
        try:
            # subprocess.Popen does not accept timeout=, only run() and
            # communicate() do. Putting it on Popen made every restore raise
            # immediately, leaving the clipboard with the dictation result.
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(input=saved.encode("utf-8"), timeout=2)
        except Exception as exc:
            LOG.debug(f"Failed to restore clipboard: {exc}")
    threading.Thread(target=_do_restore, daemon=True).start()


def trigger_haptic():
    """Trigger haptic feedback on Force Touch trackpad via NSHapticFeedbackManager."""
    try:
        from AppKit import NSHapticFeedbackManager
        performer = NSHapticFeedbackManager.defaultPerformer()
        # 1 = NSHapticFeedbackPerformanceTimeDefault
        # NSHapticFeedbackPatternGeneric = 0
        performer.performFeedbackPattern_performanceTime_(0, 1)
    except Exception:
        pass  # Silently skip on non-Force Touch hardware


def escape_applescript_string(text):
    """Escape text for safe inclusion in AppleScript string literals."""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


class OutputHandler:
    """Handles pasting text to the active window."""

    @staticmethod
    def prepare_text(text, append=False):
        """Prepare text for output, optionally appending to clipboard."""
        if append:
            try:
                current = pyperclip.paste()
                if current:
                    text = current + " " + text
            except Exception as exc:
                LOG.debug(f"Failed to read clipboard for append mode: {exc}")
        return text

    @staticmethod
    def paste_and_send(text, send_key="return", append=False, clipboard_restore=True):
        """Copy text to clipboard and simulate Cmd+V, then send key."""
        saved_clipboard = _save_clipboard() if clipboard_restore else None

        text = OutputHandler.prepare_text(text, append)
        pyperclip.copy(text)

        # Build the send key command
        if send_key == "ctrl_return":
            send_cmd = 'keystroke return using control down'
        elif send_key == "cmd_return":
            send_cmd = 'keystroke return using command down'
        elif send_key == "shift_return":
            send_cmd = 'keystroke return using shift down'
        else:
            send_cmd = 'keystroke return'

        script = f'''
        tell application "System Events"
            keystroke "v" using command down
            delay 0.1
            {send_cmd}
        end tell
        '''
        # Retry paste up to 3 times (clipboard can be transiently locked)
        for attempt in range(3):
            try:
                subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=5)
                if clipboard_restore:
                    _restore_clipboard(saved_clipboard)
                return True
            except Exception as exc:
                if attempt < 2:
                    LOG.debug(f"paste_and_send attempt {attempt + 1} failed: {exc}, retrying...")
                    time.sleep(0.1)
                    pyperclip.copy(text)  # Re-copy in case clipboard was stolen
                else:
                    LOG.warning(f"paste_and_send failed after 3 attempts: {exc}, falling back to type_text")
                    OutputHandler.type_and_send(text, send_key)
                    if clipboard_restore:
                        _restore_clipboard(saved_clipboard)
                    return False
        return False

    @staticmethod
    def paste_only(text, append=False, clipboard_restore=True):
        """Copy text to clipboard and simulate Cmd+V (no Enter)."""
        saved_clipboard = _save_clipboard() if clipboard_restore else None

        text = OutputHandler.prepare_text(text, append)
        pyperclip.copy(text)

        script = '''
        tell application "System Events"
            keystroke "v" using command down
        end tell
        '''
        for attempt in range(3):
            try:
                subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=5)
                if clipboard_restore:
                    _restore_clipboard(saved_clipboard)
                return True
            except Exception as exc:
                if attempt < 2:
                    LOG.debug(f"paste_only attempt {attempt + 1} failed: {exc}, retrying...")
                    time.sleep(0.1)
                    pyperclip.copy(text)
                else:
                    LOG.warning(f"paste_only failed after 3 attempts: {exc}, falling back to type_text")
                    OutputHandler.type_text(text)
                    if clipboard_restore:
                        _restore_clipboard(saved_clipboard)
                    return False
        return False

    @staticmethod
    def copy_only(text):
        """Just copy text to clipboard."""
        pyperclip.copy(text)
        return True

    @staticmethod
    def type_text(text):
        """Type text character by character (for apps that don't support paste)."""
        escaped = escape_applescript_string(text)
        script = f'''
        tell application "System Events"
            keystroke "{escaped}"
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=30)
            return True
        except Exception as exc:
            LOG.debug(f"type_text failed: {exc}")
            return False

    @staticmethod
    def type_and_send(text, send_key="return"):
        """Type text and press send key."""
        escaped = escape_applescript_string(text)

        # Build the send key command
        if send_key == "ctrl_return":
            send_cmd = 'keystroke return using control down'
        elif send_key == "cmd_return":
            send_cmd = 'keystroke return using command down'
        elif send_key == "shift_return":
            send_cmd = 'keystroke return using shift down'
        else:
            send_cmd = 'keystroke return'

        script = f'''
        tell application "System Events"
            keystroke "{escaped}"
            delay 0.1
            {send_cmd}
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=30)
            return True
        except Exception as exc:
            LOG.debug(f"type_and_send failed: {exc}")
            return False

    @staticmethod
    def play_sound(sound_name):
        """Play a system sound."""
        try:
            subprocess.run(["afplay", f"/System/Library/Sounds/{sound_name}.aiff"], capture_output=True, timeout=2)
        except Exception as exc:
            LOG.debug(f"Failed to play sound {sound_name}: {exc}")

    @staticmethod
    def stop_speaking():
        """Stop any currently running say command."""
        try:
            subprocess.run(["pkill", "-x", "say"], capture_output=True, timeout=2)
        except Exception as exc:
            LOG.debug(f"Failed to stop say process: {exc}")

    @staticmethod
    def show_notification(title, message, sound=False):
        """Show a macOS notification."""
        escaped_title = escape_applescript_string(str(title).replace("\n", " "))
        escaped_message = escape_applescript_string(str(message).replace("\n", " "))
        sound_clause = ' sound name "default"' if sound else ""
        script = f'''
        display notification "{escaped_message}" with title "{escaped_title}"{sound_clause}
        '''
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=2)
        except Exception as exc:
            LOG.debug(f"Failed to show notification: {exc}")


class MacOSOutputAutomation:
    """Protocol-friendly adapter for macOS output automation."""

    def paste_and_send(self, text, send_key="return", append=False, clipboard_restore=True):
        return OutputHandler.paste_and_send(text, send_key=send_key, append=append, clipboard_restore=clipboard_restore)

    def paste_only(self, text, append=False, clipboard_restore=True):
        return OutputHandler.paste_only(text, append=append, clipboard_restore=clipboard_restore)

    def copy_only(self, text):
        return OutputHandler.copy_only(text)

    def type_text(self, text):
        return OutputHandler.type_text(text)

    def type_and_send(self, text, send_key="return"):
        return OutputHandler.type_and_send(text, send_key=send_key)

    def play_sound(self, sound_name):
        return OutputHandler.play_sound(sound_name)

    def stop_speaking(self):
        return OutputHandler.stop_speaking()

    def show_notification(self, title, message, sound=False):
        return OutputHandler.show_notification(title, message, sound=sound)
