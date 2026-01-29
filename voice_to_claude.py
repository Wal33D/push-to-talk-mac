#!/usr/bin/env python3
"""
Voice to Claude - macOS Menu Bar App

A voice-to-text tool that lives in your menu bar, continuously listens for speech,
transcribes using Whisper, and auto-pastes to the active window.

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
import threading
import tempfile
import wave
import time
import subprocess
import array
from pathlib import Path
from datetime import datetime

# Set working directory for model cache
os.chdir(os.path.expanduser("~"))

import pyaudio
import pyperclip
import rumps

__version__ = "1.1.0"
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

    # Voice detection
    "silence_threshold": 800,
    "speech_threshold": 1500,
    "silence_duration": 1.0,
    "min_speech_duration": 0.3,

    # Behavior
    "auto_send": True,
    "sound_effects": True,
    "show_notifications": False,

    # Stats
    "total_transcriptions": 0,
    "total_words": 0,
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
    LISTENING = "listening"
    SPEAKING = "speaking"
    PROCESSING = "processing"
    SENDING = "sending"
    PAUSED = "paused"
    ERROR = "error"

STATE_ICONS = {
    State.LOADING:    "⏳",
    State.READY:      "🎤",
    State.LISTENING:  "👂",
    State.SPEAKING:   "🗣",
    State.PROCESSING: "⚙️",
    State.SENDING:    "📤",
    State.PAUSED:     "⏸",
    State.ERROR:      "❌",
}

STATE_DESCRIPTIONS = {
    State.LOADING:    "Loading Whisper model...",
    State.READY:      "Ready - speak to dictate",
    State.LISTENING:  "Listening for speech...",
    State.SPEAKING:   "Recording your speech...",
    State.PROCESSING: "Transcribing audio...",
    State.SENDING:    "Pasting to active window...",
    State.PAUSED:     "Paused - click to resume",
    State.ERROR:      "Error - check console",
}

# ============================================================================
# AUDIO ENGINE
# ============================================================================

class AudioEngine:
    """Handles microphone input and voice activity detection."""

    def __init__(self, config, state_callback):
        self.config = config
        self.state_callback = state_callback
        self.running = False
        self.paused = False
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

    def record_until_silence(self):
        """Record audio until speech is detected, then stop after silence."""
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
            print(f"Failed to open audio stream: {e}")
            self.state_callback(State.ERROR)
            return None

        frames = []
        silent_chunks = 0
        speech_chunks = 0
        has_speech = False

        rate = self.config["rate"]
        chunk = self.config["chunk"]
        speech_threshold = self.config["speech_threshold"]
        silence_duration = self.config["silence_duration"]
        min_speech_duration = self.config["min_speech_duration"]

        chunks_for_silence = int(silence_duration * rate / chunk)
        chunks_for_min_speech = int(min_speech_duration * rate / chunk)

        self.state_callback(State.LISTENING)

        try:
            while self.running and not self.paused:
                try:
                    data = stream.read(chunk, exception_on_overflow=False)
                except Exception:
                    continue

                frames.append(data)
                level = self.get_audio_level(data)

                if level > speech_threshold:
                    speech_chunks += 1
                    silent_chunks = 0

                    if speech_chunks >= chunks_for_min_speech and not has_speech:
                        has_speech = True
                        self.state_callback(State.SPEAKING)
                else:
                    if has_speech:
                        silent_chunks += 1
                        if silent_chunks >= chunks_for_silence:
                            break

        except Exception as e:
            print(f"Recording error: {e}")
            self.state_callback(State.ERROR)
            return None
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

        if not has_speech:
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
            print(f"Failed to save audio: {e}")
            return None

# ============================================================================
# TRANSCRIPTION ENGINE
# ============================================================================

class TranscriptionEngine:
    """Handles speech-to-text using Lightning Whisper MLX."""

    def __init__(self, model_name="base"):
        self.model_name = model_name
        self.whisper = None

    def load_model(self):
        """Load the Whisper model."""
        from lightning_whisper_mlx import LightningWhisperMLX
        self.whisper = LightningWhisperMLX(
            model=self.model_name,
            batch_size=12,
            quant=None
        )

    def transcribe(self, audio_file):
        """Transcribe an audio file to text."""
        if not self.whisper:
            return None

        try:
            result = self.whisper.transcribe(audio_file)
            text = result.get("text", "").strip()

            if not text or len(text) < 3:
                return None

            if self._is_hallucination(text):
                return None

            return text
        except Exception as e:
            print(f"Transcription error: {e}")
            return None

    def _is_hallucination(self, text):
        """Filter out Whisper hallucinations (junk output on noise)."""
        junk_patterns = [
            "1.1", "...", "♪", "***", "---", "___",
            "Thank you", "Thanks for watching",
            "Subscribe", "Bye", "See you",
            "Please subscribe", "Like and subscribe",
            "Thank you for watching", "Thanks for listening",
        ]

        text_lower = text.lower()
        for pattern in junk_patterns:
            if text.count(pattern) > 2 or text_lower.count(pattern.lower()) > 2:
                return True

        # Check if mostly non-alphanumeric
        alpha_count = sum(1 for c in text if c.isalnum() or c.isspace())
        if len(text) > 5 and alpha_count < len(text) * 0.5:
            return True

        # Check for excessive repetition
        words = text.split()
        if len(words) > 3:
            unique_words = set(w.lower() for w in words)
            if len(unique_words) < len(words) * 0.3:
                return True

        return False

# ============================================================================
# OUTPUT HANDLER
# ============================================================================

class OutputHandler:
    """Handles pasting text to the active window."""

    @staticmethod
    def paste_and_send(text):
        """Copy text to clipboard and simulate Cmd+V, Enter."""
        pyperclip.copy(text)

        script = '''
        tell application "System Events"
            keystroke "v" using command down
            delay 0.1
            keystroke return
        end tell
        '''
        try:
            subprocess.run(['osascript', '-e', script], check=True,
                         capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    @staticmethod
    def paste_only(text):
        """Copy text to clipboard and simulate Cmd+V (no Enter)."""
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
    def play_sound(sound_name):
        """Play a system sound."""
        try:
            subprocess.run(['afplay', f'/System/Library/Sounds/{sound_name}.aiff'],
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

        # Initialize components
        self.audio_engine = AudioEngine(CONFIG, self.set_state)
        self.transcription_engine = TranscriptionEngine(CONFIG["model"])
        self.output_handler = OutputHandler()

        # Sensitivity levels
        self.sensitivity_levels = {
            "Low (noisy room)": 2500,
            "Medium": 1500,
            "High (quiet room)": 800,
        }

        # Output modes
        self.output_modes = {
            "Paste + Send": "paste_send",
            "Paste Only": "paste_only",
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

        # Sensitivity submenu
        self.sensitivity_menu = rumps.MenuItem("Sensitivity")
        for name, value in self.sensitivity_levels.items():
            item = rumps.MenuItem(name, callback=self.set_sensitivity)
            if value == CONFIG["speech_threshold"]:
                item.state = 1
            self.sensitivity_menu.add(item)

        # Output mode submenu
        self.output_menu = rumps.MenuItem("Output Mode")
        current_mode = "paste_send" if CONFIG["auto_send"] else "paste_only"
        for name, mode in self.output_modes.items():
            item = rumps.MenuItem(name, callback=self.set_output_mode)
            if mode == current_mode:
                item.state = 1
            self.output_menu.add(item)

        # Model submenu
        self.model_menu = rumps.MenuItem("Whisper Model")
        models = {"Base (fast)": "base", "Small (accurate)": "small"}
        for name, model in models.items():
            item = rumps.MenuItem(name, callback=self.set_model)
            if model == CONFIG["model"]:
                item.state = 1
            self.model_menu.add(item)

        # Sound effects toggle
        self.sound_item = rumps.MenuItem("Sound Effects", callback=self.toggle_sound)
        self.sound_item.state = 1 if CONFIG.get("sound_effects", True) else 0

        # Input device submenu
        self.device_menu = rumps.MenuItem("Input Device")
        self._populate_device_menu()

        # Recent transcriptions submenu
        self.recent_menu = rumps.MenuItem("Recent Transcriptions")
        self.recent_menu.add(rumps.MenuItem("(none yet)"))

        self.menu = [
            rumps.MenuItem("Pause", callback=self.toggle_pause),
            None,
            self.sensitivity_menu,
            self.output_menu,
            self.model_menu,
            self.device_menu,
            self.sound_item,
            None,
            self.recent_menu,
            self.stats_item,
            self.status_item,
        ]

    def set_state(self, state):
        """Update current state and menu bar icon."""
        self.state = state
        self.title = STATE_ICONS.get(state, "🎤")
        try:
            self.status_item.title = f"Status: {STATE_DESCRIPTIONS.get(state, state)}"
        except:
            pass

    def toggle_pause(self, sender):
        """Toggle pause/resume listening."""
        if self.paused:
            self.paused = False
            self.audio_engine.paused = False
            sender.title = "Pause"
            self.set_state(State.READY)
            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Pop")
        else:
            self.paused = True
            self.audio_engine.paused = True
            sender.title = "Resume"
            self.set_state(State.PAUSED)
            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Blow")

    def set_sensitivity(self, sender):
        """Change microphone sensitivity."""
        new_threshold = self.sensitivity_levels.get(sender.title, 1500)
        CONFIG["speech_threshold"] = new_threshold
        self.audio_engine.config["speech_threshold"] = new_threshold
        save_config(CONFIG)

        for item in self.sensitivity_menu.values():
            item.state = 1 if item.title == sender.title else 0

    def set_output_mode(self, sender):
        """Change output mode."""
        mode = self.output_modes.get(sender.title, "paste_send")
        CONFIG["auto_send"] = (mode == "paste_send")
        CONFIG["output_mode"] = mode
        save_config(CONFIG)

        for item in self.output_menu.values():
            item.state = 1 if item.title == sender.title else 0

    def set_model(self, sender):
        """Change Whisper model (requires restart)."""
        models = {"Base (fast)": "base", "Small (accurate)": "small"}
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

    def add_recent_transcription(self, text):
        """Add a transcription to the recent list."""
        # Truncate long text
        display_text = text[:50] + "..." if len(text) > 50 else text
        timestamp = datetime.now().strftime("%H:%M")

        self.recent_transcriptions.insert(0, (timestamp, text, display_text))
        self.recent_transcriptions = self.recent_transcriptions[:10]  # Keep last 10

        # Update menu
        self.recent_menu.clear()
        for ts, full_text, display in self.recent_transcriptions:
            item = rumps.MenuItem(
                f"[{ts}] {display}",
                callback=lambda sender, t=full_text: pyperclip.copy(t)
            )
            self.recent_menu.add(item)

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
        """Load the Whisper model in background."""
        try:
            self.transcription_engine.load_model()
            self.set_state(State.READY)

            if CONFIG.get("sound_effects"):
                self.output_handler.play_sound("Glass")

            self.audio_engine.running = True
            listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            listen_thread.start()

        except Exception as e:
            print(f"Failed to load model: {e}")
            self.set_state(State.ERROR)

    def _listen_loop(self):
        """Main listening loop."""
        while self.running:
            if self.paused:
                time.sleep(0.1)
                continue

            audio_file = self.audio_engine.record_until_silence()

            if audio_file and self.running and not self.paused:
                self.set_state(State.PROCESSING)

                text = self.transcription_engine.transcribe(audio_file)

                try:
                    os.unlink(audio_file)
                except:
                    pass

                if text and self.running and not self.paused:
                    self.set_state(State.SENDING)

                    # Update stats and history
                    self.update_stats(text)
                    self.add_recent_transcription(text)

                    # Output based on mode
                    output_mode = CONFIG.get("output_mode", "paste_send")
                    if output_mode == "paste_send":
                        self.output_handler.paste_and_send(text)
                    elif output_mode == "paste_only":
                        self.output_handler.paste_only(text)
                    else:
                        self.output_handler.copy_only(text)

                    if CONFIG.get("sound_effects"):
                        self.output_handler.play_sound("Tink")

                    time.sleep(0.3)

            if self.running and not self.paused:
                self.set_state(State.READY)
                time.sleep(0.2)

# ============================================================================
# MAIN
# ============================================================================

def main():
    app = VoiceToClaudeApp()
    app.run()

if __name__ == "__main__":
    main()
