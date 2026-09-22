from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from xydp.king_mode_complete import COMBAT_DEPENDENCIES, KingModeCompleteService
from xydp.king_mode_flow import _parse_config
from xydp.runtime import platform_root
from xydp.validator import validate_package


class KingModeCompleteTests(unittest.TestCase):
    root = platform_root()

    def setUp(self):
        self.service = KingModeCompleteService(self.root)
        self.values = self.service._values(
            _parse_config(self.service.default_config.read_text(encoding="utf-8"))
        )

    def test_verified_package_declares_runtime_power_and_blast_dependencies(self):
        package = validate_package(self.service.package_root)
        self.assertEqual(package.status, "verified")
        self.assertEqual(package.version, "2.1.1")
        manifest = json.loads((self.service.package_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(tuple(manifest["dependencies"]), COMBAT_DEPENDENCIES)
        self.assertIn("xy.combat.power", manifest["dependencies"])
        self.assertIn("xy.combat.blast", manifest["dependencies"])

    def test_config_renders_all_gameplay_values_and_five_waves(self):
        core = self.service._render_core(self.values).decode("gb18030")
        flow = self.service._render_flow(self.values).decode("gb18030")
        title_sync = self.service._render_title_visual_sync(self.values).decode("gb18030")
        breakthrough = self.service._render_npc("国王模式破釜沉舟.txt", self.values).decode("gb18030")
        demon = self.service._render_npc("国王模式恶魔契约.txt", self.values).decode("gb18030")
        self.assertIn("GAMEGOLD - 200", core)
        self.assertIn("MOV N$XY_KING_KILL_REWARD 500", core)
        self.assertIn("MOV N$XY_KING_EXP_RATE 50", core)
        self.assertIn("SetNewFengHaoValue 国王 10 = 10", core)
        self.assertIn("CheckActiveFengHao 国王", title_sync)
        self.assertNotRegex(title_sync, r"(?im)^\s*(CHECKFENGHAO|GIVEFENGHAO|SetActiveFengHao)\b")
        self.assertIn("连续死亡3次", breakthrough)
        self.assertIn("累计死亡6次", breakthrough)
        self.assertIn("增加100%", breakthrough)
        self.assertIn("GAMEGOLD - 100", demon)
        self.assertEqual(flow.count("MonGenEx "), 20)
        self.assertEqual(flow.count("ClearMapMon "), 10)
        for count in (10, 15, 20, 25, 30):
            self.assertIn(f" 35 {count}", flow)

    def test_qfunction_installs_power_blast_and_breakthrough_anchors(self):
        with tempfile.TemporaryDirectory(prefix="xydp-king-qf-") as temp:
            qfunction = Path(temp) / "QFunction-0.txt"
            qfunction.write_bytes(b"")
            rendered = self.service._apply_qfunction(
                qfunction, self.values["battle_map"], self.values["break_power"]
            ).decode("gb18030")
        self.assertIn("XYDP-BEGIN xy.combat.power", rendered)
        self.assertIn("XYDP-BEGIN xy.combat.blast", rendered)
        self.assertIn("XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR", rendered)
        self.assertIn("INC N$XY_RT_Power 100", rendered)
        self.assertIn("INC N$倍攻 100", rendered)
        self.assertIn("@XYDP_RecalcPower", rendered)
        self.assertIn("@XYDP_RecalcBlast", rendered)
        self.assertIn("[@ActiveTitle_2]", rendered)
        self.assertIn("[@UnactiveTitle_2]", rendered)
        self.assertEqual(rendered.count("@XY_TITLE_VISUAL_SYNC"), 2)

    def test_login_only_syncs_current_title_without_activating_one(self):
        with tempfile.TemporaryDirectory(prefix="xydp-king-login-") as temp:
            login = Path(temp) / "登陆脚本.txt"
            login.write_bytes(b"")
            rendered = self.service._apply_login(login).decode("gb18030")
        self.assertIn("@XY_TITLE_VISUAL_SYNC", rendered)
        self.assertNotRegex(rendered, r"(?im)^\s*(GIVEFENGHAO|SetActiveFengHao)\b")

    def test_gui_keeps_one_click_workflow_in_target_management_frame(self):
        source = (self.root / "src/xydp/gui.py").read_text(encoding="utf-8")
        self.assertIn('text="国王模式完整一键安装（初始端）"', source)
        self.assertIn('text="一键安装国王模式"', source)
        self.assertIn('text="预检完整安装"', source)
        self.assertIn('text="读取并应用配置TXT"', source)
        self.assertIn('self.notebook.select(self.tabs["目标管理"])', source)
        show_start = source.index("    def _show_king_mode_flow_plan")
        show_end = source.index("    def king_mode_flow_preflight", show_start)
        self.assertNotIn('self.tabs["国王模式流程"]', source[show_start:show_end])

    def test_one_click_transaction_is_idempotent_and_byte_rollback_safe(self):
        receipt = None
        with tempfile.TemporaryDirectory(prefix="xydp-king-complete-") as temp:
            base = Path(temp)
            server = base / "server"
            client = base / "client"
            self._make_server(server)
            self._make_client(client)
            originals = {
                path.relative_to(server).as_posix(): path.read_bytes()
                for path in server.rglob("*") if path.is_file()
            }
            try:
                plan = self.service.preflight(server, client)
                self.assertEqual(plan.blockers, [])
                self.assertGreater(len(plan.changes), 30)
                receipt = self.service.apply(plan, yes=True)
                sync_path = server / "Mir200/Envir/QuestDiary/玄渊功能/称号视觉/称号视觉同步.txt"
                self.assertTrue(sync_path.exists())
                self.assertIn("CheckActiveFengHao 国王", sync_path.read_text(encoding="gb18030"))
                second = self.service.preflight(server, client)
                self.assertEqual(second.blockers, [])
                self.assertEqual(second.changes, [])
                self.service.rollback(server, yes=True)
                for relative, data in originals.items():
                    self.assertEqual((server / relative).read_bytes(), data, relative)
                self.assertFalse((server / "Mir200/Map/T218.map").exists())
                self.assertFalse(sync_path.exists())
                self.assertFalse((client / "国王模式.exe").exists())
            finally:
                if receipt and receipt.backup_root:
                    shutil.rmtree(receipt.backup_root, ignore_errors=True)

    @staticmethod
    def _make_server(root: Path) -> None:
        files = {
            "Mir200/M2Server.exe": b"fixture",
            "Mir200/Envir/MapInfo.txt": b"",
            "Mir200/Envir/MiniMap.txt": b"",
            "Mir200/Envir/MerChant.txt": b"",
            "Mir200/Envir/MonGen.txt": b"T218 10 10 test 1 1 1\r\n",
            "Mir200/Envir/Market_Def/QFunction-0.txt": b"",
            "Mir200/Envir/MapQuest_Def/QManage.txt": (
                "[@MAIN1]\r\n#CALL [\\游戏登陆\\登陆脚本.txt] @登陆设置\r\n\r\n[@MAIN]\r\nBREAK\r\n"
            ).encode("gb18030"),
            "Mir200/Envir/QuestDiary/\u6e38\u620f\u767b\u9646/\u767b\u9646\u811a\u672c.txt": b"",
            "Mir200/Envir/Nations/Nations.ini": b"[Names]\r\n",
        }
        for relative, data in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        db = root / "Mud2/DB/ApexM2.DB"
        db.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db)
        columns = (
            "Idx INTEGER PRIMARY KEY, Name TEXT, StdMode INTEGER, Shape INTEGER, Weight INTEGER, "
            "Anicount INTEGER, Source INTEGER, Reserved INTEGER, Looks INTEGER, DuraMax INTEGER, "
            "Ac INTEGER, Ac2 INTEGER, Mac INTEGER, Mac2 INTEGER, Dc INTEGER, Dc2 INTEGER, "
            "Mc INTEGER, Mc2 INTEGER, Sc INTEGER, Sc2 INTEGER, Need INTEGER, NeedLevel INTEGER, "
            "Price INTEGER, Stock INTEGER, Color INTEGER, OverLap INTEGER, HP INTEGER, MP INTEGER, "
            "Light INTEGER, Horse INTEGER"
        )
        connection.execute(f"CREATE TABLE StdItems ({columns})")
        connection.commit()
        connection.close()

    @staticmethod
    def _make_client(root: Path) -> None:
        for relative in (
            "data/npc.wzl", "data/npc.wzx", "data/Tiles.wzl", "data/Tiles.wzx",
            "data/Objects.wzl", "data/Objects.wzx",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        (root / "Map").mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    unittest.main()
