from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.archive.writers import CArchiveWriter


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR_ENV = "XYDP_FROZEN_ARTIFACT_DIR"
ARTIFACT_NAMES = ("XuanYuanDevPlatform.exe", "xydp-cli.exe")
VERIFIER = ROOT / "tools" / "verify_frozen_provenance.py"
TEST_TEMP_ROOT = ROOT / "_codex_tmp" / "20260826_p2"


def _write_carchive(
    path: Path,
    entries: list[tuple[str, bytes, str]],
    *,
    raw_toc: bytes | None = None,
) -> None:
    payload = bytearray()
    toc_entries: list[tuple[int, int, int, int, str, str]] = []
    for name, data, typecode in entries:
        offset = len(payload)
        payload.extend(data)
        toc_entries.append((offset, len(data), len(data), 0, typecode, name))
    toc_data = CArchiveWriter._serialize_toc(toc_entries) if raw_toc is None else raw_toc
    toc_offset = len(payload)
    archive_length = toc_offset + len(toc_data) + CArchiveWriter._COOKIE_LENGTH
    cookie = struct.pack(
        CArchiveWriter._COOKIE_FORMAT,
        CArchiveWriter._COOKIE_MAGIC_PATTERN,
        archive_length,
        toc_offset,
        len(toc_data),
        sys.version_info.major * 100 + sys.version_info.minor,
        b"python312.dll",
    )
    path.write_bytes(bytes(payload) + toc_data + cookie)


class FrozenProvenanceRawTocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.installer_bytes = (ROOT / "src" / "xydp" / "mingge_native_p2_install.py").read_bytes()
        cls.cli_bytes = (ROOT / "src" / "xydp" / "cli.py").read_bytes()

    def _required_entries(self) -> list[tuple[str, bytes, str]]:
        return [
            (r"xydp\mingge_native_p2_install.py", self.installer_bytes, "b"),
            (r"xydp\cli.py", self.cli_bytes, "b"),
        ] + [(f"xydp/{name}.py", (ROOT / f"src/xydp/{name}.py").read_bytes(), "b")
             for name in ("equipment_wash", "config_sync", "installer", "manifest", "mingge_dual", "target_lock", "repository")]

    def test_complete_current_wash_provenance_is_accepted(self):
        result = self._run_fixture(self._required_entries())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["required_provenance"]), 9)

    def test_missing_or_stale_wash_source_is_rejected(self):
        entries = self._required_entries()
        self._assert_rejected([entry for entry in entries if entry[0] != "xydp/equipment_wash.py"], "missing")
        self._assert_rejected([(name, data + b"# stale" if name == "xydp/equipment_wash.py" else data, kind) for name, data, kind in entries], "hash_mismatch")

    def _run_fixture(
        self,
        entries: list[tuple[str, bytes, str]],
        *,
        raw_toc: bytes | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="frozen-provenance-", dir=TEST_TEMP_ROOT) as temp_dir:
            artifact = Path(temp_dir) / "fixture.pkg"
            _write_carchive(artifact, entries, raw_toc=raw_toc)
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            return subprocess.run(
                (
                    sys.executable,
                    str(VERIFIER),
                    "--artifact",
                    str(artifact),
                    "--source-root",
                    str(ROOT / "src"),
                ),
                capture_output=True,
                check=False,
                encoding="utf-8",
                env=environment,
            )

    def _assert_rejected(
        self,
        entries: list[tuple[str, bytes, str]],
        expected_reason: str,
    ) -> dict[str, object]:
        result = self._run_fixture(entries)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "failed")
        self.assertIn(expected_reason, result.stdout)
        return report

    def test_rejects_completely_identical_raw_toc_duplicate(self) -> None:
        entries = self._required_entries()
        entries.append((r"xydp\cli.py", self.cli_bytes, "b"))
        with tempfile.TemporaryDirectory(prefix="frozen-provenance-", dir=TEST_TEMP_ROOT) as temp_dir:
            artifact = Path(temp_dir) / "duplicate.pkg"
            _write_carchive(artifact, entries)
            self.assertEqual(len(CArchiveReader(str(artifact)).toc), len(self._required_entries()))
        self._assert_rejected(entries, "path_collision")

    def test_rejects_forward_and_backslash_aliases(self) -> None:
        entries = self._required_entries()
        entries.append(("xydp/cli.py", self.cli_bytes, "b"))
        self._assert_rejected(entries, "path_collision")

    def test_rejects_windows_casefold_alias(self) -> None:
        entries = self._required_entries()
        entries.append(("XYDP/CLI.PY", self.cli_bytes, "b"))
        self._assert_rejected(entries, "path_collision")

    def test_rejects_dot_segment_prefix(self) -> None:
        entries = self._required_entries()
        entries.append((r".\xydp\cli.py", self.cli_bytes, "b"))
        self._assert_rejected(entries, "dot_segment")

    def test_rejects_parent_segment_directory_escape(self) -> None:
        entries = self._required_entries()
        entries.append(("sandbox/../xydp/cli.py", self.cli_bytes, "b"))
        self._assert_rejected(entries, "parent_segment")

    def test_rejects_empty_path_segment(self) -> None:
        entries = self._required_entries()
        entries.append(("xydp//cli.py", self.cli_bytes, "b"))
        self._assert_rejected(entries, "empty_segment")

    def test_rejects_absolute_path(self) -> None:
        entries = self._required_entries()
        entries.append(("/xydp/cli.py", self.cli_bytes, "b"))
        self._assert_rejected(entries, "absolute_path")

    def test_rejects_windows_drive_path(self) -> None:
        entries = self._required_entries()
        entries.append((r"C:\xydp\cli.py", self.cli_bytes, "b"))
        self._assert_rejected(entries, "drive_path")

    def test_rejects_windows_noncanonical_trailing_dot_and_space(self) -> None:
        for alias in ("xydp/cli.py.", "xydp/cli.py "):
            with self.subTest(alias=alias):
                entries = self._required_entries()
                entries.append((alias, self.cli_bytes, "b"))
                self._assert_rejected(entries, "windows_noncanonical_trailing")

    def test_same_basename_outside_required_directory_does_not_match(self) -> None:
        entries = [
            (r"xydp\mingge_native_p2_install.py", self.installer_bytes, "b"),
            (r"other\cli.py", self.cli_bytes, "b"),
        ]
        self._assert_rejected(entries, "missing")

    def test_rejects_required_path_with_wrong_type(self) -> None:
        entries = [
            (r"xydp\mingge_native_p2_install.py", self.installer_bytes, "b"),
            (r"xydp\cli.py", self.cli_bytes, "x"),
        ]
        self._assert_rejected(entries, "wrong_type")

    def test_rejects_hash_mismatch(self) -> None:
        entries = [
            (r"xydp\mingge_native_p2_install.py", self.installer_bytes, "b"),
            (r"xydp\cli.py", self.cli_bytes + b"tampered", "b"),
        ]
        self._assert_rejected(entries, "hash_mismatch")

    def test_rejects_malformed_raw_toc_as_parse_error(self) -> None:
        result = self._run_fixture([], raw_toc=b"\x00" * 16)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("verification error", result.stderr)


@unittest.skipUnless(
    os.environ.get(ARTIFACT_DIR_ENV),
    f"set {ARTIFACT_DIR_ENV} to run the frozen-artifact provenance gate",
)
class FrozenProvenanceArtifactTests(unittest.TestCase):
    def test_both_onefile_artifacts_embed_exact_provenance_sources(self) -> None:
        artifact_dir = Path(os.environ[ARTIFACT_DIR_ENV])

        for artifact_name in ARTIFACT_NAMES:
            with self.subTest(artifact=artifact_name):
                environment = os.environ.copy()
                environment["PYTHONDONTWRITEBYTECODE"] = "1"
                result = subprocess.run(
                    (
                        sys.executable,
                        str(VERIFIER),
                        "--artifact",
                        str(artifact_dir / artifact_name),
                        "--source-root",
                        str(ROOT / "src"),
                    ),
                    capture_output=True,
                    check=False,
                    encoding="utf-8",
                    env=environment,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
