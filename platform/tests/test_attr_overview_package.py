import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.validator import validate_package


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "packages" / "candidate" / "xy.ui.attr-overview"


def make_target(base: Path) -> Path:
    target = base / "server"
    envir = target / "Mir200/Envir"
    (envir / "MapQuest_Def").mkdir(parents=True)
    (envir / "Market_Def").mkdir(parents=True)
    (target / "Mir200/M2Server.exe").write_bytes(b"M2")
    (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
    (envir / "MerChant.txt").write_bytes(b"")
    (target / "Mir200/!setup.txt").write_bytes(b"[Setup]\r\nRevivalTime=60000\r\n")
    database = target / "Mud2/DB/ApexM2.DB"
    database.parent.mkdir(parents=True)
    rage_manifest = json.loads(
        (ROOT / "packages/candidate/xy.optional.rage.core/manifest.json").read_text(encoding="utf-8")
    )
    rage_values = next(item for item in rage_manifest["operations"] if item["type"] == "sqlite_upsert")["values"]
    columns = ["Idx INTEGER", *(
        f'"{name}" {"TEXT" if name == "Name" else "INTEGER"}' for name in rage_values
    )]
    connection = sqlite3.connect(database)
    try:
        connection.execute(f'CREATE TABLE StdItems ({", ".join(columns)})')
        connection.commit()
    finally:
        connection.close()
    (envir / "MapQuest_Def/QManage.txt").write_bytes(
        "[@MAIN1]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
    )
    (envir / "Market_Def/QFunction-0.txt").write_bytes(
        (
            "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n\r\n"
            "[@TakeOnEx]\r\n#IF\r\n#ACT\r\nBREAK\r\n\r\n"
            "[@TakeOffEx]\r\n#IF\r\n#ACT\r\nBREAK\r\n\r\n"
            "[@AttackDamage]\r\n#IF\r\n#ACT\r\nBREAK\r\n\r\n"
            "[@KillMon]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
            "\r\n[@CustomButtonClick]\r\n#IF\r\nEQUAL <$CustomButtonID> 99\r\n#ACT\r\nBREAK\r\n"
            "\r\n[@ButtonClick88]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        ).encode("gb18030")
    )
    return target


class AttrOverviewPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((PACKAGE_ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_is_optional_candidate_five_icon_package(self):
        package = validate_package(PACKAGE_ROOT)
        self.assertEqual(package.id, "xy.ui.attr-overview")
        self.assertEqual(package.version, "2.0.9-candidate.1")
        self.assertEqual(package.status, "candidate")
        self.assertEqual(package.residency, "optional")
        self.assertEqual(self.manifest["dependencies"], ["xy.optional.rage.core"])
        for name in ("panel_a", "panel_b", "panel_c"):
            self.assertEqual(self.manifest["parameters"][name]["type"], "attribute_panel")

    def test_button_ids_are_isolated_from_world_map_88(self):
        p = self.manifest["parameters"]
        ids = [p[name]["default"] for name in (
            "rage_button_id", "revive_button_id", "panel_a_button_id",
            "panel_b_button_id", "panel_c_button_id",
        )]
        self.assertEqual(ids, [89, 90, 91, 92, 93])
        self.assertNotIn(88, ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(p["rage_reserved_button_id"]["default"], 3)
        self.assertEqual(p["world_map_reserved_button_id"]["default"], 5)

    def test_revive_contract_is_shared_two_chance_window(self):
        script = (PACKAGE_ROOT / "payload/玄渊三属性按钮.txt").read_text(encoding="utf-8")
        self.assertEqual(script.count("SetReborn 1 <$STR(N$XY_UI_REVIVE_WINDOW)>"), 1)
        self.assertNotIn("SetReborn 2", script)
        self.assertIn("MOV N$XY_UI_REVIVE_WINDOW <$REVIVALTIME>", script)
        self.assertIn("LARGE <$NpcRebornCount> 0", script)
        self.assertIn("SetClientBuff {icon_wil_index} {revive_buff_id}", script)
        self.assertIn("剩余复活机会:2", script)
        self.assertIn("剩余复活机会:1", script)
        self.assertIn("N$XY_UI_REVIVE_EQUIP_COUNT", script)
        self.assertIn("CHECKITEMW <$STR(S$XY_UI_REVIVE_ITEM1)> 1", script)
        self.assertIn("CHECKITEMW <$STR(S$XY_UI_REVIVE_ITEM1)> 2", script)

    def test_rage_icon_opens_the_map0_npc_single_source(self):
        script = (PACKAGE_ROOT / "payload/玄渊三属性按钮.txt").read_text(encoding="utf-8")
        self.assertIn("CHECKFENGHAO 狂暴之力", script)
        self.assertNotIn("N$XY_RAGE_ACTIVE", script)
        self.assertNotIn("GAMEDIAMOND -", script)
        self.assertNotIn("POWERRATE", script)
        managed = next(item for item in self.manifest["operations"] if item["type"] == "managed_block")
        self.assertIn("狂暴NPC接口.txt] @XY_RAGE_NPC_MAIN", managed["content"])
        self.assertNotIn("CHECKGAMEDIAMOND", managed["content"])

    def test_panels_use_distinct_namespaces_and_required_sources(self):
        panels = [self.manifest["parameters"][name]["default"] for name in ("panel_a", "panel_b", "panel_c")]
        self.assertEqual([panel["namespace"] for panel in panels], ["A", "B", "C"])
        serialized = json.dumps(panels, ensure_ascii=False)
        for token in (
            "N$倍攻", "N$XY_RT_DamageCoeff", "N$XY_最终爆伤", "N$XY_PVE",
            "N$XY_FirstKillRate", "N$XY_TailKillRate", "N$XY_CorpseRate", "N$XY_MDA_Final",
            "N$XY_EXEC_Toughness", "N$XY_EXEC_ChanceBP", "N$XY_EXEC_PVEEquipDurationMs",
            "N$XY_EXEC_PVEEquipBonusPercent",
        ):
            self.assertIn(token, serialized)
        parameters = self.manifest["parameters"]
        self.assertEqual(parameters["panel_a_x"]["default"], 246)
        self.assertEqual(parameters["panel_a_y"]["default"], 17)
        self.assertEqual(panels[0]["items"][0]["read_mode"], "source")
        self.assertEqual(panels[0]["items"][0]["offset"], 100)
        self.assertEqual(panels[0]["items"][3]["read_mode"], "source")
        self.assertEqual(panels[0]["items"][3]["offset"], 100)
        self.assertEqual(panels[1]["items"][0]["read_mode"], "zero")
        self.assertEqual(panels[1]["items"][2]["bind_type"], 13)
        self.assertEqual(panels[1]["items"][3]["label"], "对怪吸收")
        self.assertEqual(
            [item["name"] for item in panels[0]["items"][1]["title_additions"]],
            ["赞助1档", "赞助2档", "赞助3档", "赞助4档"],
        )
        self.assertEqual(
            [item["amount"] for item in panels[2]["items"][0]["title_additions"]],
            [20, 30, 40, 50],
        )

    def test_login_refresh_waits_for_equipment_then_dispatches_the_existing_playlogin_chain(self):
        script = (PACKAGE_ROOT / "payload/玄渊三属性登录重算.txt").read_text(encoding="utf-8")
        self.assertIn("[@XYDP_ATTR_RECALC_LOGIN]", script)
        self.assertIn("DELAYGOTO 3000 @XYDP_ATTR_RECALC_LOGIN_DELAY", script)
        self.assertIn("[@XYDP_ATTR_RECALC_LOGIN_DELAY]", script)
        self.assertIn("GOTOLABEL 8 @PlayLogin <$X> <$Y> 0 0", script)
        self.assertNotIn("LockUpdateAbil", script)
        self.assertNotIn("UpdateAbil", script)
        self.assertNotIn("人物属性已刷新", script)
        self.assertNotIn("ChangeSpeed", script)
        self.assertNotIn("POWERRATE", script)

        qmanage_hooks = [
            item for item in self.manifest["operations"]
            if item["type"] == "event_hook"
            and item["target"].endswith("QManage.txt")
            and item["label"] == "MAIN1"
        ]
        self.assertEqual(len(qmanage_hooks), 1)
        content = qmanage_hooks[0]["content"]
        self.assertIn("@XYDP_ATTR_RECALC_LOGIN", content)
        self.assertNotIn("@XYDP_ATTR_BUTTON_LOGIN", content)

    def test_isolated_install_is_idempotent_and_byte_rollback_safe(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = make_target(base)
            before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            repository = PackageRepository(ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")
            plan = installer.preflight(target, ["xy.ui.attr-overview"], {})
            self.assertEqual(plan.package_ids, [
                "xy.combat.core", "xy.combat.runtime-refresh", "xy.combat.drop",
                "xy.optional.rage.core", "xy.ui.attr-overview",
            ])
            receipt = installer.install(plan)

            qfunction = (target / "Mir200/Envir/Market_Def/QFunction-0.txt").read_bytes().decode("gb18030")
            qmanage = (target / "Mir200/Envir/MapQuest_Def/QManage.txt").read_bytes().decode("gb18030")
            login_refresh = (
                target / "Mir200/Envir/QuestDiary/玄渊功能/非常驻/属性总览/玄渊三属性登录重算.txt"
            ).read_bytes().decode("gb18030")
            script = (target / "Mir200/Envir/QuestDiary/玄渊功能/非常驻/属性总览/玄渊三属性按钮.txt").read_bytes().decode("gb18030")
            self.assertIn("@XYDP_ATTR_RECALC_LOGIN", qmanage)
            self.assertNotIn("@XYDP_ATTR_BUTTON_LOGIN", qmanage)
            self.assertIn("DELAYGOTO 3000 @XYDP_ATTR_RECALC_LOGIN_DELAY", login_refresh)
            self.assertIn("GOTOLABEL 8 @PlayLogin <$X> <$Y> 0 0", login_refresh)
            self.assertNotIn("LockUpdateAbil", login_refresh)
            self.assertNotIn("UpdateAbil", login_refresh)
            self.assertIn("[@XY_UI_QF_STATUS_REFRESH]", qfunction)
            self.assertNotIn("[@XY_UI_STATUS_REFRESH]", qfunction)
            self.assertIn("#CALL [\\玄渊功能\\非常驻\\属性总览\\玄渊三属性按钮.txt] @XY_UI_STATUS_EQUIP_CHANGED", qfunction)
            self.assertNotIn("DELAYGOTO 1 @XY_UI_QF_EQUIP_REFRESH", qfunction)
            self.assertIn("GOTO @XY_UI_RAGE_PANEL", qfunction)
            self.assertIn("狂暴NPC接口.txt] @XY_RAGE_NPC_MAIN", qfunction)
            self.assertNotIn("[@XY_UI_RAGE_PANEL_APPLY]", qfunction)
            self.assertNotIn("N$XY_RAGE_ACTIVE", qfunction)
            self.assertIn("EQUAL <$CustomButtonID> 3", qfunction)
            self.assertIn("EQUAL <$CustomButtonID> 5", qfunction)
            self.assertIn("GOTO @ButtonClick88", qfunction)
            self.assertIn("[@ButtonClick89]", qfunction)
            self.assertIn("[@Revival]", qfunction)
            self.assertIn("[@NpcRevival]", qfunction)
            self.assertIn("ADDBUTTON 17 91 1772 1773 1774 246 17", script)
            self.assertIn("ADDBUTTON 17 92 1791 1792 1793 350 18", script)
            self.assertIn("ADDBUTTON 17 93 1794 1795 1796 446 17", script)
            self.assertIn("MOV N$XY_UI_A_Value01 <$STR(N$倍攻)>", script)
            self.assertIn("DEC N$XY_UI_A_Value01 100", script)
            self.assertNotIn("GetAllCustomItemValue 40", script)
            self.assertIn("MOV N$XY_UI_A_Value04 <$STR(N$XY_PVE)>", script)
            self.assertIn("DEC N$XY_UI_A_Value04 100", script)
            self.assertNotIn("GetAllCustomItemValue 41", script)
            self.assertIn("CHECKITEMW 尾刀盾牌 1", script)
            self.assertIn("INC N$XY_UI_B_Value01 50", script)
            self.assertIn("CHECKITEMW 首刀马牌 1", script)
            self.assertIn("INC N$XY_UI_B_Value02 50", script)
            self.assertIn("GetAllCustomItemValue 13 N$XY_UI_B_Value03_BindPoint", script)
            self.assertIn("CHECKITEMW 测试腰带 1", script)
            self.assertIn("INC N$XY_UI_B_Value04 10", script)
            self.assertIn("对怪吸收:+<$STR(N$XY_UI_B_Value04)>%", script)
            self.assertNotIn("对怪伤害吸收:+<$STR(N$XY_UI_B_Value04)>%", script)
            self.assertEqual(script.count("DELAYGOTO 5 @XY_UI_STATUS_REFRESH"), 2)
            self.assertIn(
                "GetAllCustomItemValue 49 N$XY_UI_C_Value02_BindPoint N$XY_UI_C_Value02_BindRate",
                script,
            )
            self.assertIn("DELBUTTON 88", script)
            self.assertIn("SetReborn 1 <$STR(N$XY_UI_REVIVE_WINDOW)>", script)
            bridge = (
                target / "Mir200/Envir/QuestDiary/玄渊功能/狂暴/狂暴界面刷新接口.txt"
            ).read_text(encoding="gb18030")
            self.assertIn("[@XY_RAGE_UI_REFRESH]\n{\n", bridge)
            self.assertIn("XYDP-HOOK-BEGIN xy.ui.attr-overview XY_RAGE_UI_REFRESH", bridge)
            self.assertIn("@XY_UI_DRAW_RAGE", bridge)
            self.assertEqual(installer.preflight(target, ["xy.ui.attr-overview"], {}).changes, [])

            installer.rollback(target, receipt.transaction_id)
            after = {
                p.relative_to(target): p.read_bytes()
                for p in target.rglob("*") if p.is_file() and ".xydp" not in p.parts
            }
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
