"""Persistent transcription history backed by a JSON file."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import CONFIG_DIR

LOG = logging.getLogger("dictator")

HISTORY_FILE = CONFIG_DIR / "history.json"
MAX_ENTRIES = 500


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _load_raw() -> list[dict]:
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as exc:
        LOG.warning("Failed to load history from %s: %s", HISTORY_FILE, exc)
    return []


def _save_raw(entries: list[dict]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)
        tmp.replace(HISTORY_FILE)
    except Exception as exc:
        LOG.warning("Failed to save history to %s: %s", HISTORY_FILE, exc)


def add(text: str) -> dict:
    """Append a transcription and return the new entry."""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": _now_iso(),
        "text": text,
        "word_count": len(text.split()),
    }
    entries = _load_raw()
    entries.insert(0, entry)
    entries = entries[:MAX_ENTRIES]
    _save_raw(entries)
    return entry


def get_all() -> list[dict]:
    """Return all history entries, newest first."""
    return _load_raw()


def search(query: str) -> list[dict]:
    """Return entries whose text contains *query* (case-insensitive)."""
    q = query.lower()
    return [e for e in _load_raw() if q in e.get("text", "").lower()]


def delete(entry_id: str) -> bool:
    """Delete a single entry by id. Returns True if found."""
    entries = _load_raw()
    before = len(entries)
    entries = [e for e in entries if e.get("id") != entry_id]
    if len(entries) < before:
        _save_raw(entries)
        return True
    return False


def clear() -> int:
    """Delete all history. Returns the count removed."""
    entries = _load_raw()
    count = len(entries)
    if count:
        _save_raw([])
    return count


def count() -> int:
    """Return total number of stored entries."""
    return len(_load_raw())
