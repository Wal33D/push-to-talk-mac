"""Transcription backend protocol."""

from __future__ import annotations

from typing import Protocol


class TranscriptionBackend(Protocol):
    """Platform/model-specific speech-to-text backend."""

    def load_model(self, model_name: str | None = None) -> None:
        """Load or initialize model resources."""

    def transcribe(self, audio_file: str, language: str | None = None) -> str | None:
        """Transcribe audio from file path to text."""
