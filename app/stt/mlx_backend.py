"""Lightning Whisper MLX transcription backend."""

from __future__ import annotations

from lightning_whisper_mlx import LightningWhisperMLX


class MlxTranscriptionBackend:
    """MLX-based speech-to-text backend."""

    def __init__(self, model_name="base"):
        self.model_name = model_name
        self.whisper = None

    def load_model(self, model_name=None):
        """Load the MLX Whisper model."""
        if model_name:
            self.model_name = model_name
        self.whisper = LightningWhisperMLX(
            model=self.model_name,
            batch_size=12,
            quant=None,
        )

    def transcribe(self, audio_file, language=None):
        """Transcribe an audio file and return raw text."""
        if not self.whisper:
            return None
        kwargs = {}
        if language:
            kwargs["language"] = language
        result = self.whisper.transcribe(audio_file, **kwargs)
        return result.get("text", "").strip()

