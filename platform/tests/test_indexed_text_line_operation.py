from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xydp.installer import InstallError, Installer  # noqa: E402
from xydp.repository import PackageRepository  # noqa: E402


def make_target(root: Path, *, line41: str = "") -> Path:
    envir = root / "Mir200/Envir"
    envir.mkdir(parents=True)
    (root / "Mir200/M2Server.exe").write_bytes(b"M2")
    (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
    rows = [""] * 41
    rows[40] = line41
    (envir / "CustomItemPropertyTextVarList.txt").write_bytes(
        ("\r\n".join(rows) + "\r\n").encode("gb18030")
    )
    return root


def make_package(root: Path, *, checks: list[dict] | None = None) -> Path:
    folder = root / "packages/candidate/xy.test.indexed-line"
    folder.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "id": "xy.test.indexed-line",
        "version": "1.0.0-candidate.1",
        "display_name": "索引文本行测试",
        "status": "candidate",
        "engine": "LFM2",
        "residency": "optional",
        "bundle": None,
        "dependencies": [],
        "parameters": {},
        "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
        "operations": [{
            "type": "indexed_text_line",
            "target": "Mir200/Envir/CustomItemPropertyTextVarList.txt",
            "line_number": 41,
            "content": "{人物等级∶|251}+$$2",
            "target_encoding": "gb18030",
        }],
        "preflight_checks": checks or [],
        "post_checks": [{
            "type": "indexed_text_line_equals",
            "path": "Mir200/Envir/CustomItemPropertyTextVarList.txt",
            "line_number": 41,
            "text": "{人物等级∶|251}+$$2",
        }],
        "evidence": ["test:indexed-line"],
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return folder


class IndexedTextLineOperationTests(unittest.TestCase):
    def test_exact_row_is_set_idempotently_and_rollback_restores_original_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base / "server")
            original = (target / "Mir200/Envir/CustomItemPropertyTextVarList.txt").read_bytes()
            make_package(base)
            repository = PackageRepository(base / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")

            try:
                first = installer.preflight(target, ["xy.test.indexed-line"], {})
            except (InstallError, PermissionError) as exc:
                self.fail(f"indexed_text_line 尚未实现：{exc}")
            self.assertEqual(len(first.changes), 1)
            rows = first.changes[0].after.decode("gb18030").splitlines()
            self.assertEqual(rows[40], "{人物等级∶|251}+$$2")
            receipt = installer.install(first)
            self.assertEqual(installer.preflight(target, ["xy.test.indexed-line"], {}).changes, [])
            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(
                (target / "Mir200/Envir/CustomItemPropertyTextVarList.txt").read_bytes(), original
            )

    def test_nonblank_different_row_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base / "server", line41="其他系统占用")
            path = target / "Mir200/Envir/CustomItemPropertyTextVarList.txt"
            original = path.read_bytes()
            make_package(base)
            repository = PackageRepository(base / "packages")
            repository.refresh()
            with self.assertRaisesRegex(InstallError, "第41行.*占用"):
                Installer(repository, base / "backups").preflight(
                    target, ["xy.test.indexed-line"], {}
                )
            self.assertEqual(path.read_bytes(), original)

    def test_tree_token_available_allows_owned_paths_but_rejects_other_scripts(self):
        checks = [{
            "type": "tree_token_available",
            "path": "Mir200/Envir",
            "token": "U470",
            "allowed_paths": ["Mir200/Envir/QuestDiary/玄渊等级加成/等级加成核心.txt"],
        }]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base / "server")
            owned = target / "Mir200/Envir/QuestDiary/玄渊等级加成/等级加成核心.txt"
            owned.parent.mkdir(parents=True)
            owned.write_text("MOV U470 0\n", encoding="gb18030")
            make_package(base, checks=checks)
            repository = PackageRepository(base / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")
            try:
                clean_plan = installer.preflight(target, ["xy.test.indexed-line"], {})
            except (InstallError, PermissionError) as exc:
                self.fail(f"tree_token_available 尚未实现：{exc}")
            self.assertEqual(len(clean_plan.changes), 1)

            conflict = target / "Mir200/Envir/QuestDiary/其他系统/冲突.txt"
            conflict.parent.mkdir(parents=True)
            conflict.write_text("MOV U470 9\n", encoding="gb18030")
            with self.assertRaisesRegex(InstallError, "U470.*冲突.txt"):
                installer.preflight(target, ["xy.test.indexed-line"], {})

    def test_text_not_contains_rejects_legacy_marker(self):
        checks = [{
            "type": "text_not_contains",
            "path": "Mir200/Envir/Market_Def/QFunction-0.txt",
            "text": "XY-LV-VERIFY",
        }]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base / "server")
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.parent.mkdir(parents=True)
            qfunction.write_text("; XY-LV-VERIFY-BEGIN\n", encoding="gb18030")
            make_package(base, checks=checks)
            repository = PackageRepository(base / "packages")
            repository.refresh()
            with self.assertRaisesRegex(InstallError, "禁止文本"):
                Installer(repository, base / "backups").preflight(
                    target, ["xy.test.indexed-line"], {}
                )


if __name__ == "__main__":
    unittest.main()
