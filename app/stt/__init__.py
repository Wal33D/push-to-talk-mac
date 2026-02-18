"""Speech-to-text backend abstractions and implementations."""

from app.stt.base import TranscriptionBackend
from app.stt.mlx_backend import MlxTranscriptionBackend

__all__ = ["TranscriptionBackend", "MlxTranscriptionBackend"]
