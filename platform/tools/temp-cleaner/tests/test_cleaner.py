from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cleaner_core import CleanerError, quarantine, restore, scan


class CleanerCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "platform"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, data: bytes = b"test") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_protected_assets_and_outputs_are_not_candidates(self) -> None:
        self.write("assets/material/icon.bmp")
        self.write("outputs/acceptance/evidence.json")
        self.write("packages/verified/a/manifest.json")
        result = scan(self.root, min_age_days=0)
        paths = {item.relative_path for item in result.candidates}
        self.assertFalse(any(path.startswith("assets/") for path in paths))
        self.assertFalse(any(path.startswith("outputs/") for path in paths))
        self.assertFalse(any(path.startswith("packages/") for path in paths))

    def test_cache_is_default_but_build_and_tmp_are_review_only(self) -> None:
        self.write("src/__pycache__/a.pyc")
        self.write("build/old-release/app.exe", b"release")
        self.write("tmp/old-evidence/report.json", b"{}")
        result = scan(self.root, min_age_days=0)
        by_path = {item.relative_path: item for item in result.candidates}
        self.assertTrue(by_path["src/__pycache__"].default_selected)
        self.assertFalse(by_path["build/old-release"].default_selected)
        self.assertFalse(by_path["tmp/old-evidence"].default_selected)

    def test_quarantine_and_restore_preserve_bytes(self) -> None:
        original = self.write("src/__pycache__/a.pyc", b"exact-bytes")
        result = scan(self.root, min_age_days=0)
        item = next(item for item in result.candidates if item.relative_path == "src/__pycache__")
        receipt = quarantine(result, [item.candidate_id])
        self.assertFalse(original.exists())
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "quarantined")
        restore(receipt)
        self.assertEqual(original.read_bytes(), b"exact-bytes")

    def test_changed_candidate_blocks_without_move(self) -> None:
        original = self.write("src/__pycache__/a.pyc", b"before")
        result = scan(self.root, min_age_days=0)
        item = next(item for item in result.candidates if item.relative_path == "src/__pycache__")
        original.write_bytes(b"after")
        with self.assertRaisesRegex(CleanerError, "已变化"):
            quarantine(result, [item.candidate_id])
        self.assertEqual(original.read_bytes(), b"after")

    def test_restore_refuses_overwrite(self) -> None:
        original = self.write("src/__pycache__/a.pyc", b"before")
        result = scan(self.root, min_age_days=0)
        item = next(item for item in result.candidates if item.relative_path == "src/__pycache__")
        receipt = quarantine(result, [item.candidate_id])
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"new-content")
        with self.assertRaisesRegex(CleanerError, "禁止覆盖"):
            restore(receipt)
        self.assertEqual(original.read_bytes(), b"new-content")


if __name__ == "__main__":
    unittest.main()

