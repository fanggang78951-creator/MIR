from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xydp.cli import _parser
from xydp.gui import TAB_TITLES, PlatformApp
from xydp.monster_library import (
    MONSTER_COLUMNS,
    MonsterLibraryError,
    MonsterLibraryService,
    appr_to_library,
)
from tests.monster_v3_fixtures import (
    write_effect_image_list,
    write_smartmonster_ini,
    write_wzl_wzx_pair,
)


def monster_values(name: str, appr: int, **updates) -> dict[str, object]:
    values: dict[str, object] = {column: 0 for column in MONSTER_COLUMNS}
    values.update({
        "Name": name,
        "Race": 81,
        "RaceImg": 19,
        "Appr": appr,
        "Lvl": 80,
        "Exp": 50000,
        "HP": 100000,
        "AC": 100,
        "MAC": 100,
        "DC": 200,
        "DCMAX": 300,
        "HIT": 200,
        "WALK_SPD": 300,
        "WalkStep": 1,
        "WalkWait": 1,
        "ATTACK_SPD": 800,
    })
    values.update(updates)
    return values


def make_monster_db(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        definitions = ", ".join(
            f'"{column}" TEXT' if column == "Name" else f'"{column}" INTEGER'
            for column in MONSTER_COLUMNS
        )
        connection.execute(f'CREATE TABLE "Monster" ({definitions})')
        columns = ", ".join(f'"{item}"' for item in MONSTER_COLUMNS)
        placeholders = ", ".join("?" for _ in MONSTER_COLUMNS)
        connection.executemany(
            f'INSERT INTO "Monster" ({columns}) VALUES ({placeholders})',
            [tuple(row[item] for item in MONSTER_COLUMNS) for row in rows],
        )
        connection.commit()
    finally:
        connection.close()


class MonsterLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.platform = self.root / "platform"
        self.donor_server = self.root / "donor-server"
        self.donor_db = self.donor_server / "Mud2" / "DB" / "ApexM2.DB"
        self.donor_wzl = self.root / "donor-client" / "data"
        self.donor_pak = self.root / "donor-client" / "mycm" / "data"
        self.donor_rules = self.root / "donor-login" / "pak.txt"
        self.server = self.root / "server"
        self.client_data = self.root / "client" / "data"
        self.donor_wzl.mkdir(parents=True)
        self.donor_pak.mkdir(parents=True)
        self.client_data.mkdir(parents=True)
        (self.client_data.parent / "Game.exe").write_bytes(b"CLIENT")
        self.donor_effect_list = self.donor_server / "Mir200" / "Envir" / "EffectImageList.txt"
        self.donor_smartmonster = self.donor_effect_list.parent / "SmartMonster"
        self.donor_smartmonster.mkdir(parents=True)
        (self.donor_effect_list.parent / "!setup.txt").write_bytes(b"[Setup]\r\n")
        (self.server / "登录器").mkdir(parents=True)
        (self.server / "登录器" / "pak.txt").write_bytes("旧规则.pak|旧密码\r\n".encode("gb18030"))
        make_monster_db(self.donor_db, [
            monster_values("供体怪物甲", 1230, Exp=111111),
            monster_values("供体怪物乙", 1231, Exp=222222, MAC=""),
            monster_values("---分隔---", 0, Race=0, RaceImg=0),
        ])
        # 相同Appr但不同名称不应阻止导入；只按名称避免重复怪物行。
        make_monster_db(
            self.server / "Mud2" / "DB" / "ApexM2.DB",
            [monster_values("本端怪物", 1231)],
        )
        self.source_pak = self.donor_pak / "Mon124.Pak"
        self.source_pak.write_bytes(b"CORRECT-MON124-FULL-ACTION-FRAMES")
        (self.donor_pak / "Mon123.Pak").write_bytes(b"WRONG-OLD-FORMULA-MON123")
        self.donor_rules.parent.mkdir(parents=True)
        self.donor_rules.write_bytes(
            f"{self.source_pak}|测试密码\r\n".encode("gb18030")
        )
        self.service = MonsterLibraryService(self.platform)

    def tearDown(self):
        self.temp.cleanup()

    def scan(self):
        return self.service.scan(
            self.donor_db,
            self.donor_wzl,
            self.donor_pak,
            self.donor_rules,
            self.server,
            self.client_data,
            materialize=True,
        )

    def records(self):
        return {item.monster_name: item for item in self.service.list_monsters("all", self.server)}

    def make_smartmonster(self, *names: str, extra_attack: bool = False) -> None:
        """Prepare one shared zero-based dependency for named RaceImg=156 donors."""
        connection = sqlite3.connect(self.donor_db)
        try:
            connection.executemany(
                'UPDATE "Monster" SET "Race"=156, "RaceImg"=156, "Appr"=1123 WHERE "Name"=?',
                [(name,) for name in names],
            )
            connection.commit()
        finally:
            connection.close()
        write_wzl_wzx_pair(self.donor_wzl, "Mon7")
        write_effect_image_list(
            self.donor_effect_list,
            [f"Existing{index}.wzl" for index in range(78)] + ["Mon7.wzl"],
        )
        for name in names:
            write_smartmonster_ini(
                self.donor_smartmonster / f"{name}.ini",
                extra_attack=extra_attack,
            )

    def prepare_smartmonster_transaction(self):
        """Build one isolated, deployable SmartMonster closure target."""
        self.make_smartmonster("供体怪物甲")
        target_envir = self.server / "Mir200" / "Envir"
        (target_envir / "SmartMonster").mkdir(parents=True)
        write_effect_image_list(target_envir / "EffectImageList.txt", ["History0.wzl"])
        (self.client_data / "History0.wzl").write_bytes(b"HISTORICAL-WZL")
        (self.client_data / "History0.wzx").write_bytes(b"HISTORICAL-WZX")
        (target_envir / "MonGen.txt").write_bytes(b"BASELINE-MONGEN\r\n")
        self.scan()
        return self.records()["供体怪物甲"]

    def prepare_smartmonster_pak_transaction(self):
        """Build an isolated SmartMonster closure whose only dependency is a passworded PAK."""
        self.make_smartmonster("供体怪物甲")
        smart_pak = self.donor_pak / "smartbody.pak"
        smart_pak.write_bytes(b"SMARTMONSTER-PAK")
        write_effect_image_list(
            self.donor_effect_list,
            [f"Existing{index}.wzl" for index in range(78)] + [smart_pak.name],
        )
        self.donor_rules.write_bytes(
            (f"{self.source_pak}|测试密码\r\n{smart_pak}|isolated-password\r\n").encode("gb18030")
        )
        target_envir = self.server / "Mir200" / "Envir"
        (target_envir / "SmartMonster").mkdir(parents=True)
        write_effect_image_list(target_envir / "EffectImageList.txt", ["History0.wzl"])
        (self.client_data / "History0.wzl").write_bytes(b"HISTORICAL-WZL")
        (self.client_data / "History0.wzx").write_bytes(b"HISTORICAL-WZX")
        (target_envir / "MonGen.txt").write_bytes(b"BASELINE-MONGEN\r\n")
        self.scan()
        return self.records()["供体怪物甲"]

    def prepare_shared_pak_smartmonster_transaction(self):
        """Make two zero-based source indexes resolve to one passworded Smart PAK."""
        self.make_smartmonster("供体怪物甲")
        smart_pak = self.donor_pak / "sharedbody.pak"
        smart_pak.write_bytes(b"SHARED-SMARTMONSTER-PAK")
        write_effect_image_list(
            self.donor_effect_list,
            [f"Existing{index}.wzl" for index in range(78)] + [smart_pak.name, smart_pak.name],
        )
        ini = self.donor_smartmonster / "供体怪物甲.ini"
        ini.write_bytes(ini.read_bytes().replace(
            b"[EffectAttack]\r\nEffectFile=78", b"[EffectAttack]\r\nEffectFile=79",
        ))
        self.donor_rules.write_bytes(
            (f"{self.source_pak}|测试密码\r\n{smart_pak}|shared-password\r\n").encode("gb18030")
        )
        target_envir = self.server / "Mir200" / "Envir"
        (target_envir / "SmartMonster").mkdir(parents=True)
        write_effect_image_list(target_envir / "EffectImageList.txt", ["History0.wzl"])
        (self.client_data / "History0.wzl").write_bytes(b"HISTORICAL-WZL")
        (self.client_data / "History0.wzx").write_bytes(b"HISTORICAL-WZX")
        (target_envir / "MonGen.txt").write_bytes(b"BASELINE-MONGEN\r\n")
        self.scan()
        return self.records()["供体怪物甲"]

    def prepare_reversed_ordinal_smartmonster_transaction(self):
        """Create two distinct SmartMonster resources whose catalog ordinal is intentionally reversed."""
        self.make_smartmonster("供体怪物甲")
        second_wzl, second_wzx = write_wzl_wzx_pair(self.donor_wzl, "Mon42")
        second_wzl.write_bytes(second_wzl.read_bytes() + b"-second-resource")
        second_wzx.write_bytes(second_wzx.read_bytes() + b"-second-resource")
        write_effect_image_list(
            self.donor_effect_list,
            [f"Existing{index}.wzl" for index in range(78)] + ["Mon7.wzl", "Mon42.wzl"],
        )
        ini = self.donor_smartmonster / "供体怪物甲.ini"
        ini.write_bytes(ini.read_bytes().replace(
            b"[EffectAttack]\r\nEffectFile=78", b"[EffectAttack]\r\nEffectFile=79",
        ))
        target_envir = self.server / "Mir200" / "Envir"
        (target_envir / "SmartMonster").mkdir(parents=True)
        write_effect_image_list(target_envir / "EffectImageList.txt", ["History0.wzl"])
        (self.client_data / "History0.wzl").write_bytes(b"HISTORICAL-WZL")
        (self.client_data / "History0.wzx").write_bytes(b"HISTORICAL-WZX")
        (target_envir / "MonGen.txt").write_bytes(b"BASELINE-MONGEN\r\n")
        self.scan()
        record = self.records()["供体怪物甲"]
        connection = self.service.catalog.open()
        try:
            dependencies = connection.execute(
                "SELECT source_index FROM monster_dependencies WHERE monster_id=? ORDER BY source_index",
                (record.monster_id,),
            ).fetchall()
            self.assertEqual([row[0] for row in dependencies], [78, 79])
            connection.execute(
                "UPDATE monster_dependencies SET ordinal=ordinal+10 WHERE monster_id=?",
                (record.monster_id,),
            )
            connection.execute(
                "UPDATE monster_dependencies SET ordinal=CASE source_index WHEN 79 THEN 0 WHEN 78 THEN 1 END "
                "WHERE monster_id=?",
                (record.monster_id,),
            )
            manifest = json.loads(record.resource_manifest_json)
            for item in manifest:
                item["ordinal"] = 0 if int(item["source_index"]) == 79 else 1
            connection.execute(
                "UPDATE monsters SET resource_manifest_json=? WHERE monster_id=?",
                (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")), record.monster_id),
            )
            connection.commit()
        finally:
            connection.close()
        return self.records()["供体怪物甲"]

    def interrupt_smart_install(self, fault_kind: str):
        """Leave one real transaction in-progress after a controlled BaseException."""
        record = self.prepare_smartmonster_transaction()
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        before = self.target_snapshot()
        fault_target = next(
            Path(change.target_path).resolve() for change in plan.changes if change.kind == fault_kind
        )
        from xydp import monster_library
        original_write = monster_library._atomic_write

        def interrupt_after_target(path: Path, content: bytes) -> None:
            original_write(path, content)
            if Path(path).resolve() == fault_target:
                raise KeyboardInterrupt(f"controlled interruption after {fault_kind}")

        with patch("xydp.monster_library._atomic_write", side_effect=interrupt_after_target):
            with self.assertRaises(KeyboardInterrupt):
                self.service.install(plan)
        manifest = next(self.service.backups_root.glob("*/**/in-progress.json"))
        return plan, before, manifest, fault_target

    def target_snapshot(self) -> dict[str, bytes]:
        roots = (self.server, self.client_data)
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for root in roots
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_appr_mapping_uses_game_verified_plus_one_formula(self):
        self.assertEqual(appr_to_library(215), (22, 5))
        self.assertEqual(appr_to_library(1052), (106, 2))
        self.assertEqual(appr_to_library(1230), (124, 0))
        self.assertEqual(appr_to_library(1800), (181, 0))

    def test_scan_stores_complete_monster_rows_and_correct_patch(self):
        result = self.scan()
        self.assertEqual(result.total_monsters, 2)
        self.assertEqual(result.total_appearances, 2)
        self.assertEqual(result.ready, 2)
        self.assertEqual(result.existing, 0)
        self.assertEqual(result.localized_libraries, 1)
        records = self.records()
        first = records["供体怪物甲"]
        self.assertEqual(first.library_no, 124)
        self.assertEqual(first.slot_no, 0)
        self.assertEqual(first.resource_name.casefold(), "mon124.pak")
        self.assertEqual(first.monster_values["Exp"], 111111)
        self.assertEqual(records["供体怪物乙"].monster_values["MAC"], 0)
        self.assertEqual(first.pak_password, "测试密码")
        self.assertTrue(Path(first.source_path).is_file())
        self.assertNotEqual(Path(first.source_path), self.source_pak)
        self.assertNotIn("Mon123", first.source_path)

    def test_missing_standard_resource_is_not_ready_in_repository_or_service(self):
        """若普通资源缺失仍被标记verified，绕过service的V3消费者会选到不可用模型。"""
        self.source_pak.unlink()

        result = self.scan()

        self.assertEqual(result.skipped, 2)
        self.assertEqual(result.ready, 0)
        self.assertEqual(result.ready_verified, 0)
        self.assertEqual(result.incomplete, 2)
        records = self.records()
        self.assertTrue(all(record.status == "skipped" for record in records.values()))
        self.assertTrue(all(record.closure_status == "incomplete" for record in records.values()))
        from xydp.monster_catalog_v3 import CatalogV3Repository

        self.assertEqual(CatalogV3Repository(self.service.root).list_monsters("ready"), [])
        self.assertEqual(self.service.list_monsters("ready"), [])

    def test_scan_recovers_standard_pak_from_local_archive_after_donor_path_moved(self):
        """供体路径迁移后，已归档的同名原始 PAK 仍须可重建标准 Appr 模型。"""
        archived = self.service.assets_root / "pak" / "fixture" / self.source_pak.name
        archived.parent.mkdir(parents=True)
        archived.write_bytes(self.source_pak.read_bytes())
        self.source_pak.unlink()

        result = self.scan()

        self.assertEqual(result.ready_verified, 2)
        records = self.records()
        self.assertEqual(Path(records["供体怪物甲"].source_path).read_bytes(), archived.read_bytes())
        self.assertEqual(records["供体怪物甲"].pak_password, "测试密码")

    def test_scan_persists_all_classification_counts_after_catalog_reopen(self):
        """若摘要只留在返回值，重开V3 catalog后的GUI/CLI无法读取经过审计的扫描计数。"""
        result = self.scan()
        expected = {
            "standard_appr": 2,
            "smartmonster": 0,
            "ready_verified": 2,
            "ready_opaque": 0,
            "incomplete": 0,
            "complex_ability": 0,
        }

        self.assertEqual({key: getattr(result, key) for key in expected}, expected)
        from xydp.monster_catalog_v3 import CatalogV3Repository

        reopened = CatalogV3Repository(self.service.root).open()
        try:
            persisted = dict(reopened.execute(
                "SELECT key, value FROM meta WHERE key IN (?,?,?,?,?,?) ORDER BY key",
                tuple(expected),
            ).fetchall())
        finally:
            reopened.close()
        self.assertEqual(persisted, {key: str(value) for key, value in expected.items()})

    def test_scan_routes_standard_and_smartmonster_through_different_parsers(self):
        """若RaceImg=156仍走Appr路径，零基闭包不会入库且会误报ready。"""
        self.make_smartmonster("供体怪物甲")

        result = self.scan()

        records = self.records()
        self.assertEqual(result.standard_appr, 1)
        self.assertEqual(result.smartmonster, 1)
        self.assertEqual(result.ready_verified, 2)
        self.assertEqual(records["供体怪物乙"].engine_mode, "standard_appr")
        self.assertEqual(records["供体怪物甲"].engine_mode, "smartmonster")
        self.assertEqual(records["供体怪物甲"].closure_status, "ready_verified")
        self.assertEqual(records["供体怪物甲"].total_verified_play_frames, 224)

    def test_scan_derives_server_root_from_mud2_db_path(self):
        """若未传覆盖根目录时不从Mud2/DB推导，将找不到同服EffectImageList。"""
        self.make_smartmonster("供体怪物甲")

        result = self.scan()

        self.assertEqual(result.donor_server_root, str(self.donor_server.resolve()))
        connection = self.service.catalog.open()
        try:
            value = connection.execute(
                "SELECT value FROM meta WHERE key='donor_server_root'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(value, str(self.donor_server.resolve()))

    def test_raceimg156_missing_ini_is_incomplete_not_ready(self):
        """若缺同名INI的RaceImg=156进入ready，默认随机会产生无闭包怪物。"""
        connection = sqlite3.connect(self.donor_db)
        try:
            connection.execute('UPDATE "Monster" SET "RaceImg"=156 WHERE "Name"=?', ("供体怪物甲",))
            connection.commit()
        finally:
            connection.close()

        result = self.scan()

        record = self.records()["供体怪物甲"]
        self.assertEqual(record.engine_mode, "smartmonster")
        self.assertEqual(record.closure_status, "incomplete")
        self.assertIn("INI", record.skip_reason or "")
        self.assertEqual(result.incomplete, 1)
        self.assertNotIn(record.monster_id, [item.monster_id for item in self.service.list_monsters("ready")])

    def test_smartmonster_localizes_ini_and_every_dependency_by_hash(self):
        """若闭包仅保留供体路径或按怪物重复复制，同一资源漂移或占用会失控。"""
        self.make_smartmonster("供体怪物甲", "供体怪物乙")

        self.scan()

        records = self.records()
        first_dependencies = self.service.catalog.dependencies_for(records["供体怪物甲"].monster_id)
        second_dependencies = self.service.catalog.dependencies_for(records["供体怪物乙"].monster_id)
        self.assertTrue(Path(records["供体怪物甲"].smart_ini_path or "").is_file())
        self.assertTrue(Path(records["供体怪物乙"].smart_ini_path or "").is_file())
        self.assertEqual(len(first_dependencies), 1)
        self.assertEqual(len(second_dependencies), 1)
        self.assertEqual(first_dependencies[0].source_hash, second_dependencies[0].source_hash)
        self.assertEqual(first_dependencies[0].source_path, second_dependencies[0].source_path)
        self.assertTrue(Path(first_dependencies[0].source_path).is_file())
        self.assertTrue(Path(first_dependencies[0].companion_path or "").is_file())
        self.assertIn("assets", first_dependencies[0].source_path)

    def test_complex_ability_is_excluded_from_default_random_pool(self):
        """若复杂服务端攻击仍可从ready池选到，会把禁止迁移的能力带入新怪。"""
        self.make_smartmonster("供体怪物甲", extra_attack=True)

        result = self.scan()

        record = self.records()["供体怪物甲"]
        self.assertEqual(record.closure_status, "complex_ability")
        self.assertEqual(result.complex_ability, 1)
        ready_names = {item.monster_name for item in self.service.list_monsters("ready")}
        self.assertNotIn("供体怪物甲", ready_names)

    def test_import_sidecar_uses_correct_library_and_slot_stride(self):
        self.scan()
        exports = self.root / "exports"
        exports.mkdir()
        preview0 = exports / "00000.png"
        preview360 = exports / "00360.png"
        preview0.write_bytes(b"png-zero")
        preview360.write_bytes(b"png-three-sixty")
        sidecar = exports / "mon124.sidecar.json"
        sidecar.write_text(json.dumps({
            "schemaVersion": 1,
            "library": "Mon124",
            "sourcePakPath": str(self.source_pak),
            "entries": [
                {"index": 0, "source": str(preview0), "preview": str(preview0)},
                {"index": 360, "source": str(preview360), "preview": str(preview360)},
            ],
        }), encoding="utf-8")
        result = self.service.import_sidecars(sidecar)
        self.assertEqual(result.updated_monsters, 2)
        records = self.records()
        self.assertEqual(records["供体怪物甲"].preview_path, str(preview0.resolve()))
        self.assertEqual(records["供体怪物乙"].preview_path, str(preview360.resolve()))

    def test_preflight_installs_database_patch_rule_and_byte_exact_rollback(self):
        self.scan()
        # 证明正式植入只依赖怪物库，不再依赖供体pak.txt仍然存在。
        self.donor_rules.unlink()
        pak_rules = self.server / "登录器" / "pak.txt"
        database = self.server / "Mud2" / "DB" / "ApexM2.DB"
        before_rules = pak_rules.read_bytes()
        before_database = database.read_bytes()
        ids = [item.monster_id for item in self.service.list_monsters()]
        plan = self.service.preflight(ids, self.server, self.client_data)
        self.assertEqual(plan.blockers, [])
        self.assertEqual(plan.library_numbers, (124,))
        self.assertEqual(set(plan.monster_names), {"供体怪物甲", "供体怪物乙"})
        receipt = self.service.install(plan)
        target = self.client_data / "Mon124.Pak"
        self.assertEqual(target.read_bytes(), self.source_pak.read_bytes())
        decoded = pak_rules.read_bytes().decode("gb18030")
        self.assertIn("Mon124.Pak", decoded)
        self.assertIn("测试密码", decoded)
        connection = sqlite3.connect(database)
        try:
            rows = dict(connection.execute(
                'SELECT "Name", "Exp" FROM "Monster" WHERE "Name" IN (?,?)',
                ("供体怪物甲", "供体怪物乙"),
            ))
        finally:
            connection.close()
        self.assertEqual(rows, {"供体怪物甲": 111111, "供体怪物乙": 222222})
        receipt_json = Path(receipt.receipt_path).read_text(encoding="utf-8")
        receipt_payload = json.loads(receipt_json)
        self.assertNotIn("测试密码", receipt_json)
        self.assertEqual(receipt_payload["status"], "deployed")
        self.assertFalse(receipt_payload["requires_custom_monster_dat"])
        self.assertFalse(receipt_payload["requires_login_regeneration"])
        self.assertEqual(
            receipt_payload["custom_monster_dat_path"],
            str((self.server / "Mir200" / "自定义怪物.dat").resolve()),
        )
        self.assertEqual(receipt_payload["client_integration_status"], "not-required")
        self.service.rollback(receipt.transaction_id)
        self.assertFalse(target.exists())
        self.assertEqual(pak_rules.read_bytes(), before_rules)
        self.assertEqual(database.read_bytes(), before_database)

    def test_install_commits_db_ini_resources_and_effect_list_in_one_transaction(self):
        """若闭包未纳入既有事务，数据库、INI、资源和索引会形成不可加载的半成品。"""
        record = self.prepare_smartmonster_transaction()
        database = self.server / "Mud2" / "DB" / "ApexM2.DB"
        effect_list = self.server / "Mir200" / "Envir" / "EffectImageList.txt"
        before = self.target_snapshot()

        plan = self.service.preflight([record.monster_id], self.server, self.client_data)

        self.assertEqual(plan.blockers, [])
        self.assertTrue(any(change.kind == "smart-generated-file" for change in plan.changes))
        self.assertTrue(any(change.kind == "effect-image-list" for change in plan.changes))
        self.assertTrue(plan.requires_custom_monster_dat)
        self.assertTrue(plan.requires_login_regeneration)
        receipt = self.service.install(plan)

        connection = sqlite3.connect(database)
        try:
            names = {row[0] for row in connection.execute('SELECT "Name" FROM "Monster"')}
        finally:
            connection.close()
        self.assertIn("供体怪物甲", names)
        for target, content in plan.generated_files_after.items():
            self.assertEqual(Path(target).read_bytes(), content)
        effect_lines = effect_list.read_bytes().decode("gb18030").splitlines()
        for assignment in plan.engine_assignments:
            self.assertEqual(effect_lines[assignment["target_index"]], assignment["target_entry"])
        summary = self.service.plan_summary(plan)
        self.assertEqual(summary["engine_assignments"], list(plan.engine_assignments))
        self.assertTrue(summary["requires_custom_monster_dat"])
        self.assertTrue(summary["requires_login_regeneration"])
        receipt_payload = json.loads(Path(receipt.receipt_path).read_text(encoding="utf-8"))
        self.assertEqual(receipt_payload["engine_assignments"], list(plan.engine_assignments))
        self.assertEqual(receipt_payload["status"], "deployed-awaiting-client-integration")
        self.assertTrue(receipt_payload["requires_custom_monster_dat"])
        self.assertTrue(receipt_payload["requires_login_regeneration"])
        self.assertEqual(
            receipt_payload["custom_monster_dat_path"],
            str((self.server / "Mir200" / "自定义怪物.dat").resolve()),
        )
        self.assertEqual(
            receipt_payload["client_integration_status"],
            "awaiting-client-integration",
        )
        self.service.rollback(receipt.transaction_id)
        self.assertEqual(self.target_snapshot(), before)

    def test_failure_after_second_generated_file_restores_every_prior_target(self):
        """若第二个生成文件落盘后失败没有反向恢复，目标会残留半套WZL/WZX闭包。"""
        record = self.prepare_smartmonster_transaction()
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        before = self.target_snapshot()
        generated_targets = {
            Path(change.target_path).resolve()
            for change in plan.changes
            if change.kind == "smart-generated-file"
        }
        from xydp import monster_library

        original_write = monster_library._atomic_write
        writes = 0

        def fail_after_second_generated(path: Path, content: bytes) -> None:
            nonlocal writes
            original_write(path, content)
            if Path(path).resolve() in generated_targets:
                writes += 1
                if writes == 2:
                    raise OSError("injected failure after second generated file")

        with patch("xydp.monster_library._atomic_write", side_effect=fail_after_second_generated):
            with self.assertRaisesRegex(MonsterLibraryError, "已回滚"):
                self.service.install(plan)

        self.assertEqual(writes, 2)
        self.assertEqual(self.target_snapshot(), before)

    def test_rollback_refuses_when_effect_list_changed_after_install(self):
        """若EffectImageList部署后漂移仍整体回滚，会抹掉其他任务的零基登记。"""
        record = self.prepare_smartmonster_transaction()
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        receipt = self.service.install(plan)
        effect_list = self.server / "Mir200" / "Envir" / "EffectImageList.txt"
        effect_list.write_bytes(effect_list.read_bytes() + b"OTHER-TASK.wzl\r\n")
        generated = next(
            Path(change.target_path) for change in plan.changes if change.kind == "smart-generated-file"
        )

        with self.assertRaisesRegex(MonsterLibraryError, "植入后被修改"):
            self.service.rollback(receipt.transaction_id)

        self.assertTrue(generated.is_file())
        self.assertTrue(effect_list.read_bytes().endswith(b"OTHER-TASK.wzl\r\n"))

    def test_database_and_mongen_are_unchanged_when_only_model_closure_is_added(self):
        """若仅补模型闭包仍重写数据库或MonGen，会把非模型业务数据带入事务。"""
        record = self.prepare_smartmonster_transaction()
        database = self.server / "Mud2" / "DB" / "ApexM2.DB"
        connection = sqlite3.connect(database)
        try:
            columns = ", ".join(f'"{item}"' for item in MONSTER_COLUMNS)
            placeholders = ", ".join("?" for _ in MONSTER_COLUMNS)
            connection.execute(
                f'INSERT INTO "Monster" ({columns}) VALUES ({placeholders})',
                tuple(record.monster_values[item] for item in MONSTER_COLUMNS),
            )
            connection.commit()
        finally:
            connection.close()
        mon_gen = self.server / "Mir200" / "Envir" / "MonGen.txt"
        before_database = database.read_bytes()
        before_mon_gen = mon_gen.read_bytes()

        plan = self.service.preflight([record.monster_id], self.server, self.client_data)

        self.assertEqual(plan.blockers, [])
        self.assertFalse(any(change.kind in {"monster-database", "monster-name-colors"} for change in plan.changes))
        self.service.install(plan)
        self.assertEqual(database.read_bytes(), before_database)
        self.assertEqual(mon_gen.read_bytes(), before_mon_gen)

    def test_repeated_preflight_reports_already_deployed(self):
        """若同一闭包重复预检继续追加EffectImageList，会改变所有后续资源零基号。"""
        record = self.prepare_smartmonster_transaction()
        first = self.service.preflight([record.monster_id], self.server, self.client_data)
        self.service.install(first)
        database = self.server / "Mud2" / "DB" / "ApexM2.DB"
        effect_list = self.server / "Mir200" / "Envir" / "EffectImageList.txt"
        before_database = database.read_bytes()
        before_effect = effect_list.read_bytes()

        repeated = self.service.preflight([record.monster_id], self.server, self.client_data)

        self.assertEqual(repeated.operation, "already-deployed")
        self.assertEqual(repeated.blockers, [])
        self.assertEqual(repeated.changes, [])
        self.assertEqual(database.read_bytes(), before_database)
        self.assertEqual(effect_list.read_bytes(), before_effect)

    def test_multi_dependency_ordinals_survive_catalog_and_manifest_fallback_lifecycle(self):
        """逆序稳定ordinal必须在目录直通、派生manifest回退及真实事务中保持不变。"""
        record = self.prepare_reversed_ordinal_smartmonster_transaction()
        catalog_dependencies = self.service._smart_dependencies_for(record)
        self.assertEqual(
            [(item.ordinal, item.source_index) for item in catalog_dependencies],
            [(0, 79), (1, 78)],
        )
        derived_values = dict(record.monster_values)
        derived_values["Name"] = "派生逆序闭包怪"
        derived_json = json.dumps(derived_values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        derived = replace(
            record,
            monster_id=999,
            source_rowid=999,
            monster_name="派生逆序闭包怪",
            monster_json=derived_json,
            monster_hash=hashlib.sha256(derived_json.encode("utf-8")).hexdigest().upper(),
        )
        fallback_dependencies = self.service._smart_dependencies_for(derived)
        self.assertEqual(
            [(item.ordinal, item.source_index, item.monster_id) for item in fallback_dependencies],
            [(0, 79, 999), (1, 78, 999)],
        )
        before = self.target_snapshot()
        initial = self.service.preflight_records([derived], self.server, self.client_data)
        self.assertEqual(initial.blockers, [])
        self.assertEqual(
            [(item["ordinal"], item["source_index"]) for item in initial.engine_assignments],
            [(0, 79), (1, 78)],
        )
        self.assertTrue(all(
            f"XY_MonV3_999_{item['ordinal']}_" in str(item["target_entry"])
            for item in initial.engine_assignments
        ))
        receipt = self.service.install(initial)
        repeated = self.service.preflight_records([derived], self.server, self.client_data)
        self.assertEqual(repeated.operation, "already-deployed")
        self.assertEqual(repeated.changes, [])
        self.service.rollback(receipt.transaction_id)
        self.assertEqual(self.target_snapshot(), before)

    def test_manifest_identity_fields_reject_non_json_integers_and_fail_closed(self):
        """派生SmartMonster manifest的三个身份数值只能接受JSON原生整数。"""
        record = self.prepare_reversed_ordinal_smartmonster_transaction()
        manifest = json.loads(record.resource_manifest_json)
        self.assertEqual([(item["ordinal"], item["source_index"]) for item in manifest], [(1, 78), (0, 79)])

        def mutate_all(field: str, value: object):
            def apply(items: list[dict[str, object]]) -> None:
                for item in items:
                    item[field] = value
            return apply

        cases = [
            ("monster_id-bool", mutate_all("monster_id", True)),
            ("monster_id-float", mutate_all("monster_id", 1.25)),
            ("monster_id-string", mutate_all("monster_id", "1")),
            ("monster_id-zero", mutate_all("monster_id", 0)),
            ("monster_id-negative", mutate_all("monster_id", -1)),
            ("monster_id-too-large", mutate_all("monster_id", 2**63)),
            ("ordinal-bool", lambda items: items[0].__setitem__("ordinal", True)),
            ("ordinal-float", lambda items: items[0].__setitem__("ordinal", 1.25)),
            ("ordinal-string", lambda items: items[0].__setitem__("ordinal", "1")),
            ("source_index-bool", lambda items: items[0].__setitem__("source_index", True)),
            ("source_index-float", lambda items: items[0].__setitem__("source_index", 78.25)),
            ("source_index-string", lambda items: items[0].__setitem__("source_index", "78")),
            ("negative-ordinal", lambda items: items[0].__setitem__("ordinal", -1)),
            ("ordinal-too-large", lambda items: items[0].__setitem__("ordinal", 2**63)),
            ("source_index-negative", lambda items: items[0].__setitem__("source_index", -1)),
            ("source_index-too-large", lambda items: items[0].__setitem__("source_index", 2**63)),
            ("duplicate-ordinal", lambda items: items[0].__setitem__("ordinal", items[1]["ordinal"])),
            ("mixed-source-monster-id", lambda items: items[0].__setitem__("monster_id", int(items[1]["monster_id"]) + 1)),
        ]
        before = self.target_snapshot()
        for index, (name, mutate) in enumerate(cases, start=1):
            with self.subTest(name=name):
                items = json.loads(json.dumps(manifest))
                mutate(items)
                values = dict(record.monster_values)
                target_name = f"损坏身份字段怪{index}"
                values["Name"] = target_name
                monster_json = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                derived = replace(
                    record,
                    monster_id=900 + index,
                    source_rowid=900 + index,
                    monster_name=target_name,
                    monster_json=monster_json,
                    monster_hash=hashlib.sha256(monster_json.encode("utf-8")).hexdigest().upper(),
                    resource_manifest_json=json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                )

                self.assertEqual(self.service._smart_dependencies_for(derived), ())
                plan = self.service.preflight_records([derived], self.server, self.client_data)
                self.assertTrue(any("缺少SmartMonster资源依赖" in blocker for blocker in plan.blockers))
                self.assertEqual(plan.changes, [])
                with self.assertRaisesRegex(MonsterLibraryError, "预检阻止植入"):
                    self.service.install(plan)
        self.assertEqual(self.target_snapshot(), before)

    def test_manifest_overlong_identity_integer_literal_fails_closed(self):
        """超长身份整数必须在JSON解析失败后仍形成安全的失败关闭计划。"""
        record = self.prepare_reversed_ordinal_smartmonster_transaction()
        overlong_integer = "9" * 5000
        overlong_manifest_json = re.sub(
            r'("monster_id"\s*:\s*)\d+',
            rf"\g<1>{overlong_integer}",
            record.resource_manifest_json,
            count=1,
        )
        self.assertNotEqual(overlong_manifest_json, record.resource_manifest_json)
        with self.assertRaisesRegex(ValueError, "Exceeds the limit"):
            json.loads(overlong_manifest_json)

        values = dict(record.monster_values)
        target_name = "超长身份整数怪"
        values["Name"] = target_name
        monster_json = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        derived = replace(
            record,
            monster_id=950,
            source_rowid=950,
            monster_name=target_name,
            monster_json=monster_json,
            monster_hash=hashlib.sha256(monster_json.encode("utf-8")).hexdigest().upper(),
            resource_manifest_json=overlong_manifest_json,
        )
        before = self.target_snapshot()

        self.assertEqual(self.service._smart_dependencies_for(derived), ())
        plan = self.service.preflight_records([derived], self.server, self.client_data)
        self.assertTrue(any("缺少SmartMonster资源依赖" in blocker for blocker in plan.blockers))
        self.assertEqual(plan.changes, [])
        with self.assertRaisesRegex(MonsterLibraryError, "预检阻止植入"):
            self.service.install(plan)
        self.assertEqual(self.target_snapshot(), before)

    def test_mixed_exact_and_skipped_batch_is_not_already_deployed(self):
        """同批仍有未部署跳过项时，已部署子集不能掩盖整个批次未完成。"""
        self.scan()
        records = self.records()
        deployed = records["供体怪物甲"]
        skipped = records["供体怪物乙"]
        self.service.install(self.service.preflight([deployed.monster_id], self.server, self.client_data))
        conflicting_values = dict(skipped.monster_values)
        conflicting_values["Exp"] = int(conflicting_values["Exp"]) + 1
        database = self.server / "Mud2" / "DB" / "ApexM2.DB"
        connection = sqlite3.connect(database)
        try:
            columns = ", ".join(f'"{item}"' for item in MONSTER_COLUMNS)
            placeholders = ", ".join("?" for _ in MONSTER_COLUMNS)
            connection.execute(
                f'INSERT INTO "Monster" ({columns}) VALUES ({placeholders})',
                tuple(conflicting_values[item] for item in MONSTER_COLUMNS),
            )
            connection.commit()
        finally:
            connection.close()

        mixed = self.service.preflight([deployed.monster_id, skipped.monster_id], self.server, self.client_data)

        self.assertNotEqual(mixed.operation, "already-deployed")
        self.assertEqual(mixed.changes, [])
        self.assertTrue(any("供体怪物乙" in item and "同名怪物" in item for item in mixed.skipped))
        self.assertTrue(any("未完成" in item for item in mixed.blockers))

    def test_standard_appr_lifecycle_records_full_five_states_and_byte_hash_rollback(self):
        """普通Appr也必须闭合ready→deployed→already-deployed→rolled-back→ready。"""
        self.scan()
        record = self.records()["供体怪物甲"]

        def snapshot_hashes() -> dict[str, str]:
            return {
                path: hashlib.sha256(content).hexdigest()
                for path, content in self.target_snapshot().items()
            }

        before = snapshot_hashes()
        initial = self.service.preflight([record.monster_id], self.server, self.client_data)
        self.assertEqual(initial.blockers, [])
        self.assertGreater(len(initial.changes), 0)

        receipt = self.service.install(initial)
        deployed = snapshot_hashes()
        self.assertNotEqual(deployed, before)
        self.assertEqual(
            json.loads(Path(receipt.receipt_path).read_text(encoding="utf-8"))["status"],
            "deployed",
        )

        repeated = self.service.preflight([record.monster_id], self.server, self.client_data)
        self.assertEqual(repeated.operation, "already-deployed")
        self.assertEqual(repeated.blockers, [])
        self.assertEqual(repeated.changes, [])

        self.service.rollback(receipt.transaction_id)
        rolled_back = snapshot_hashes()
        self.assertEqual(rolled_back, before)
        final = self.service.preflight([record.monster_id], self.server, self.client_data)
        self.assertEqual(final.blockers, [])
        self.assertGreater(len(final.changes), 0)
        print(json.dumps({
            "task10_isolated_lifecycle": {
                "path": "standard_appr",
                "states": ["ready", "deployed", "already-deployed", "rolled-back", "ready"],
                "receipt_status": "deployed",
                "before_sha256": before,
                "deployed_sha256": deployed,
                "rolled_back_sha256": rolled_back,
                "rollback_matches_before": rolled_back == before,
            },
        }, ensure_ascii=False, sort_keys=True))

    def test_smartmonster_lifecycle_records_full_five_states_and_byte_hash_rollback(self):
        """SmartMonster必须在独立目录闭合五状态并回滚INI、资源和PAK规则。"""
        record = self.prepare_smartmonster_pak_transaction()
        generator = self.root / "actual-generator"
        generator.mkdir()
        (generator / "MakeGameLogin.exe").write_bytes(b"EXE")
        generator_rules = generator / "pak.txt"
        generator_before = b"GENERATOR-BASELINE\r\n"
        generator_rules.write_bytes(generator_before)

        def snapshot_hashes() -> dict[str, str]:
            files = self.target_snapshot()
            files[str(generator_rules.relative_to(self.root))] = generator_rules.read_bytes()
            return {
                path: hashlib.sha256(content).hexdigest()
                for path, content in files.items()
            }

        before = snapshot_hashes()
        initial = self.service.preflight(
            [record.monster_id], self.server, self.client_data, generator_login_dir=generator,
        )
        self.assertEqual(initial.blockers, [])
        self.assertTrue(any(change.kind == "smart-generated-file" for change in initial.changes))
        self.assertTrue(any(change.kind == "effect-image-list" for change in initial.changes))
        self.assertTrue(any(item["kind"] == "pak" for item in initial.engine_assignments))

        receipt = self.service.install(initial)
        deployed = snapshot_hashes()
        self.assertNotEqual(deployed, before)
        status = json.loads(Path(receipt.receipt_path).read_text(encoding="utf-8"))["status"]
        self.assertTrue(status.startswith("deployed"))
        self.assertIn("isolated-password", generator_rules.read_bytes().decode("gb18030"))

        repeated = self.service.preflight(
            [record.monster_id], self.server, self.client_data, generator_login_dir=generator,
        )
        self.assertEqual(repeated.operation, "already-deployed")
        self.assertEqual(repeated.blockers, [])
        self.assertEqual(repeated.changes, [])

        self.service.rollback(receipt.transaction_id)
        rolled_back = snapshot_hashes()
        self.assertEqual(rolled_back, before)
        final = self.service.preflight(
            [record.monster_id], self.server, self.client_data, generator_login_dir=generator,
        )
        self.assertEqual(final.blockers, [])
        self.assertGreater(len(final.changes), 0)
        print(json.dumps({
            "task10_isolated_lifecycle": {
                "path": "smartmonster",
                "states": ["ready", "deployed", "already-deployed", "rolled-back", "ready"],
                "receipt_status": status,
                "before_sha256": before,
                "deployed_sha256": deployed,
                "rolled_back_sha256": rolled_back,
                "rollback_matches_before": rolled_back == before,
                "coverage": ["INI", "EffectImageList", "client-action-resource", "PAK-password-rule"],
            },
        }, ensure_ascii=False, sort_keys=True))

    def test_smartmonster_pak_rule_uses_existing_rule_transaction_and_lifecycle(self):
        """若Smart PAK未纳入既有规则事务，闭包会部署为无法由引擎解密的半成品。"""
        record = self.prepare_smartmonster_pak_transaction()
        generator = self.root / "actual-generator"
        generator.mkdir()
        (generator / "MakeGameLogin.exe").write_bytes(b"EXE")
        generator_rules = generator / "pak.txt"
        generator_before = b"GENERATOR-BASELINE\r\n"
        generator_rules.write_bytes(generator_before)
        server_rules = self.server / "登录器" / "pak.txt"
        server_before = server_rules.read_bytes()

        plan = self.service.preflight(
            [record.monster_id], self.server, self.client_data, generator_login_dir=generator,
        )

        self.assertTrue(any(change.kind == "pak-rules" for change in plan.changes))
        self.assertTrue(any(change.kind == "generator-pak-rules" for change in plan.changes))
        pak_entry = next(item["target_entry"] for item in plan.engine_assignments if item["kind"] == "pak")
        target_pak = self.client_data / pak_entry
        before = self.target_snapshot()
        from xydp import monster_library
        original_write = monster_library._atomic_write

        def fail_after_generator_rule(path: Path, content: bytes) -> None:
            original_write(path, content)
            if Path(path).resolve() == generator_rules.resolve():
                raise OSError("injected failure after SmartMonster generator pak rule")

        with patch("xydp.monster_library._atomic_write", side_effect=fail_after_generator_rule):
            with self.assertRaisesRegex(MonsterLibraryError, "已回滚"):
                self.service.install(plan)
        self.assertEqual(self.target_snapshot(), before)
        self.assertEqual(server_rules.read_bytes(), server_before)
        self.assertEqual(generator_rules.read_bytes(), generator_before)

        deployed = self.service.preflight(
            [record.monster_id], self.server, self.client_data, generator_login_dir=generator,
        )
        receipt = self.service.install(deployed)
        self.assertIn(f"{pak_entry}|isolated-password", server_rules.read_bytes().decode("gb18030"))
        self.assertIn(f"{pak_entry}|isolated-password", generator_rules.read_bytes().decode("gb18030"))
        repeated = self.service.preflight(
            [record.monster_id], self.server, self.client_data, generator_login_dir=generator,
        )
        self.assertEqual(repeated.operation, "already-deployed")
        self.assertEqual(repeated.changes, [])
        deployed_rules = server_rules.read_bytes()
        server_rules.write_bytes(deployed_rules + b"OTHER-TASK.pak|drift\r\n")
        with self.assertRaisesRegex(MonsterLibraryError, "植入后被修改"):
            self.service.rollback(receipt.transaction_id)
        self.assertTrue(target_pak.is_file())
        server_rules.write_bytes(deployed_rules)
        self.service.rollback(receipt.transaction_id)
        self.assertFalse(target_pak.exists())
        self.assertEqual(server_rules.read_bytes(), server_before)
        self.assertEqual(generator_rules.read_bytes(), generator_before)

    def test_smartmonster_pak_password_conflict_blocks_preflight(self):
        """同名Smart PAK已有不同密码时，不能以新规则覆盖既有解密契约。"""
        record = self.prepare_smartmonster_pak_transaction()
        initial = self.service.preflight([record.monster_id], self.server, self.client_data)
        pak_entry = next(item["target_entry"] for item in initial.engine_assignments if item["kind"] == "pak")
        server_rules = self.server / "登录器" / "pak.txt"
        server_rules.write_bytes(
            server_rules.read_bytes() + f"{self.client_data / pak_entry}|different-password\r\n".encode("gb18030")
        )
        before_preflight = self.target_snapshot()

        blocked = self.service.preflight([record.monster_id], self.server, self.client_data)

        self.assertTrue(any("已登记不同密码" in item for item in blocked.blockers))
        with self.assertRaisesRegex(MonsterLibraryError, "预检阻止植入"):
            self.service.install(blocked)
        self.assertEqual(self.target_snapshot(), before_preflight)

    def test_shared_smartmonster_pak_has_one_rule_per_target_filename(self):
        """两个源索引复用同一PAK时，重复规则会让服务端和生成器语义失配。"""
        record = self.prepare_shared_pak_smartmonster_transaction()
        generator = self.root / "actual-generator"
        generator.mkdir()
        (generator / "MakeGameLogin.exe").write_bytes(b"EXE")
        generator_rules = generator / "pak.txt"
        generator_before = b"GENERATOR-BASELINE\r\n"
        generator_rules.write_bytes(generator_before)
        server_rules = self.server / "登录器" / "pak.txt"
        server_before = server_rules.read_bytes()
        plan = self.service.preflight(
            [record.monster_id], self.server, self.client_data, generator_login_dir=generator,
        )
        pak_assignments = [item for item in plan.engine_assignments if item["kind"] == "pak"]
        self.assertEqual(len(pak_assignments), 2)
        self.assertEqual({item["target_entry"] for item in pak_assignments}, {pak_assignments[0]["target_entry"]})
        entry = pak_assignments[0]["target_entry"]
        before = self.target_snapshot()
        from xydp import monster_library
        original_write = monster_library._atomic_write

        def fail_after_generator_rule(path: Path, content: bytes) -> None:
            original_write(path, content)
            if Path(path).resolve() == generator_rules.resolve():
                raise OSError("injected shared PAK generator rule failure")

        with patch("xydp.monster_library._atomic_write", side_effect=fail_after_generator_rule):
            with self.assertRaisesRegex(MonsterLibraryError, "已回滚"):
                self.service.install(plan)
        self.assertEqual(self.target_snapshot(), before)
        self.assertEqual(server_rules.read_bytes(), server_before)
        self.assertEqual(generator_rules.read_bytes(), generator_before)

        receipt = self.service.install(self.service.preflight(
            [record.monster_id], self.server, self.client_data, generator_login_dir=generator,
        ))
        for rules in (server_rules, generator_rules):
            matching = [
                line for line in rules.read_bytes().decode("gb18030").splitlines()
                if line.endswith(f"{entry}|shared-password")
            ]
            self.assertEqual(matching, [matching[0]])
        repeated = self.service.preflight(
            [record.monster_id], self.server, self.client_data, generator_login_dir=generator,
        )
        self.assertEqual(repeated.operation, "already-deployed")
        self.assertEqual(repeated.changes, [])
        self.service.rollback(receipt.transaction_id)
        self.assertEqual(server_rules.read_bytes(), server_before)
        self.assertEqual(generator_rules.read_bytes(), generator_before)

    def test_client_identity_only_accepts_known_client_and_ignores_unrelated_external_tool(self):
        """任意根目录或外部工具EXE不得被误认成可写入的目标客户端。"""
        record = self.prepare_smartmonster_transaction()
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        known_client = self.client_data.parent / "Game.exe"
        known_client.unlink()
        unrelated_root = self.client_data.parent / "UnrelatedTool.exe"
        unrelated_root.write_bytes(b"TOOL")
        before = self.target_snapshot()

        with patch("xydp.monster_library.running_executable_paths", return_value=[]):
            with self.assertRaisesRegex(MonsterLibraryError, "无法确认目标客户端可执行文件"):
                self.service.install(plan)
        self.assertEqual(self.target_snapshot(), before)
        known_client.write_bytes(b"CLIENT")
        with patch("xydp.monster_library.running_executable_paths", return_value=[known_client]):
            with self.assertRaisesRegex(MonsterLibraryError, "目标客户端正在运行"):
                self.service.install(plan)
        external_tool = self.root / "external" / "UnrelatedEditor.exe"
        external_tool.parent.mkdir()
        external_tool.write_bytes(b"EXTERNAL-TOOL")
        with patch("xydp.monster_library.running_executable_paths", return_value=[external_tool]):
            receipt = self.service.install(plan)
        with patch("xydp.monster_library.running_executable_paths", return_value=[external_tool]):
            self.service.rollback(receipt.transaction_id)
        self.assertEqual(self.target_snapshot(), before)

    def test_audited_chinese_launcher_identifies_client_without_accepting_unrelated_root_exe(self):
        """缺少英文Game.exe时，审计过的中文启动器仍须唯一允许事务进入。"""
        record = self.prepare_smartmonster_transaction()
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        game = self.client_data.parent / "Game.exe"
        game.unlink()
        chinese_launcher = self.client_data.parent / "传奇登陆器.exe"
        chinese_launcher.write_bytes(b"AUDITED-CHINESE-LAUNCHER")
        (self.client_data.parent / "UnrelatedTool.exe").write_bytes(b"UNRELATED")
        external_editor = self.root / "external" / "UnrelatedEditor.exe"
        external_editor.parent.mkdir()
        external_editor.write_bytes(b"EXTERNAL")
        before = self.target_snapshot()

        try:
            with patch("xydp.monster_library.running_executable_paths", return_value=[]):
                receipt = self.service.install(plan)
        except MonsterLibraryError as exc:
            self.fail(f"审计中文启动器未被识别：{exc}")
        with patch("xydp.monster_library.running_executable_paths", return_value=[chinese_launcher]):
            with self.assertRaisesRegex(MonsterLibraryError, "目标客户端正在运行"):
                self.service.rollback(receipt.transaction_id)
        with patch("xydp.monster_library.running_executable_paths", return_value=[external_editor]):
            self.service.rollback(receipt.transaction_id)
        self.assertEqual(self.target_snapshot(), before)

    def test_recovery_rejects_forged_external_target_before_writes(self):
        """清单把外部目标伪装成已写目标时，恢复不得删除该外部文件。"""
        plan, _before, manifest, fault_target = self.interrupt_smart_install("smart-generated-file")
        outside = self.root / "outside-target.bin"
        outside.write_bytes(fault_target.read_bytes())
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["files"][0]["target_path"] = str(outside)
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        manifest_before = manifest.read_bytes()
        targets_before = self.target_snapshot()

        with self.assertRaisesRegex(MonsterLibraryError, "恢复清单无效"):
            self.service.recover_in_progress()
        self.assertEqual(manifest.read_bytes(), manifest_before)
        self.assertEqual(outside.read_bytes(), fault_target.read_bytes())
        self.assertEqual(self.target_snapshot(), targets_before)

    def test_recovery_rejects_forged_external_backup_before_writes(self):
        """清单把外部文件伪装成备份时，恢复不得用它覆盖任何目标。"""
        _plan, _before, manifest, _fault_target = self.interrupt_smart_install("effect-image-list")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        effect = next(item for item in payload["files"] if item["kind"] == "effect-image-list")
        outside = self.root / "outside-backup.bin"
        outside.write_bytes(Path(effect["backup_path"]).read_bytes())
        outside_before = outside.read_bytes()
        effect["backup_path"] = str(outside)
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        manifest_before = manifest.read_bytes()
        targets_before = self.target_snapshot()

        with self.assertRaisesRegex(MonsterLibraryError, "恢复清单无效"):
            self.service.recover_in_progress()
        self.assertEqual(manifest.read_bytes(), manifest_before)
        self.assertEqual(outside.read_bytes(), outside_before)
        self.assertEqual(self.target_snapshot(), targets_before)

    def test_recovery_rejects_parent_target_id_mismatch_before_writes(self):
        """transaction目录与声明目标不匹配时，恢复不得消费该清单。"""
        _plan, _before, manifest, _fault_target = self.interrupt_smart_install("smart-generated-file")
        transaction_id = manifest.parent.name
        forged = self.service.backups_root / "wrong-target-id" / transaction_id / "in-progress.json"
        forged.parent.mkdir(parents=True)
        manifest.replace(forged)
        manifest_before = forged.read_bytes()
        targets_before = self.target_snapshot()

        with self.assertRaisesRegex(MonsterLibraryError, "恢复清单无效"):
            self.service.recover_in_progress()
        self.assertEqual(forged.read_bytes(), manifest_before)
        self.assertEqual(self.target_snapshot(), targets_before)

    def test_recovery_rejects_symlink_target_escape_before_writes(self):
        """位于声明根目录的符号链接若逃逸到外部，也不能成为恢复目标。"""
        _plan, _before, manifest, fault_target = self.interrupt_smart_install("smart-generated-file")
        outside = self.root / "outside-directory"
        outside.mkdir()
        victim = outside / "victim.bin"
        victim.write_bytes(fault_target.read_bytes())
        link = self.server / "escape-link"
        link.symlink_to(outside, target_is_directory=True)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["files"][0]["target_path"] = str(link / "victim.bin")
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        manifest_before = manifest.read_bytes()
        targets_before = self.target_snapshot()

        with self.assertRaisesRegex(MonsterLibraryError, "恢复清单无效"):
            self.service.recover_in_progress()
        self.assertEqual(manifest.read_bytes(), manifest_before)
        self.assertEqual(victim.read_bytes(), fault_target.read_bytes())
        self.assertEqual(self.target_snapshot(), targets_before)

    def test_recovery_accepts_valid_mixed_before_and_after_targets(self):
        """真实中断清单的部分已恢复前态与部分后态必须能整体恢复。"""
        plan, before, manifest, _fault_target = self.interrupt_smart_install("effect-image-list")
        one_generated = next(
            Path(change.target_path) for change in plan.changes if change.kind == "smart-generated-file"
        )
        one_generated.unlink()
        transaction_id = json.loads(manifest.read_text(encoding="utf-8"))["transaction_id"]

        self.assertEqual(self.service.recover_in_progress(), (transaction_id,))
        self.assertEqual(self.target_snapshot(), before)
        self.assertEqual(json.loads(manifest.with_name("recovered.json").read_text(encoding="utf-8"))["status"], "recovered")

    def test_process_gate_blocks_install_and_rollback_without_process_control(self):
        """若目标客户端或资源编辑器运行仍继续写入，资源可能被占用或半更新。"""
        record = self.prepare_smartmonster_transaction()
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        before = self.target_snapshot()
        client_exe = self.client_data.parent / "Game.exe"

        with patch("xydp.monster_library.running_executable_paths", return_value=[client_exe]):
            with self.assertRaisesRegex(MonsterLibraryError, "目标客户端正在运行"):
                self.service.install(plan)
        self.assertEqual(self.target_snapshot(), before)
        client_exe.unlink()
        with self.assertRaisesRegex(MonsterLibraryError, "无法确认目标客户端可执行文件"):
            self.service.install(plan)
        client_exe.write_bytes(b"CLIENT")
        receipt = self.service.install(plan)
        editor = self.root / "tools" / "WzlEditor.exe"
        editor.parent.mkdir()
        editor.write_bytes(b"EDITOR")
        with patch("xydp.monster_library.running_executable_paths", return_value=[editor]):
            with self.assertRaisesRegex(MonsterLibraryError, "资源编辑器正在运行"):
                self.service.rollback(receipt.transaction_id)
        self.assertTrue(any(Path(change.target_path).is_file() for change in plan.changes))

    def test_baseexception_interruption_recovers_from_durable_in_progress_manifest(self):
        """若写后发生BaseException而无持久清单，标准回滚无法定位并恢复半提交事务。"""
        record = self.prepare_smartmonster_transaction()
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        before = self.target_snapshot()
        generated_targets = {
            Path(change.target_path).resolve()
            for change in plan.changes if change.kind == "smart-generated-file"
        }
        from xydp import monster_library
        original_write = monster_library._atomic_write

        def interrupt_after_generated_target(path: Path, content: bytes) -> None:
            original_write(path, content)
            if Path(path).resolve() in generated_targets:
                raise KeyboardInterrupt("controlled BaseException interruption")

        with patch("xydp.monster_library._atomic_write", side_effect=interrupt_after_generated_target):
            with self.assertRaises(KeyboardInterrupt):
                self.service.install(plan)
        manifests = list(self.service.backups_root.glob("*/**/in-progress.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "in-progress")
        self.assertTrue(manifest["files"])
        self.assertEqual(self.service.recover_in_progress(), (manifest["transaction_id"],))
        self.assertEqual(self.target_snapshot(), before)
        recovered = manifests[0].with_name("recovered.json")
        self.assertEqual(json.loads(recovered.read_text(encoding="utf-8"))["status"], "recovered")

    def test_schema2_receipt_rollback_remains_compatible(self):
        """若新恢复逻辑假定schema 3，既有schema 2收据将失去可回滚能力。"""
        self.scan()
        record = self.records()["供体怪物甲"]
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        receipt = self.service.install(plan)
        receipt_path = Path(receipt.receipt_path)
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        payload["schema_version"] = 2
        payload.pop("engine_assignments", None)
        payload.pop("requires_custom_monster_dat", None)
        payload.pop("requires_login_regeneration", None)
        receipt_path.write_text(json.dumps(payload), encoding="utf-8")
        self.service.rollback(receipt.transaction_id)
        self.assertFalse((self.client_data / "Mon124.Pak").exists())

    def test_schema3_receipt_rollback_restores_target_byte_exactly(self):
        """若回滚要求Task7字段，历史schema 3收据将无法逐字节恢复目标。"""
        self.scan()
        record = self.records()["供体怪物甲"]
        before = self.target_snapshot()
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        receipt = self.service.install(plan)
        receipt_path = Path(receipt.receipt_path)
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        payload["schema_version"] = 3
        payload.pop("requires_custom_monster_dat", None)
        payload.pop("requires_login_regeneration", None)
        payload.pop("custom_monster_dat_path", None)
        payload.pop("client_integration_status", None)
        receipt_path.write_text(json.dumps(payload), encoding="utf-8")

        self.service.rollback(receipt.transaction_id)

        self.assertEqual(self.target_snapshot(), before)

    def test_actual_generator_rules_are_synced_in_same_transaction_and_rolled_back(self):
        self.scan()
        generator = self.root / "actual-generator"
        generator.mkdir()
        (generator / "MakeGameLogin.exe").write_bytes(b"EXE")
        generator_rules = generator / "pak.txt"
        generator_before = "生成器旧规则.pak|旧密码\r\n".encode("gb18030")
        generator_rules.write_bytes(generator_before)
        ids = [item.monster_id for item in self.service.list_monsters()]

        plan = self.service.preflight(
            ids,
            self.server,
            self.client_data,
            generator_login_dir=generator,
        )

        self.assertEqual(plan.blockers, [])
        self.assertEqual(plan.generator_login_dir, generator.resolve())
        self.assertEqual(plan.generator_rules_added, ("mon124.pak",))
        self.assertTrue(any(change.kind == "generator-pak-rules" for change in plan.changes))
        receipt = self.service.install(plan)
        self.assertIn("Mon124.Pak", generator_rules.read_bytes().decode("gb18030"))
        self.service.rollback(receipt.transaction_id)
        self.assertEqual(generator_rules.read_bytes(), generator_before)

    def test_actual_generator_password_conflict_blocks_all_writes(self):
        self.scan()
        generator = self.root / "actual-generator"
        generator.mkdir()
        (generator / "MakeGameLogin.exe").write_bytes(b"EXE")
        generator_rules = generator / "pak.txt"
        generator_before = f"{self.client_data / 'Mon124.Pak'}|错误密码\r\n".encode("gb18030")
        generator_rules.write_bytes(generator_before)
        ids = [item.monster_id for item in self.service.list_monsters()]

        plan = self.service.preflight(
            ids,
            self.server,
            self.client_data,
            generator_login_dir=generator,
        )

        self.assertTrue(any("已登记不同密码" in item for item in plan.blockers))
        with self.assertRaises(MonsterLibraryError):
            self.service.install(plan)
        self.assertEqual(generator_rules.read_bytes(), generator_before)

    def test_same_name_target_monster_is_skipped_without_overwrite(self):
        self.scan()
        database = self.server / "Mud2" / "DB" / "ApexM2.DB"
        connection = sqlite3.connect(database)
        try:
            row = monster_values("供体怪物甲", 999, Exp=9)
            columns = ", ".join(f'"{item}"' for item in MONSTER_COLUMNS)
            placeholders = ", ".join("?" for _ in MONSTER_COLUMNS)
            connection.execute(
                f'INSERT INTO "Monster" ({columns}) VALUES ({placeholders})',
                tuple(row[item] for item in MONSTER_COLUMNS),
            )
            connection.commit()
        finally:
            connection.close()
        before = database.read_bytes()
        record = self.records()["供体怪物甲"]
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        self.assertTrue(plan.blockers)
        self.assertTrue(any("同名怪物" in item for item in plan.skipped))
        self.assertEqual(database.read_bytes(), before)

    def test_same_name_different_patch_is_skipped_without_overwrite(self):
        self.scan()
        target = self.client_data / "Mon124.Pak"
        target.write_bytes(b"CURRENT-CLIENT-CONTENT")
        before = target.read_bytes()
        record = self.records()["供体怪物甲"]
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        self.assertTrue(plan.blockers)
        self.assertTrue(any("同名异内容" in item for item in plan.skipped))
        self.assertEqual(target.read_bytes(), before)

    def test_manual_change_after_install_blocks_rollback(self):
        self.scan()
        record = self.records()["供体怪物甲"]
        plan = self.service.preflight([record.monster_id], self.server, self.client_data)
        receipt = self.service.install(plan)
        target = self.client_data / "Mon124.Pak"
        target.write_bytes(b"MANUAL-CHANGE")
        with self.assertRaises(MonsterLibraryError):
            self.service.rollback(receipt.transaction_id)
        self.assertEqual(target.read_bytes(), b"MANUAL-CHANGE")

    def test_gui_and_cli_expose_monster_library_workflow(self):
        self.assertIn("怪物库", TAB_TITLES)
        self.assertNotIn("怪物外观库", TAB_TITLES)
        args = _parser().parse_args([
            "monster-library-preflight",
            "--monster-id", "1",
            "--server", str(self.server),
            "--client-data", str(self.client_data),
        ])
        self.assertEqual(args.command, "monster-library-preflight")
        self.assertEqual(args.monster_id, [1])
        self.assertTrue(hasattr(args, "generator_login_dir"))

    def test_gui_returns_manual_generator_step_without_opening_program(self):
        no_patch_plan = SimpleNamespace(
            changes=[],
            generator_login_dir=self.root / "generator",
            generator_rules_added=(),
        )
        with patch("xydp.gui.os.startfile") as startfile:
            message = PlatformApp._prepare_monster_login_generator(no_patch_plan)
        startfile.assert_not_called()
        self.assertIn("无需重新生成", message)

        patch_plan = SimpleNamespace(
            changes=[SimpleNamespace(scope="generator", kind="generator-pak-rules")],
            generator_login_dir=self.root / "generator",
            generator_rules_added=("mon124.pak",),
        )
        with patch("xydp.gui.os.startfile") as startfile:
            message = PlatformApp._prepare_monster_login_generator(patch_plan)
        startfile.assert_not_called()
        self.assertIn(str(patch_plan.generator_login_dir / "MakeGameLogin.exe"), message)
        self.assertIn("请手动打开", message)
        self.assertNotIn("生成器已打开", message)
        self.assertNotIn("只需点击", message)

    def test_gui_refresh_renders_monster_without_preview_image(self):
        self.scan()
        app = PlatformApp(self.platform)
        app.withdraw()
        try:
            app.monster_server_var.set(str(self.server))
            app.monster_status_var.set("可植入")
            app.monster_filter_var.set("供体怪物甲")
            app.monster_refresh()
            self.assertEqual(app.monster_tree.get_children(), ("1",))
            self.assertEqual(app.monster_tree.item("1", "text"), "待桥接")
            self.assertEqual(app.monster_tree.item("1", "values")[1], "供体怪物甲")
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
