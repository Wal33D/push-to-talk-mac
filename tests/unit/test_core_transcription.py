import unittest

from app.core.transcription import TranscriptionEngine


class StubBackend:
    def __init__(self, text):
        self._text = text
        self.loaded_model_name = None
        self.calls = []

    def load_model(self, model_name=None):
        self.loaded_model_name = model_name

    def transcribe(self, audio_file, language=None, initial_prompt=None):
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

        with self.assertLogs("pusha", level="WARNING") as logs:
            result = engine.transcribe("clip.wav")

        self.assertIsNone(result)
        self.assertTrue(any("HALLUCINATION FILTER dropped" in line for line in logs.output))

    def test_transcribe_returns_text_when_valid(self):
        backend = StubBackend("hello from test")
        engine = TranscriptionEngine(model_name="base", language="en", backend=backend)

        result = engine.transcribe("clip.wav")

        self.assertEqual(result, "hello from test")

    def test_short_valid_speech_not_filtered(self):
        """Short utterances like 'Yeah', 'OK', 'Thanks' must NOT be filtered."""
        engine = TranscriptionEngine(model_name="base", language="en")
        valid_phrases = ["Yeah", "OK", "Thanks", "Hmm", "Sure", "Bye", "Nope", "Yep"]
        for phrase in valid_phrases:
            backend = StubBackend(phrase)
            engine_instance = TranscriptionEngine(model_name="base", language="en", backend=backend)
            result = engine_instance.transcribe("clip.wav")
            self.assertEqual(result, phrase, f"'{phrase}' was wrongly filtered")

    def test_whisper_artifacts_filtered(self):
        """Known Whisper artifacts must be filtered."""
        engine = TranscriptionEngine(model_name="base", language="en")
        artifacts = [
            "Thanks for watching",
            "Please subscribe",
            "Transcribed by AI",
            "♪♪♪",
            "1.5",
            "...",
            "[Music]",
            "(applause)",
        ]
        for artifact in artifacts:
            backend = StubBackend(artifact)
            engine_instance = TranscriptionEngine(model_name="base", language="en", backend=backend)
            result = engine_instance.transcribe("clip.wav")
            self.assertIsNone(result, f"'{artifact}' should have been filtered as hallucination")

    def test_empty_and_whitespace_filtered(self):
        """Empty or whitespace-only text returns None."""
        for text in ["", "   ", None]:
            backend = StubBackend(text)
            engine = TranscriptionEngine(model_name="base", language="en", backend=backend)
            result = engine.transcribe("clip.wav")
            self.assertIsNone(result, f"'{text}' should return None")

    def test_normal_sentences_pass(self):
        """Normal dictated sentences must pass through."""
        sentences = [
            "Send me the file please",
            "I'll be there in 5 minutes",
            "Can you check the pull request",
            "Hey what's up",
            "Thank you so much for helping",
        ]
        for sentence in sentences:
            backend = StubBackend(sentence)
            engine = TranscriptionEngine(model_name="base", language="en", backend=backend)
            result = engine.transcribe("clip.wav")
            self.assertEqual(result, sentence, f"'{sentence}' was wrongly filtered")

    def test_excessive_repetition_filtered(self):
        """Text with extreme word repetition is filtered."""
        backend = StubBackend("the the the the the the the the")
        engine = TranscriptionEngine(model_name="base", language="en", backend=backend)
        result = engine.transcribe("clip.wav")
        self.assertIsNone(result, "Excessive repetition should be filtered")


if __name__ == "__main__":
    unittest.main()
