import tempfile
import unittest
from pathlib import Path

from app.core import config as core_config


class CoreConfigTests(unittest.TestCase):
    def test_normalize_output_mode_fallback_uses_auto_send(self):
        cfg = core_config.normalize_config({"output_mode": "invalid-mode", "auto_send": False})
        self.assertEqual(cfg["output_mode"], "paste_only")
        self.assertFalse(cfg["auto_send"])

    def test_normalize_output_mode_updates_auto_send_for_send_modes(self):
        cfg_send = core_config.normalize_config({"output_mode": "type_send", "auto_send": False})
        self.assertEqual(cfg_send["output_mode"], "type_send")
        self.assertTrue(cfg_send["auto_send"])

        cfg_no_send = core_config.normalize_config({"output_mode": "type_only", "auto_send": True})
        self.assertEqual(cfg_no_send["output_mode"], "type_only")
        self.assertFalse(cfg_no_send["auto_send"])

    def test_load_save_round_trip_uses_normalization(self):
        original_dir = core_config.CONFIG_DIR
        original_file = core_config.CONFIG_FILE

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                core_config.CONFIG_DIR = Path(tmpdir)
                core_config.CONFIG_FILE = core_config.CONFIG_DIR / "config.json"

                core_config.save_config({"output_mode": "type_send", "auto_send": False})
                loaded = core_config.load_config()

                self.assertEqual(loaded["output_mode"], "type_send")
                self.assertTrue(loaded["auto_send"])
                self.assertEqual(loaded["model"], "base")
        finally:
            core_config.CONFIG_DIR = original_dir
            core_config.CONFIG_FILE = original_file


if __name__ == "__main__":
    unittest.main()

