from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xyequip.resources.import_complete_weapon_clothing import (
    CompleteResourceImportError,
    STATIC_LIBRARIES,
    add_launcher_static_sources,
    deploy_verified_files,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CompleteWeaponClothingImportTests(unittest.TestCase):
    def test_deploy_replaces_all_verified_targets_and_keeps_recoverable_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_a, source_b = root / "source_a", root / "source_b"
            target_a, target_b = root / "target_a", root / "target_b"
            source_a.write_bytes(b"new-a")
            source_b.write_bytes(b"new-b")
            target_a.write_bytes(b"old-a")
            target_b.write_bytes(b"old-b")
            expected = {target_a: sha(target_a), target_b: sha(target_b)}

            backup, after = deploy_verified_files(
                {source_a: target_a, source_b: target_b},
                expected_before=expected,
                backup_root=root / "backups",
            )

            self.assertEqual(b"new-a", target_a.read_bytes())
            self.assertEqual(b"new-b", target_b.read_bytes())
            self.assertEqual(sha(source_a), after[str(target_a)])
            self.assertEqual(b"old-a", (backup / "00_target_a").read_bytes())
            self.assertEqual(b"old-b", (backup / "01_target_b").read_bytes())

    def test_deploy_rejects_target_changed_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target = root / "source", root / "target"
            source.write_bytes(b"new")
            target.write_bytes(b"old")
            expected = {target: sha(target)}
            target.write_bytes(b"changed")

            with self.assertRaises(CompleteResourceImportError):
                deploy_verified_files({source: target}, expected_before=expected, backup_root=root / "backups")
            self.assertEqual(b"changed", target.read_bytes())

    def test_launcher_static_sources_do_not_overwrite_client_static_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            staging, client, patch = root / "staging", root / "client", root / "patch"
            for directory in (staging, client, patch):
                directory.mkdir()
            mapping: dict[Path, Path] = {}
            for library in STATIC_LIBRARIES:
                for ext in (".wzl", ".wzx"):
                    source = staging / f"{library}{ext}"
                    source.write_bytes(f"{library}{ext}".encode())
                    mapping[source] = client / source.name

            add_launcher_static_sources(
                mapping,
                staging=staging,
                launcher_patch=patch,
                launcher_staging=root / "launcher_staging",
            )

            self.assertEqual(12, len(mapping))
            self.assertEqual({client / f"{lib}{ext}" for lib in STATIC_LIBRARIES for ext in (".wzl", ".wzx")}, set(mapping.values()) & {client / f"{lib}{ext}" for lib in STATIC_LIBRARIES for ext in (".wzl", ".wzx")})
            self.assertEqual({patch / f"{lib}{ext}" for lib in STATIC_LIBRARIES for ext in (".wzl", ".wzx")}, set(mapping.values()) & {patch / f"{lib}{ext}" for lib in STATIC_LIBRARIES for ext in (".wzl", ".wzx")})
