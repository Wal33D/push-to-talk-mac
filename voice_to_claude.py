#!/usr/bin/env python3
"""
Voice to Claude - macOS Menu Bar App

A push-to-talk voice-to-text tool that lives in your menu bar.
Hold Fn (Globe) to speak, release to transcribe and paste.

Perfect for hands-free dictation to Claude Code or any text input.

Usage:
    python3 voice_to_claude.py

Requirements:
    - macOS (uses rumps for menu bar, AppleScript for paste)
    - Python 3.9+
    - See requirements.txt for dependencies
"""

import os
import sys
import json
import re
import threading
import tempfile
import wave
import subprocess
import array
import logging
from pathlib import Path
from datetime import datetime

# Debug logging — opt-in via --debug flag or VTC_DEBUG=1 env var
_DEBUG = ("--debug" in sys.argv) or (os.environ.get("VTC_DEBUG") == "1")
if "--debug" in sys.argv:
    sys.argv.remove("--debug")
_LOG_PATH = Path.home() / ".config" / "voice-to-claude" / "debug.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(_LOG_PATH) if _DEBUG else os.devnull,
    level=logging.DEBUG if _DEBUG else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("vtc")

# Set working directory for model cache
os.chdir(os.path.expanduser("~"))

import pyaudio
import pyperclip
import rumps

# Optional: pynput for push-to-talk global hotkey
try:
    from pynput import keyboard as pynput_keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

# Quartz for Fn/Globe key detection (modifier flag monitoring)
try:
    import Quartz
    HAS_QUARTZ = True
except ImportError:
    HAS_QUARTZ = False

# AppKit for floating HUD widget
try:
    import math
    import objc
    from Foundation import NSObject, NSTimer, NSMakeRect, NSMakePoint, NSNumber, NSDictionary
    from AppKit import (
        NSPanel, NSView, NSScreen, NSColor, NSFont, NSBezierPath,
        NSBackingStoreBuffered, NSFloatingWindowLevel,
        NSWindowStyleMaskBorderless,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSFontAttributeName, NSForegroundColorAttributeName,
        NSMutableParagraphStyle, NSParagraphStyleAttributeName,
        NSTextAlignmentCenter, NSString, NSMakeSize,
    )
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False

__version__ = "2.0.0"
__author__ = "Waleed Judah"

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG_DIR = Path.home() / ".config" / "voice-to-claude"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    # Model - "base" for speed, "small" for accuracy
    "model": "base",

    # Audio settings
    "rate": 16000,
    "chunk": 1024,
    "channels": 1,

    # Behavior
    "auto_send": True,
    "sound_effects": True,
    "show_notifications": True,
    "dictation_commands": True,
    "auto_capitalize": True,  # Capitalize first letter of transcriptions
    "smart_punctuation": True,  # Auto-add period, capitalize after sentences

    # Stats
    "total_transcriptions": 0,
    "total_words": 0,

    # Advanced
    "send_key": "return",  # Options: return, ctrl_return, cmd_return
    "append_mode": False,  # Append to clipboard instead of replacing
    "custom_replacements": {},  # User-defined text replacements

    # Push-to-Talk key
    "ptt_key": "fn",  # Key to hold for PTT
}

def load_config():
    """Load config from file or create default."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
                # Merge with defaults (in case new options added)
                config = DEFAULT_CONFIG.copy()
                config.update(saved)
                return config
    except Exception:
        pass
    return DEFAULT_CONFIG.copy()

def save_config(config):
    """Save config to file."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass

CONFIG = load_config()

# ============================================================================
# STATES
# ============================================================================

class State:
    LOADING = "loading"
    READY = "ready"
    SPEAKING = "speaking"
    PROCESSING = "processing"
    SENDING = "sending"
    PAUSED = "paused"
    ERROR = "error"

STATE_ICONS = {
    State.LOADING:    "⏳",
    State.READY:      "🎤",
    State.SPEAKING:   "🗣",
    State.PROCESSING: "⚙️",
    State.SENDING:    "📤",
    State.PAUSED:     "⏸",
    State.ERROR:      "❌",
}

STATE_DESCRIPTIONS = {
    State.LOADING:    "Loading Whisper model...",
    State.READY:      "PTT Ready — Hold Fn to speak",
    State.SPEAKING:   "Recording your speech...",
    State.PROCESSING: "Transcribing audio...",
    State.SENDING:    "Pasting to active window...",
    State.PAUSED:     "Paused - click to resume",
    State.ERROR:      "Error - check console",
}

# ============================================================================
# FLOATING HUD WIDGET
# ============================================================================

if HAS_APPKIT:

    class HUDBarView(NSView):
        """Custom NSView that draws the floating HUD pill with three states."""

        def initWithFrame_(self, frame):
            self = objc.super(HUDBarView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._state = "idle"       # idle / recording / processing
            self._audio_levels = [0.0] * 12
            self._label_text = "Hold Fn (Globe) to speak"
            self._tick = 0
            return self

        def isFlipped(self):
            return False

        def drawRect_(self, rect):
            bounds = self.bounds()
            w = bounds.size.width
            h = bounds.size.height

            # Draw pill background
            pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, h / 2.0, h / 2.0
            )
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.1, 0.1, 0.85).setFill()
            pill.fill()

            if self._state == "recording":
                self._draw_audio_bars(w, h)
            elif self._state == "processing":
                self._draw_processing_dots(w, h)
            else:
                self._draw_label(w, h)

        def _draw_label(self, w, h):
            """Draw centered white text for idle state."""
            text = NSString.stringWithString_(self._label_text)
            style = NSMutableParagraphStyle.alloc().init()
            style.setAlignment_(NSTextAlignmentCenter)
            attrs = {
                NSFontAttributeName: NSFont.systemFontOfSize_(13.0),
                NSForegroundColorAttributeName: NSColor.whiteColor(),
                NSParagraphStyleAttributeName: style,
            }
            text_size = text.sizeWithAttributes_(attrs)
            y = (h - text_size.height) / 2.0
            text_rect = NSMakeRect(0, y, w, text_size.height)
            text.drawInRect_withAttributes_(text_rect, attrs)

        def _draw_audio_bars(self, w, h):
            """Draw 12 vertical audio bars that respond to mic levels."""
            num_bars = 12
            bar_width = 4.0
            bar_gap = 3.0
            total_bar_width = num_bars * bar_width + (num_bars - 1) * bar_gap
            start_x = (w - total_bar_width) / 2.0
            min_bar_h = 4.0
            max_bar_h = h - 10.0

            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.85, 0.4, 1.0).setFill()

            for i in range(num_bars):
                level = self._audio_levels[i] if i < len(self._audio_levels) else 0.0
                bar_h = min_bar_h + level * (max_bar_h - min_bar_h)
                x = start_x + i * (bar_width + bar_gap)
                y = (h - bar_h) / 2.0
                bar_rect = NSMakeRect(x, y, bar_width, bar_h)
                bar_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    bar_rect, bar_width / 2.0, bar_width / 2.0
                )
                bar_path.fill()

        def _draw_processing_dots(self, w, h):
            """Draw 3 pulsing dots for processing state."""
            num_dots = 3
            dot_radius = 4.0
            dot_gap = 12.0
            total_w = num_dots * dot_radius * 2 + (num_dots - 1) * dot_gap
            start_x = (w - total_w) / 2.0

            for i in range(num_dots):
                # Sine-wave alpha pulsing, staggered per dot
                phase = self._tick * 0.15 + i * 1.2
                alpha = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(phase))
                NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, alpha).setFill()
                cx = start_x + dot_radius + i * (dot_radius * 2 + dot_gap)
                cy = h / 2.0
                dot_rect = NSMakeRect(cx - dot_radius, cy - dot_radius,
                                      dot_radius * 2, dot_radius * 2)
                dot_path = NSBezierPath.bezierPathWithOvalInRect_(dot_rect)
                dot_path.fill()

        def setAudioLevels_(self, levels):
            self._audio_levels = list(levels)
            self.setNeedsDisplay_(True)

        def setState_label_(self, state, label):
            self._state = state
            self._label_text = label
            self.setNeedsDisplay_(True)

        def animationTick(self):
            self._tick += 1
            self.setNeedsDisplay_(True)


    class HUDUpdater(NSObject):
        """Main-thread bridge for updating the HUD from background threads."""

        def init(self):
            self = objc.super(HUDUpdater, self).init()
            if self is None:
                return None
            self._panel = None
            self._view = None
            self._timer = None
            self._level_buffer = [0.0] * 12
            return self

        def createAndShow(self):
            """Create the NSPanel + HUDBarView and show it. Must be called on main thread."""
            screen = NSScreen.mainScreen()
            if screen is None:
                return
            screen_frame = screen.frame()
            hud_w = 300.0
            hud_h = 40.0
            bottom_margin = 60.0
            x = (screen_frame.size.width - hud_w) / 2.0
            y = bottom_margin

            panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(x, y, hud_w, hud_h),
                NSWindowStyleMaskBorderless,
                NSBackingStoreBuffered,
                False,
            )
            panel.setLevel_(NSFloatingWindowLevel + 1)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(NSColor.clearColor())
            panel.setIgnoresMouseEvents_(True)
            panel.setHidesOnDeactivate_(False)
            panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorStationary
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )

            view = HUDBarView.alloc().initWithFrame_(NSMakeRect(0, 0, hud_w, hud_h))
            panel.setContentView_(view)
            panel.orderFront_(None)

            self._panel = panel
            self._view = view

        def updateLevel_(self, ns_number):
            """Receives an NSNumber with a float level, shifts into rolling buffer."""
            if self._view is None:
                return
            level = ns_number.floatValue()
            self._level_buffer.pop(0)
            self._level_buffer.append(level)
            self._view.setAudioLevels_(self._level_buffer)

        def setState_(self, ns_dict):
            """Receives NSDictionary with 'state' and 'label' keys."""
            if self._view is None:
                return
            state = str(ns_dict["state"])
            label = str(ns_dict["label"])
            self._view.setState_label_(state, label)

            # Manage processing animation timer
            if state == "processing":
                self._start_animation_timer()
            else:
                self._stop_animation_timer()

        def _start_animation_timer(self):
            if self._timer is not None:
                return
            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / 12.0,  # 12 fps
                self,
                objc.selector(self.animationTick_, signature=b'v@:@'),
                None,
                True,
            )

        def _stop_animation_timer(self):
            if self._timer is not None:
                self._timer.invalidate()
                self._timer = None

        def animationTick_(self, timer):
            if self._view is not None:
                self._view.animationTick()

        def showPanel(self):
            if self._panel is not None:
                self._panel.orderFront_(None)

        def hidePanel(self):
            if self._panel is not None:
                self._panel.orderOut_(None)


class FloatingHUD:
    """Python wrapper around the AppKit HUD panel.

    All AppKit calls are dispatched to the main thread via
    performSelectorOnMainThread to ensure thread safety.
    """

    HUD_WIDTH = 300
    HUD_HEIGHT = 40
    BOTTOM_MARGIN = 60
    NUM_BARS = 12

    def __init__(self):
        self._updater = None
        self._enabled = HAS_APPKIT
        if self._enabled:
            self._updater = HUDUpdater.alloc().init()

    def create_and_show(self):
        if not self._enabled or self._updater is None:
            return
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'createAndShow', None, False
        )

    def set_idle(self, key_display="Fn (Globe)"):
        if not self._enabled or self._updater is None:
            return
        info = NSDictionary.dictionaryWithDictionary_({
            "state": "idle",
            "label": f"Hold {key_display} to speak",
        })
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'setState:', info, False
        )

    def set_recording(self):
        if not self._enabled or self._updater is None:
            return
        info = NSDictionary.dictionaryWithDictionary_({
            "state": "recording",
            "label": "Recording...",
        })
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'setState:', info, False
        )

    def set_processing(self):
        if not self._enabled or self._updater is None:
            return
        info = NSDictionary.dictionaryWithDictionary_({
            "state": "processing",
            "label": "Processing...",
        })
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'setState:', info, False
        )

    def update_audio_level(self, raw_level):
        """Normalize raw audio level (0-32768) to 0.0-1.0 and send to main thread."""
        if not self._enabled or self._updater is None:
            return
        normalized = min(1.0, max(0.0, raw_level / 32768.0))
        ns_num = NSNumber.numberWithFloat_(normalized)
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'updateLevel:', ns_num, False
        )

    def show(self):
        if not self._enabled or self._updater is None:
            return
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'showPanel', None, False
        )

    def hide(self):
        if not self._enabled or self._updater is None:
            return
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'hidePanel', None, False
        )


# ============================================================================
# AUDIO ENGINE
# ============================================================================

class AudioEngine:
    """Handles microphone input for push-to-talk recording."""

    def __init__(self, config, state_callback):
        self.config = config
        self.state_callback = state_callback
        self.running = False
        self.device_index = config.get("input_device", None)

    @staticmethod
    def list_input_devices():
        """List available audio input devices."""
        p = pyaudio.PyAudio()
        devices = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                devices.append({
                    'index': i,
                    'name': info['name'],
                    'channels': info['maxInputChannels'],
                })
        p.terminate()
        return devices

    def set_device(self, device_index):
        """Set the input device to use."""
        self.device_index = device_index
        self.config["input_device"] = device_index

    def get_audio_level(self, data):
        """Calculate the peak audio level from raw bytes."""
        audio_data = array.array('h', data)
        return max(abs(sample) for sample in audio_data) if audio_data else 0

    def record_until_released(self, stop_event, level_callback=None):
        """Record audio until stop_event is set (key released). For PTT mode."""
        p = pyaudio.PyAudio()

        try:
            stream_kwargs = {
                'format': pyaudio.paInt16,
                'channels': self.config["channels"],
                'rate': self.config["rate"],
                'input': True,
                'frames_per_buffer': self.config["chunk"],
            }
            if self.device_index is not None:
                stream_kwargs['input_device_index'] = self.device_index

            stream = p.open(**stream_kwargs)
        except Exception as e:
            print(f"PTT: Failed to open audio stream: {e}")
            self.state_callback(State.ERROR)
            return None

        frames = []
        rate = self.config["rate"]
        chunk = self.config["chunk"]
        max_chunks = int(120 * rate / chunk)  # 2 minute cap
        min_record_chunks = int(0.5 * rate / chunk)  # Record at least 0.5s no matter what
        tail_chunks = int(0.3 * rate / chunk)  # 0.3s extra after key release
        total_chunks = 0
        released = False

        self.state_callback(State.SPEAKING)

        try:
            while total_chunks < max_chunks:
                try:
                    data = stream.read(chunk, exception_on_overflow=False)
                except Exception:
                    continue
                frames.append(data)
                total_chunks += 1

                if level_callback is not None:
                    level_callback(self.get_audio_level(data))

                # Don't check stop_event until we've recorded the minimum
                if total_chunks < min_record_chunks:
                    continue

                # After minimum, check if key was released
                if not released and stop_event.is_set():
                    released = True
                    tail_remaining = tail_chunks

                # Record tail buffer after release for trailing audio
                if released:
                    tail_remaining -= 1
                    if tail_remaining <= 0:
                        break
        except Exception as e:
            print(f"PTT recording error: {e}")
            self.state_callback(State.ERROR)
            return None
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

        # Skip only if extremely short (< 0.3s of actual audio)
        min_useful_chunks = int(0.3 * rate / chunk)
        if total_chunks < min_useful_chunks:
            return None

        # Save to temp file
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                wf = wave.open(f.name, 'wb')
                wf.setnchannels(self.config["channels"])
                wf.setsampwidth(2)
                wf.setframerate(self.config["rate"])
                wf.writeframes(b''.join(frames))
                wf.close()
                return f.name
        except Exception as e:
            print(f"PTT: Failed to save audio: {e}")
            return None

# ============================================================================
# KEY LISTENER (Push-to-Talk)
# ============================================================================

# Fn/Globe key modifier flag on macOS
_FN_FLAG = 0x800000  # NX_SECONDARYFNMASK / kCGEventFlagMaskSecondaryFn


class FnKeyMonitor:
    """Monitors the Fn/Globe key via Quartz modifier flag changes.

    The Fn key doesn't fire normal key events — it only toggles a modifier
    flag bit (0x800000). This class uses a CGEventTap on flagsChanged events
    to detect press/release.
    """

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
            except Exception:
                pass
        if self._tap is not None:
            try:
                Quartz.CGEventTapEnable(self._tap, False)
            except Exception:
                pass
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
            print("PTT: Could not create event tap for Fn key. "
                  "Grant Accessibility permission and retry.")
            return

        self._tap = tap
        self._source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(loop, self._source, Quartz.kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(tap, True)
        Quartz.CFRunLoopRun()


class KeyListener:
    """Global hotkey listener for push-to-talk mode.

    Uses FnKeyMonitor (Quartz) for the Fn/Globe key, pynput for all others.
    """

    # Map config key names to pynput key objects
    KEY_MAP = {
        "fn": None,  # Handled by FnKeyMonitor, not pynput
        "right_option": "Key.alt_r",
        "right_command": "Key.cmd_r",
        "right_shift": "Key.shift_r",
        "left_option": "Key.alt",
        "f18": "Key.f18",
        "f19": "Key.f19",
        "f17": "Key.f17",
    }

    # Human-readable names for the menu
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
        self._listener = None       # pynput listener (non-Fn keys)
        self._fn_monitor = None     # Quartz Fn monitor
        self._target_key = self._resolve_key(key_name)

    def _resolve_key(self, key_name):
        """Resolve a config key name to a pynput key object (None for Fn)."""
        if key_name == "fn":
            return None  # Fn uses FnKeyMonitor
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
            # Use Quartz monitor for Fn key
            if HAS_QUARTZ:
                self._fn_monitor = FnKeyMonitor(self.on_press_cb, self.on_release_cb)
                self._fn_monitor.start()
            else:
                print("PTT: Quartz not available for Fn key detection")
        else:
            # Use pynput for all other keys
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

# ============================================================================
# TRANSCRIPTION ENGINE
# ============================================================================

class TranscriptionEngine:
    """Handles speech-to-text using Lightning Whisper MLX."""

    # Supported languages (subset of Whisper's 99 languages)
    LANGUAGES = {
        "Auto-detect": None,
        "English": "en",
        "Spanish": "es",
        "French": "fr",
        "German": "de",
        "Italian": "it",
        "Portuguese": "pt",
        "Dutch": "nl",
        "Russian": "ru",
        "Chinese": "zh",
        "Japanese": "ja",
        "Korean": "ko",
        "Arabic": "ar",
        "Hindi": "hi",
    }

    def __init__(self, model_name="base", language=None):
        self.model_name = model_name
        self.language = language
        self.whisper = None

    def load_model(self):
        """Load the Whisper model."""
        from lightning_whisper_mlx import LightningWhisperMLX
        self.whisper = LightningWhisperMLX(
            model=self.model_name,
            batch_size=12,
            quant=None
        )

    def set_language(self, language):
        """Set the transcription language."""
        self.language = language

    def transcribe(self, audio_file):
        """Transcribe an audio file to text."""
        if not self.whisper:
            return None

        try:
            # Pass language hint if set
            kwargs = {}
            if self.language:
                kwargs['language'] = self.language
            result = self.whisper.transcribe(audio_file, **kwargs)
            text = result.get("text", "").strip()
            log.info(f"Raw whisper output: {repr(text)}")

            if not text or len(text) < 3:
                log.warning(f"Text too short, discarding: {repr(text)}")
                return None

            if self._is_hallucination(text):
                log.warning(f"HALLUCINATION FILTER dropped: {repr(text)}")
                return None

            return text
        except Exception as e:
            log.error(f"Transcription error: {e}", exc_info=True)
            return None

    def _is_hallucination(self, text):
        """Filter out Whisper hallucinations (junk output on noise)."""
        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        # Very short text is often hallucination
        if len(text_stripped) < 3:
            return True

        # Just numbers, percentages, or decimals (e.g., "1.5%", "2.0", "1.1.1")
        if re.match(r'^[\d\.\,\%\s\-]+$', text_stripped):
            return True

        # Just punctuation and numbers
        if re.match(r'^[\d\.\,\%\s\-\!\?\.\,\:\;]+$', text_stripped):
            return True

        # Timestamps like "00:00", "1:23", "12:34:56"
        if re.match(r'^[\d\:\s]+$', text_stripped):
            return True

        # Music notes, symbols, special characters
        if re.match(r'^[♪♫♬\*\-\_\.\s]+$', text_stripped):
            return True

        # Foreign characters that are likely noise (Chinese/Japanese/Korean single chars)
        if len(text_stripped) <= 3 and re.match(r'^[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]+$', text_stripped):
            return True

        # Common junk patterns (Whisper hallucinations)
        junk_patterns = [
            # Numbers and decimals
            "1.1", "1.5", "2.0", "0.5", "1.0", "2.5", "3.0",
            # Symbols
            "...", "♪", "***", "---", "___", "…", "・・・",
            # YouTube/video endings
            "Thank you", "Thanks for watching", "Thanks for listening",
            "Subscribe", "Bye", "See you", "Goodbye", "See you next time",
            "Please subscribe", "Like and subscribe", "Hit the bell",
            "Thank you for watching", "You're welcome", "Don't forget to",
            # Whisper artifacts
            "I'm sorry", "Hmm", "Uh", "Um", "Huh",
            "silence", "music", "applause", "laughter", "background noise",
            "[Music]", "[Applause]", "[Laughter]", "(music)", "(applause)",
            # Very short common words (when alone)
            "you", "the", "a", "to", "is", "it", "and", "of", "in", "on",
            # Sounds
            "Shhh", "Shh", "Ssh", "Psst", "Sss",
            "Mm-hmm", "Uh-huh", "Mhm", "Mmm", "Uh huh",
            "Oh", "Ah", "Eh", "Ooh", "Aah",
            "Yeah", "Yep", "Nope", "Yup", "Nah",
            "Ha", "Haha", "Hehe", "Lol",
            # Attribution text
            "Transcribed by", "Subtitles by", "Translated by",
            "Copyright", "All rights reserved", "www.", "http",
            # Repeated sounds
            "la la la", "da da da", "na na na", "doo doo",
            # Breathing/ambient
            "breathing", "sighs", "coughs", "sniffs",
        ]

        # Check for exact matches (short hallucinations)
        if text_lower in [p.lower() for p in junk_patterns]:
            return True

        # Check for patterns that start with common hallucinations
        hallucination_starts = [
            "thank you for", "thanks for", "please subscribe",
            "don't forget", "see you", "bye bye", "goodbye",
            "transcribed by", "subtitles by", "translated by",
        ]
        for start in hallucination_starts:
            if text_lower.startswith(start):
                return True

        # Check for repeated patterns — but ONLY in short text (< 8 words).
        # In longer text, common words like "to", "you", "the" naturally repeat.
        words = text.split()
        if len(words) <= 8:
            for pattern in junk_patterns:
                if len(pattern) <= 3:
                    word_count = len(re.findall(r'\b' + re.escape(pattern) + r'\b', text_lower, re.IGNORECASE))
                    if word_count > 2:
                        log.debug(f"Hallucination: short pattern '{pattern}' repeated {word_count}x in short text")
                        return True
                else:
                    if text.count(pattern) > 2 or text_lower.count(pattern.lower()) > 2:
                        log.debug(f"Hallucination: long pattern '{pattern}' repeated >2x")
                        return True

        # Check if mostly non-alphanumeric
        alpha_count = sum(1 for c in text if c.isalpha())
        if len(text_stripped) > 5 and alpha_count < len(text_stripped) * 0.3:
            return True

        # Check for excessive repetition (same word repeated)
        words = text.split()
        if len(words) > 3:
            unique_words = set(w.lower() for w in words)
            if len(unique_words) < len(words) * 0.3:
                return True

        # Check for stuttering pattern (word repeated immediately)
        if len(words) >= 2:
            repeated_count = sum(1 for i in range(len(words) - 1) if words[i].lower() == words[i + 1].lower())
            if repeated_count >= len(words) // 2:
                return True

        # Single word that's just a number or very short
        if len(words) == 1 and (text_stripped.replace('.', '').replace('%', '').isdigit() or len(text_stripped) < 4):
            return True

        # Check for all-caps short text (often noise)
        if len(text_stripped) < 10 and text_stripped.isupper() and text_stripped.isalpha():
            return True

        return False

# ============================================================================
# DICTATION COMMANDS
# ============================================================================

class DictationProcessor:
    """Processes dictation commands like 'new line', 'period', etc."""

    # Voice commands mapped to their replacements
    COMMANDS = {
        # Punctuation
        "period": ".",
        "full stop": ".",
        "comma": ",",
        "question mark": "?",
        "exclamation mark": "!",
        "exclamation point": "!",
        "colon": ":",
        "semicolon": ";",
        "hyphen": "-",
        "dash": " - ",
        "open quote": '"',
        "close quote": '"',
        "open paren": "(",
        "close paren": ")",
        "open bracket": "[",
        "close bracket": "]",
        "ellipsis": "...",

        # Whitespace
        "new line": "\n",
        "newline": "\n",
        "new paragraph": "\n\n",
        "tab": "\t",
        "space": " ",

        # Special
        "ampersand": "&",
        "at sign": "@",
        "hashtag": "#",
        "hash": "#",
        "dollar sign": "$",
        "percent sign": "%",
        "percent": "%",
        "asterisk": "*",
        "star": "*",
        "plus sign": "+",
        "plus": "+",
        "minus sign": "-",
        "minus": "-",
        "equals sign": "=",
        "equals": "=",
        "slash": "/",
        "forward slash": "/",
        "backslash": "\\",
        "back slash": "\\",
        "underscore": "_",
        "pipe": "|",
        "tilde": "~",
        "caret": "^",
        "greater than": ">",
        "less than": "<",

        # Common programming
        "arrow": "->",
        "fat arrow": "=>",
        "double colon": "::",
        "triple dot": "...",

        # Formatting
        "all caps": "",  # Placeholder - handled specially
        "capitalize": "",  # Placeholder - handled specially

        # Common words/phrases
        "smiley face": ":)",
        "smiley": ":)",
        "frown face": ":(",
        "frowny face": ":(",
        "wink": ";)",
        "heart": "<3",

        # Markdown formatting (spoken wrappers)
        "bold start": "**",
        "bold end": "**",
        "italic start": "*",
        "italic end": "*",
        "code start": "`",
        "code end": "`",
        "strike start": "~~",
        "strike end": "~~",
        "link start": "[",
        "link end": "]",
        "bullet point": "- ",
        "numbered": "1. ",

        # Quick phrases (common responses)
        "sounds good": "Sounds good!",
        "thank you": "Thank you!",
        "no problem": "No problem!",
        "on my way": "On my way!",
        "be right back": "Be right back.",
        "one moment": "One moment please.",
        "let me check": "Let me check on that.",
        "good morning": "Good morning!",
        "good afternoon": "Good afternoon!",
        "good evening": "Good evening!",
        "have a good day": "Have a good day!",
        "talk to you later": "Talk to you later!",
    }

    # Special commands that control the app (processed separately)
    CONTROL_COMMANDS = {
        "scratch that": "SCRATCH",
        "delete that": "SCRATCH",
        "undo that": "SCRATCH",
        "never mind": "SCRATCH",
        "cancel that": "CANCEL",
        "repeat that": "REPEAT",
        "say that again": "REPEAT",
    }

    # Commands that should remove preceding space
    NO_SPACE_BEFORE = {".", ",", "?", "!", ":", ";", ")", "]", '"'}

    # Common text corrections
    TEXT_CORRECTIONS = {
        # "I" corrections
        r'\bi\b': 'I',  # Standalone "i" -> "I"
        r'\bi\'m\b': "I'm",
        r'\bi\'ll\b': "I'll",
        r'\bi\'ve\b': "I've",
        r'\bi\'d\b': "I'd",
        r'\bim\b': "I'm",  # Common speech-to-text error
        r'\bill\b': "I'll",  # Common speech-to-text error
        r'\bive\b': "I've",  # Common speech-to-text error
        # Note: "id" -> "I'd" removed as "id" is a valid word (user id, etc.)

        # Contractions without apostrophes
        r'\bdont\b': "don't",
        r'\bwont\b': "won't",
        r'\bcant\b': "can't",
        r'\bwouldnt\b': "wouldn't",
        r'\bcouldnt\b': "couldn't",
        r'\bshouldnt\b': "shouldn't",
        r'\bdidnt\b': "didn't",
        r'\bdoesnt\b': "doesn't",
        r'\bisnt\b': "isn't",
        r'\barent\b': "aren't",
        r'\bwasnt\b': "wasn't",
        r'\bwerent\b': "weren't",
        r'\bhasnt\b': "hasn't",
        r'\bhavent\b': "haven't",
        r'\bhadnt\b': "hadn't",
        r'\bwontnt\b': "won't",  # Rare but happens
        r'\bmustnt\b': "mustn't",
        r'\bneednt\b': "needn't",
        r'\bshant\b': "shan't",
        r'\bmightnt\b': "mightn't",

        # Common word contractions
        r'\bthats\b': "that's",
        r'\bwhats\b': "what's",
        r'\bheres\b': "here's",
        r'\btheres\b': "there's",
        r'\bwheres\b': "where's",
        r'\bwhos\b': "who's",
        r'\bhows\b': "how's",
        r'\bwhens\b': "when's",
        r'\bwhys\b': "why's",
        r'\bits\b': "it's",
        r'\blets\b': "let's",
        r'\byoure\b': "you're",
        r'\btheyre\b': "they're",
        r'\bwere\b(?!\s)': "we're",
        r'\bshes\b': "she's",
        r'\bhes\b': "he's",
        r'\bweve\b': "we've",
        r'\btheyve\b': "they've",
        r'\byouve\b': "you've",
        r'\bwhatll\b': "what'll",
        r'\bwholl\b': "who'll",
        r'\bthatll\b': "that'll",
        r'\bitll\b': "it'll",
        r'\btheyll\b': "they'll",
        # Note: "well" -> "we'll" removed as it's too context-dependent
        r'\byoull\b': "you'll",
        # Note: "shell" -> "she'll" and "hell" -> "he'll" removed as too context-dependent

        # Common speech-to-text phonetic errors
        r'\bgonna\b': "going to",
        r'\bwanna\b': "want to",
        r'\bgotta\b': "got to",
        r'\blemme\b': "let me",
        r'\bgimme\b': "give me",
        r'\bkinda\b': "kind of",
        r'\bsorta\b': "sort of",
        r'\blotta\b': "lot of",
        r'\bouttta\b': "out of",
        r'\bcuz\b': "because",
        r'\bcause\b': "because",
        r'\btho\b': "though",
        r'\bthru\b': "through",
        r'\bok\b': "okay",

        # Double word fixes
        r'\bthe the\b': "the",
        r'\ba a\b': "a",
        r'\ban an\b': "an",
        r'\band and\b': "and",
        r'\bto to\b': "to",
        r'\bof of\b': "of",
        r'\bis is\b': "is",
        r'\bit it\b': "it",
        r'\bthat that\b': "that",
    }

    # Filler words to remove (like Wispr Flow's auto-edit)
    # Note: Be conservative - only remove clear fillers, not words that might be intentional
    FILLER_WORDS = [
        # Basic filler sounds with surrounding punctuation (safe to remove)
        # Pattern: ", um," or ", um " -> " "
        r',?\s*\b(um+)\b\s*,?\s*',
        r',?\s*\b(uh+)\b\s*,?\s*',
        r',?\s*\b(er+)\b\s*,?\s*',
        r',?\s*\b(hmm+)\b\s*,?\s*',
        r',?\s*\b(hm+)\b\s*,?\s*',
        # Repeated words (duplicate only, keep one)
        r'\b(like)\s+(?=like\b)',
        r'\b(so)\s+(?=so\b)',
        r'\b(really)\s+(?=really\b)',
        r'\b(very)\s+(?=very\b)',
        r'\b(just)\s+(?=just\b)',
        # Filler phrases that don't add meaning (with surrounding punctuation)
        r',?\s*\b(you know)\b\s*,?\s*',
        r',?\s*\b(i mean)\b\s*,?\s*',
        # Sentence starters that are often just filler (at beginning only)
        r'^(so)\s*,\s+',  # "So, " at start (with comma)
        r'^(well)\s*,\s+',  # "Well, " at start (with comma)
        r'^(okay)\s*,\s+',  # "Okay, " at start (with comma)
    ]

    @classmethod
    def process(cls, text, enabled=True, auto_capitalize=True, smart_punctuation=True):
        """Process text and replace dictation commands."""
        if not enabled and not auto_capitalize and not smart_punctuation:
            return text

        result = text

        if enabled:
            # Sort commands by length (longest first) to avoid partial matches
            sorted_commands = sorted(cls.COMMANDS.keys(), key=len, reverse=True)

            for command in sorted_commands:
                replacement = cls.COMMANDS[command]

                # Case-insensitive replacement
                # Use re.escape on replacement to handle special chars like backslash
                pattern = re.compile(re.escape(command), re.IGNORECASE)
                # For sub(), backslash needs to be escaped in replacement string
                safe_replacement = replacement.replace('\\', '\\\\')
                result = pattern.sub(safe_replacement, result)

            # Clean up spacing around punctuation
            for punct in cls.NO_SPACE_BEFORE:
                result = result.replace(f" {punct}", punct)

            # Remove double spaces
            while "  " in result:
                result = result.replace("  ", " ")

        result = result.strip()

        # Remove filler words (um, uh, like, you know, etc.)
        # Apply multiple passes to catch nested fillers
        # Replace with a space to prevent words from merging
        for _ in range(2):
            for pattern in cls.FILLER_WORDS:
                result = re.sub(pattern, ' ', result, flags=re.IGNORECASE | re.MULTILINE)

        # Apply text corrections (contractions, common errors)
        for pattern, replacement in cls.TEXT_CORRECTIONS.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # Clean up extra spaces and punctuation issues
        result = re.sub(r'\s+', ' ', result).strip()  # Multiple spaces to single
        result = re.sub(r'\s+([.,!?;:])', r'\1', result)  # Remove space before punctuation
        result = re.sub(r',\s*,+', ',', result)  # Remove duplicate/multiple commas
        result = re.sub(r'([.!?;:])\s*([.!?;:])', r'\1', result)  # Remove duplicate sentence-end punctuation
        result = re.sub(r'^[.,;:]\s*', '', result)  # Remove leading punctuation (except ? !)
        result = re.sub(r',\s*([.!?])', r'\1', result)  # Remove comma before sentence end

        # Remove trailing filler that might remain
        result = re.sub(r'\s+(um|uh|er|ah|hmm|hm|mm|eh)\s*[.,]?\s*$', '', result, flags=re.IGNORECASE)

        # Smart punctuation: add period at end if no sentence-ending punctuation
        if smart_punctuation and result:
            # Don't add period if it's a question (detected by question words at start)
            question_starters = ['what', 'where', 'when', 'why', 'who', 'how', 'which', 'whose',
                                 'is it', 'are you', 'do you', 'does', 'did', 'can', 'could',
                                 'would', 'should', 'will', 'have you', 'has', 'was', 'were']
            text_lower = result.lower()
            is_question = any(text_lower.startswith(q) for q in question_starters)

            if result[-1] not in '.?!':
                result += '?' if is_question else '.'

        # Auto-capitalize first letter
        if auto_capitalize and result:
            result = result[0].upper() + result[1:]

            # Capitalize after sentence endings (. ! ?)
            result = re.sub(r'([.!?])\s+([a-z])', lambda m: m.group(1) + ' ' + m.group(2).upper(), result)

            # Capitalize "I" in contractions that may have been lowercased
            result = re.sub(r"\bi'm\b", "I'm", result)
            result = re.sub(r"\bi'll\b", "I'll", result)
            result = re.sub(r"\bi've\b", "I've", result)
            result = re.sub(r"\bi'd\b", "I'd", result)
            result = re.sub(r'\bi\b', 'I', result)

        return result

    @classmethod
    def check_control_command(cls, text):
        """Check if text is a control command. Returns command or None."""
        text_lower = text.lower().strip()
        for phrase, command in cls.CONTROL_COMMANDS.items():
            if text_lower == phrase or text_lower.startswith(phrase):
                return command
        return None

# ============================================================================
# OUTPUT HANDLER
# ============================================================================

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
            except:
                pass
        return text

    @staticmethod
    def paste_and_send(text, send_key="return", append=False):
        """Copy text to clipboard and simulate Cmd+V, then send key."""
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
        try:
            subprocess.run(['osascript', '-e', script], check=True,
                         capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    @staticmethod
    def paste_only(text, append=False):
        """Copy text to clipboard and simulate Cmd+V (no Enter)."""
        text = OutputHandler.prepare_text(text, append)
        pyperclip.copy(text)

        script = '''
        tell application "System Events"
            keystroke "v" using command down
        end tell
        '''
        try:
            subprocess.run(['osascript', '-e', script], check=True,
                         capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    @staticmethod
    def copy_only(text):
        """Just copy text to clipboard."""
        pyperclip.copy(text)
        return True

    @staticmethod
    def type_text(text):
        """Type text character by character (for apps that don't support paste)."""
        # Escape special characters for AppleScript
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')

        script = f'''
        tell application "System Events"
            keystroke "{escaped}"
        end tell
        '''
        try:
            subprocess.run(['osascript', '-e', script], check=True,
                         capture_output=True, timeout=30)
            return True
        except Exception:
            return False

    @staticmethod
    def type_and_send(text, send_key="return"):
        """Type text and press send key."""
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')

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
            subprocess.run(['osascript', '-e', script], check=True,
                         capture_output=True, timeout=30)
            return True
        except Exception:
            return False

    @staticmethod
    def play_sound(sound_name):
        """Play a system sound."""
        try:
            subprocess.run(['afplay', f'/System/Library/Sounds/{sound_name}.aiff'],
                         capture_output=True, timeout=2)
        except Exception:
            pass

    @staticmethod
    def stop_speaking():
        """Stop any currently running say command."""
        try:
            subprocess.run(['pkill', '-x', 'say'], capture_output=True, timeout=2)
        except Exception:
            pass

    @staticmethod
    def show_notification(title, message, sound=False):
        """Show a macOS notification."""
        script = f'''
        display notification "{message}" with title "{title}"
        '''
        try:
            subprocess.run(['osascript', '-e', script],
                         capture_output=True, timeout=2)
        except Exception:
            pass

# ============================================================================
# MENU BAR APPLICATION
# ============================================================================

class VoiceToClaudeApp(rumps.App):
    """Main menu bar application."""

    def __init__(self):
        super(VoiceToClaudeApp, self).__init__(
            "Voice to Claude",
            icon=None,
            title=STATE_ICONS[State.LOADING]
        )

        self.state = State.LOADING
        self.running = True
        self.paused = False
        self.session_transcriptions = 0
        self.session_words = 0
        self.recent_transcriptions = []
        self.last_original_text = None  # For undo feature
        self.last_processed_text = None

        # Push-to-Talk state
        self.ptt_stop_event = threading.Event()
        self.ptt_recording = False

        # Initialize components
        self.audio_engine = AudioEngine(CONFIG, self.set_state)
        self.transcription_engine = TranscriptionEngine(
            CONFIG["model"],
            CONFIG.get("language")
        )
        self.output_handler = OutputHandler()
        self.hud = FloatingHUD()

        # Key listener for PTT (Fn key uses Quartz, others use pynput)
        if HAS_PYNPUT or HAS_QUARTZ:
            self.key_listener = KeyListener(
                CONFIG.get("ptt_key", "fn"),
                self._ptt_key_pressed,
                self._ptt_key_released,
            )
        else:
            self.key_listener = None

        # Output modes
        self.output_modes = {
            "Paste + Send": "paste_send",
            "Paste Only": "paste_only",
            "Type + Send": "type_send",
            "Type Only": "type_only",
            "Copy Only": "copy_only",
        }

        # Build menu
        self._build_menu()

        # Start background threads
        self.start_background_threads()

    def _build_menu(self):
        """Build the menu bar menu."""
        self.status_item = rumps.MenuItem("Status: Loading...")
        self.stats_item = rumps.MenuItem("Session: 0 transcriptions, 0 words")

        # PTT Key submenu
        self.ptt_key_menu = rumps.MenuItem("PTT Key")
        current_ptt_key = CONFIG.get("ptt_key", "fn")
        for key_name, display_name in KeyListener.KEY_DISPLAY_NAMES.items():
            item = rumps.MenuItem(display_name, callback=self.set_ptt_key)
            item.key_name = key_name
            if key_name == current_ptt_key:
                item.state = 1
            self.ptt_key_menu.add(item)

        # Output mode submenu
        self.output_menu = rumps.MenuItem("Output Mode")
        current_mode = "paste_send" if CONFIG["auto_send"] else "paste_only"
        for name, mode in self.output_modes.items():
            item = rumps.MenuItem(name, callback=self.set_output_mode)
            if mode == current_mode:
                item.state = 1
            self.output_menu.add(item)

        # Send key submenu
        self.send_key_menu = rumps.MenuItem("Send Key")
        send_keys = {
            "Enter": "return",
            "Ctrl+Enter": "ctrl_return",
            "Cmd+Enter": "cmd_return",
            "Shift+Enter": "shift_return",
        }
        current_send_key = CONFIG.get("send_key", "return")
        for name, key in send_keys.items():
            item = rumps.MenuItem(name, callback=self.set_send_key)
            item.key_value = key
            if key == current_send_key:
                item.state = 1
            self.send_key_menu.add(item)

        # Model submenu
        self.model_menu = rumps.MenuItem("Whisper Model")
        models = {
            "Tiny (fastest)": "tiny",
            "Base (fast)": "base",
            "Small (balanced)": "small",
            "Medium (accurate)": "medium",
            "Large (best)": "large-v3",
        }
        for name, model in models.items():
            item = rumps.MenuItem(name, callback=self.set_model)
            if model == CONFIG["model"]:
                item.state = 1
            self.model_menu.add(item)

        # Language submenu
        self.language_menu = rumps.MenuItem("Language")
        current_lang = CONFIG.get("language")
        for name, code in TranscriptionEngine.LANGUAGES.items():
            item = rumps.MenuItem(name, callback=self.set_language)
            item.language_code = code
            if code == current_lang:
                item.state = 1
            self.language_menu.add(item)

        # Sound effects toggle
        self.sound_item = rumps.MenuItem("Sound Effects", callback=self.toggle_sound)
        self.sound_item.state = 1 if CONFIG.get("sound_effects", True) else 0

        # Dictation commands toggle
        self.dictation_item = rumps.MenuItem("Dictation Commands", callback=self.toggle_dictation)
        self.dictation_item.state = 1 if CONFIG.get("dictation_commands", True) else 0

        # Auto-capitalize toggle
        self.capitalize_item = rumps.MenuItem("Auto-Capitalize", callback=self.toggle_capitalize)
        self.capitalize_item.state = 1 if CONFIG.get("auto_capitalize", True) else 0

        # Smart punctuation toggle
        self.smart_punct_item = rumps.MenuItem("Smart Punctuation", callback=self.toggle_smart_punctuation)
        self.smart_punct_item.state = 1 if CONFIG.get("smart_punctuation", True) else 0

        # Notifications toggle
        self.notif_item = rumps.MenuItem("Notifications", callback=self.toggle_notifications)
        self.notif_item.state = 1 if CONFIG.get("show_notifications", True) else 0

        # Append mode toggle
        self.append_mode_item = rumps.MenuItem("Append Mode", callback=self.toggle_append_mode)
        self.append_mode_item.state = 1 if CONFIG.get("append_mode", False) else 0

        # Input device submenu
        self.device_menu = rumps.MenuItem("Input Device")
        self._populate_device_menu()

        # Undo last transcription
        self.undo_item = rumps.MenuItem("Undo Last", callback=self.undo_last)

        # Recent transcriptions submenu
        self.recent_menu = rumps.MenuItem("Recent Transcriptions")
        self.recent_menu.add(rumps.MenuItem("(none yet)"))
        self.recent_menu.add(None)  # Separator
        self.recent_menu.add(rumps.MenuItem("Export History...", callback=self.export_history))
        self.recent_menu.add(rumps.MenuItem("Clear History", callback=self.clear_history))

        # Test microphone
        self.test_mic_item = rumps.MenuItem("Test Microphone", callback=self.test_microphone)

        # Quick Help
        self.help_item = rumps.MenuItem("Quick Help", callback=self.show_help)

        # About
        self.about_item = rumps.MenuItem(f"About (v{__version__})", callback=self.show_about)

        self.menu = [
            rumps.MenuItem("Pause", callback=self.toggle_pause),
            None,
            self.ptt_key_menu,
            self.output_menu,
            self.send_key_menu,
            self.model_menu,
            self.language_menu,
            self.device_menu,
            None,
            self.sound_item,
            self.dictation_item,
            self.capitalize_item,
            self.smart_punct_item,
            self.notif_item,
            self.append_mode_item,
            None,
            self.test_mic_item,
            self.undo_item,
            self.recent_menu,
            self.stats_item,
            self.status_item,
            None,
            self.help_item,
            self.about_item,
        ]

    def set_state(self, state):
        """Update current state and menu bar icon."""
        self.state = state
        self.title = STATE_ICONS.get(state, "🎤")
        try:
            if state == State.READY:
                key_display = KeyListener.KEY_DISPLAY_NAMES.get(
                    CONFIG.get("ptt_key", "fn"), "Fn (Globe)"
                )
                self.status_item.title = f"Status: PTT Ready — Hold {key_display}"
                self.hud.set_idle(key_display)
                self.hud.show()
            elif state == State.SPEAKING:
                self.status_item.title = f"Status: {STATE_DESCRIPTIONS.get(state, state)}"
                self.hud.set_recording()
            elif state == State.PROCESSING:
                self.status_item.title = f"Status: {STATE_DESCRIPTIONS.get(state, state)}"
                self.hud.set_processing()
            elif state == State.PAUSED:
                self.status_item.title = f"Status: {STATE_DESCRIPTIONS.get(state, state)}"
                self.hud.hide()
            else:
                self.status_item.title = f"Status: {STATE_DESCRIPTIONS.get(state, state)}"
        except:
            pass

    # ---- Push-to-Talk methods ----

    def set_ptt_key(self, sender):
        """Change the push-to-talk key."""
        key_name = getattr(sender, 'key_name', 'fn')
        CONFIG["ptt_key"] = key_name
        save_config(CONFIG)

        if self.key_listener:
            self.key_listener.set_key(key_name)

        for item in self.ptt_key_menu.values():
            item.state = 1 if getattr(item, 'key_name', None) == key_name else 0

        # Update status text with new key name
        self.set_state(State.READY)

    def _ptt_key_pressed(self):
        """Called when PTT key is pressed down."""
        if self.ptt_recording or self.paused:
            return
        if self.state == State.LOADING:
            return
        self.ptt_recording = True
        self.ptt_stop_event.clear()

        # Play a ding sound when PTT key is pressed
        threading.Thread(
            target=lambda: self.output_handler.play_sound("Tink"),
            daemon=True
        ).start()

        # Spawn recording thread
        t = threading.Thread(target=self._ptt_record_and_transcribe, daemon=True)
        t.start()

    def _ptt_key_released(self):
        """Called when PTT key is released."""
        self.ptt_stop_event.set()

    def _ptt_record_and_transcribe(self):
        """Record while key held, then transcribe and output. Runs in daemon thread."""
        try:
            audio_file = self.audio_engine.record_until_released(
                self.ptt_stop_event, level_callback=self.hud.update_audio_level
            )

            log.info(f"record_until_released returned: {audio_file}")

            if audio_file:
                try:
                    fsize = os.path.getsize(audio_file)
                    log.info(f"Audio file size: {fsize} bytes")
                except:
                    pass

                self.set_state(State.PROCESSING)
                log.info("Starting transcription...")
                text = self.transcription_engine.transcribe(audio_file)
                log.info(f"Transcription result: {repr(text)}")

                try:
                    os.unlink(audio_file)
                except:
                    pass

                if text:
                    self._output_text(text)
                else:
                    log.warning("Text was None or empty — skipped output")
            else:
                log.warning("No audio file returned (too short?)")
        except Exception as e:
            log.error(f"PTT error: {e}", exc_info=True)
        finally:
            self.ptt_recording = False
            self.set_state(State.READY)

    def _output_text(self, text):
        """Process and output transcribed text."""
        # Check for control commands first
        control_cmd = DictationProcessor.check_control_command(text)

        if control_cmd == "SCRATCH":
            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Basso")
            script = 'tell application "System Events" to keystroke "z" using command down'
            subprocess.run(['osascript', '-e', script], capture_output=True, timeout=2)
            return

        elif control_cmd == "CANCEL":
            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Basso")
            return

        elif control_cmd == "REPEAT":
            if self.last_processed_text:
                processed_text = self.last_processed_text
            else:
                return
        else:
            # Normal processing
            self.set_state(State.SENDING)
            self.last_original_text = text
            processed_text = DictationProcessor.process(
                text,
                enabled=CONFIG.get("dictation_commands", True),
                auto_capitalize=CONFIG.get("auto_capitalize", True),
                smart_punctuation=CONFIG.get("smart_punctuation", True)
            )
            self.last_processed_text = processed_text

        self.set_state(State.SENDING)

        # Update stats and history
        self.update_stats(processed_text)
        self.add_recent_transcription(processed_text)

        # Output based on mode
        output_mode = CONFIG.get("output_mode", "paste_send")
        send_key = CONFIG.get("send_key", "return")
        append_mode = CONFIG.get("append_mode", False)

        if output_mode == "paste_send":
            self.output_handler.paste_and_send(processed_text, send_key, append_mode)
        elif output_mode == "paste_only":
            self.output_handler.paste_only(processed_text, append_mode)
        elif output_mode == "type_send":
            self.output_handler.type_and_send(processed_text, send_key)
        elif output_mode == "type_only":
            self.output_handler.type_text(processed_text)
        else:
            self.output_handler.copy_only(processed_text)

        if CONFIG.get("sound_effects"):
            self.output_handler.play_sound("Tink")

        if CONFIG.get("show_notifications"):
            preview = processed_text[:50] + "..." if len(processed_text) > 50 else processed_text
            self.output_handler.show_notification("Voice to Claude", preview)

    def toggle_pause(self, sender):
        """Toggle pause/resume PTT."""
        if self.paused:
            self.paused = False
            if self.key_listener:
                self.key_listener.start()
            sender.title = "Pause"
            self.hud.show()
            self.set_state(State.READY)
            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Pop")
        else:
            self.paused = True
            if self.key_listener:
                self.key_listener.stop()
            sender.title = "Resume"
            self.hud.hide()
            self.set_state(State.PAUSED)
            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Blow")

    def set_output_mode(self, sender):
        """Change output mode."""
        mode = self.output_modes.get(sender.title, "paste_send")
        CONFIG["auto_send"] = (mode == "paste_send")
        CONFIG["output_mode"] = mode
        save_config(CONFIG)

        for item in self.output_menu.values():
            item.state = 1 if item.title == sender.title else 0

    def set_send_key(self, sender):
        """Change the send key."""
        key_value = getattr(sender, 'key_value', 'return')
        CONFIG["send_key"] = key_value
        save_config(CONFIG)

        for item in self.send_key_menu.values():
            expected_key = getattr(item, 'key_value', None)
            item.state = 1 if expected_key == key_value else 0

    def set_model(self, sender):
        """Change Whisper model (requires restart)."""
        models = {
            "Tiny (fastest)": "tiny",
            "Base (fast)": "base",
            "Small (balanced)": "small",
            "Medium (accurate)": "medium",
            "Large (best)": "large-v3",
        }
        new_model = models.get(sender.title, "base")

        if new_model != CONFIG["model"]:
            CONFIG["model"] = new_model
            save_config(CONFIG)

            for item in self.model_menu.values():
                item.state = 1 if item.title == sender.title else 0

            rumps.alert(
                title="Model Changed",
                message=f"Switched to {sender.title}. Restart the app for changes to take effect.",
                ok="OK"
            )

    def toggle_sound(self, sender):
        """Toggle sound effects."""
        CONFIG["sound_effects"] = not CONFIG.get("sound_effects", True)
        sender.state = 1 if CONFIG["sound_effects"] else 0
        save_config(CONFIG)

    def toggle_dictation(self, sender):
        """Toggle dictation commands processing."""
        CONFIG["dictation_commands"] = not CONFIG.get("dictation_commands", True)
        sender.state = 1 if CONFIG["dictation_commands"] else 0
        save_config(CONFIG)

    def toggle_capitalize(self, sender):
        """Toggle auto-capitalize first letter."""
        CONFIG["auto_capitalize"] = not CONFIG.get("auto_capitalize", True)
        sender.state = 1 if CONFIG["auto_capitalize"] else 0
        save_config(CONFIG)

    def toggle_smart_punctuation(self, sender):
        """Toggle smart punctuation (auto-period, sentence capitalization)."""
        CONFIG["smart_punctuation"] = not CONFIG.get("smart_punctuation", True)
        sender.state = 1 if CONFIG["smart_punctuation"] else 0
        save_config(CONFIG)

    def toggle_notifications(self, sender):
        """Toggle macOS notifications."""
        CONFIG["show_notifications"] = not CONFIG.get("show_notifications", True)
        sender.state = 1 if CONFIG["show_notifications"] else 0
        save_config(CONFIG)

    def toggle_append_mode(self, sender):
        """Toggle append mode (append to clipboard instead of replacing)."""
        CONFIG["append_mode"] = not CONFIG.get("append_mode", False)
        sender.state = 1 if CONFIG["append_mode"] else 0
        save_config(CONFIG)

    def set_language(self, sender):
        """Set transcription language."""
        lang_code = getattr(sender, 'language_code', None)
        CONFIG["language"] = lang_code
        self.transcription_engine.set_language(lang_code)
        save_config(CONFIG)

        # Update checkmarks
        for item in self.language_menu.values():
            expected_code = getattr(item, 'language_code', None)
            item.state = 1 if expected_code == lang_code else 0

    def _populate_device_menu(self):
        """Populate the input device menu."""
        # Default device option
        default_item = rumps.MenuItem("System Default", callback=self.set_device)
        default_item.state = 1 if CONFIG.get("input_device") is None else 0
        self.device_menu.add(default_item)

        # List all input devices
        try:
            devices = AudioEngine.list_input_devices()
            for device in devices:
                name = device['name'][:40]  # Truncate long names
                item = rumps.MenuItem(name, callback=self.set_device)
                item.device_index = device['index']
                if CONFIG.get("input_device") == device['index']:
                    item.state = 1
                self.device_menu.add(item)
        except Exception as e:
            print(f"Failed to list devices: {e}")

    def set_device(self, sender):
        """Set the input device."""
        device_index = getattr(sender, 'device_index', None)
        CONFIG["input_device"] = device_index
        self.audio_engine.set_device(device_index)
        save_config(CONFIG)

        # Update checkmarks
        for item in self.device_menu.values():
            if item is None:
                continue
            expected_index = getattr(item, 'device_index', None)
            item.state = 1 if expected_index == device_index else 0

    def test_microphone(self, sender):
        """Test microphone with live audio level display."""
        was_paused = self.paused
        if not self.paused:
            self.paused = True
            if self.key_listener:
                self.key_listener.stop()

        try:
            p = pyaudio.PyAudio()
            stream_kwargs = {
                'format': pyaudio.paInt16,
                'channels': CONFIG["channels"],
                'rate': CONFIG["rate"],
                'input': True,
                'frames_per_buffer': CONFIG["chunk"],
            }
            if CONFIG.get("input_device") is not None:
                stream_kwargs['input_device_index'] = CONFIG["input_device"]

            stream = p.open(**stream_kwargs)

            # Collect samples for 5 seconds
            samples = []
            duration = 5
            chunks_per_sec = CONFIG["rate"] // CONFIG["chunk"]

            self.title = "🎚️"  # Indicate testing

            for i in range(duration * chunks_per_sec):
                data = stream.read(CONFIG["chunk"], exception_on_overflow=False)
                level = self.audio_engine.get_audio_level(data)
                samples.append(level)

                # Update title with level bar
                bar_len = min(10, level // 300)
                bar = "█" * bar_len + "░" * (10 - bar_len)
                self.title = f"🎚️{bar}"

            stream.stop_stream()
            stream.close()
            p.terminate()

            avg = sum(samples) / len(samples)
            peak = max(samples)
            min_level = min(samples)

            status = "Good" if peak > 500 else "Too quiet"

            rumps.alert(
                title="Microphone Test Complete",
                message=f"5-second test results:\n\n"
                        f"  Average: {int(avg)}\n"
                        f"  Peak: {int(peak)}\n"
                        f"  Minimum: {int(min_level)}\n\n"
                        f"  Status: {status}\n\n"
                        f"If status shows 'Too quiet', try:\n"
                        f"  • Speaking louder\n"
                        f"  • Moving closer to mic\n"
                        f"  • Selecting a different input device",
                ok="OK"
            )

        except Exception as e:
            rumps.alert(title="Test Failed", message=str(e))

        # Resume if wasn't paused before test
        if not was_paused:
            self.paused = False
            if self.key_listener:
                self.key_listener.start()
        self.set_state(State.PAUSED if self.paused else State.READY)

    def show_help(self, sender):
        """Show quick help dialog."""
        rumps.alert(
            title="Voice to Claude - Quick Help",
            message="How to use (Push-to-Talk):\n\n"
                    "1. Look for 🎤 in the menu bar (ready state)\n"
                    "2. Hold the PTT key (default: Fn/Globe)\n"
                    "3. Speak while holding the key\n"
                    "4. Release to transcribe and paste\n\n"
                    "Icon states:\n"
                    "  🎤 Ready — hold PTT key to speak\n"
                    "  🗣 Recording — capturing speech\n"
                    "  ⚙️ Processing — transcribing\n"
                    "  ⏸ Paused — click to resume\n\n"
                    "Tips:\n"
                    "  • Say 'period', 'comma', 'new line'\n"
                    "  • Change PTT key in the PTT Key menu\n"
                    "  • Use Pause/Resume to disable PTT\n\n"
                    "For full docs: github.com/Wal33D/voice-to-claude",
            ok="Got it"
        )

    def show_about(self, sender):
        """Show about dialog."""
        total_transcriptions = CONFIG.get("total_transcriptions", 0)
        total_words = CONFIG.get("total_words", 0)

        rumps.alert(
            title="Voice to Claude",
            message=f"Version {__version__}\n"
                    f"By {__author__}\n\n"
                    f"A hands-free voice dictation tool\n"
                    f"for macOS menu bar.\n\n"
                    f"Lifetime stats:\n"
                    f"  {total_transcriptions} transcriptions\n"
                    f"  {total_words} words\n\n"
                    f"github.com/Wal33D/voice-to-claude",
            ok="OK"
        )

    def add_recent_transcription(self, text):
        """Add a transcription to the recent list."""
        # Truncate long text
        display_text = text[:50] + "..." if len(text) > 50 else text
        timestamp = datetime.now().strftime("%H:%M")
        full_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.recent_transcriptions.insert(0, (timestamp, full_timestamp, text, display_text))
        self.recent_transcriptions = self.recent_transcriptions[:10]  # Keep last 10

        # Update menu (keep export/clear at bottom)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        """Rebuild the recent transcriptions menu."""
        # Clear and rebuild
        keys_to_remove = [k for k in self.recent_menu.keys()
                         if k not in ["Export History...", "Clear History"]]
        for key in keys_to_remove:
            del self.recent_menu[key]

        # Add transcriptions at the top
        if not self.recent_transcriptions:
            self.recent_menu["(none yet)"] = rumps.MenuItem("(none yet)")
        else:
            for ts, full_ts, full_text, display in reversed(self.recent_transcriptions):
                item = rumps.MenuItem(
                    f"[{ts}] {display}",
                    callback=lambda sender, t=full_text: pyperclip.copy(t)
                )
                self.recent_menu.add(item)

    def export_history(self, sender):
        """Export transcription history to a file."""
        if not self.recent_transcriptions:
            rumps.alert(title="Export", message="No transcriptions to export.", ok="OK")
            return

        # Build export text
        lines = ["Voice to Claude - Transcription History", "=" * 40, ""]
        for ts, full_ts, text, _ in self.recent_transcriptions:
            lines.append(f"[{full_ts}]")
            lines.append(text)
            lines.append("")

        export_text = "\n".join(lines)

        # Copy to clipboard and save to file
        pyperclip.copy(export_text)

        export_path = Path.home() / "Desktop" / f"voice-transcriptions-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        try:
            with open(export_path, 'w') as f:
                f.write(export_text)
            rumps.alert(
                title="Export Complete",
                message=f"Exported {len(self.recent_transcriptions)} transcriptions.\n\n"
                        f"Saved to: {export_path}\n"
                        f"Also copied to clipboard.",
                ok="OK"
            )
        except Exception as e:
            rumps.alert(
                title="Export",
                message=f"Copied to clipboard.\n\nCould not save file: {e}",
                ok="OK"
            )

    def clear_history(self, sender):
        """Clear transcription history."""
        if not self.recent_transcriptions:
            return

        result = rumps.alert(
            title="Clear History",
            message=f"Clear {len(self.recent_transcriptions)} transcriptions?",
            ok="Clear",
            cancel="Cancel"
        )

        if result == 1:
            self.recent_transcriptions = []
            self._rebuild_recent_menu()

    def undo_last(self, sender):
        """Copy the original (unprocessed) last transcription to clipboard."""
        if self.last_original_text:
            pyperclip.copy(self.last_original_text)
            rumps.notification(
                title="Voice to Claude",
                subtitle="Undo",
                message=f"Original text copied: {self.last_original_text[:30]}..."
            )
        else:
            rumps.alert(title="Undo", message="No transcription to undo.", ok="OK")

    def update_stats(self, text):
        """Update session statistics."""
        word_count = len(text.split())
        self.session_transcriptions += 1
        self.session_words += word_count

        CONFIG["total_transcriptions"] = CONFIG.get("total_transcriptions", 0) + 1
        CONFIG["total_words"] = CONFIG.get("total_words", 0) + word_count
        save_config(CONFIG)

        self.stats_item.title = f"Session: {self.session_transcriptions} transcriptions, {self.session_words} words"

    def start_background_threads(self):
        """Start model loading and listening threads."""
        load_thread = threading.Thread(target=self._load_model, daemon=True)
        load_thread.start()

    def _load_model(self):
        """Load the Whisper model in background, then start PTT key listener."""
        try:
            self.transcription_engine.load_model()
            self.hud.create_and_show()
            self.set_state(State.READY)

            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Glass")

            self.audio_engine.running = True

            # Start PTT key listener
            if self.key_listener:
                self.key_listener.start()

        except Exception as e:
            print(f"Failed to load model: {e}")
            self.set_state(State.ERROR)

# ============================================================================
# MAIN
# ============================================================================

def main():
    app = VoiceToClaudeApp()
    app.run()

if __name__ == "__main__":
    main()
