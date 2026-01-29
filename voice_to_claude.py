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
import re
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

__version__ = "1.7.0"
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
    "speech_threshold": 2000,  # Raised from 1500 to reduce false triggers
    "silence_duration": 2.5,  # Seconds of silence before sending
    "min_speech_duration": 0.3,

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
    "ready_sound": False,  # Play sound when ready to listen again
    "recording_sound": False,  # Play sound when recording starts
    "custom_replacements": {},  # User-defined text replacements
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

    def __init__(self, config, state_callback, recording_callback=None):
        self.config = config
        self.state_callback = state_callback
        self.recording_callback = recording_callback  # Called when recording starts
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
        total_chunks = 0

        rate = self.config["rate"]
        chunk = self.config["chunk"]
        speech_threshold = self.config["speech_threshold"]
        silence_duration = self.config["silence_duration"]
        min_speech_duration = self.config["min_speech_duration"]

        chunks_for_silence = int(silence_duration * rate / chunk)
        chunks_for_min_speech = int(min_speech_duration * rate / chunk)
        max_listen_chunks = int(30 * rate / chunk)  # 30 second timeout
        max_record_chunks = int(120 * rate / chunk)  # 2 minute max recording

        self.state_callback(State.LISTENING)

        try:
            while self.running and not self.paused:
                try:
                    data = stream.read(chunk, exception_on_overflow=False)
                except Exception:
                    continue

                frames.append(data)
                level = self.get_audio_level(data)
                total_chunks += 1

                # Timeout: if listening for too long with no speech, reset
                if not has_speech and total_chunks > max_listen_chunks:
                    break

                # Timeout: if recording for too long, stop
                if has_speech and total_chunks > max_record_chunks:
                    break

                if level > speech_threshold:
                    speech_chunks += 1
                    silent_chunks = 0

                    if speech_chunks >= chunks_for_min_speech and not has_speech:
                        has_speech = True
                        # Stop any TTS (say command) when user starts speaking
                        OutputHandler.stop_speaking()
                        # Notify that recording started
                        if self.recording_callback:
                            self.recording_callback()
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

        # Common junk patterns
        junk_patterns = [
            "1.1", "1.5", "2.0", "...", "♪", "***", "---", "___",
            "Thank you", "Thanks for watching", "Thanks for listening",
            "Subscribe", "Bye", "See you", "Goodbye",
            "Please subscribe", "Like and subscribe",
            "Thank you for watching", "You're welcome",
            "I'm sorry", "Okay", "OK", "Hmm", "Uh",
            "silence", "music", "applause", "laughter",
        ]

        # Check for exact matches (short hallucinations)
        if text_lower in [p.lower() for p in junk_patterns]:
            return True

        # Check for repeated patterns
        for pattern in junk_patterns:
            if text.count(pattern) > 2 or text_lower.count(pattern.lower()) > 2:
                return True

        # Check if mostly non-alphanumeric
        alpha_count = sum(1 for c in text if c.isalpha())
        if len(text_stripped) > 5 and alpha_count < len(text_stripped) * 0.3:
            return True

        # Check for excessive repetition
        words = text.split()
        if len(words) > 3:
            unique_words = set(w.lower() for w in words)
            if len(unique_words) < len(words) * 0.3:
                return True

        # Single word that's just a number or very short
        if len(words) == 1 and (text_stripped.replace('.', '').replace('%', '').isdigit() or len(text_stripped) < 4):
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
    }

    # Commands that should remove preceding space
    NO_SPACE_BEFORE = {".", ",", "?", "!", ":", ";", ")", "]", '"'}

    # Common text corrections
    TEXT_CORRECTIONS = {
        r'\bi\b': 'I',  # Standalone "i" -> "I"
        r'\bi\'m\b': "I'm",
        r'\bi\'ll\b': "I'll",
        r'\bi\'ve\b': "I've",
        r'\bi\'d\b': "I'd",
        r'\bim\b': "I'm",  # Common speech-to-text error
        r'\bdont\b': "don't",
        r'\bwont\b': "won't",
        r'\bcant\b': "can't",
        r'\bwouldnt\b': "wouldn't",
        r'\bcouldnt\b': "couldn't",
        r'\bshouldnt\b': "shouldn't",
        r'\bdidnt\b': "didn't",
        r'\bisnt\b': "isn't",
        r'\barent\b': "aren't",
        r'\bwasnt\b': "wasn't",
        r'\bwerent\b': "weren't",
        r'\bhasnt\b': "hasn't",
        r'\bhavent\b': "haven't",
        r'\bhadnt\b': "hadn't",
    }

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

        # Apply text corrections (i -> I, etc.)
        for pattern, replacement in cls.TEXT_CORRECTIONS.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # Smart punctuation: add period at end if no sentence-ending punctuation
        if smart_punctuation and result:
            if result[-1] not in '.?!':
                result += '.'

        # Auto-capitalize first letter
        if auto_capitalize and result:
            result = result[0].upper() + result[1:]

            # Capitalize after sentence endings (. ! ?)
            result = re.sub(r'([.!?])\s+([a-z])', lambda m: m.group(1) + ' ' + m.group(2).upper(), result)

        return result

# ============================================================================
# OUTPUT HANDLER
# ============================================================================

class OutputHandler:
    """Handles pasting text to the active window."""

    @staticmethod
    def paste_and_send(text, send_key="return"):
        """Copy text to clipboard and simulate Cmd+V, then send key."""
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

        # Initialize components
        self.audio_engine = AudioEngine(CONFIG, self.set_state, self.on_recording_start)
        self.transcription_engine = TranscriptionEngine(
            CONFIG["model"],
            CONFIG.get("language")
        )
        self.output_handler = OutputHandler()

        # Sensitivity levels (higher number = less sensitive, needs louder speech)
        self.sensitivity_levels = {
            "Very Low (very noisy)": 3500,
            "Low (noisy room)": 2500,
            "Medium": 2000,
            "High (quiet room)": 1200,
        }

        # Pause duration options (how long to wait after silence before sending)
        self.pause_durations = {
            "Short (1s)": 1.0,
            "Medium (1.5s)": 1.5,
            "Long (2s)": 2.0,
            "Very Long (2.5s)": 2.5,
            "Extra Long (3s)": 3.0,
        }

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

        # Sensitivity submenu
        self.sensitivity_menu = rumps.MenuItem("Sensitivity")
        for name, value in self.sensitivity_levels.items():
            item = rumps.MenuItem(name, callback=self.set_sensitivity)
            if value == CONFIG["speech_threshold"]:
                item.state = 1
            self.sensitivity_menu.add(item)

        # Pause duration submenu
        self.pause_menu = rumps.MenuItem("Pause Duration")
        current_pause = CONFIG.get("silence_duration", 2.5)
        for name, value in self.pause_durations.items():
            item = rumps.MenuItem(name, callback=self.set_pause_duration)
            item.duration_value = value
            if abs(value - current_pause) < 0.1:  # Float comparison
                item.state = 1
            self.pause_menu.add(item)

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

        # Ready sound toggle
        self.ready_sound_item = rumps.MenuItem("Ready Sound", callback=self.toggle_ready_sound)
        self.ready_sound_item.state = 1 if CONFIG.get("ready_sound", False) else 0

        # Recording sound toggle
        self.recording_sound_item = rumps.MenuItem("Recording Sound", callback=self.toggle_recording_sound)
        self.recording_sound_item.state = 1 if CONFIG.get("recording_sound", False) else 0

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

        # Calibrate option
        self.calibrate_item = rumps.MenuItem("Calibrate Microphone", callback=self.calibrate_mic)

        # Test microphone
        self.test_mic_item = rumps.MenuItem("Test Microphone", callback=self.test_microphone)

        # Quick Help
        self.help_item = rumps.MenuItem("Quick Help", callback=self.show_help)

        # About
        self.about_item = rumps.MenuItem(f"About (v{__version__})", callback=self.show_about)

        self.menu = [
            rumps.MenuItem("Pause", callback=self.toggle_pause),
            None,
            self.sensitivity_menu,
            self.pause_menu,
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
            self.ready_sound_item,
            self.recording_sound_item,
            None,
            self.calibrate_item,
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
            self.status_item.title = f"Status: {STATE_DESCRIPTIONS.get(state, state)}"
        except:
            pass

    def on_recording_start(self):
        """Called when recording starts (speech detected)."""
        if CONFIG.get("recording_sound"):
            # Play in a thread to not block recording
            threading.Thread(
                target=lambda: self.output_handler.play_sound("Morse"),
                daemon=True
            ).start()

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
        new_threshold = self.sensitivity_levels.get(sender.title, 2000)
        CONFIG["speech_threshold"] = new_threshold
        self.audio_engine.config["speech_threshold"] = new_threshold
        save_config(CONFIG)

        for item in self.sensitivity_menu.values():
            item.state = 1 if item.title == sender.title else 0

    def set_pause_duration(self, sender):
        """Change how long to wait after silence before sending."""
        duration = getattr(sender, 'duration_value', 2.5)
        CONFIG["silence_duration"] = duration
        self.audio_engine.config["silence_duration"] = duration
        save_config(CONFIG)

        for item in self.pause_menu.values():
            expected = getattr(item, 'duration_value', None)
            item.state = 1 if expected == duration else 0

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

    def toggle_ready_sound(self, sender):
        """Toggle ready sound (beep when ready to listen again)."""
        CONFIG["ready_sound"] = not CONFIG.get("ready_sound", False)
        sender.state = 1 if CONFIG["ready_sound"] else 0
        save_config(CONFIG)

    def toggle_recording_sound(self, sender):
        """Toggle recording sound (beep when recording starts)."""
        CONFIG["recording_sound"] = not CONFIG.get("recording_sound", False)
        sender.state = 1 if CONFIG["recording_sound"] else 0
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

    def calibrate_mic(self, sender):
        """Calibrate microphone by measuring ambient noise level."""
        # Pause listening during calibration
        was_paused = self.paused
        self.paused = True
        self.audio_engine.paused = True

        rumps.alert(
            title="Calibrating Microphone",
            message="Stay quiet for 3 seconds to measure background noise...",
            ok="Start"
        )

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

            levels = []
            for _ in range(int(3 * CONFIG["rate"] / CONFIG["chunk"])):
                data = stream.read(CONFIG["chunk"], exception_on_overflow=False)
                level = self.audio_engine.get_audio_level(data)
                levels.append(level)

            stream.stop_stream()
            stream.close()
            p.terminate()

            avg_level = sum(levels) / len(levels)
            max_level = max(levels)

            # Suggest threshold at 2x max level
            suggested = int(max_level * 2) + 100
            suggested = max(500, min(3000, suggested))  # Clamp to reasonable range

            result = rumps.alert(
                title="Calibration Complete",
                message=f"Background noise:\n"
                        f"  Average: {int(avg_level)}\n"
                        f"  Peak: {int(max_level)}\n\n"
                        f"Suggested threshold: {suggested}\n"
                        f"Current threshold: {CONFIG['speech_threshold']}\n\n"
                        f"Apply suggested threshold?",
                ok="Apply",
                cancel="Cancel"
            )

            if result == 1:  # OK clicked
                CONFIG["speech_threshold"] = suggested
                self.audio_engine.config["speech_threshold"] = suggested
                save_config(CONFIG)

                # Update sensitivity menu checkmarks
                for item in self.sensitivity_menu.values():
                    item.state = 0

        except Exception as e:
            rumps.alert(title="Calibration Failed", message=str(e))

        # Resume if wasn't paused
        if not was_paused:
            self.paused = False
            self.audio_engine.paused = False

    def test_microphone(self, sender):
        """Test microphone with live audio level display."""
        was_paused = self.paused
        self.paused = True
        self.audio_engine.paused = True

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

            threshold = CONFIG["speech_threshold"]
            status = "✓ Good" if peak > threshold else "⚠ Too quiet"

            rumps.alert(
                title="Microphone Test Complete",
                message=f"5-second test results:\n\n"
                        f"  Average: {int(avg)}\n"
                        f"  Peak: {int(peak)}\n"
                        f"  Minimum: {int(min_level)}\n\n"
                        f"  Speech threshold: {threshold}\n"
                        f"  Status: {status}\n\n"
                        f"If status shows 'Too quiet', try:\n"
                        f"  • Speaking louder\n"
                        f"  • Moving closer to mic\n"
                        f"  • Lowering sensitivity setting",
                ok="OK"
            )

        except Exception as e:
            rumps.alert(title="Test Failed", message=str(e))

        # Resume if wasn't paused
        if not was_paused:
            self.paused = False
            self.audio_engine.paused = False
        self.set_state(State.PAUSED if self.paused else State.READY)

    def show_help(self, sender):
        """Show quick help dialog."""
        rumps.alert(
            title="Voice to Claude - Quick Help",
            message="How to use:\n\n"
                    "1. Look for 🎤 in the menu bar (ready state)\n"
                    "2. Speak naturally - it auto-detects speech\n"
                    "3. Pause briefly when done speaking\n"
                    "4. Text is transcribed and pasted\n\n"
                    "Icon states:\n"
                    "  🎤 Ready - listening for speech\n"
                    "  👂 Detecting - heard something\n"
                    "  🗣 Recording - capturing speech\n"
                    "  ⚙️ Processing - transcribing\n"
                    "  ⏸ Paused - click to resume\n\n"
                    "Tips:\n"
                    "  • Say 'period', 'comma', 'new line'\n"
                    "  • Adjust sensitivity for your room\n"
                    "  • Use Calibrate to auto-tune\n\n"
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

                    # Save original for undo
                    self.last_original_text = text

                    # Process dictation commands, capitalize, and punctuate
                    processed_text = DictationProcessor.process(
                        text,
                        enabled=CONFIG.get("dictation_commands", True),
                        auto_capitalize=CONFIG.get("auto_capitalize", True),
                        smart_punctuation=CONFIG.get("smart_punctuation", True)
                    )
                    self.last_processed_text = processed_text

                    # Update stats and history
                    self.update_stats(processed_text)
                    self.add_recent_transcription(processed_text)

                    # Output based on mode
                    output_mode = CONFIG.get("output_mode", "paste_send")
                    send_key = CONFIG.get("send_key", "return")
                    if output_mode == "paste_send":
                        self.output_handler.paste_and_send(processed_text, send_key)
                    elif output_mode == "paste_only":
                        self.output_handler.paste_only(processed_text)
                    elif output_mode == "type_send":
                        self.output_handler.type_and_send(processed_text, send_key)
                    elif output_mode == "type_only":
                        self.output_handler.type_text(processed_text)
                    else:
                        self.output_handler.copy_only(processed_text)

                    if CONFIG.get("sound_effects"):
                        self.output_handler.play_sound("Tink")

                    # Show notification
                    if CONFIG.get("show_notifications"):
                        preview = processed_text[:50] + "..." if len(processed_text) > 50 else processed_text
                        self.output_handler.show_notification(
                            "Voice to Claude",
                            preview
                        )

                    time.sleep(0.3)

            if self.running and not self.paused:
                self.set_state(State.READY)
                # Play ready sound if enabled
                if CONFIG.get("ready_sound"):
                    self.output_handler.play_sound("Pop")
                time.sleep(0.2)

# ============================================================================
# MAIN
# ============================================================================

def main():
    app = VoiceToClaudeApp()
    app.run()

if __name__ == "__main__":
    main()
