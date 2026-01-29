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
import threading
import tempfile
import wave
import time
import subprocess
import array

# Set working directory for model cache
os.chdir(os.path.expanduser("~"))

import pyaudio
import pyperclip
import rumps

__version__ = "1.0.0"
__author__ = "Waleed Judah"

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    # Model - "base" for speed, "small" for accuracy
    "model": "base",

    # Audio settings
    "rate": 16000,
    "chunk": 1024,
    "channels": 1,

    # Voice detection
    "silence_threshold": 800,
    "speech_threshold": 1500,  # Tuned for typical room noise
    "silence_duration": 1.0,   # Seconds of silence before stopping
    "min_speech_duration": 0.3,

    # Behavior
    "auto_send": True,  # Paste + Enter (False = just paste)
}

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

    def get_audio_level(self, data):
        """Calculate the peak audio level from raw bytes."""
        audio_data = array.array('h', data)
        return max(abs(sample) for sample in audio_data) if audio_data else 0

    def record_until_silence(self):
        """Record audio until speech is detected, then stop after silence."""
        p = pyaudio.PyAudio()

        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=self.config["channels"],
                rate=self.config["rate"],
                input=True,
                frames_per_buffer=self.config["chunk"]
            )
        except Exception:
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

        except Exception:
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
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.config["rate"])
                wf.writeframes(b''.join(frames))
                wf.close()
                return f.name
        except Exception:
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
            "1.1", "...", "♪", "***", "---",
            "Thank you", "Thanks for watching",
            "Subscribe", "Bye", "See you",
        ]

        for pattern in junk_patterns:
            if text.count(pattern) > 2:
                return True

        alpha_count = sum(1 for c in text if c.isalnum() or c.isspace())
        if len(text) > 5 and alpha_count < len(text) * 0.5:
            return True

        words = text.split()
        if len(words) > 3:
            unique_words = set(words)
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

        # Build menu
        self.status_item = rumps.MenuItem("Status: Loading...")

        self.sensitivity_menu = rumps.MenuItem("Sensitivity")
        for name, value in self.sensitivity_levels.items():
            item = rumps.MenuItem(name, callback=self.set_sensitivity)
            if value == CONFIG["speech_threshold"]:
                item.state = 1
            self.sensitivity_menu.add(item)

        self.auto_send_item = rumps.MenuItem(
            "Auto-Send (Enter after paste)",
            callback=self.toggle_auto_send
        )
        self.auto_send_item.state = 1 if CONFIG["auto_send"] else 0

        self.menu = [
            rumps.MenuItem("Pause", callback=self.toggle_pause),
            self.sensitivity_menu,
            self.auto_send_item,
            None,
            self.status_item,
        ]

        # Start background threads
        self.start_background_threads()

    def set_state(self, state):
        """Update current state and menu bar icon."""
        self.state = state
        self.title = STATE_ICONS.get(state, "🎤")
        try:
            self.status_item.title = f"Status: {state.capitalize()}"
        except:
            pass

    def toggle_pause(self, sender):
        """Toggle pause/resume listening."""
        if self.paused:
            self.paused = False
            self.audio_engine.paused = False
            sender.title = "Pause"
            self.set_state(State.READY)
        else:
            self.paused = True
            self.audio_engine.paused = True
            sender.title = "Resume"
            self.set_state(State.PAUSED)

    def set_sensitivity(self, sender):
        """Change microphone sensitivity."""
        new_threshold = self.sensitivity_levels.get(sender.title, 1500)
        CONFIG["speech_threshold"] = new_threshold
        self.audio_engine.config["speech_threshold"] = new_threshold

        for item in self.sensitivity_menu.values():
            item.state = 1 if item.title == sender.title else 0

    def toggle_auto_send(self, sender):
        """Toggle auto-send (Enter after paste)."""
        CONFIG["auto_send"] = not CONFIG["auto_send"]
        sender.state = 1 if CONFIG["auto_send"] else 0

    def start_background_threads(self):
        """Start model loading and listening threads."""
        load_thread = threading.Thread(target=self._load_model, daemon=True)
        load_thread.start()

    def _load_model(self):
        """Load the Whisper model in background."""
        try:
            self.transcription_engine.load_model()
            self.set_state(State.READY)

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

                    if CONFIG["auto_send"]:
                        self.output_handler.paste_and_send(text)
                    else:
                        self.output_handler.paste_only(text)

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
