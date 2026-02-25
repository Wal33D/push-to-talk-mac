import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import history


class CoreHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._file = Path(self._tmp) / "history.json"
        self._patches = [
            patch.object(history, "HISTORY_FILE", self._file),
            patch.object(history, "CONFIG_DIR", Path(self._tmp)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        if self._file.exists():
            self._file.unlink()

    def test_add_creates_entry(self):
        entry = history.add("hello world")
        self.assertEqual(entry["text"], "hello world")
        self.assertEqual(entry["word_count"], 2)
        self.assertIn("id", entry)
        self.assertIn("timestamp", entry)

    def test_add_persists_to_disk(self):
        history.add("first")
        history.add("second")
        with open(self._file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["text"], "second")  # newest first

    def test_get_all_returns_entries(self):
        history.add("one")
        history.add("two")
        entries = history.get_all()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["text"], "two")

    def test_search_filters_by_text(self):
        history.add("the quick brown fox")
        history.add("lazy dog")
        results = history.search("fox")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], "the quick brown fox")

    def test_search_is_case_insensitive(self):
        history.add("Hello World")
        results = history.search("hello")
        self.assertEqual(len(results), 1)

    def test_delete_removes_entry(self):
        entry = history.add("delete me")
        self.assertTrue(history.delete(entry["id"]))
        self.assertEqual(len(history.get_all()), 0)

    def test_delete_returns_false_for_missing_id(self):
        self.assertFalse(history.delete("nonexistent"))

    def test_clear_removes_all(self):
        history.add("a")
        history.add("b")
        removed = history.clear()
        self.assertEqual(removed, 2)
        self.assertEqual(len(history.get_all()), 0)

    def test_count(self):
        self.assertEqual(history.count(), 0)
        history.add("x")
        self.assertEqual(history.count(), 1)

    def test_max_entries_cap(self):
        with patch.object(history, "MAX_ENTRIES", 3):
            for i in range(5):
                history.add(f"entry {i}")
            self.assertEqual(len(history.get_all()), 3)
            self.assertEqual(history.get_all()[0]["text"], "entry 4")  # newest
