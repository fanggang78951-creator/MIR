from __future__ import annotations

import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from xydp.growth_stage import GrowthStageError, GrowthStageService, STAGE_SPECS, _stage_script
from xydp.initial_camp import read_workbook


class GrowthStageTests(unittest.TestCase):
    platform = Path(r"E:\XuanYuanDevPlatform")

    def database_with_items(self, *names: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix="xydp-growth-stage-") as td:
            path = Path(td) / "ApexM2.DB"
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT)")
                for index, name in enumerate(names, 1):
                    connection.execute("INSERT INTO StdItems VALUES (?, ?)", (index, name))
                connection.commit()
            finally:
                connection.close()
            return path.read_bytes()

    def make_target(self, root: Path) -> Path:
        envir = root / "Mir200" / "Envir"
        (envir / "Market_Def").mkdir(parents=True)
        (root / "Mir200" / "M2Server.exe").write_bytes(b"M2")
        (envir / "MapInfo.txt").write_text(
            "[XY_NMGF_MAIN|vx175 宁姆格福] SAFE\r\n", encoding="gb18030"
        )
        (envir / "MerChant.txt").write_text(
            "旧NPC/测试\tXY_NMGF_MAIN\t84\t88\t旧NPC\t0\t1\t0\r\n",
            encoding="gb18030",
        )
        width, height, cell_size = 200, 150, 14
        map_data = bytearray(52 + width * height * cell_size)
        struct.pack_into("<HH", map_data, 0, width, height)
        (root / "Mir200" / "Map").mkdir(parents=True)
        (root / "Mir200" / "Map" / "vx175.map").write_bytes(map_data)
        db = root / "Mud2" / "DB" / "ApexM2.DB"
        db.parent.mkdir(parents=True)
        connection = sqlite3.connect(db)
        try:
            connection.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT)")
            connection.executemany(
                "INSERT INTO StdItems VALUES (?, ?)",
                [(1, "圣律之剑LV10"), (2, "黄金圣物LV10")],
            )
            connection.commit()
        finally:
            connection.close()
        return root

    def test_pending_nmgf_stage_recognizes_lv10_without_consuming_resources(self):
        spec = STAGE_SPECS["nmgf_sword"]
        script, state = _stage_script(
            spec,
            "圣律之剑进阶",
            ({"功能ID": "nmgf_sword", "状态": "待配置", "当前装备": "圣律之剑LV10"},),
            self.database_with_items("圣律之剑LV10"),
        )
        self.assertEqual(state, "待配置")
        self.assertIn("CHECKITEM 圣律之剑LV10 1", script)
        self.assertIn("宁姆格福后续成长表尚未配置", script)
        self.assertNotIn("TAKE ", script)

    def test_nmgf_stage_is_unbounded_and_last_item_is_only_continent_complete(self):
        spec = STAGE_SPECS["nmgf_sword"]
        rows = (
            {"状态": "可安装", "当前装备": "圣律之剑LV10", "下一装备": "圣律之剑LV11", "货币A": "金币", "货币A数量": 10},
            {"状态": "可安装", "当前装备": "圣律之剑LV11", "下一装备": "圣律之剑LV12", "货币A": "金币", "货币A数量": 20},
        )
        script, state = _stage_script(
            spec, "圣律之剑进阶", rows,
            self.database_with_items("圣律之剑LV10", "圣律之剑LV11", "圣律之剑LV12"),
        )
        self.assertEqual(state, "可安装")
        self.assertIn("CHECKITEM 圣律之剑LV12 1\n#ACT\nGOTO @XY_NMGF_SWORD_FULL", script)
        self.assertIn("本大陆阶段已经完成", script)
        self.assertIn("后续大陆请前往对应成长NPC", script)
        self.assertNotIn("已满级", script)
        self.assertEqual(script.count("<ItemShow:"), 2)

    def test_nmgf_stage_uses_native_yuanbao_instead_of_backpack_item(self):
        spec = STAGE_SPECS["nmgf_sword"]
        rows = (
            {"状态": "可安装", "当前装备": "圣律之剑LV10", "下一装备": "圣律真言LV1",
             "材料A": "失色锻造石", "材料A数量": 50, "货币A": "元宝", "货币A数量": 10000},
        )
        script, state = _stage_script(
            spec, "圣律之剑进阶", rows,
            self.database_with_items("圣律之剑LV10", "圣律真言LV1"),
        )
        self.assertEqual(state, "可安装")
        self.assertIn("CHECKITEM 失色锻造石 50", script)
        self.assertIn("TAKE 失色锻造石 50", script)
        self.assertIn("CHECKGAMEGOLD > 9999", script)
        self.assertIn("GAMEGOLD - 10000", script)
        self.assertNotIn("CHECKITEM 元宝", script)
        self.assertNotIn("TAKE 元宝", script)

    def test_nmgf_stage_must_start_at_lv10(self):
        spec = STAGE_SPECS["nmgf_relic"]
        rows = ({"状态": "可安装", "当前装备": "黄金圣物LV11", "下一装备": "黄金圣物LV12", "货币A": "金币", "货币A数量": 1},)
        with self.assertRaisesRegex(GrowthStageError, "必须从黄金圣物LV10开始"):
            _stage_script(
                spec, "黄金圣物进阶", rows,
                self.database_with_items("黄金圣物LV11", "黄金圣物LV12"),
            )

    def test_registered_nmgf_workbooks_are_pending_and_keep_distinct_npcs(self):
        sword = read_workbook(self.platform / "所需材料表格汇总" / "23_宁姆格福_圣律之剑.xlsx")
        relic = read_workbook(self.platform / "所需材料表格汇总" / "24_宁姆格福_黄金圣物.xlsx")
        self.assertEqual(sword.rows[0]["功能ID"], "nmgf_sword")
        self.assertEqual(relic.rows[0]["功能ID"], "nmgf_relic")
        self.assertEqual(sword.rows[0]["当前装备"], "圣律之剑LV10")
        self.assertEqual(relic.rows[0]["当前装备"], "黄金圣物LV10")
        self.assertNotEqual(sword.rows[0]["NPC名称"], relic.rows[0]["NPC名称"])

    def test_pending_stage_install_is_idempotent_and_byte_rollback(self):
        with tempfile.TemporaryDirectory(prefix="xydp-growth-stage-target-") as td:
            target = self.make_target(Path(td) / "server")
            merchant = target / "Mir200" / "Envir" / "MerChant.txt"
            before = merchant.read_bytes()
            documents = [
                self.platform / "所需材料表格汇总" / "23_宁姆格福_圣律之剑.xlsx",
                self.platform / "所需材料表格汇总" / "24_宁姆格福_黄金圣物.xlsx",
            ]
            # 正式23/24号表会持续增加成长装备；夹具数据库必须按当前母表补齐名称，
            # 不能把曾经只有LV10的待配置状态写死成永久测试前提。
            names = {
                str(row.get(column, "")).strip()
                for document in documents
                for row in read_workbook(document).rows
                for column in ("当前装备", "下一装备")
                if str(row.get(column, "")).strip()
            }
            database = target / "Mud2" / "DB" / "ApexM2.DB"
            connection = sqlite3.connect(database)
            try:
                next_index = int(connection.execute("SELECT COALESCE(MAX(Idx), 0) FROM StdItems").fetchone()[0]) + 1
                existing = {row[0] for row in connection.execute("SELECT Name FROM StdItems")}
                for name in sorted(names - existing):
                    connection.execute("INSERT INTO StdItems VALUES (?, ?)", (next_index, name))
                    next_index += 1
                connection.commit()
            finally:
                connection.close()
            service = GrowthStageService(self.platform)
            plan = service.preflight(target, documents)
            self.assertFalse(plan.blockers)
            receipt = service.install(plan)
            self.assertTrue((target / "Mir200" / "Envir" / "Market_Def" / "玄渊成长" / "圣律之剑进阶-XY_NMGF_MAIN.txt").is_file())
            second = service.preflight(target, documents)
            self.assertFalse(second.blockers)
            self.assertFalse(second.changes)
            service.installer.rollback(target, receipt.transaction_id)
            self.assertEqual(merchant.read_bytes(), before)
            self.assertFalse((target / "Mir200" / "Envir" / "Market_Def" / "玄渊成长" / "圣律之剑进阶-XY_NMGF_MAIN.txt").exists())


if __name__ == "__main__":
    unittest.main()
