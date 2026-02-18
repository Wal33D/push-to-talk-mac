"""Shared application state values."""

from enum import Enum


class AppState(str, Enum):
    """High-level user-visible app states."""

    LOADING = "loading"
    READY = "ready"
    SPEAKING = "speaking"
    PROCESSING = "processing"
    SENDING = "sending"
    PAUSED = "paused"
    ERROR = "error"


STATE_ICONS = {
    AppState.LOADING: "⏳",
    AppState.READY: "🎤",
    AppState.SPEAKING: "🗣",
    AppState.PROCESSING: "⚙️",
    AppState.SENDING: "📤",
    AppState.PAUSED: "⏸",
    AppState.ERROR: "❌",
}

STATE_DESCRIPTIONS = {
    AppState.LOADING: "Loading Whisper model...",
    AppState.READY: "PTT Ready — Hold Fn to speak",
    AppState.SPEAKING: "Recording your speech...",
    AppState.PROCESSING: "Transcribing audio...",
    AppState.SENDING: "Pasting to active window...",
    AppState.PAUSED: "Paused - click to resume",
    AppState.ERROR: "Error - check console",
}
