#!/usr/bin/env python3
"""
Pusha Talk - macOS Menu Bar App

A push-to-talk voice-to-text tool that lives in your menu bar.
Hold Fn (Globe) to speak, release to transcribe and paste.

Perfect for hands-free dictation to any text input.

Usage:
    python3 pusha_talk.py

Requirements:
    - macOS (uses rumps for menu bar, AppleScript for paste)
    - Python 3.9+
    - See requirements.txt for dependencies
"""

import os
import sys
import threading
import subprocess
import logging
from pathlib import Path
from datetime import datetime

from app.core.audio import AudioEngine
from app.core.config import load_config, save_config
from app.core.dictation import DictationProcessor
from app.core import history as hist
from app.core.state import AppState as State, STATE_DESCRIPTIONS, STATE_ICONS
from app.core.transcription import TranscriptionEngine
from app.gui.history_window import HistoryWindow
from app.platform.macos.context import FocusedAppContext
from app.platform.macos.hotkey import HAS_PYNPUT, HAS_QUARTZ, MacOSHotkeyProvider
from app.platform.macos.output import MacOSOutputAutomation, trigger_haptic

# Debug logging — opt-in via --debug flag or PUSHA_DEBUG=1 env var
_DEBUG = ("--debug" in sys.argv) or (os.environ.get("PUSHA_DEBUG") == "1")
if "--debug" in sys.argv:
    sys.argv.remove("--debug")
_LOG_PATH = Path.home() / ".config" / "pusha-talk" / "debug.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(_LOG_PATH) if _DEBUG else os.devnull,
    level=logging.DEBUG if _DEBUG else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pusha")

# Set working directory for model cache
os.chdir(os.path.expanduser("~"))

import pyaudio
import pyperclip
import rumps

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

__version__ = "2.1.0"
__author__ = "Waleed Judah"

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = load_config()

# ============================================================================
# STATES
# ============================================================================

# ============================================================================
# FLOATING HUD WIDGET
# ============================================================================

if HAS_APPKIT:

    class HUDBarView(NSView):
        """Custom NSView that draws the floating HUD pill with visual states."""

        def initWithFrame_(self, frame):
            self = objc.super(HUDBarView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._state = "idle"       # idle / recording / processing
            self._audio_levels = [0.0] * 12
            self._label_text = "Hold Fn (Globe) to speak"
            self._app_name = ""        # Focused app name during recording
            self._record_secs = 0.0    # Elapsed recording seconds
            self._in_tail = False      # True when capturing VAD tail after release
            self._continuous = False   # True when in continuous (double-tap) mode
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
                NSFontAttributeName: NSFont.systemFontOfSize_(11.0),
                NSForegroundColorAttributeName: NSColor.whiteColor(),
                NSParagraphStyleAttributeName: style,
            }
            text_size = text.sizeWithAttributes_(attrs)
            y = (h - text_size.height) / 2.0
            text_rect = NSMakeRect(0, y, w, text_size.height)
            text.drawInRect_withAttributes_(text_rect, attrs)

        def _draw_audio_bars(self, w, h):
            """Draw app name, audio bars, and elapsed timer."""
            num_bars = 9
            bar_width = 3.5
            bar_gap = 2.5
            total_bar_width = num_bars * bar_width + (num_bars - 1) * bar_gap

            # Layout: [app_label] [bars] [timer]
            margin = 14.0
            timer_w = 36.0
            bars_center_x = w / 2.0

            # Draw app name on the left
            if self._app_name:
                app_str = NSString.stringWithString_(self._app_name)
                style = NSMutableParagraphStyle.alloc().init()
                style.setAlignment_(NSTextAlignmentCenter)
                app_attrs = {
                    NSFontAttributeName: NSFont.systemFontOfSize_(9.0),
                    NSForegroundColorAttributeName: NSColor.colorWithCalibratedRed_green_blue_alpha_(0.7, 0.7, 0.7, 0.9),
                    NSParagraphStyleAttributeName: style,
                }
                app_size = app_str.sizeWithAttributes_(app_attrs)
                app_y = (h - app_size.height) / 2.0
                app_rect = NSMakeRect(margin, app_y, w / 2.0 - total_bar_width / 2.0 - margin - 4.0, app_size.height)
                app_str.drawInRect_withAttributes_(app_rect, app_attrs)

            # Draw audio bars centered — green normally, amber during tail, blue in continuous
            start_x = bars_center_x - total_bar_width / 2.0
            min_bar_h = 4.0
            max_bar_h = h - 10.0
            if self._continuous:
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.6, 1.0, 1.0).setFill()
            elif self._in_tail:
                NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.75, 0.2, 1.0).setFill()
            else:
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

            # Draw elapsed timer on the right
            secs = self._record_secs
            timer_text = f"{int(secs)}s" if secs < 60 else f"{int(secs // 60)}:{int(secs % 60):02d}"
            timer_str = NSString.stringWithString_(timer_text)
            style2 = NSMutableParagraphStyle.alloc().init()
            style2.setAlignment_(NSTextAlignmentCenter)
            timer_attrs = {
                NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(10.0, 0.0),
                NSForegroundColorAttributeName: NSColor.colorWithCalibratedRed_green_blue_alpha_(0.6, 0.9, 0.6, 0.9),
                NSParagraphStyleAttributeName: style2,
            }
            timer_size = timer_str.sizeWithAttributes_(timer_attrs)
            timer_y = (h - timer_size.height) / 2.0
            timer_rect = NSMakeRect(w - margin - timer_w, timer_y, timer_w, timer_size.height)
            timer_str.drawInRect_withAttributes_(timer_rect, timer_attrs)

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

        def setAppName_(self, name):
            self._app_name = name
            self.setNeedsDisplay_(True)

        def setRecordSecs_(self, secs):
            self._record_secs = secs
            self.setNeedsDisplay_(True)

        def setInTail_(self, flag):
            self._in_tail = bool(flag)
            self.setNeedsDisplay_(True)

        def setContinuous_(self, flag):
            self._continuous = bool(flag)
            self.setNeedsDisplay_(True)

        def setResultPreview_(self, text):
            """Temporarily show transcription result text in the HUD."""
            self._state = "idle"
            self._label_text = text if len(text) <= 45 else text[:42] + "..."
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
            hud_h = 36.0
            margin = 20.0
            x = (screen_frame.size.width - hud_w) / 2.0
            hud_pos = CONFIG.get("hud_position", "bottom")
            if hud_pos == "top":
                y = screen_frame.size.height - hud_h - margin - 30  # 30 for menu bar
            else:
                y = margin

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

        def setAppName_(self, ns_string):
            """Set the focused app name in the HUD."""
            if self._view is not None:
                self._view.setAppName_(str(ns_string))

        def setRecordSecs_(self, ns_number):
            """Update elapsed recording seconds."""
            if self._view is not None:
                self._view.setRecordSecs_(ns_number.floatValue())

        def setInTail_(self, ns_number):
            if self._view is not None:
                self._view.setInTail_(ns_number.boolValue())

        def setContinuous_(self, ns_number):
            if self._view is not None:
                self._view.setContinuous_(ns_number.boolValue())

        def setResultPreview_(self, ns_string):
            """Show transcription result preview in the HUD."""
            if self._view is not None:
                self._stop_animation_timer()
                self._view.setResultPreview_(str(ns_string))

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
    HUD_HEIGHT = 36
    BOTTOM_MARGIN = 20
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

    def set_recording(self, app_name=""):
        if not self._enabled or self._updater is None:
            return
        info = NSDictionary.dictionaryWithDictionary_({
            "state": "recording",
            "label": "Recording...",
        })
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'setState:', info, False
        )
        if app_name:
            from Foundation import NSString as _NSString
            ns_str = _NSString.stringWithString_(app_name)
            self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
                'setAppName:', ns_str, False
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

    def update_record_time(self, seconds):
        """Update elapsed recording time in the HUD."""
        if not self._enabled or self._updater is None:
            return
        ns_num = NSNumber.numberWithFloat_(float(seconds))
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'setRecordSecs:', ns_num, False
        )

    def set_in_tail(self, flag):
        """Set VAD tail indicator (bars turn amber)."""
        if not self._enabled or self._updater is None:
            return
        ns_num = NSNumber.numberWithBool_(flag)
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'setInTail:', ns_num, False
        )

    def set_continuous(self, flag):
        """Set continuous mode indicator (bars turn blue)."""
        if not self._enabled or self._updater is None:
            return
        ns_num = NSNumber.numberWithBool_(flag)
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'setContinuous:', ns_num, False
        )

    def set_result_preview(self, text):
        """Flash transcribed text in HUD before pasting."""
        if not self._enabled or self._updater is None:
            return
        from Foundation import NSString as _NSString
        ns_str = _NSString.stringWithString_(text)
        self._updater.performSelectorOnMainThread_withObject_waitUntilDone_(
            'setResultPreview:', ns_str, False
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
# MENU BAR APPLICATION
# ============================================================================

class PushaTalkApp(rumps.App):
    """Main menu bar application."""

    def __init__(self):
        super(PushaTalkApp, self).__init__(
            "Pusha Talk",
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
        self.undo_stack = []  # Last 5 (original, processed) pairs

        # Push-to-Talk state
        self.ptt_stop_event = threading.Event()
        self.ptt_recording = False
        self.focused_app = None  # Captured on PTT press for context-aware transcription
        self.continuous_mode = False  # Double-tap PTT to toggle continuous recording
        self._last_press_time = 0.0  # For double-tap detection

        # Initialize components
        self.audio_engine = AudioEngine(CONFIG, self.set_state)
        self.transcription_engine = TranscriptionEngine(
            CONFIG["model"],
            CONFIG.get("language")
        )
        self.output_handler = MacOSOutputAutomation()
        self.hud = FloatingHUD()

        # Key listener for PTT (Fn key uses Quartz, others use pynput)
        if HAS_PYNPUT or HAS_QUARTZ:
            self.key_listener = MacOSHotkeyProvider(
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
        for key_name, display_name in MacOSHotkeyProvider.KEY_DISPLAY_NAMES.items():
            item = rumps.MenuItem(display_name, callback=self.set_ptt_key)
            item.key_name = key_name
            if key_name == current_ptt_key:
                item.state = 1
            self.ptt_key_menu.add(item)

        # Output mode submenu
        self.output_menu = rumps.MenuItem("Output Mode")
        current_mode = CONFIG.get("output_mode")
        if current_mode not in self.output_modes.values():
            current_mode = "paste_send" if CONFIG.get("auto_send", True) else "paste_only"
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

        # Clipboard restore toggle
        self.clipboard_restore_item = rumps.MenuItem("Clipboard Restore", callback=self.toggle_clipboard_restore)
        self.clipboard_restore_item.state = 1 if CONFIG.get("clipboard_restore", True) else 0

        # Haptic feedback toggle
        self.haptic_item = rumps.MenuItem("Haptic Feedback", callback=self.toggle_haptic)
        self.haptic_item.state = 1 if CONFIG.get("haptic_feedback", True) else 0

        # Context-aware transcription toggle
        self.context_item = rumps.MenuItem("Context-Aware", callback=self.toggle_context_aware)
        self.context_item.state = 1 if CONFIG.get("context_aware", True) else 0

        # Auto output mode toggle
        self.auto_output_item = rumps.MenuItem("Auto Output Mode", callback=self.toggle_auto_output_mode)
        self.auto_output_item.state = 1 if CONFIG.get("auto_output_mode", False) else 0

        # HUD position submenu
        self.hud_pos_menu = rumps.MenuItem("HUD Position")
        current_pos = CONFIG.get("hud_position", "bottom")
        for pos_name, pos_val in [("Bottom", "bottom"), ("Top", "top")]:
            item = rumps.MenuItem(pos_name, callback=self.set_hud_position)
            item.pos_value = pos_val
            if pos_val == current_pos:
                item.state = 1
            self.hud_pos_menu.add(item)

        # Save per-app config
        self.save_app_config_item = rumps.MenuItem("Save Config for Current App", callback=self.save_per_app_config)

        # Input device submenu
        self.device_menu = rumps.MenuItem("Input Device")
        self._populate_device_menu()

        # Undo last transcription
        self.undo_item = rumps.MenuItem("Undo Last", callback=self.undo_last)

        # History window
        self.history_item = rumps.MenuItem("View History...", callback=self.open_history)

        # Recent transcriptions submenu
        self.recent_menu = rumps.MenuItem("Recent Transcriptions")
        self._rebuild_recent_menu()

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
            self.clipboard_restore_item,
            self.haptic_item,
            self.context_item,
            self.auto_output_item,
            self.hud_pos_menu,
            self.save_app_config_item,
            None,
            self.test_mic_item,
            self.undo_item,
            self.history_item,
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
        icon = STATE_ICONS.get(state, "🎤")
        if state == State.SPEAKING and self.continuous_mode:
            icon = "🔴"  # Red dot for continuous mode
        self.title = icon
        status_text = STATE_DESCRIPTIONS.get(state, state)
        try:
            if state == State.READY:
                key_display = MacOSHotkeyProvider.KEY_DISPLAY_NAMES.get(
                    CONFIG.get("ptt_key", "fn"), "Fn (Globe)"
                )
                status_text = f"PTT Ready — Hold {key_display}"
                self.hud.set_idle(key_display)
                self.hud.show()
            elif state == State.SPEAKING:
                pass  # HUD is set in _ptt_record_and_transcribe with app name
            elif state == State.PROCESSING:
                self.hud.set_processing()
            elif state == State.PAUSED:
                self.hud.hide()
        except Exception as exc:
            log.debug(f"Failed to update HUD/state UI: {exc}")
        self.status_item.title = f"Status: {status_text}"

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
        import time as _time
        now = _time.time()

        # If in continuous mode, any press stops it
        if self.continuous_mode:
            self.continuous_mode = False
            self.ptt_stop_event.set()
            if CONFIG.get("sound_effects"):
                threading.Thread(
                    target=lambda: self.output_handler.play_sound("Blow"),
                    daemon=True
                ).start()
            return

        if self.ptt_recording or self.paused:
            return
        if self.state == State.LOADING:
            return

        # Double-tap detection: two presses within 400ms → continuous mode
        double_tap = (now - self._last_press_time) < 0.4
        self._last_press_time = now

        self.ptt_recording = True
        self.ptt_stop_event.clear()

        if double_tap:
            self.continuous_mode = True

        # Capture focused app before recording starts (for context-aware transcription)
        self.focused_app = FocusedAppContext.get_focused_app()

        # Haptic feedback on press
        if CONFIG.get("haptic_feedback", True):
            trigger_haptic()

        # Play a ding sound when PTT key is pressed
        if CONFIG.get("sound_effects"):
            sound = "Morse" if self.continuous_mode else "Tink"
            threading.Thread(
                target=lambda: self.output_handler.play_sound(sound),
                daemon=True
            ).start()

        # Spawn recording thread
        t = threading.Thread(target=self._ptt_record_and_transcribe, daemon=True)
        t.start()

    def _ptt_key_released(self):
        """Called when PTT key is released."""
        if self.continuous_mode:
            return  # In continuous mode, release doesn't stop recording

        self.ptt_stop_event.set()

        # Haptic feedback on release
        if CONFIG.get("haptic_feedback", True):
            trigger_haptic()

    def _ptt_record_and_transcribe(self):
        """Record while key held, then transcribe and output. Runs in daemon thread."""
        try:
            # Show app name in HUD during recording
            app_name = ""
            if self.focused_app:
                app_name = self.focused_app.get("name", "")
                if app_name == "Unknown":
                    app_name = ""
            self.hud.set_recording(app_name)
            if self.continuous_mode:
                self.hud.set_continuous(True)

            audio_file = self.audio_engine.record_until_released(
                self.ptt_stop_event,
                level_callback=self.hud.update_audio_level,
                time_callback=self.hud.update_record_time,
                tail_callback=self.hud.set_in_tail,
            )

            log.info(f"record_until_released returned: {audio_file}")

            if audio_file:
                try:
                    fsize = os.path.getsize(audio_file)
                    log.info(f"Audio file size: {fsize} bytes")
                except Exception as exc:
                    log.debug(f"Failed to stat temp audio file: {exc}")

                self.set_state(State.PROCESSING)

                # Build context-aware initial_prompt from focused app
                initial_prompt = None
                if CONFIG.get("context_aware", True) and self.focused_app:
                    app_name = self.focused_app.get("name", "")
                    bundle_id = self.focused_app.get("bundle_id", "")
                    if app_name and app_name != "Unknown":
                        category = FocusedAppContext.get_app_category(bundle_id)
                        if category == "messaging":
                            initial_prompt = f"Dictating a chat message in {app_name}. Casual, conversational tone."
                        elif category == "editor" or category == "terminal":
                            initial_prompt = f"Dictating in {app_name}. Technical context, code terminology expected."
                        elif category == "browser":
                            initial_prompt = f"Dictating in {app_name}. Web browsing context."
                        else:
                            initial_prompt = f"Dictating in {app_name}."
                        log.info(f"Context prompt: {initial_prompt}")

                log.info("Starting transcription...")
                text = self.transcription_engine.transcribe(
                    audio_file, initial_prompt=initial_prompt
                )
                log.info(f"Transcription result: {repr(text)}")

                try:
                    os.unlink(audio_file)
                except Exception as exc:
                    log.debug(f"Failed to remove temp audio file: {exc}")

                if text:
                    # Flash transcription preview in HUD with word count
                    word_count = len(text.split())
                    preview = f"{text} ({word_count}w)"
                    self.hud.set_result_preview(preview)
                    threading.Event().wait(0.75)

                    self._output_text(text)
                else:
                    log.warning("Text was None or empty — skipped output")
            else:
                log.warning("No audio file returned (too short?)")
        except Exception as e:
            log.error(f"PTT error: {e}", exc_info=True)
        finally:
            self.ptt_recording = False
            self.continuous_mode = False
            self.hud.set_in_tail(False)
            self.hud.set_continuous(False)
            self.set_state(State.READY)

    def _output_text(self, text):
        """Process and output transcribed text."""
        # Check for control commands first
        control_cmd = DictationProcessor.check_control_command(text)

        if control_cmd == "SCRATCH":
            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Basso")
            script = 'tell application "System Events" to keystroke "z" using command down'
            try:
                subprocess.run(['osascript', '-e', script], capture_output=True, timeout=2)
            except Exception as exc:
                log.debug(f"Failed to issue scratch/undo shortcut: {exc}")
            return

        elif control_cmd == "CANCEL":
            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Basso")
            return

        elif control_cmd == "COPY":
            # Copy the last transcription to clipboard (no paste)
            if self.last_processed_text:
                self.output_handler.copy_only(self.last_processed_text)
                if CONFIG.get("sound_effects"):
                    self.output_handler.play_sound("Pop")
            return

        elif control_cmd == "UPPERCASE":
            # Transform last transcription to ALL CAPS and re-paste
            if self.last_processed_text:
                processed_text = self.last_processed_text.upper()
                self.last_processed_text = processed_text
            else:
                return

        elif control_cmd == "LOWERCASE":
            if self.last_processed_text:
                processed_text = self.last_processed_text.lower()
                self.last_processed_text = processed_text
            else:
                return

        elif control_cmd == "TITLECASE":
            if self.last_processed_text:
                processed_text = self.last_processed_text.title()
                self.last_processed_text = processed_text
            else:
                return

        elif control_cmd == "SELECT_ALL":
            script = 'tell application "System Events" to keystroke "a" using command down'
            try:
                subprocess.run(['osascript', '-e', script], capture_output=True, timeout=2)
            except Exception as exc:
                log.debug(f"Failed to select all: {exc}")
            return

        elif control_cmd == "REPEAT":
            if self.last_processed_text:
                processed_text = self.last_processed_text
            else:
                return
        else:
            # Normal processing
            self.last_original_text = text
            processed_text = DictationProcessor.process(
                text,
                enabled=CONFIG.get("dictation_commands", True),
                auto_capitalize=CONFIG.get("auto_capitalize", True),
                smart_punctuation=CONFIG.get("smart_punctuation", True),
                custom_replacements=CONFIG.get("custom_replacements") or None,
            )
            self.last_processed_text = processed_text
            self.undo_stack.append((text, processed_text))
            if len(self.undo_stack) > 5:
                self.undo_stack.pop(0)

        self.set_state(State.SENDING)

        # Update stats and history
        self.update_stats(processed_text)
        self.add_recent_transcription(processed_text)

        # Output based on mode — check per-app config, then auto-select
        output_mode = CONFIG.get("output_mode", "paste_send")
        send_key = CONFIG.get("send_key", "return")
        append_mode = CONFIG.get("append_mode", False)
        clipboard_restore = CONFIG.get("clipboard_restore", True)

        # Per-app config overrides (user-learned preferences per app)
        if self.focused_app:
            bundle_id = self.focused_app.get("bundle_id", "")
            per_app = CONFIG.get("per_app_config", {}).get(bundle_id)
            if per_app:
                output_mode = per_app.get("output_mode", output_mode)
                send_key = per_app.get("send_key", send_key)
            elif CONFIG.get("auto_output_mode", False):
                recommended = FocusedAppContext.get_recommended_send_key(bundle_id)
                if recommended is None:
                    output_mode = "paste_only"
                elif recommended == "return":
                    output_mode = "paste_send"
                    send_key = "return"

        if output_mode == "paste_send":
            self.output_handler.paste_and_send(processed_text, send_key, append_mode, clipboard_restore)
        elif output_mode == "paste_only":
            self.output_handler.paste_only(processed_text, append_mode, clipboard_restore)
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
            self.output_handler.show_notification("Pusha Talk", preview)

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
        CONFIG["auto_send"] = mode in {"paste_send", "type_send"}
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

    def toggle_clipboard_restore(self, sender):
        """Toggle clipboard save/restore around paste operations."""
        CONFIG["clipboard_restore"] = not CONFIG.get("clipboard_restore", True)
        sender.state = 1 if CONFIG["clipboard_restore"] else 0
        save_config(CONFIG)

    def toggle_haptic(self, sender):
        """Toggle haptic feedback on PTT press/release."""
        CONFIG["haptic_feedback"] = not CONFIG.get("haptic_feedback", True)
        sender.state = 1 if CONFIG["haptic_feedback"] else 0
        save_config(CONFIG)

    def toggle_context_aware(self, sender):
        """Toggle context-aware transcription (sends app name to Whisper)."""
        CONFIG["context_aware"] = not CONFIG.get("context_aware", True)
        sender.state = 1 if CONFIG["context_aware"] else 0
        save_config(CONFIG)

    def toggle_auto_output_mode(self, sender):
        """Toggle auto output mode (selects paste/send behavior based on focused app)."""
        CONFIG["auto_output_mode"] = not CONFIG.get("auto_output_mode", False)
        sender.state = 1 if CONFIG["auto_output_mode"] else 0
        save_config(CONFIG)

    def set_hud_position(self, sender):
        """Change HUD position (requires restart to take effect)."""
        pos_value = getattr(sender, 'pos_value', 'bottom')
        CONFIG["hud_position"] = pos_value
        save_config(CONFIG)
        for item in self.hud_pos_menu.values():
            item.state = 1 if getattr(item, 'pos_value', None) == pos_value else 0

    def save_per_app_config(self, sender):
        """Save current output mode and send key for the focused app."""
        app_info = FocusedAppContext.get_focused_app()
        bundle_id = app_info.get("bundle_id", "")
        app_name = app_info.get("name", "Unknown")
        if not bundle_id:
            rumps.alert(title="Per-App Config", message="Could not detect focused app.", ok="OK")
            return
        per_app = CONFIG.get("per_app_config", {})
        per_app[bundle_id] = {
            "output_mode": CONFIG.get("output_mode", "paste_send"),
            "send_key": CONFIG.get("send_key", "return"),
        }
        CONFIG["per_app_config"] = per_app
        save_config(CONFIG)
        rumps.alert(
            title="Per-App Config Saved",
            message=f"Saved for {app_name}:\n"
                    f"  Output: {CONFIG.get('output_mode')}\n"
                    f"  Send key: {CONFIG.get('send_key')}",
            ok="OK"
        )

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
        for key in list(self.device_menu.keys()):
            del self.device_menu[key]

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
            log.warning(f"Failed to list devices: {e}")

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
            title="Pusha Talk - Quick Help",
            message="Push-to-Talk:\n"
                    "  Hold PTT key → speak → release\n"
                    "  Double-tap PTT → continuous mode (press to stop)\n\n"
                    "Voice Commands:\n"
                    "  'period' 'comma' 'new line' 'new paragraph'\n"
                    "  'scratch that' — undo last paste\n"
                    "  'copy that' — copy last to clipboard\n"
                    "  'all caps that' / 'lowercase that' / 'title case that'\n"
                    "  'repeat that' — re-paste last transcription\n"
                    "  'select all' — Cmd+A\n\n"
                    "HUD Colors:\n"
                    "  Green bars — recording\n"
                    "  Amber bars — capturing trailing speech\n"
                    "  Blue bars — continuous mode\n\n"
                    "Pro Tips:\n"
                    "  • Save per-app config (output mode per app)\n"
                    "  • Enable Auto Output Mode for smart send\n"
                    "  • Add custom replacements in config.json\n\n"
                    "github.com/Wal33D/push-to-talk-mac",
            ok="Got it"
        )

    def show_about(self, sender):
        """Show about dialog."""
        total_transcriptions = CONFIG.get("total_transcriptions", 0)
        total_words = CONFIG.get("total_words", 0)

        rumps.alert(
            title="Pusha Talk",
            message=f"Version {__version__}\n"
                    f"By {__author__}\n\n"
                    f"A hands-free voice dictation tool\n"
                    f"for macOS menu bar.\n\n"
                    f"Lifetime stats:\n"
                    f"  {total_transcriptions} transcriptions\n"
                    f"  {total_words} words\n\n"
                    f"github.com/Wal33D/push-to-talk-mac",
            ok="OK"
        )

    def open_history(self, sender):
        """Open the transcription history window."""
        HistoryWindow.show()

    def add_recent_transcription(self, text):
        """Add a transcription to the recent list and persist to disk."""
        # Persist to history file
        hist.add(text)

        # In-memory recent list for menu
        display_text = text[:50] + "..." if len(text) > 50 else text
        timestamp = datetime.now().strftime("%H:%M")
        full_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.recent_transcriptions.insert(0, (timestamp, full_timestamp, text, display_text))
        self.recent_transcriptions = self.recent_transcriptions[:10]  # Keep last 10

        # Update menu and refresh history window if open
        self._rebuild_recent_menu()
        HistoryWindow.refresh_if_visible()

    def _rebuild_recent_menu(self):
        """Rebuild the recent transcriptions menu."""
        for key in list(self.recent_menu.keys()):
            del self.recent_menu[key]

        if not self.recent_transcriptions:
            self.recent_menu["(none yet)"] = rumps.MenuItem("(none yet)")
        else:
            for ts, full_ts, full_text, display in reversed(self.recent_transcriptions):
                item = rumps.MenuItem(
                    f"[{ts}] {display}",
                    callback=lambda sender, t=full_text: pyperclip.copy(t)
                )
                self.recent_menu.add(item)

        self.recent_menu.add(None)  # Separator
        self.recent_menu.add(rumps.MenuItem("Export History...", callback=self.export_history))
        self.recent_menu.add(rumps.MenuItem("Clear History", callback=self.clear_history))

    def export_history(self, sender):
        """Export full persistent transcription history to a file."""
        all_entries = hist.get_all()
        if not all_entries:
            rumps.alert(title="Export", message="No transcriptions to export.", ok="OK")
            return

        # Build export text
        lines = ["Pusha Talk - Transcription History", "=" * 40, ""]
        for entry in all_entries:
            lines.append(f"[{entry.get('timestamp', '')}]")
            lines.append(entry.get("text", ""))
            lines.append("")

        export_text = "\n".join(lines)

        # Copy to clipboard and save to file
        pyperclip.copy(export_text)

        export_path = Path.home() / "Desktop" / f"pusha-talk-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        try:
            with open(export_path, 'w') as f:
                f.write(export_text)
            rumps.alert(
                title="Export Complete",
                message=f"Exported {len(all_entries)} transcriptions.\n\n"
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
        """Clear transcription history (in-memory and persistent)."""
        total = hist.count()
        if not self.recent_transcriptions and total == 0:
            return

        result = rumps.alert(
            title="Clear History",
            message=f"Clear all {total} transcriptions?",
            ok="Clear",
            cancel="Cancel"
        )

        if result == 1:
            self.recent_transcriptions = []
            hist.clear()
            self._rebuild_recent_menu()
            HistoryWindow.refresh_if_visible()

    def undo_last(self, sender):
        """Pop the last transcription from undo stack and copy original text."""
        if self.undo_stack:
            original, processed = self.undo_stack.pop()
            pyperclip.copy(original)
            self.last_original_text = self.undo_stack[-1][0] if self.undo_stack else None
            self.last_processed_text = self.undo_stack[-1][1] if self.undo_stack else None
            remaining = len(self.undo_stack)
            rumps.notification(
                title="Pusha Talk",
                subtitle=f"Undo ({remaining} remaining)",
                message=f"Original: {original[:40]}..."
            )
        else:
            rumps.alert(title="Undo", message="Nothing to undo.", ok="OK")

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
    app = PushaTalkApp()
    app.run()

if __name__ == "__main__":
    main()
