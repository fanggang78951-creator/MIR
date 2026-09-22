from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xydp.monster_engine import EngineDependency, MonsterEngineClosure
from xydp.monster_library import MonsterLibraryError


class CatalogV3RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "怪物库"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def record(self, **updates):
        from xydp.monster_catalog_v3 import MonsterRecord

        values = {
            "monster_id": 7,
            "source_rowid": 7,
            "monster_name": "闭包测试怪",
            "appearance_id": 1230,
            "library_no": 124,
            "slot_no": 0,
            "race": 81,
            "race_img": 156,
            "level": 80,
            "exp": 50000,
            "hp": 100000,
            "hit": 200,
            "monster_json": '{"Name":"闭包测试怪","RaceImg":156}',
            "monster_hash": "A" * 64,
            "source_kind": "wzl",
            "resource_name": "Mon124.wzl",
            "source_path": "C:/donor/data/Mon124.wzl",
            "companion_path": "C:/donor/data/Mon124.wzx",
            "source_hash": "B" * 64,
            "companion_hash": "C" * 64,
            "source_size": 123,
            "preview_path": "C:/preview/monster.png",
            "preview_state": "ready",
            "status": "ready",
            "skip_reason": None,
            "pak_password": None,
            "source_effect_list_path": "C:/donor/EffectImageList.txt",
            "source_effect_list_hash": "D" * 64,
        }
        values.update(updates)
        return MonsterRecord(**values)

    def closure(self) -> MonsterEngineClosure:
        return MonsterEngineClosure(
            engine_mode="smartmonster",
            closure_status="ready_verified",
            closure_hash="E" * 64,
            smart_ini_path="C:/donor/SmartMonster/闭包测试怪.ini",
            smart_ini_hash="F" * 64,
            dependencies=(
                EngineDependency(3, "Monster/Body.wzl", "wzl_wzx", "C:/donor/Body.wzl", "C:/donor/Body.wzx", "1" * 64, "2" * 64, None),
                EngineDependency(8, "Monster/Attack.pak", "pak", "C:/donor/Attack.pak", None, "3" * 64, None, "attack-password"),
            ),
            resource_reference_counts={"ActionFile": 2},
            total_verified_play_frames=40,
            login_policy="custom_monster_dat_required",
            capability_policy="basic_melee",
            reason=None,
        )

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def create_v2_catalog(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        catalog_path = self.root / "catalog.sqlite"
        connection = sqlite3.connect(catalog_path)
        try:
            connection.execute("CREATE TABLE monsters (monster_id INTEGER PRIMARY KEY, monster_name TEXT)")
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")
            connection.commit()
        finally:
            connection.close()
        return catalog_path

    def test_v2_catalog_is_backed_up_before_v3_replace(self):
        from xydp.monster_catalog_v3 import CatalogV3Repository, backup_v2_catalog

        catalog_path = self.create_v2_catalog()
        v2_hash = self.sha256(catalog_path)
        repository = CatalogV3Repository(self.root)
        backup_path = backup_v2_catalog(catalog_path, self.root / "backups" / "v2-catalog")

        self.assertEqual(self.sha256(backup_path), v2_hash)
        repository.rebuild([self.record()], {7: self.closure()})

        backups = list((self.root / "backups" / "v2-catalog").glob("*.sqlite"))
        self.assertEqual(backups, [backup_path])
        self.assertEqual(self.sha256(backup_path), v2_hash)
        self.assertNotEqual(self.sha256(repository.catalog_path), v2_hash)

    def test_large_assets_are_reused_by_hash_not_duplicated(self):
        from xydp.monster_catalog_v3 import backup_v2_catalog

        first_catalog = self.create_v2_catalog()
        (self.root / "assets").mkdir()
        (self.root / "assets" / "large-resource.bin").write_bytes(b"asset" * 1024 * 1024)
        second_catalog = Path(self.temp.name) / "second" / "catalog.sqlite"
        second_catalog.parent.mkdir()
        second_catalog.write_bytes(first_catalog.read_bytes())
        backup_root = Path(self.temp.name) / "backups"

        first_backup = backup_v2_catalog(first_catalog, backup_root)
        second_backup = backup_v2_catalog(second_catalog, backup_root)

        self.assertEqual(first_backup, second_backup)
        self.assertEqual(self.sha256(first_backup), self.sha256(first_catalog))
        self.assertEqual(list(backup_root.glob("*.sqlite")), [first_backup])
        self.assertEqual(list(backup_root.rglob("large-resource.bin")), [])

    def test_backup_rejects_existing_file_when_hash_readback_differs(self):
        from xydp.monster_catalog_v3 import backup_v2_catalog

        catalog_path = self.create_v2_catalog()
        backup_root = Path(self.temp.name) / "backups"
        backup_path = backup_v2_catalog(catalog_path, backup_root)
        backup_path.write_bytes(b"damaged backup")

        with self.assertRaisesRegex(MonsterLibraryError, "哈希"):
            backup_v2_catalog(catalog_path, backup_root)

        self.assertNotEqual(self.sha256(backup_path), self.sha256(catalog_path))

    def test_v2_rebuild_failure_keeps_original_catalog_after_backup(self):
        from xydp.monster_catalog_v3 import CatalogV3Repository

        catalog_path = self.create_v2_catalog()
        before = catalog_path.read_bytes()
        repository = CatalogV3Repository(self.root)
        real_replace = os.replace

        def reject_catalog_replace(source, destination):
            if Path(destination) == repository.catalog_path:
                raise OSError("replace denied")
            return real_replace(source, destination)

        with patch("xydp.monster_catalog_v3.os.replace", side_effect=reject_catalog_replace):
            with self.assertRaisesRegex(MonsterLibraryError, "V3重建失败"):
                repository.rebuild([self.record()], {7: self.closure()})

        backups = list((self.root / "backups" / "v2-catalog").glob("*.sqlite"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.sha256(backups[0]), self.sha256(catalog_path))
        self.assertEqual(catalog_path.read_bytes(), before)

    def test_v3_catalog_persists_multiple_dependencies_and_engine_fields(self):
        from xydp.monster_catalog_v3 import CatalogV3Repository, MonsterDependencyRecord

        repository = CatalogV3Repository(self.root)
        repository.rebuild([self.record()], {7: self.closure()})

        record = repository.list_monsters()[0]
        dependencies = repository.dependencies_for(7)
        self.assertEqual(record.engine_mode, "smartmonster")
        self.assertEqual(record.closure_status, "ready_verified")
        self.assertEqual(record.closure_hash, "E" * 64)
        self.assertEqual(record.smart_ini_hash, "F" * 64)
        self.assertEqual(record.source_effect_list_hash, "D" * 64)
        self.assertEqual(dependencies, [
            MonsterDependencyRecord(7, 0, 3, "Monster/Body.wzl", "wzl_wzx", "C:/donor/Body.wzl", "C:/donor/Body.wzx", "1" * 64, "2" * 64, None),
            MonsterDependencyRecord(7, 1, 8, "Monster/Attack.pak", "pak", "C:/donor/Attack.pak", None, "3" * 64, None, "attack-password"),
        ])
        self.assertEqual(json.loads(record.resource_manifest_json), [
            {
                "companion_hash": "2" * 64,
                "companion_path": "C:/donor/Body.wzx",
                "entry": "Monster/Body.wzl",
                "kind": "wzl_wzx",
                "monster_id": 7,
                "ordinal": 0,
                "pak_password": None,
                "source_hash": "1" * 64,
                "source_index": 3,
                "source_path": "C:/donor/Body.wzl",
            },
            {
                "companion_hash": None,
                "companion_path": None,
                "entry": "Monster/Attack.pak",
                "kind": "pak",
                "monster_id": 7,
                "ordinal": 1,
                "pak_password": "attack-password",
                "source_hash": "3" * 64,
                "source_index": 8,
                "source_path": "C:/donor/Attack.pak",
            },
        ])
        connection = repository.open()
        try:
            self.assertEqual(connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "3")
        finally:
            connection.close()

    def test_v2_catalog_is_rejected_instead_of_guessed(self):
        from xydp.monster_catalog_v3 import CatalogV3Repository

        self.root.mkdir(parents=True)
        connection = sqlite3.connect(self.root / "catalog.sqlite")
        try:
            connection.execute("CREATE TABLE monsters (monster_id INTEGER PRIMARY KEY, monster_name TEXT)")
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")
            connection.commit()
        finally:
            connection.close()

        opened = None
        try:
            with self.assertRaisesRegex(MonsterLibraryError, "V2.*重建V3"):
                opened = CatalogV3Repository(self.root).open()
        finally:
            if opened is not None:
                opened.close()

    def test_v2_catalog_with_v3_meta_but_missing_engine_column_is_rejected(self):
        from xydp.monster_catalog_v3 import CatalogV3Repository

        self.root.mkdir(parents=True)
        connection = sqlite3.connect(self.root / "catalog.sqlite")
        try:
            connection.execute("CREATE TABLE monsters (monster_id INTEGER PRIMARY KEY, monster_name TEXT)")
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '3')")
            connection.commit()
        finally:
            connection.close()

        opened = None
        try:
            with self.assertRaisesRegex(MonsterLibraryError, "V2.*重建V3"):
                opened = CatalogV3Repository(self.root).open()
        finally:
            if opened is not None:
                opened.close()

    def test_v2_catalog_with_engine_column_but_non_v3_meta_is_rejected(self):
        from xydp.monster_catalog_v3 import CatalogV3Repository

        self.root.mkdir(parents=True)
        connection = sqlite3.connect(self.root / "catalog.sqlite")
        try:
            connection.execute("CREATE TABLE monsters (monster_id INTEGER PRIMARY KEY, engine_mode TEXT NOT NULL)")
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")
            connection.commit()
        finally:
            connection.close()

        opened = None
        try:
            with self.assertRaisesRegex(MonsterLibraryError, "V2.*重建V3"):
                opened = CatalogV3Repository(self.root).open()
        finally:
            if opened is not None:
                opened.close()

    def test_rebuild_integrity_failure_preserves_existing_catalog_and_cleans_staging(self):
        from xydp.monster_catalog_v3 import CatalogV3Repository

        repository = CatalogV3Repository(self.root)
        repository.rebuild([self.record()], {7: self.closure()})
        before = repository.catalog_path.read_bytes()
        real_connect = sqlite3.connect

        class IntegrityFailureConnection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, statement, *parameters):
                if statement == "PRAGMA integrity_check":
                    return type("IntegrityCursor", (), {"fetchone": lambda self: ("not ok",)})()
                return self.connection.execute(statement, *parameters)

            def __getattr__(self, name):
                return getattr(self.connection, name)

        def connect_with_bad_integrity(*args, **kwargs):
            return IntegrityFailureConnection(real_connect(*args, **kwargs))

        with patch("xydp.monster_catalog_v3.sqlite3.connect", side_effect=connect_with_bad_integrity):
            with self.assertRaisesRegex(MonsterLibraryError, "完整性检查失败"):
                repository.rebuild([self.record(monster_name="替换失败怪")], {7: self.closure()})

        self.assertEqual(repository.catalog_path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("catalog.sqlite.staging-*")), [])

    def test_rebuild_replace_failure_preserves_existing_catalog_and_cleans_staging(self):
        from xydp.monster_catalog_v3 import CatalogV3Repository

        repository = CatalogV3Repository(self.root)
        repository.rebuild([self.record()], {7: self.closure()})
        before = repository.catalog_path.read_bytes()

        with patch("xydp.monster_catalog_v3.os.replace", side_effect=OSError("replace denied")):
            with self.assertRaisesRegex(MonsterLibraryError, "V3重建失败"):
                repository.rebuild([self.record(monster_name="替换失败怪")], {7: self.closure()})

        self.assertEqual(repository.catalog_path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("catalog.sqlite.staging-*")), [])

    def test_preview_state_does_not_change_closure_status(self):
        from xydp.monster_catalog_v3 import CatalogV3Repository

        repository = CatalogV3Repository(self.root)
        repository.rebuild([self.record(preview_state="missing")], {7: self.closure()})

        ready = repository.list_monsters("ready")
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].preview_state, "missing")
        self.assertEqual(ready[0].closure_status, "ready_verified")


if __name__ == "__main__":
    unittest.main()
