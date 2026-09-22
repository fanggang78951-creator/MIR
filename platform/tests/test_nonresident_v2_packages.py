from __future__ import annotations

import json
import sqlite3
import unittest
import tempfile
from pathlib import Path

from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.runtime import platform_root
from xydp.validator import validate_package


class NonresidentV2PackageTests(unittest.TestCase):
    def package(self, package_id: str):
        return validate_package(platform_root() / "packages/candidate" / package_id)

    def payload_text(self, package_id: str, name: str) -> str:
        return (platform_root() / "packages/candidate" / package_id / "payload" / name).read_text(encoding="utf-8")

    def test_duplicate_npc_adapter_packages_are_removed(self):
        root = platform_root() / "packages/candidate"
        self.assertFalse((root / "xy.optional.rage.npc").exists())
        self.assertFalse((root / "xy.optional.donate.npc").exists())

    def test_rage_packages(self):
        core = self.package("xy.optional.rage.core")
        self.assertEqual(core.status, "candidate")
        self.assertEqual(core.residency, "optional")
        operation_types = {item["type"] for item in core.operations}
        self.assertIn("sqlite_upsert", operation_types)
        self.assertIn("ensure_callable_label", operation_types)
        refresh = next(
            item for item in core.operations
            if item.get("label") == "XY_RAGE_UI_REFRESH"
        )
        self.assertEqual(refresh["type"], "ensure_callable_label")
        self.assertIn("exclusive_unique_line", operation_types)
        self.assertIn("managed_anchor_hook", operation_types)
        targets = "\n".join(str(item.get("target", "")) for item in core.operations)
        self.assertIn("MerChant", targets)
        script = self.payload_text(core.id, "狂暴NPC接口.txt")
        wrapper = self.payload_text(core.id, "狂暴NPC入口.txt")
        self.assertIn("[@XY_RAGE_NPC_MAIN]", script)
        self.assertIn("CHECKFENGHAO 狂暴之力", script)
        self.assertIn("GIVEFENGHAO 狂暴之力 1", script)
        self.assertIn("CHECKGAMEGIRD > {rage_cost_threshold}", script)
        self.assertIn("GAMEGIRD - {rage_cost}", script)
        self.assertNotIn("CHECKGAMEDIAMOND", script)
        self.assertNotIn("N$XY_RAGE_ACTIVE", script)
        self.assertNotIn("POWERRATE", script)
        self.assertIn("狂暴NPC接口.txt] @XY_RAGE_NPC_MAIN", wrapper)
        command = next(item for item in core.operations if item["type"] == "managed_block")
        self.assertIn("[@XY_RAGE_COMMAND]", command["content"])
        self.assertIn("狂暴NPC接口.txt] @XY_RAGE_NPC_MAIN", command["content"])

    def test_donate_packages(self):
        core = self.package("xy.optional.donate.core")
        self.assertEqual(core.status, "candidate")
        self.assertEqual(core.residency, "optional")
        operation_types = {item["type"] for item in core.operations}
        self.assertIn("config_merge", operation_types)
        self.assertNotIn("unique_line", operation_types)
        self.assertNotIn("sqlite_upsert", operation_types)
        script = self.payload_text(core.id, "捐献核心.txt")
        config = self.payload_text(core.id, "捐献配置.txt")
        self.assertIn("[@XY_DONATE_TRIGGER]", script)
        self.assertIn("ReadConfigFileItem", script)
        self.assertNotIn("WriteConfigFileItem", script)
        self.assertNotIn("玄渊数据\\xy_donate", script)
        self.assertNotIn("ForceDirectories", script)
        self.assertNotIn("CreateFile", script)
        self.assertNotIn("GAMEDIAMOND - 100", script)
        first_guard = script.index("CHECKFENGHAO {donate_title}")
        grant = script.index("GIVEFENGHAO {donate_title} 1")
        grant_confirm = script.index("CHECKFENGHAO {donate_title}", grant)
        self.assertIn("EQUAL S$XY_DONATE_COST_TYPE 原生灵符", script)
        self.assertIn("CHECKGAMEGIRD > <$STR(N$XY_DONATE_COST_THRESHOLD)>", script)
        self.assertIn("GAMEGIRD - <$STR(N$XY_DONATE_COST_COUNT)>", script)
        lingfu_debit = script.index("GAMEGIRD - <$STR(N$XY_DONATE_COST_COUNT)>")
        self.assertLess(first_guard, grant)
        self.assertLess(grant, grant_confirm)
        self.assertLess(grant_confirm, lingfu_debit)
        self.assertIn("EQUAL S$XY_DONATE_COST_TYPE 原生金币", script)
        self.assertIn("GOLDCOUNT - <$STR(N$XY_DONATE_COST_COUNT)>", script)
        self.assertIn("EQUAL S$XY_DONATE_COST_TYPE 原生元宝", script)
        self.assertIn("GAMEGOLD - <$STR(N$XY_DONATE_COST_COUNT)>", script)
        self.assertIn("EQUAL S$XY_DONATE_COST_TYPE 原生金刚石", script)
        self.assertIn("GAMEDIAMOND - <$STR(N$XY_DONATE_COST_COUNT)>", script)
        self.assertIn("消耗类型=原生灵符", config)
        self.assertIn("消耗名称=灵符", config)
        for key in ("消耗类型", "消耗名称", "消耗数量", "捐献成功", "已经激活", "发放失败"):
            self.assertIn(key + "=", config)
        self.assertNotIn("累计增加=", config)
        self.assertNotIn("封榜阈值=", config)
        self.assertNotIn("榜一奖励数量=", config)
        self.assertFalse(any(
            str(item.get("target", "")).endswith("玄渊数据/xy_donate/捐献状态.txt")
            for item in core.operations
        ))
        command = next(item for item in core.operations if item["type"] == "managed_block")
        self.assertIn("[@XY_DONATE_COMMAND]", command["content"])
        self.assertIn("@XY_DONATE_TRIGGER", command["content"])

    def test_rage_death_cleanup_uses_the_same_title_state(self):
        core = self.package("xy.optional.rage.core")
        die = next(
            item for item in core.operations
            if item["type"] == "event_hook" and item["label"] == "PlayDie"
        )["content"]
        self.assertIn("CHECKFENGHAO 狂暴之力", die)
        self.assertIn("RECYCFENGHAO 狂暴之力", die)
        self.assertIn("KillByHum", die)
        self.assertNotIn("N$XY_RAGE_ACTIVE", die)

    def test_single_packages_create_one_rage_npc_source_and_roll_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); target = root / "server"; envir = target / "Mir200/Envir"
            (target / "Mir200").mkdir(parents=True)
            (target / "Mir200/M2Server.exe").write_bytes(b"M2")
            (target / "Mir200/!setup.txt").write_bytes("[Setup]\r\nRevivalTime=60000\r\n".encode("gb18030"))
            (envir / "Market_Def").mkdir(parents=True)
            (envir / "MapInfo.txt").write_bytes("[0 盟重]\r\n".encode("gb18030"))
            (envir / "MerChant.txt").write_bytes(b"")
            (envir / "Market_Def/QFunction-0.txt").write_bytes("[@PlayLogin]\r\n#IF\r\n#ACT\r\n".encode("gb18030"))
            database = target / "Mud2/DB/ApexM2.DB"
            database.parent.mkdir(parents=True)
            rage_manifest = json.loads(
                (platform_root() / "packages/candidate/xy.optional.rage.core/manifest.json").read_text(encoding="utf-8")
            )
            rage_values = next(
                item for item in rage_manifest["operations"] if item["type"] == "sqlite_upsert"
            )["values"]
            columns = ["Idx INTEGER", *(
                f'"{name}" {"TEXT" if name == "Name" else "INTEGER"}' for name in rage_values
            )]
            connection = sqlite3.connect(database)
            try:
                connection.execute(f'CREATE TABLE StdItems ({", ".join(columns)})')
                connection.commit()
            finally:
                connection.close()
            before = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}

            repository = PackageRepository(platform_root() / "packages"); repository.refresh()
            installer = Installer(repository, root / "backups")
            plan = installer.preflight(target, ["xy.optional.rage.core", "xy.optional.donate.core"], {})
            self.assertTrue(any("MerChant" in item.relative_path for item in plan.changes))
            self.assertTrue(any("Market_Def/玄渊运营" in item.relative_path for item in plan.changes))
            receipt = installer.install(plan)
            rage_script = (envir / "QuestDiary/玄渊功能/狂暴/狂暴NPC接口.txt").read_text(
                encoding="gb18030"
            )
            rage_npc = (envir / "Market_Def/玄渊运营/狂暴之力-0.txt").read_text(encoding="gb18030")
            donate_core = (envir / "QuestDiary/玄渊功能/捐献/捐献核心.txt").read_text(
                encoding="gb18030"
            )
            self.assertIn("CHECKFENGHAO 狂暴之力", rage_script)
            self.assertIn("CHECKGAMEGIRD > 99", rage_script)
            self.assertIn("GAMEGIRD - 100", rage_script)
            self.assertIn("狂暴NPC接口.txt] @XY_RAGE_NPC_MAIN", rage_npc)
            self.assertNotIn("N$XY_RAGE_ACTIVE", rage_script)
            first_guard = donate_core.index("CHECKFENGHAO 沙城捐献")
            grant = donate_core.index("GIVEFENGHAO 沙城捐献 1")
            grant_confirm = donate_core.index("CHECKFENGHAO 沙城捐献", grant)
            debit = donate_core.index("GAMEGIRD - <$STR(N$XY_DONATE_COST_COUNT)>")
            self.assertLess(first_guard, grant)
            self.assertLess(grant, grant_confirm)
            self.assertLess(grant_confirm, debit)
            self.assertNotIn("WriteConfigFileItem", donate_core)
            state = envir / "QuestDiary/玄渊数据/xy_donate/捐献状态.txt"
            self.assertFalse(state.exists())
            qfunction = (envir / "Market_Def/QFunction-0.txt").read_text(encoding="gb18030")
            self.assertIn("[@XY_RAGE_COMMAND]", qfunction)
            self.assertIn("[@XY_DONATE_COMMAND]", qfunction)
            self.assertIn("CHECKFENGHAO 狂暴之力", qfunction)
            self.assertEqual(installer.preflight(
                target, ["xy.optional.rage.core", "xy.optional.donate.core"], {}
            ).changes, [])
            installer.rollback(target, receipt.transaction_id)
            after = {
                path.relative_to(target): path.read_bytes()
                for path in target.rglob("*") if path.is_file() and ".xydp" not in path.parts
            }
            self.assertEqual(after, before)

    def test_donate_install_preserves_existing_state_file_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "server"
            envir = target / "Mir200/Envir"
            (target / "Mir200").mkdir(parents=True)
            (target / "Mir200/M2Server.exe").write_bytes(b"M2")
            (target / "Mir200/!setup.txt").write_bytes(b"[Setup]\r\n")
            (envir / "Market_Def").mkdir(parents=True)
            (envir / "MapInfo.txt").write_bytes("[0 盟重]\r\n".encode("gb18030"))
            (envir / "Market_Def/QFunction-0.txt").write_bytes(b"[@PlayLogin]\r\n#IF\r\n#ACT\r\n")
            state = envir / "QuestDiary/玄渊数据/xy_donate/捐献状态.txt"
            state.parent.mkdir(parents=True)
            expected = "[全服]\r\n累计=900\r\n榜一金额=600\r\n[玩家]\r\n测试玩家=600\r\n".encode("gb18030")
            state.write_bytes(expected)
            before = {
                path.relative_to(target): path.read_bytes()
                for path in target.rglob("*") if path.is_file()
            }

            repository = PackageRepository(platform_root() / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")
            plan = installer.preflight(target, ["xy.optional.donate.core"], {})
            self.assertFalse(any(item.relative_path.endswith("捐献状态.txt") for item in plan.changes))
            receipt = installer.install(plan)
            self.assertEqual(state.read_bytes(), expected)
            self.assertEqual(installer.preflight(target, ["xy.optional.donate.core"], {}).changes, [])
            installer.rollback(target, receipt.transaction_id)
            after = {
                path.relative_to(target): path.read_bytes()
                for path in target.rglob("*") if path.is_file() and ".xydp" not in path.parts
            }
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
