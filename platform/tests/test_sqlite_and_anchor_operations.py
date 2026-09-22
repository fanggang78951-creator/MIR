from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository
from xydp.validator import PackageValidationError, validate_package


class SqliteOperationTests(unittest.TestCase):
    def make_target(self, root: Path) -> Path:
        envir = root / "Mir200" / "Envir"
        (root / "Mir200").mkdir(parents=True, exist_ok=True)
        (root / "Mir200" / "M2Server.exe").write_bytes(b"M2")
        (envir / "Market_Def").mkdir(parents=True)
        (envir / "MapInfo.txt").write_text("[0 盟重]\r\n", encoding="gb18030")
        (envir / "Market_Def" / "QFunction-0.txt").write_text("", encoding="gb18030")
        database = root / "Mud2" / "DB" / "ApexM2.DB"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "CREATE TABLE StdItems ("
                "Idx INTEGER NOT NULL, Name TEXT NOT NULL, StdMode INTEGER NOT NULL, "
                "Shape INTEGER NOT NULL, Anicount INTEGER NOT NULL, Looks INTEGER NOT NULL, "
                "Dc INTEGER NOT NULL, Dc2 INTEGER NOT NULL, Color INTEGER NOT NULL, HP INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT INTO StdItems VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (100, "已有称号", 70, 9, 1, 0, 1, 1, 1, 0),
            )
            connection.commit()
        finally:
            connection.close()
        return database

    def make_package(self, packages: Path, *, values: dict | None = None, table: str = "StdItems") -> Path:
        package = packages / "candidate" / "xy.ops.sqlite-test"
        package.mkdir(parents=True)
        row = values or {
            "Name": "狂暴之力",
            "StdMode": 70,
            "Shape": 0,
            "Anicount": 1,
            "Looks": 0,
            "Dc": 50,
            "Dc2": 50,
            "Color": 251,
            "HP": 10000,
        }
        manifest = {
            "schema_version": 1,
            "id": "xy.ops.sqlite-test",
            "version": "1.0.0",
            "display_name": "SQLite 测试包",
            "status": "candidate",
            "engine": "LFM2",
            "bundle": None,
            "dependencies": [],
            "parameters": {},
            "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
            "operations": [{
                "type": "sqlite_upsert",
                "target": "Mud2/DB/ApexM2.DB",
                "table": table,
                "unique_key": ["Name"],
                "conflict_keys": [["Shape"]],
                "values": row,
                "allocate": {"Idx": "max_plus_one"},
                "on_conflict": "error",
            }],
            "preflight_checks": [{"type": "file_exists", "path": "Mud2/DB/ApexM2.DB"}],
            "post_checks": [],
            "evidence": [],
        }
        path = package / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return package

    def make_installer(self, packages: Path, backups: Path) -> Installer:
        repository = PackageRepository(packages)
        repository.refresh()
        return Installer(repository, backups)

    def read_rows(self, database: Path) -> list[tuple]:
        connection = sqlite3.connect(database)
        try:
            return connection.execute(
                "SELECT Idx, Name, StdMode, Shape, Anicount, Looks, Dc, Dc2, Color, HP "
                "FROM StdItems ORDER BY Idx"
            ).fetchall()
        finally:
            connection.close()

    def test_sqlite_upsert_preflight_is_read_only_and_install_rolls_back_byte_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            database = self.make_target(base / "server")
            self.make_package(base / "packages")
            installer = self.make_installer(base / "packages", base / "backups")
            original = database.read_bytes()

            plan = installer.preflight(base / "server", ["xy.ops.sqlite-test"], {})

            self.assertEqual(database.read_bytes(), original)
            change = next(item for item in plan.changes if item.relative_path == "Mud2/DB/ApexM2.DB")
            staged = base / "staged.db"
            staged.write_bytes(change.after)
            self.assertEqual(self.read_rows(staged)[-1], (101, "狂暴之力", 70, 0, 1, 0, 50, 50, 251, 10000))

            receipt = installer.install(plan)
            self.assertEqual(self.read_rows(database)[-1][1], "狂暴之力")
            installer.rollback(base / "server", receipt.transaction_id)
            self.assertEqual(database.read_bytes(), original)

    def test_sqlite_upsert_is_idempotent_for_an_exact_existing_row(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            database = self.make_target(base / "server")
            self.make_package(base / "packages")
            installer = self.make_installer(base / "packages", base / "backups")
            first = installer.preflight(base / "server", ["xy.ops.sqlite-test"], {})
            installer.install(first)
            installed = database.read_bytes()

            second = installer.preflight(base / "server", ["xy.ops.sqlite-test"], {})

            self.assertFalse(any(item.relative_path == "Mud2/DB/ApexM2.DB" for item in second.changes))
            self.assertEqual(database.read_bytes(), installed)

    def test_sqlite_upsert_rejects_same_name_with_different_values(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            database = self.make_target(base / "server")
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "INSERT INTO StdItems VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (101, "狂暴之力", 70, 0, 1, 0, 40, 40, 251, 10000),
                )
                connection.commit()
            finally:
                connection.close()
            self.make_package(base / "packages")
            installer = self.make_installer(base / "packages", base / "backups")
            before = database.read_bytes()

            with self.assertRaisesRegex(InstallError, "同名记录.*不一致"):
                installer.preflight(base / "server", ["xy.ops.sqlite-test"], {})

            self.assertEqual(database.read_bytes(), before)

    def test_sqlite_upsert_rejects_shape_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            database = self.make_target(base / "server")
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "INSERT INTO StdItems VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (101, "别的称号", 70, 0, 1, 0, 1, 1, 1, 0),
                )
                connection.commit()
            finally:
                connection.close()
            self.make_package(base / "packages")
            installer = self.make_installer(base / "packages", base / "backups")

            with self.assertRaisesRegex(InstallError, "字段占用冲突.*Shape"):
                installer.preflight(base / "server", ["xy.ops.sqlite-test"], {})

    def test_sqlite_upsert_validator_rejects_unapproved_table(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.make_package(Path(td) / "packages", table="OtherTable")
            with self.assertRaisesRegex(PackageValidationError, "SQLite 表不在白名单"):
                validate_package(package)


if __name__ == "__main__":
    unittest.main()
