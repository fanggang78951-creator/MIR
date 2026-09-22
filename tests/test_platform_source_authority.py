from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.platform_source_authority import inventory_source, load_policy


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.policy_path = self.root / "policy.json"
        self.write_policy()

    def write_policy(self, **overrides: object) -> None:
        policy: dict[str, object] = {
            "schemaVersion": 1,
            "includeDirectories": ["src", "tests"],
            "rootFiles": ["README.md"],
            "excludeDirectoryNames": ["__pycache__", ".git"],
            "excludeSuffixes": [".pyc", ".log"],
            "sensitiveNamePatterns": [r"(?i)(^|/)(\.env|.*secret.*|.*token.*)$"],
            "maxFileBytes": 16,
        }
        policy.update(overrides)
        self.policy_path.write_text(
            json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def make_source_tree(self) -> bool:
        (self.source / "src" / "xydp").mkdir(parents=True)
        (self.source / "tests").mkdir()
        (self.source / "packages").mkdir()
        (self.source / "src" / "__pycache__").mkdir()
        (self.source / "README.md").write_bytes(b"platform\n")
        (self.source / "src" / "xydp" / "app.py").write_bytes(b"print('ok')\n")
        (self.source / "src" / "big.txt").write_bytes(b"x" * 17)
        (self.source / "tests" / ".env").write_bytes(b"not-read")
        (self.source / "src" / "__pycache__" / "app.pyc").write_bytes(b"cache")
        (self.source / "packages" / "ignored.pak").write_bytes(b"ignored")

        outside = self.root / "outside"
        outside.mkdir()
        (outside / "escaped.py").write_bytes(b"escape")
        link = self.source / "src" / "linked"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError:
            return False
        return True

    def test_inventory_is_deterministic_and_blocks_unsafe_entries(self) -> None:
        link_created = self.make_source_tree()

        report = inventory_source(self.source, load_policy(self.policy_path))

        self.assertEqual(
            [entry["path"] for entry in report["files"]],
            ["README.md", "src/xydp/app.py"],
        )
        app_entry = report["files"][1]
        self.assertEqual(
            app_entry["sha256"], hashlib.sha256(b"print('ok')\n").hexdigest()
        )
        self.assertEqual(
            report["sourceFingerprint"],
            inventory_source(self.source, load_policy(self.policy_path))[
                "sourceFingerprint"
            ],
        )
        expected = {"sensitive-name", "file-too-large"}
        if link_created:
            expected.add("reparse-point")
        self.assertEqual({item["code"] for item in report["blockers"]}, expected)
        self.assertEqual(report["summary"]["managedFiles"], 2)
        self.assertEqual(report["summary"]["blockers"], len(expected))

    def test_policy_rejects_absolute_and_parent_paths(self) -> None:
        for bad in [str(self.root.resolve()), "../outside", "src/../../outside"]:
            with self.subTest(path=bad):
                self.write_policy(includeDirectories=[bad])
                with self.assertRaisesRegex(ValueError, "relative"):
                    load_policy(self.policy_path)

    def test_policy_requires_positive_file_limit(self) -> None:
        self.write_policy(maxFileBytes=0)
        with self.assertRaisesRegex(ValueError, "maxFileBytes"):
            load_policy(self.policy_path)

    def test_cli_exit_code_and_source_are_read_only(self) -> None:
        self.make_source_tree()
        before = {
            path.relative_to(self.source).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in self.source.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        output = self.root / "report.json"

        completed = subprocess.run(
            [
                sys.executable,
                "tools/platform_source_authority.py",
                "inventory",
                "--source-root",
                str(self.source),
                "--policy",
                str(self.policy_path),
                "--output",
                str(output),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertGreater(json.loads(output.read_text(encoding="utf-8"))["summary"]["blockers"], 0)
        after = {
            path.relative_to(self.source).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in self.source.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
