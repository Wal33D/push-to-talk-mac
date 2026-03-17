"""Lightning Whisper MLX transcription backend."""

from __future__ import annotations

from lightning_whisper_mlx import LightningWhisperMLX
from lightning_whisper_mlx.transcribe import transcribe_audio


class MlxTranscriptionBackend:
    """MLX-based speech-to-text backend."""

    def __init__(self, model_name="base"):
        self.model_name = model_name
        self.whisper = None
        self._model_path = None

    def load_model(self, model_name=None):
        """Load the MLX Whisper model."""
        if model_name:
            self.model_name = model_name
        self.whisper = LightningWhisperMLX(
            model=self.model_name,
            batch_size=12,
            quant=None,
        )
        self._model_path = f"./mlx_models/{self.model_name}"

    def transcribe(self, audio_file, language=None, initial_prompt=None):
        """Transcribe an audio file and return raw text."""
        if not self.whisper:
            return None
        # Use transcribe_audio directly to access initial_prompt parameter
        # that the LightningWhisperMLX wrapper doesn't expose
        if initial_prompt and self._model_path:
            kwargs = {"batch_size": self.whisper.batch_size}
            if language:
                kwargs["language"] = language
            result = transcribe_audio(
                audio_file,
                path_or_hf_repo=self._model_path,
                initial_prompt=initial_prompt,
                **kwargs,
            )
        else:
            kwargs = {}
            if language:
                kwargs["language"] = language
            result = self.whisper.transcribe(audio_file, **kwargs)
        return result.get("text", "").strip()

