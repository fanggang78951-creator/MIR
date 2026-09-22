from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository
from xydp.validator import PackageValidationError, validate_package


class MagicSkillUpdateOperationTests(unittest.TestCase):
    def make_target(self, root: Path, *, source_state: tuple[int, int] = (0, 0)) -> Path:
        envir = root / "Mir200/Envir"
        (envir / "Market_Def").mkdir(parents=True)
        (root / "Mir200/M2Server.exe").write_bytes(b"M2")
        (envir / "MapInfo.txt").write_bytes("[0 盟重]\r\n".encode("gb18030"))
        (envir / "Market_Def/QFunction-0.txt").write_bytes(b"")
        database = root / "Mud2/DB/ApexM2.DB"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "CREATE TABLE Magic ("
                "MagID INTEGER NOT NULL, MagName TEXT NOT NULL, Job INTEGER NOT NULL, "
                "CanUpgrade INTEGER NOT NULL, MaxUpgradeLv INTEGER NOT NULL)"
            )
            rows = [
                (7, "攻杀剑术", 0, source_state[0], source_state[1]),
                (7, "英雄攻杀剑术", 0, 0, 0),
                (7, "怒之攻杀剑术", 0, 0, 0),
            ]
            connection.executemany("INSERT INTO Magic VALUES (?, ?, ?, ?, ?)", rows)
            connection.commit()
        finally:
            connection.close()
        return database

    def make_package(
        self,
        packages: Path,
        *,
        target: str = "Mud2/DB/ApexM2.DB",
        match: dict | None = None,
        values: dict | None = None,
    ) -> Path:
        package = packages / "candidate/xy.test.magic-skill-update"
        package.mkdir(parents=True)
        manifest = {
            "schema_version": 1,
            "id": "xy.test.magic-skill-update",
            "version": "1.0.0",
            "display_name": "技能升级开关数据库操作测试",
            "status": "candidate",
            "engine": "LFM2",
            "residency": "optional",
            "bundle": None,
            "dependencies": [],
            "parameters": {},
            "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
            "operations": [
                {
                    "type": "sqlite_magic_skill_update",
                    "target": target,
                    "match": match or {"MagID": 7, "MagName": "攻杀剑术", "Job": 0},
                    "values": values or {"CanUpgrade": 1, "MaxUpgradeLv": 9},
                }
            ],
            "preflight_checks": [{"type": "file_exists", "path": target}],
            "post_checks": [],
            "evidence": [],
        }
        path = package / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return package

    @staticmethod
    def read_rows(database: Path) -> list[tuple]:
        connection = sqlite3.connect(database)
        try:
            return connection.execute(
                "SELECT MagID, MagName, Job, CanUpgrade, MaxUpgradeLv FROM Magic ORDER BY rowid"
            ).fetchall()
        finally:
            connection.close()

    def test_preflight_is_read_only_install_is_exact_and_rollback_is_byte_exact(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            database = self.make_target(base / "server")
            self.make_package(base / "packages")
            repository = PackageRepository(base / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")
            before = database.read_bytes()

            plan = installer.preflight(base / "server", ["xy.test.magic-skill-update"], {})

            self.assertEqual(database.read_bytes(), before)
            change = next(item for item in plan.changes if item.relative_path == "Mud2/DB/ApexM2.DB")
            staged = base / "staged.db"
            staged.write_bytes(change.after)
            self.assertEqual(
                self.read_rows(staged),
                [
                    (7, "攻杀剑术", 0, 1, 9),
                    (7, "英雄攻杀剑术", 0, 0, 0),
                    (7, "怒之攻杀剑术", 0, 0, 0),
                ],
            )

            receipt = installer.install(plan)
            self.assertEqual(self.read_rows(database)[0], (7, "攻杀剑术", 0, 1, 9))
            installer.rollback(base / "server", receipt.transaction_id)
            self.assertEqual(database.read_bytes(), before)

    def test_exact_desired_state_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            database = self.make_target(base / "server", source_state=(1, 9))
            self.make_package(base / "packages")
            repository = PackageRepository(base / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")
            before = database.read_bytes()

            plan = installer.preflight(base / "server", ["xy.test.magic-skill-update"], {})

            self.assertFalse(any(item.relative_path == "Mud2/DB/ApexM2.DB" for item in plan.changes))
            self.assertEqual(database.read_bytes(), before)

    def test_partial_or_foreign_state_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            database = self.make_target(base / "server", source_state=(1, 5))
            self.make_package(base / "packages")
            repository = PackageRepository(base / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")
            before = database.read_bytes()

            with self.assertRaisesRegex(InstallError, "当前升级开关状态冲突"):
                installer.preflight(base / "server", ["xy.test.magic-skill-update"], {})

            self.assertEqual(database.read_bytes(), before)

    def test_missing_or_duplicate_match_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            database = self.make_target(base / "server")
            connection = sqlite3.connect(database)
            try:
                connection.execute("INSERT INTO Magic VALUES (?, ?, ?, ?, ?)", (7, "攻杀剑术", 0, 0, 0))
                connection.commit()
            finally:
                connection.close()
            self.make_package(base / "packages")
            repository = PackageRepository(base / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")

            with self.assertRaisesRegex(InstallError, "技能记录匹配不唯一"):
                installer.preflight(base / "server", ["xy.test.magic-skill-update"], {})

    def test_validator_rejects_other_database_other_fields_and_non_warrior_job(self):
        cases = [
            ({"target": "Mud2/DB/Other.DB"}, "只允许修改 Mud2/DB/ApexM2.DB"),
            ({"values": {"CanUpgrade": 1, "MaxUpgradeLv": 9, "MaxTrainLv": 3}}, "values 字段必须恰好"),
            ({"match": {"MagID": 7, "MagName": "攻杀剑术", "Job": 1}}, "Job 只允许 0"),
        ]
        for override, message in cases:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as td:
                package = self.make_package(Path(td) / "packages", **override)
                with self.assertRaisesRegex(PackageValidationError, message):
                    validate_package(package)


if __name__ == "__main__":
    unittest.main()
