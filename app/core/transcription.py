"""Transcription engine orchestration and filtering."""

from __future__ import annotations

import logging
import re

from app.stt.base import TranscriptionBackend
from app.stt.mlx_backend import MlxTranscriptionBackend

LOG = logging.getLogger("vtc")


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

    def transcribe(self, audio_file):
        """Transcribe an audio file to text."""
        try:
            text = self.backend.transcribe(audio_file, language=self.language)
            if text is None:
                return None
            text = text.strip()
            LOG.info(f"Raw whisper output: {repr(text)}")

            if not text or len(text) < 3:
                LOG.warning(f"Text too short, discarding: {repr(text)}")
                return None

            if self._is_hallucination(text):
                LOG.warning(f"HALLUCINATION FILTER dropped: {repr(text)}")
                return None

            return text
        except Exception as exc:
            LOG.error(f"Transcription error: {exc}", exc_info=True)
            return None

    def _is_hallucination(self, text):
        """Filter out Whisper hallucinations (junk output on noise)."""
        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        # Very short text is often hallucination
        if len(text_stripped) < 3:
            return True

        # Just numbers, percentages, or decimals (e.g., "1.5%", "2.0", "1.1.1")
        if re.match(r"^[\d\.\,\%\s\-]+$", text_stripped):
            return True

        # Just punctuation and numbers
        if re.match(r"^[\d\.\,\%\s\-\!\?\.\,\:\;]+$", text_stripped):
            return True

        # Timestamps like "00:00", "1:23", "12:34:56"
        if re.match(r"^[\d\:\s]+$", text_stripped):
            return True

        # Music notes, symbols, special characters
        if re.match(r"^[♪♫♬\*\-\_\.\s]+$", text_stripped):
            return True

        # Foreign characters that are likely noise (Chinese/Japanese/Korean single chars)
        if len(text_stripped) <= 3 and re.match(r"^[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]+$", text_stripped):
            return True

        # Common junk patterns (Whisper hallucinations)
        junk_patterns = [
            # Numbers and decimals
            "1.1",
            "1.5",
            "2.0",
            "0.5",
            "1.0",
            "2.5",
            "3.0",
            # Symbols
            "...",
            "♪",
            "***",
            "---",
            "___",
            "…",
            "・・・",
            # YouTube/video endings
            "Thank you",
            "Thanks for watching",
            "Thanks for listening",
            "Subscribe",
            "Bye",
            "See you",
            "Goodbye",
            "See you next time",
            "Please subscribe",
            "Like and subscribe",
            "Hit the bell",
            "Thank you for watching",
            "You're welcome",
            "Don't forget to",
            # Whisper artifacts
            "I'm sorry",
            "Hmm",
            "Uh",
            "Um",
            "Huh",
            "silence",
            "music",
            "applause",
            "laughter",
            "background noise",
            "[Music]",
            "[Applause]",
            "[Laughter]",
            "(music)",
            "(applause)",
            # Very short common words (when alone)
            "you",
            "the",
            "a",
            "to",
            "is",
            "it",
            "and",
            "of",
            "in",
            "on",
            # Sounds
            "Shhh",
            "Shh",
            "Ssh",
            "Psst",
            "Sss",
            "Mm-hmm",
            "Uh-huh",
            "Mhm",
            "Mmm",
            "Uh huh",
            "Oh",
            "Ah",
            "Eh",
            "Ooh",
            "Aah",
            "Yeah",
            "Yep",
            "Nope",
            "Yup",
            "Nah",
            "Ha",
            "Haha",
            "Hehe",
            "Lol",
            # Attribution text
            "Transcribed by",
            "Subtitles by",
            "Translated by",
            "Copyright",
            "All rights reserved",
            "www.",
            "http",
            # Repeated sounds
            "la la la",
            "da da da",
            "na na na",
            "doo doo",
            # Breathing/ambient
            "breathing",
            "sighs",
            "coughs",
            "sniffs",
        ]

        # Check for exact matches (short hallucinations)
        if text_lower in [p.lower() for p in junk_patterns]:
            return True

        # Check for patterns that start with common hallucinations
        hallucination_starts = [
            "thank you for",
            "thanks for",
            "please subscribe",
            "don't forget",
            "see you",
            "bye bye",
            "goodbye",
            "transcribed by",
            "subtitles by",
            "translated by",
        ]
        for start in hallucination_starts:
            if text_lower.startswith(start):
                return True

        # Check for repeated patterns — but ONLY in short text (< 8 words).
        # In longer text, common words like "to", "you", "the" naturally repeat.
        words = text.split()
        if len(words) <= 8:
            for pattern in junk_patterns:
                if len(pattern) <= 3:
                    word_count = len(re.findall(r"\b" + re.escape(pattern) + r"\b", text_lower, re.IGNORECASE))
                    if word_count > 2:
                        LOG.debug(f"Hallucination: short pattern '{pattern}' repeated {word_count}x in short text")
                        return True
                else:
                    if text.count(pattern) > 2 or text_lower.count(pattern.lower()) > 2:
                        LOG.debug(f"Hallucination: long pattern '{pattern}' repeated >2x")
                        return True

        # Check if mostly non-alphanumeric
        alpha_count = sum(1 for c in text if c.isalpha())
        if len(text_stripped) > 5 and alpha_count < len(text_stripped) * 0.3:
            return True

        # Check for excessive repetition (same word repeated)
        words = text.split()
        if len(words) > 3:
            unique_words = set(w.lower() for w in words)
            if len(unique_words) < len(words) * 0.3:
                return True

        # Check for stuttering pattern (word repeated immediately)
        if len(words) >= 2:
            repeated_count = sum(1 for i in range(len(words) - 1) if words[i].lower() == words[i + 1].lower())
            if repeated_count >= len(words) // 2:
                return True

        # Single word that's just a number or very short
        if len(words) == 1 and (text_stripped.replace(".", "").replace("%", "").isdigit() or len(text_stripped) < 4):
            return True

        # Check for all-caps short text (often noise)
        if len(text_stripped) < 10 and text_stripped.isupper() and text_stripped.isalpha():
            return True

        return False
