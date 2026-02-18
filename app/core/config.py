"""Application configuration management."""

from __future__ import annotations

import json
import logging
from pathlib import Path

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
    "output_mode": "paste_send",
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

VALID_OUTPUT_MODES = {"paste_send", "paste_only", "type_send", "type_only", "copy_only"}

_LOG = logging.getLogger("vtc")


def normalize_config(config):
    """Normalize config data and keep backward compatibility for older keys."""
    normalized = DEFAULT_CONFIG.copy()
    if isinstance(config, dict):
        normalized.update(config)

    output_mode = normalized.get("output_mode")
    if output_mode not in VALID_OUTPUT_MODES:
        output_mode = "paste_send" if normalized.get("auto_send", True) else "paste_only"
    normalized["output_mode"] = output_mode
    normalized["auto_send"] = output_mode in {"paste_send", "type_send"}
    return normalized


def load_config():
    """Load config from file or create default."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
                return normalize_config(saved)
    except Exception as exc:
        _LOG.warning(f"Failed to load config from {CONFIG_FILE}: {exc}")
    return normalize_config({})


def save_config(config):
    """Save config to file."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        normalized = normalize_config(config)
        tmp_path = CONFIG_FILE.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=2)
        tmp_path.replace(CONFIG_FILE)
    except Exception as exc:
        _LOG.warning(f"Failed to save config to {CONFIG_FILE}: {exc}")

