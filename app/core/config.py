"""Application configuration management."""

from __future__ import annotations

import json
import logging
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "pusha-talk"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    # Model - "base" for speed, "small" for accuracy
    "model": "base",
    # Audio settings
    "rate": 16000,
    "chunk": 640,  # 640 samples = 40ms at 16kHz, aligned with Whisper HOP_LENGTH
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
    # Wispr Flow-inspired enhancements
    "clipboard_restore": True,  # Restore clipboard after paste operations
    "haptic_feedback": True,  # Haptic feedback on PTT press/release (Force Touch)
    "context_aware": True,  # Send focused app name as Whisper initial_prompt
    "vad_silence_threshold": 500,  # Energy threshold for VAD tail buffer
    "vad_tail_max": 1.5,  # Max seconds to continue recording after key release
    "auto_output_mode": False,  # Auto-select output mode based on focused app
    "noise_gate": 50,  # RMS threshold below which audio is considered ambient noise
    "per_app_config": {},  # Per-app overrides: {"bundle_id": {"output_mode": "...", "send_key": "..."}}
    "hud_position": "bottom",  # HUD position: "bottom" or "top"
}

VALID_OUTPUT_MODES = {"paste_send", "paste_only", "type_send", "type_only", "copy_only"}

# Legacy default values that we now know were too aggressive and silently
# broke recordings. Migrated forward on load. Keys are config field names,
# values are (legacy_value, new_value) pairs. Add new entries here whenever
# we lower a default that already shipped to users.
LEGACY_DEFAULT_MIGRATIONS = {
    "noise_gate": (150, 50),
}

_LOG = logging.getLogger("pusha")


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


def migrate_legacy_defaults(config):
    """Bump fields that still hold a known-bad legacy default to the new one.

    Why: when we lower a default in code (e.g. noise_gate 150 -> 50), users
    with an existing config keep the old value forever, so the fix never
    reaches them. This walks the LEGACY_DEFAULT_MIGRATIONS table and rewrites
    matching values in place. Returns (config, changed) so callers can persist
    the new values.
    """
    if not isinstance(config, dict):
        return config, False
    changed = False
    for key, (legacy_value, new_value) in LEGACY_DEFAULT_MIGRATIONS.items():
        if config.get(key) == legacy_value:
            _LOG.info(
                f"Migrating legacy default for {key}: {legacy_value} -> {new_value}"
            )
            config[key] = new_value
            changed = True
    return config, changed


def load_config():
    """Load config from file or create default."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            normalized = normalize_config(saved)
            normalized, changed = migrate_legacy_defaults(normalized)
            if changed:
                save_config(normalized)
            return normalized
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

