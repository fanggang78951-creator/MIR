from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class PortableExeBlackBoxTests(unittest.TestCase):
    def test_scan_quarantine_restore_round_trip(self) -> None:
        exe = Path(r"D:\XuanYuanDevPlatform\bin\XuanYuanTempCleaner.exe")
        if not exe.is_file():
            self.skipTest("portable EXE has not been built")

        with tempfile.TemporaryDirectory(prefix="XYDP_Cleaner_Blackbox_") as temp:
            root = Path(temp) / "platform"
            original = root / "src" / "__pycache__" / "sample.pyc"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"portable-exe-exact-bytes")
            report = root / "scan.json"

            scanned = subprocess.run(
                [str(exe), "scan", "--root", str(root), "--days", "0", "--output", str(report)],
                check=False,
                timeout=60,
            )
            self.assertEqual(scanned.returncode, 0)
            payload = json.loads(report.read_text(encoding="utf-8"))
            item = next(row for row in payload["candidates"] if row["relative_path"] == "src/__pycache__")

            quarantined = subprocess.run(
                [
                    str(exe),
                    "quarantine",
                    "--plan",
                    str(report),
                    "--candidate-id",
                    item["candidate_id"],
                    "--yes",
                ],
                check=False,
                timeout=60,
            )
            self.assertEqual(quarantined.returncode, 0)
            self.assertFalse(original.exists())
            receipts = list((root / "backups" / "cleanup_quarantine").glob("*/receipt.json"))
            self.assertEqual(len(receipts), 1)

            restored = subprocess.run(
                [str(exe), "restore", "--receipt", str(receipts[0]), "--yes"],
                check=False,
                timeout=60,
            )
            self.assertEqual(restored.returncode, 0)
            self.assertEqual(original.read_bytes(), b"portable-exe-exact-bytes")


if __name__ == "__main__":
    unittest.main()
