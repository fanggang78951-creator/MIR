from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.platform_source_authority import (
    SourceAuthorityError,
    apply_bootstrap,
    inventory_source,
    load_policy,
    plan_bootstrap,
    preflight_sync,
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

    def make_source_tree(self) -> None:
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

    def test_inventory_is_deterministic_and_blocks_unsafe_entries(self) -> None:
        self.make_source_tree()

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
        self.assertEqual({item["code"] for item in report["blockers"]}, expected)
        self.assertEqual(report["summary"]["managedFiles"], 2)
        self.assertEqual(report["summary"]["blockers"], len(expected))

    def test_inventory_blocks_nested_reparse_ancestor(self) -> None:
        (self.source / "nested" / "src").mkdir(parents=True)
        (self.source / "nested" / "src" / "app.py").write_bytes(b"safe\n")
        self.write_policy(includeDirectories=["nested/src"], rootFiles=[])

        real_is_reparse = __import__(
            "tools.platform_source_authority", fromlist=["_is_reparse"]
        )._is_reparse

        def fake_is_reparse(path: Path) -> bool:
            return Path(path).name == "nested" or real_is_reparse(Path(path))

        with mock.patch(
            "tools.platform_source_authority._is_reparse", side_effect=fake_is_reparse
        ):
            report = inventory_source(self.source, load_policy(self.policy_path))

        self.assertEqual(report["files"], [])
        self.assertEqual(
            report["blockers"],
            [
                {
                    "code": "reparse-point",
                    "path": "nested",
                    "message": "managed source path contains a reparse point",
                }
            ],
        )

    def test_inventory_blocks_real_directory_symlink(self) -> None:
        (self.source / "src").mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "escaped.py").write_bytes(b"escape")
        link = self.source / "src" / "linked"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlink unavailable: {exc}")
        self.write_policy(includeDirectories=["src"], rootFiles=[])

        report = inventory_source(self.source, load_policy(self.policy_path))

        self.assertEqual(report["files"], [])
        self.assertEqual({item["code"] for item in report["blockers"]}, {"reparse-point"})

    def test_inventory_rejects_symlinked_source_root(self) -> None:
        self.make_source_tree()
        alias = self.root / "source-alias"
        try:
            os.symlink(self.source, alias, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlink unavailable: {exc}")

        with self.assertRaisesRegex(SourceAuthorityError, "source root"):
            inventory_source(alias, load_policy(self.policy_path))

    def test_policy_rejects_absolute_and_parent_paths(self) -> None:
        for bad in [
            str(self.root.resolve()),
            "../outside",
            "src/../../outside",
            "D:outside",
            "file:stream",
        ]:
            with self.subTest(path=bad):
                self.write_policy(includeDirectories=[bad])
                with self.assertRaisesRegex(ValueError, "relative"):
                    load_policy(self.policy_path)

    def test_policy_requires_positive_file_limit(self) -> None:
        self.write_policy(maxFileBytes=0)
        with self.assertRaisesRegex(ValueError, "maxFileBytes"):
            load_policy(self.policy_path)

    def test_sensitive_content_is_blocked_without_reading_explicit_exclusions(self) -> None:
        (self.source / "src" / "xydp").mkdir(parents=True)
        (self.source / "tools").mkdir()
        (self.source / "src" / "xydp" / "compat.py").write_text(
            'PASSWORD = "hardcoded-value"\n', encoding="utf-8"
        )
        (self.source / "tools" / "excluded.py").write_text(
            'PASSWORD = "excluded-value"\n', encoding="utf-8"
        )
        self.write_policy(
            includeDirectories=["src", "tools"],
            rootFiles=[],
            excludeRelativePaths=["tools/excluded.py"],
            contentScanSuffixes=[".py"],
            maxFileBytes=1024,
            sensitiveContentPatterns=[
                r'(?im)\b(?:PASSWORD|PASSWD|API_KEY|TOKEN)\s*=\s*["\'][^"\'\r\n]{4,}["\']'
            ],
        )

        report = inventory_source(self.source, load_policy(self.policy_path))

        self.assertEqual(report["files"], [])
        self.assertEqual(
            report["blockers"],
            [
                {
                    "code": "sensitive-content",
                    "path": "src/xydp/compat.py",
                    "message": "file content matches a sensitive-content rule",
                }
            ],
        )

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

    def test_inventory_cli_rejects_output_inside_source(self) -> None:
        self.make_source_tree()
        protected = self.source / "README.md"
        before = protected.read_bytes()

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
                str(protected),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("protected root", completed.stderr)
        self.assertEqual(protected.read_bytes(), before)


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

    def test_bootstrap_plan_rejects_symlinked_source_root(self) -> None:
        alias = self.root / "source-alias"
        try:
            os.symlink(self.source, alias, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlink unavailable: {exc}")

        with self.assertRaisesRegex(SourceAuthorityError, "source root"):
            plan_bootstrap(alias, self.mirror, self.policy)

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

    def test_bootstrap_preserves_destination_created_during_copy(self) -> None:
        plan = plan_bootstrap(self.source, self.mirror, self.policy)
        destination = self.mirror / "README.md"
        real_copy2 = shutil.copy2

        def copy_then_race(source: Path, pending: Path) -> Path:
            result = real_copy2(source, pending)
            destination.write_bytes(b"concurrent work\n")
            return result

        with mock.patch(
            "tools.platform_source_authority.shutil.copy2", side_effect=copy_then_race
        ):
            with self.assertRaisesRegex(SourceAuthorityError, "appeared during bootstrap"):
                apply_bootstrap(plan, confirmed=True)

        self.assertEqual(destination.read_bytes(), b"concurrent work\n")

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

    def test_bootstrap_plan_cli_rejects_output_inside_mirror(self) -> None:
        protected = self.mirror / "plan.json"
        completed = subprocess.run(
            [
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
                str(protected),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("protected root", completed.stderr)
        self.assertFalse(protected.exists())


class SyncPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mirror = self.root / "mirror"
        self.runtime = self.root / "runtime"
        self.mirror.mkdir()
        self.runtime.mkdir()
        self.baseline = b"baseline\n"
        self.snapshot_path = self.mirror / "source-authority.snapshot.json"
        self.paths = [
            "unchanged.txt",
            "git-change.txt",
            "runtime-change.txt",
            "converged.txt",
            "conflict.txt",
            "runtime-missing.txt",
            "mirror-missing.txt",
        ]
        for relative in self.paths:
            if relative != "mirror-missing.txt":
                (self.mirror / relative).write_bytes(self.baseline)
            if relative != "runtime-missing.txt":
                (self.runtime / relative).write_bytes(self.baseline)
        (self.mirror / "git-change.txt").write_bytes(b"git\n")
        (self.runtime / "runtime-change.txt").write_bytes(b"runtime\n")
        (self.mirror / "converged.txt").write_bytes(b"same-new\n")
        (self.runtime / "converged.txt").write_bytes(b"same-new\n")
        (self.mirror / "conflict.txt").write_bytes(b"git-side\n")
        (self.runtime / "conflict.txt").write_bytes(b"runtime-side\n")
        (self.runtime / "bin").mkdir()
        (self.runtime / "bin" / "large.exe").write_bytes(b"unmanaged")
        files = [
            {
                "path": relative,
                "bytes": len(self.baseline),
                "sha256": hashlib.sha256(self.baseline).hexdigest(),
            }
            for relative in self.paths
        ]
        canonical = json.dumps(
            files, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        self.snapshot_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "sourceRoot": str(self.runtime),
                    "sourceFingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                    "snapshotFingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                    "files": files,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def runtime_state(self) -> dict[str, tuple[bytes, int]]:
        return {
            path.relative_to(self.runtime).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in self.runtime.rglob("*")
            if path.is_file()
        }

    def test_three_way_matrix_and_unmanaged_files_are_ignored(self) -> None:
        before = self.runtime_state()

        report = preflight_sync(self.mirror, self.runtime, self.snapshot_path)

        actions = {entry["path"]: entry["action"] for entry in report["changes"]}
        self.assertEqual(
            actions,
            {
                "conflict.txt": "blocked",
                "converged.txt": "converged",
                "git-change.txt": "update-runtime",
                "mirror-missing.txt": "blocked",
                "runtime-change.txt": "blocked",
                "runtime-missing.txt": "create-runtime",
                "unchanged.txt": "unchanged",
            },
        )
        self.assertEqual(
            {item["code"] for item in report["blockers"]},
            {"mirror-missing", "runtime-drift", "three-way-conflict"},
        )
        self.assertFalse(report["isNoop"])
        self.assertNotIn("bin/large.exe", actions)
        self.assertEqual(self.runtime_state(), before)

    def test_sync_preflight_rejects_unsafe_snapshot_path(self) -> None:
        snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        snapshot["files"][0]["path"] = "../escape.txt"
        self.snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        with self.assertRaisesRegex(SourceAuthorityError, "relative"):
            preflight_sync(self.mirror, self.runtime, self.snapshot_path)

    def test_sync_preflight_cli_is_read_only_and_returns_two_for_blockers(self) -> None:
        before = self.runtime_state()
        output = self.root / "sync-report.json"
        completed = subprocess.run(
            [
                sys.executable,
                "tools/platform_source_authority.py",
                "sync-preflight",
                "--mirror-root",
                str(self.mirror),
                "--runtime-root",
                str(self.runtime),
                "--snapshot",
                str(self.snapshot_path),
                "--output",
                str(output),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))["blockers"]), 3)
        self.assertEqual(self.runtime_state(), before)

    def test_sync_preflight_cli_rejects_output_inside_runtime(self) -> None:
        protected = self.runtime / "unchanged.txt"
        before = protected.read_bytes()

        completed = subprocess.run(
            [
                sys.executable,
                "tools/platform_source_authority.py",
                "sync-preflight",
                "--mirror-root",
                str(self.mirror),
                "--runtime-root",
                str(self.runtime),
                "--snapshot",
                str(self.snapshot_path),
                "--output",
                str(protected),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("protected root", completed.stderr)
        self.assertEqual(protected.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
