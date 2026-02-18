import unittest

from app.core.dictation import DictationProcessor


class CoreDictationTests(unittest.TestCase):
    def test_whole_word_command_does_not_mutate_substring(self):
        text = "periodic updates are useful"
        processed = DictationProcessor.process(
            text,
            enabled=True,
            auto_capitalize=False,
            smart_punctuation=False,
        )
        self.assertEqual(processed, text)

    def test_command_replacement_applies_on_word_boundary(self):
        processed = DictationProcessor.process(
            "hello period",
            enabled=True,
            auto_capitalize=False,
            smart_punctuation=False,
        )
        self.assertEqual(processed, "hello.")

    def test_control_command_detection(self):
        self.assertEqual(DictationProcessor.check_control_command("scratch that"), "SCRATCH")
        self.assertEqual(DictationProcessor.check_control_command("repeat that please"), "REPEAT")
        self.assertIsNone(DictationProcessor.check_control_command("normal sentence"))


if __name__ == "__main__":
    unittest.main()

