"""Core platform-agnostic application logic."""

from app.core.audio import AudioEngine
from app.core.config import (
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    VALID_OUTPUT_MODES,
    load_config,
    normalize_config,
    save_config,
)
from app.core.dictation import DictationProcessor
from app.core.state import AppState, STATE_DESCRIPTIONS, STATE_ICONS
from app.core.transcription import TranscriptionEngine
from app.core import history

__all__ = [
    "AppState",
    "STATE_ICONS",
    "STATE_DESCRIPTIONS",
    "AudioEngine",
    "DictationProcessor",
    "TranscriptionEngine",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "DEFAULT_CONFIG",
    "VALID_OUTPUT_MODES",
    "load_config",
    "normalize_config",
    "save_config",
    "history",
]
