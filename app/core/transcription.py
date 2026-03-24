"""Transcription engine orchestration and filtering."""

from __future__ import annotations

import logging
import re

from app.stt.base import TranscriptionBackend
from app.stt.mlx_backend import MlxTranscriptionBackend

LOG = logging.getLogger("pusha")


class TranscriptionEngine:
    """Handles speech-to-text using pluggable backend."""

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

    def __init__(self, model_name="base", language=None, backend: TranscriptionBackend | None = None):
        self.model_name = model_name
        self.language = language
        self.backend: TranscriptionBackend = backend or MlxTranscriptionBackend(model_name=model_name)

    def load_model(self):
        """Load the Whisper model."""
        self.backend.load_model(model_name=self.model_name)

    def set_language(self, language):
        """Set the transcription language."""
        self.language = language

    def transcribe(self, audio_file, initial_prompt=None):
        """Transcribe an audio file to text."""
        try:
            text = self.backend.transcribe(
                audio_file, language=self.language, initial_prompt=initial_prompt
            )
            if text is None:
                return None
            text = text.strip()
            LOG.info(f"Raw whisper output: {repr(text)}")

            if not text:
                LOG.warning("Text was empty after strip")
                return None

            if self._is_hallucination(text):
                LOG.warning(f"HALLUCINATION FILTER dropped: {repr(text)}")
                return None

            return text
        except Exception as exc:
            LOG.error(f"Transcription error: {exc}", exc_info=True)
            return None

    def _is_hallucination(self, text):
        """Filter out Whisper hallucinations (junk output on noise).

        IMPORTANT: This filter should be CONSERVATIVE. Only filter patterns
        that are definitively Whisper artifacts, never valid user speech.
        False positives (filtering real speech) are much worse than false
        negatives (letting through occasional junk).
        """
        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        # Just numbers, percentages, or decimals (e.g., "1.5%", "2.0")
        if re.match(r"^[\d\.\,\%\s\-]+$", text_stripped):
            return True

        # Just punctuation, numbers, and whitespace
        if re.match(r"^[\d\.\,\%\s\-\!\?\:\;]+$", text_stripped):
            return True

        # Music notes, symbols, special characters only
        if re.match(r"^[♪♫♬\*\-\_\.\s…]+$", text_stripped):
            return True

        # Whisper metadata hallucinations (bracketed/parenthesized descriptions)
        if re.match(r"^\[.*\]$", text_stripped) or re.match(r"^\(.*\)$", text_stripped):
            return True

        # Definitive Whisper hallucination patterns — things a real user
        # would NEVER intentionally dictate
        hallucination_exact = [
            "thanks for watching",
            "thanks for listening",
            "please subscribe",
            "like and subscribe",
            "hit the bell",
            "thank you for watching",
            "don't forget to subscribe",
            "see you next time",
            "transcribed by",
            "subtitles by",
            "translated by",
            "copyright",
            "all rights reserved",
        ]

        if text_lower in hallucination_exact:
            return True

        # Patterns that START with definitive hallucinations
        hallucination_starts = [
            "thank you for watching",
            "thanks for watching",
            "please subscribe",
            "don't forget to subscribe",
            "transcribed by",
            "subtitles by",
            "translated by",
        ]
        for start in hallucination_starts:
            if text_lower.startswith(start):
                return True

        # URLs (Whisper sometimes hallucinates URLs)
        if text_lower.startswith("www.") or text_lower.startswith("http"):
            return True

        # Excessive repetition (same word/phrase repeated 4+ times)
        words = text.split()
        if len(words) > 4:
            unique_words = set(w.lower() for w in words)
            if len(unique_words) == 1:
                return True  # All same word
            if len(unique_words) < len(words) * 0.2:
                return True  # >80% repeated

        # Check if mostly non-alphanumeric (symbols/noise)
        alpha_count = sum(1 for c in text if c.isalpha())
        if len(text_stripped) > 5 and alpha_count < len(text_stripped) * 0.3:
            return True

        return False
