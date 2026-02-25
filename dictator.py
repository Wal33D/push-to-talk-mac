#!/usr/bin/env python3
"""
Dictator - macOS Menu Bar App

A push-to-talk voice-to-text tool that lives in your menu bar.
Hold Fn (Globe) to speak, release to transcribe and paste.

Perfect for hands-free dictation to Claude Code or any text input.

Usage:
    python3 dictator.py

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
from app.core.state import AppState as State, STATE_DESCRIPTIONS, STATE_ICONS
from app.core.transcription import TranscriptionEngine
from app.platform.macos.hotkey import HAS_PYNPUT, HAS_QUARTZ, MacOSHotkeyProvider
from app.platform.macos.output import MacOSOutputAutomation

# Debug logging — opt-in via --debug flag or DICTATOR_DEBUG=1 env var
_DEBUG = ("--debug" in sys.argv) or (os.environ.get("DICTATOR_DEBUG") == "1")
if "--debug" in sys.argv:
    sys.argv.remove("--debug")
_LOG_PATH = Path.home() / ".config" / "dictator" / "debug.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(_LOG_PATH) if _DEBUG else os.devnull,
    level=logging.DEBUG if _DEBUG else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dictator")

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

__version__ = "2.0.1"
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
                NSFontAttributeName: NSFont.systemFontOfSize_(11.0),
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
            hud_w = 220.0
            hud_h = 36.0
            bottom_margin = 20.0
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

    HUD_WIDTH = 220
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
# MENU BAR APPLICATION
# ============================================================================

class DictatorApp(rumps.App):
    """Main menu bar application."""

    def __init__(self):
        super(DictatorApp, self).__init__(
            "Dictator",
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

        # Input device submenu
        self.device_menu = rumps.MenuItem("Input Device")
        self._populate_device_menu()

        # Undo last transcription
        self.undo_item = rumps.MenuItem("Undo Last", callback=self.undo_last)

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
                self.hud.set_recording()
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
        if self.ptt_recording or self.paused:
            return
        if self.state == State.LOADING:
            return
        self.ptt_recording = True
        self.ptt_stop_event.clear()

        # Play a ding sound when PTT key is pressed
        if CONFIG.get("sound_effects"):
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
                except Exception as exc:
                    log.debug(f"Failed to stat temp audio file: {exc}")

                self.set_state(State.PROCESSING)
                log.info("Starting transcription...")
                text = self.transcription_engine.transcribe(audio_file)
                log.info(f"Transcription result: {repr(text)}")

                try:
                    os.unlink(audio_file)
                except Exception as exc:
                    log.debug(f"Failed to remove temp audio file: {exc}")

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
            try:
                subprocess.run(['osascript', '-e', script], capture_output=True, timeout=2)
            except Exception as exc:
                log.debug(f"Failed to issue scratch/undo shortcut: {exc}")
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
            self.output_handler.show_notification("Dictator", preview)

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
            title="Dictator - Quick Help",
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
                    "For full docs: github.com/Wal33D/push-to-talk-mac",
            ok="Got it"
        )

    def show_about(self, sender):
        """Show about dialog."""
        total_transcriptions = CONFIG.get("total_transcriptions", 0)
        total_words = CONFIG.get("total_words", 0)

        rumps.alert(
            title="Dictator",
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
        """Export transcription history to a file."""
        if not self.recent_transcriptions:
            rumps.alert(title="Export", message="No transcriptions to export.", ok="OK")
            return

        # Build export text
        lines = ["Dictator - Transcription History", "=" * 40, ""]
        for _, full_ts, text, _ in self.recent_transcriptions:
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
                title="Dictator",
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
    app = DictatorApp()
    app.run()

if __name__ == "__main__":
    main()
