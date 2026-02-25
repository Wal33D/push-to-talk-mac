import unittest

from app.core.transcription import TranscriptionEngine


class StubBackend:
    def __init__(self, text):
        self._text = text
        self.loaded_model_name = None
        self.calls = []

    def load_model(self, model_name=None):
        self.loaded_model_name = model_name

    def transcribe(self, audio_file, language=None):
        self.calls.append((audio_file, language))
        return self._text


class CoreTranscriptionTests(unittest.TestCase):
    def test_load_model_delegates_to_backend(self):
        backend = StubBackend("hello world")
        engine = TranscriptionEngine(model_name="base", language="en", backend=backend)

        engine.load_model()

        self.assertEqual(backend.loaded_model_name, "base")

    def test_transcribe_returns_none_when_backend_not_ready(self):
        backend = StubBackend(None)
        engine = TranscriptionEngine(model_name="base", language="en", backend=backend)

        result = engine.transcribe("clip.wav")

        self.assertIsNone(result)
        self.assertEqual(backend.calls, [("clip.wav", "en")])

    def test_transcribe_filters_hallucination(self):
        backend = StubBackend("1.5")
        engine = TranscriptionEngine(model_name="base", language="en", backend=backend)

        with self.assertLogs("dictator", level="WARNING") as logs:
            result = engine.transcribe("clip.wav")

        self.assertIsNone(result)
        self.assertTrue(any("HALLUCINATION FILTER dropped" in line for line in logs.output))

    def test_transcribe_returns_text_when_valid(self):
        backend = StubBackend("hello from test")
        engine = TranscriptionEngine(model_name="base", language="en", backend=backend)

        result = engine.transcribe("clip.wav")

        self.assertEqual(result, "hello from test")


if __name__ == "__main__":
    unittest.main()
