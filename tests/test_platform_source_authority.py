from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.platform_source_authority import (
    SourceAuthorityError,
    apply_bootstrap,
    inventory_source,
    load_policy,
    plan_bootstrap,
)


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


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.mirror = self.root / "mirror"
        (self.source / "src" / "xydp").mkdir(parents=True)
        self.mirror.mkdir()
        self.readme_bytes = b"platform\n"
        self.app_bytes = b"print('ok')\n"
        (self.source / "README.md").write_bytes(self.readme_bytes)
        (self.source / "src" / "xydp" / "app.py").write_bytes(self.app_bytes)
        os.utime(self.source / "src" / "xydp" / "app.py", ns=(1_700_000_000_000_000_000,) * 2)
        self.policy_path = self.root / "policy.json"
        self.policy_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "includeDirectories": ["src"],
                    "rootFiles": ["README.md"],
                    "excludeDirectoryNames": ["__pycache__"],
                    "excludeSuffixes": [".pyc"],
                    "sensitiveNamePatterns": [r"(?i)(^|/)\.env$"],
                    "maxFileBytes": 1024,
                }
            ),
            encoding="utf-8",
        )
        self.policy = load_policy(self.policy_path)

    def test_empty_mirror_plans_only_create_actions(self) -> None:
        plan = plan_bootstrap(self.source, self.mirror, self.policy)

        self.assertEqual([item["action"] for item in plan["changes"]], ["create", "create"])
        self.assertEqual([item["path"] for item in plan["changes"]], ["README.md", "src/xydp/app.py"])
        self.assertEqual(plan["blockers"], [])
        self.assertFalse(plan["isNoop"])

    def test_same_destination_is_unchanged(self) -> None:
        (self.mirror / "README.md").write_bytes(self.readme_bytes)

        plan = plan_bootstrap(self.source, self.mirror, self.policy)

        self.assertEqual(plan["changes"][0]["action"], "unchanged")
        self.assertEqual(plan["changes"][1]["action"], "create")

    def test_bootstrap_refuses_to_overwrite_different_destination(self) -> None:
        (self.mirror / "src" / "xydp").mkdir(parents=True)
        destination = self.mirror / "src" / "xydp" / "app.py"
        destination.write_bytes(b"git work\n")

        plan = plan_bootstrap(self.source, self.mirror, self.policy)

        self.assertEqual(plan["blockers"][0]["code"], "destination-conflict")
        with self.assertRaises(SourceAuthorityError):
            apply_bootstrap(plan, confirmed=True)
        self.assertEqual(destination.read_bytes(), b"git work\n")

    def test_bootstrap_requires_confirmation(self) -> None:
        plan = plan_bootstrap(self.source, self.mirror, self.policy)
        with self.assertRaisesRegex(SourceAuthorityError, "confirmation"):
            apply_bootstrap(plan, confirmed=False)
        self.assertFalse((self.mirror / "README.md").exists())

    def test_bootstrap_copies_bytes_metadata_and_writes_snapshot(self) -> None:
        source_app = self.source / "src" / "xydp" / "app.py"
        source_mtime = source_app.stat().st_mtime_ns
        plan = plan_bootstrap(self.source, self.mirror, self.policy)

        result = apply_bootstrap(plan, confirmed=True)

        mirror_app = self.mirror / "src" / "xydp" / "app.py"
        self.assertEqual(mirror_app.read_bytes(), self.app_bytes)
        self.assertEqual(mirror_app.stat().st_mtime_ns, source_mtime)
        snapshot = json.loads(
            (self.mirror / "source-authority.snapshot.json").read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot["sourceFingerprint"], plan["sourceFingerprint"])
        self.assertEqual(result["copiedFiles"], 2)

        before_mtime = mirror_app.stat().st_mtime_ns
        repeated = plan_bootstrap(self.source, self.mirror, self.policy)
        self.assertTrue(repeated["isNoop"])
        repeated_result = apply_bootstrap(repeated, confirmed=True)
        self.assertEqual(repeated_result["copiedFiles"], 0)
        self.assertEqual(mirror_app.stat().st_mtime_ns, before_mtime)

    def test_source_drift_stops_before_first_write(self) -> None:
        plan = plan_bootstrap(self.source, self.mirror, self.policy)
        (self.source / "README.md").write_bytes(b"changed after plan\n")

        with self.assertRaisesRegex(SourceAuthorityError, "source changed"):
            apply_bootstrap(plan, confirmed=True)

        self.assertFalse((self.mirror / "README.md").exists())

    def test_bootstrap_cli_plans_and_applies_only_with_confirmation(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        plan_path = self.root / "bootstrap-plan.json"
        plan_command = [
            sys.executable,
            "tools/platform_source_authority.py",
            "bootstrap-plan",
            "--source-root",
            str(self.source),
            "--mirror-root",
            str(self.mirror),
            "--policy",
            str(self.policy_path),
            "--output",
            str(plan_path),
        ]

        planned = subprocess.run(
            plan_command, cwd=repo, text=True, capture_output=True, check=False
        )

        self.assertEqual(planned.returncode, 0, planned.stdout + planned.stderr)
        self.assertEqual(len(json.loads(plan_path.read_text(encoding="utf-8"))["changes"]), 2)
        apply_command = [
            sys.executable,
            "tools/platform_source_authority.py",
            "bootstrap-apply",
            "--plan",
            str(plan_path),
            "--policy",
            str(self.policy_path),
        ]
        unconfirmed = subprocess.run(
            apply_command, cwd=repo, text=True, capture_output=True, check=False
        )
        self.assertNotEqual(unconfirmed.returncode, 0)
        self.assertFalse((self.mirror / "README.md").exists())

        applied = subprocess.run(
            [*apply_command, "--yes"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual((self.mirror / "README.md").read_bytes(), self.readme_bytes)
        self.assertTrue((self.mirror / "source-authority.snapshot.json").is_file())


if __name__ == "__main__":
    unittest.main()
