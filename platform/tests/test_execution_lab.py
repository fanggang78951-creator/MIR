import json
import tempfile
import unittest
from pathlib import Path

from xydp.execution_lab import ExecutionLabService, OPERATION_TYPE, PACKAGE_ID
from xydp.installer import InstallError
from xydp.repository import PackageRepository
from xydp.runtime import platform_root
from xydp.validator import validate_package


def make_target(root: Path) -> Path:
    target = root / "server"
    envir = target / "Mir200/Envir"
    market = envir / "Market_Def"
    mapquest = envir / "MapQuest_Def"
    market.mkdir(parents=True)
    mapquest.mkdir(parents=True)
    (target / "Mir200/M2Server.exe").write_bytes(b"M2")
    (target / "Mir200/!setup.txt").write_bytes(
        b"SendItemDescList=0\r\nSendTzItemDescList=0\r\n"
    )
    (envir / "MapInfo.txt").write_bytes("[0 盟重]\r\n".encode("gb18030"))
    (envir / "MerChant.txt").write_bytes(b"")
    (market / "QFunction-0.txt").write_bytes(
        "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
    )
    (mapquest / "QManage.txt").write_bytes(
        "[@Login]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
    )
    return target


def game_files(target: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(target): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file() and ".xydp" not in path.parts
    }


class ExecutionLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = platform_root()
        cls.package_dir = cls.root / "labs/execution/packages/candidate/xy.lab.execution"
        cls.package = validate_package(cls.package_dir)
        cls.script = next(
            operation["content"] for operation in cls.package.operations
            if operation["type"] == "event_hook" and operation["label"] == "AttackDamage"
        )

    def test_lab_package_is_not_in_normal_repository_or_resident_base(self):
        normal = PackageRepository(self.root / "packages")
        normal.refresh()
        self.assertNotIn(PACKAGE_ID, normal.packages)
        self.assertNotIn("xy.combat.execution", normal.packages)
        self.assertNotIn("xy.combat.execution", normal.packages["xy.combat-suite"].dependencies)
        self.assertNotIn(PACKAGE_ID, normal.packages["xy.combat-suite"].dependencies)
        resident = {item.id for item in normal.packages.values() if item.residency == "resident"}
        self.assertNotIn(PACKAGE_ID, resident)

    def test_production_equipment_registry_has_controlled_execution_bridge(self):
        profile = json.loads(
            (self.root / "做装备/profiles/script_properties.json").read_text(encoding="utf-8")
        )["properties"]
        self.assertEqual(
            {key: profile[key]["display"]["bind_type"] for key in ("处决概率", "韧性", "处决倍率", "处决时间")},
            {"处决概率": 49, "韧性": 50, "处决倍率": 51, "处决时间": 52},
        )
        contract = json.loads(
            (self.root / "labs/execution/equipment/script_properties.execution-lab.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(contract["properties"]),
            {"处决概率", "韧性", "处决倍率", "处决时间"},
        )

    def test_formula_and_pvp_contract(self):
        self.assertIn("100+(<$STR(N$XY_EXEC_Tier)>-1)*80/3", self.script)
        self.assertIn("(5+(<$STR(N$XY_EXEC_Tier)>-1))*200", self.script)
        self.assertEqual(self.script.count("100+(<$STR(N$XY_EXEC_Tier)>-1)*80/3"), 2)
        self.assertEqual(self.script.count("(5+(<$STR(N$XY_EXEC_Tier)>-1))*200"), 2)
        self.assertNotIn("#CALL", self.script)
        self.assertNotIn("GOTO", self.script)
        self.assertNotIn("XY_EXEC_ATTACK", self.script)
        self.assertNotIn("XY_EXEC_CALC_TIER", self.script)
        self.assertIn("*10", self.script)
        qmanage = next(
            operation["content"] for operation in self.package.operations
            if operation["type"] == "managed_block"
            and operation["target"] == "Mir200/Envir/MapQuest_Def/QManage.txt"
        )
        self.assertIn("[@XYDP_ExecutionApplySlow]", qmanage)
        self.assertIn("ChangeSpeed 1 -10", qmanage)
        self.assertIn("ChangeSpeed 1 0", qmanage)
        self.assertNotIn("ChangeSpeedEX", qmanage)
        self.assertIn("DelayCall <$STR(N$XY_EXEC_SlowDurationMs)> @XYDP_ExecutionClearSlow", qmanage)
        pvp = self.script.split("#IF\nCHECKCURRTARGETRACE = 0", 1)[1]
        pvp = "#IF\nCHECKCURRTARGETRACE = 0" + pvp.split("NOT CHECKCURRTARGETRACE = 0", 1)[0]
        self.assertIn("ChangeDamageValue 1 + <$STR(N$XY_EXEC_PVPBonusPercent)>", pvp)
        self.assertEqual(pvp.count("ChangeDamageValue"), 2)
        self.assertIn("MOV S$XY_EXEC_PVPTarget <$C.USERNAME>", pvp)
        self.assertIn("CompareText S$XY_EXEC_PVPCurrentTarget S$XY_EXEC_PVPTarget", pvp)
        self.assertIn("MOV N$XY_EXEC_PVPActive 1", pvp)
        self.assertIn("DelayCall <$STR(N$XY_EXEC_DurationMs)> @XYDP_ExecutionClearPVP", pvp)
        self.assertNotIn("N$XY_EXEC_PVEEquipBonusPercent", pvp)
        self.assertNotIn("N$XY_EXEC_PVEEquipDurationMs", pvp)
        pve = self.script.split("NOT CHECKCURRTARGETRACE = 0", 1)[1]
        self.assertIn("INC N$XY_EXEC_BonusPercent <$STR(N$XY_EXEC_PVEEquipBonusPercent)>", pve)
        self.assertIn("INC N$XY_EXEC_DurationMs <$STR(N$XY_EXEC_PVEEquipDurationMs)>", pve)
        self.assertEqual(1000 - 60 * 10, 400)
        self.assertEqual(100 + (4 - 1) * 80 // 3, 180)
        self.assertEqual((5 + 4 - 1) * 200, 1600)

    def test_qfunction_dispatches_directly_and_test_npc_is_isolated(self):
        attack = next(
            operation["content"] for operation in self.package.operations
            if operation["type"] == "event_hook" and operation["label"] == "AttackDamage"
        )
        self.assertIn("CHECKCURRTARGETRACE = 0", attack)
        self.assertIn("NOT CHECKCURRTARGETRACE = 0", attack)
        self.assertNotIn("@XY_EXEC_ATTACK", attack)
        self.assertNotIn("#CALL", attack)
        self.assertIn("N$XY_EXEC_TestChanceBP", attack)
        npc_copy = next(
            operation for operation in self.package.operations
            if operation["type"] == "transcode_copy"
            and operation["source"] == "payload/处决测试员.txt"
        )
        self.assertEqual(
            npc_copy["target"],
            "Mir200/Envir/Market_Def/玄渊实验室/处决/处决测试员-0.txt",
        )
        merchant = next(
            operation for operation in self.package.operations
            if operation["type"] == "unique_line"
        )
        self.assertIn("\t0\t330\t330\t处决测试员\t", merchant["line"])

    def test_preflight_is_zero_write_and_plan_contains_only_lab_package(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base)
            before = game_files(target)
            service = ExecutionLabService(self.root)
            plan = service.preflight(target)
            self.assertEqual(plan.operation_type, OPERATION_TYPE)
            self.assertEqual(plan.package_ids, [PACKAGE_ID])
            self.assertTrue(plan.changes)
            self.assertEqual(before, game_files(target))
            self.assertFalse((target / ".xydp").exists())

    def test_preflight_compiles_registered_map_rules_into_same_transaction(self):
        """Catches a regression where 13号表 is registered but omitted from the execution plan."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base)
            rules = base / "13_地图怪物处决规则.csv"
            rules.write_text(
                "map_id,enabled,required_toughness,base_chance_bp,monster_execution_toughness,中文说明,填写说明\n"
                "0,1,100,1000,60,地图0,100BP等于1%\n"
                "17,1,200,800,25,地图17,玩家韧性达到200免疫\n",
                encoding="utf-8-sig",
            )
            before = game_files(target)
            service = ExecutionLabService(self.root)
            service.rules_path = rules

            plan = service.preflight(target)

            qfunction = next(
                change.after.decode("gb18030")
                for change in plan.changes
                if change.relative_path == "Mir200/Envir/Market_Def/QFunction-0.txt"
            )
            self.assertEqual(plan.package_ids, [PACKAGE_ID])
            self.assertEqual(plan.parameters["map_rule_count"], 2)
            self.assertEqual(plan.parameters["map_rule_ids"], [0, 17])
            self.assertEqual(len(plan.parameters["map_rules_sha256"]), 64)
            self.assertIn("ISONMAP 0", qfunction)
            self.assertIn("ISONMAP 17", qfunction)
            self.assertIn("MOV N$XY_EXEC_MONSTER_MapRequiredToughness 200", qfunction)
            self.assertIn("MOV N$XY_EXEC_MONSTER_MapPVEToughness 25", qfunction)
            self.assertIn("SMALL N$XY_EXEC_PVEMapEffectiveBP 0", qfunction)
            self.assertIn("MOV N$XY_EXEC_PVEMapEffectiveBP 0", qfunction)
            self.assertEqual(before, game_files(target))

    def test_preflight_accepts_lfm2_xx_logical_map_ids(self):
        """Catches coercing real LFM2 map ids such as XX346 to integers."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base)
            before = game_files(target)
            rules = base / "rules.csv"
            rules.write_text(
                "map_id,enabled,required_toughness,base_chance_bp,monster_execution_toughness,中文说明\n"
                "XX346,1,150,700,150,漂流墓地\n"
                "XX347,1,150,725,150,英雄墓地\n"
                "XX932,1,1050,1150,1050,王城下城区\n",
                encoding="utf-8-sig",
            )
            service = ExecutionLabService(self.root)
            service.rules_path = rules

            plan = service.preflight(target)

            qfunction = next(
                change.after.decode("gb18030")
                for change in plan.changes
                if change.relative_path == "Mir200/Envir/Market_Def/QFunction-0.txt"
            )
            self.assertEqual(plan.parameters["map_rule_ids"], ["XX346", "XX347", "XX932"])
            self.assertIn("ISONMAP XX346", qfunction)
            self.assertIn("ISONMAP XX347", qfunction)
            self.assertIn("MOV N$XY_EXEC_MONSTER_MapPVEToughness 1050", qfunction)
            self.assertEqual(before, game_files(target))

    def test_map_rule_table_rejects_duplicate_map_without_writing_target(self):
        """Catches silent last-row-wins behavior for duplicate logical map ids."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base)
            before = game_files(target)
            rules = base / "rules.csv"
            rules.write_text(
                "map_id,enabled,required_toughness,base_chance_bp,monster_execution_toughness,中文说明,填写说明\n"
                "0,1,100,1000,60,第一行,说明\n"
                "0,1,200,500,20,重复行,说明\n",
                encoding="utf-8-sig",
            )
            service = ExecutionLabService(self.root)
            service.rules_path = rules

            with self.assertRaisesRegex(InstallError, "地图规则重复.*0"):
                service.preflight(target)

            self.assertEqual(before, game_files(target))
            self.assertFalse((target / ".xydp").exists())

    def test_existing_verified_legacy_map_pilot_is_updated_without_reinstalling_parent(self):
        """Catches attempts to overwrite the historically mixed parent block on an accepted server."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base)
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            legacy = """[@PlayLogin]\r
#IF\r
#ACT\r
BREAK\r
\r
; XYDP-LAB-BEGIN xy.lab.execution.monster-map0\r
[@XYDP_ExecutionLoadMapRule]\r
#IF\r
#ACT\r
MOV N$XY_EXEC_MONSTER_MapEnabled 0\r
; XY_EXECUTION_MONSTER_MAP_RULES_BEGIN\r
#IF\r
ISONMAP 0\r
#ACT\r
MOV N$XY_EXEC_MONSTER_MapEnabled 1\r
MOV N$XY_EXEC_MONSTER_MapRequiredToughness 100\r
MOV N$XY_EXEC_MONSTER_MapChanceBP 1000\r
MOV N$XY_EXEC_MONSTER_MapPVEToughness 60\r
; XY_EXECUTION_MONSTER_MAP_RULES_END\r
MOV N$XY_EXEC_MONSTER_MapRuleLoaded 1\r
; XYDP-LAB-END xy.lab.execution.monster-map0\r
""".encode("gb18030")
            qfunction.write_bytes(legacy)
            rules = base / "rules.csv"
            rules.write_text(
                "map_id,enabled,required_toughness,base_chance_bp,monster_execution_toughness,中文说明,填写说明\n"
                "0,1,150,1200,30,更新地图0,说明\n"
                "17,1,200,800,25,新增地图17,说明\n",
                encoding="utf-8-sig",
            )
            before = game_files(target)
            service = ExecutionLabService(self.root)
            service.rules_path = rules

            plan = service.preflight(target)

            self.assertEqual(len(plan.changes), 1)
            self.assertEqual(plan.changes[0].relative_path, "Mir200/Envir/Market_Def/QFunction-0.txt")
            rendered = plan.changes[0].after.decode("gb18030")
            self.assertEqual(rendered.count("[@XYDP_ExecutionLoadMapRule]"), 1)
            self.assertIn("ISONMAP 17", rendered)
            self.assertIn("MOV N$XY_EXEC_MONSTER_MapRequiredToughness 150", rendered)
            self.assertNotIn("MOV N$XY_EXEC_MONSTER_MapPVEToughness 60", rendered)
            self.assertEqual(before, game_files(target))

            receipt = service.install(plan, confirmed_test_server=True)
            self.assertEqual(receipt.operation_type, OPERATION_TYPE)
            self.assertEqual(receipt.packages, {PACKAGE_ID: "1.2.0-lab.10"})
            installed = qfunction.read_text(encoding="gb18030")
            self.assertIn("ISONMAP 17", installed)
            self.assertIn("MOV N$XY_EXEC_MONSTER_MapRequiredToughness 150", installed)
            self.assertEqual(len(service.preflight(target).changes), 0)

            self.assertEqual(service.rollback_latest(target), receipt.transaction_id)
            self.assertEqual(before, game_files(target))

    def test_install_requires_explicit_test_server_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            target = make_target(Path(td))
            service = ExecutionLabService(self.root)
            plan = service.preflight(target)
            with self.assertRaisesRegex(InstallError, "独立测试服"):
                service.install(plan, confirmed_test_server=False)
            self.assertFalse((target / ".xydp").exists())

    def test_independent_backup_and_byte_exact_rollback_preserve_global_state(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base)
            global_state = target / ".xydp/installed.json"
            global_state.parent.mkdir(parents=True)
            global_state.write_bytes(b'{"packages":{"xy.other":"1"},"transactions":["other"]}')
            global_before = global_state.read_bytes()
            before = game_files(target)

            service = ExecutionLabService(self.root)
            receipt = service.install(service.preflight(target), confirmed_test_server=True)
            self.assertEqual(receipt.operation_type, OPERATION_TYPE)
            self.assertEqual(receipt.packages, {PACKAGE_ID: "1.2.0-lab.10"})
            self.assertTrue(Path(receipt.backup_root).is_relative_to(service.lab_root / "backups"))
            self.assertTrue((Path(receipt.backup_root) / "receipt.json").exists())
            self.assertTrue((target / ".xydp/execution-lab/installed.json").exists())
            self.assertEqual(global_state.read_bytes(), global_before)
            self.assertFalse((target / "Mir200/Envir/QuestDiary/玄渊实验室/处决/处决核心.txt").exists())
            self.assertTrue((target / "Mir200/Envir/Market_Def/玄渊实验室/处决/处决测试员-0.txt").exists())
            qmanage = target / "Mir200/Envir/MapQuest_Def/QManage.txt"
            self.assertIn("[@XYDP_ExecutionApplySlow]", qmanage.read_text(encoding="gb18030"))

            transaction = service.rollback_latest(target)
            self.assertEqual(transaction, receipt.transaction_id)
            self.assertEqual(before, game_files(target))
            self.assertEqual(global_state.read_bytes(), global_before)
            self.assertFalse((target / ".xydp/execution-lab").exists())

    def test_manual_change_after_install_blocks_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            target = make_target(Path(td))
            service = ExecutionLabService(self.root)
            receipt = service.install(service.preflight(target), confirmed_test_server=True)
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_bytes(qfunction.read_bytes() + b"\r\n; manual change")
            with self.assertRaisesRegex(InstallError, "安装后被修改"):
                service.rollback_latest(target)
            self.assertEqual(service.latest_transaction(target), receipt.transaction_id)

    def test_preflight_change_aborts_transaction_without_half_product(self):
        with tempfile.TemporaryDirectory() as td:
            target = make_target(Path(td))
            service = ExecutionLabService(self.root)
            plan = service.preflight(target)
            backups_before = set(service.installer.backups_root.glob("*"))
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            changed = qfunction.read_bytes() + b"\r\n; changed after preflight"
            qfunction.write_bytes(changed)
            with self.assertRaisesRegex(InstallError, "预检后目标发生变化"):
                service.install(plan, confirmed_test_server=True)
            self.assertEqual(qfunction.read_bytes(), changed)
            self.assertFalse((target / "Mir200/Envir/Market_Def/玄渊实验室/处决/处决测试员-0.txt").exists())
            self.assertEqual(backups_before, set(service.installer.backups_root.glob("*")))
            self.assertFalse((target / ".xydp/execution-lab").exists())

    def test_repeated_preflight_after_install_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            target = make_target(Path(td))
            service = ExecutionLabService(self.root)
            service.install(service.preflight(target), confirmed_test_server=True)
            second = service.preflight(target)
            self.assertEqual(second.package_ids, [PACKAGE_ID])
            self.assertEqual(second.changes, [])

    def test_every_changespeed_uses_supported_native_range(self):
        scripts = [
            operation["content"]
            for operation in self.package.operations
            if "content" in operation
        ]
        scripts.append(
            (self.package_dir / "payload/处决测试员.txt").read_text(encoding="utf-8")
        )
        commands = [
            line.strip().split()
            for script in scripts
            for line in script.splitlines()
            if line.strip().lower().startswith("changespeed ")
        ]
        self.assertTrue(commands)
        self.assertTrue(all(len(command) == 3 for command in commands), commands)
        self.assertTrue(all(command[1] == "1" for command in commands), commands)
        self.assertTrue(all(-10 <= int(command[2]) <= 10 for command in commands), commands)
        self.assertFalse(any("ChangeSpeedEX" in script for script in scripts))

    def test_pvp_window_is_cleared_by_timer_and_lifecycle_events(self):
        managed = next(
            operation["content"] for operation in self.package.operations
            if operation["type"] == "managed_block"
            and operation["target"] == "Mir200/Envir/Market_Def/QFunction-0.txt"
        )
        self.assertIn("[@XYDP_ExecutionClearPVP]", managed)
        for value in (
            "N$XY_EXEC_PVPActive",
            "N$XY_EXEC_PVPBonusPercent",
            "S$XY_EXEC_PVPTarget",
            "S$XY_EXEC_PVPCurrentTarget",
        ):
            self.assertIn(f"MOV {value} 0", managed)
            for label in ("PlayLogin", "PlayDie", "PlayOffLine"):
                hook = next(
                    operation["content"] for operation in self.package.operations
                    if operation["type"] == "event_hook" and operation["label"] == label
                )
                self.assertIn(f"MOV {value} 0", hook)


if __name__ == "__main__":
    unittest.main()
