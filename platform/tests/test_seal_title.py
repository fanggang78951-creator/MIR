from __future__ import annotations

import re
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from xydp.config_sync import ConfigSyncService
from xydp.seal_title import (
    MERCHANT_RELATIVE,
    SEAL_CORE_RELATIVE,
    SEAL_STATE_RELATIVE,
    TITLE_CORE_RELATIVE,
    SealTitleService,
    SealTitleError,
    _cost_lines,
    _seal_core,
    _title_configured,
    _title_core,
)


TITLE_NAMES = [
    "漂泊余烬",
    "失乡之魂",
    "赐福初燃",
    "卢恩觉醒",
    "黄金誓血",
    "风暴踏灭",
    "王城染血",
    "接肢终焉",
    "大卢恩之主",
    "黄金树下·初王",
]


class SealTitleCurrencyTests(unittest.TestCase):
    def test_currency_field_is_native_and_unknown_value_is_blocked(self):
        checks, actions = _cost_lines({"货币A": "元宝", "货币A数量": 100})
        self.assertEqual(checks, ["CHECKGAMEGOLD > 99"])
        self.assertEqual(actions, ["GAMEGOLD - 100"])
        with self.assertRaisesRegex(SealTitleError, "货币A只允许填写原生货币"):
            _cost_lines({"货币A": "失色锻造石", "货币A数量": 1})


def seal_rows() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for level in range(1, 201):
        total = level * (level + 1) // 2
        rows.append({
            "档位/等级": level,
            "状态": "可安装",
            "攻击": total,
            "魔法": total,
            "道术": total,
            "HP": total * 100,
            "材料A": "野兽骨片",
            "材料A数量": level + 9,
        })
    return tuple(rows)


def title_rows(payment_mode: str = "") -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for level, name in enumerate(TITLE_NAMES, 1):
        row = {
            "档位/等级": level,
            "状态": "可安装",
            "称号名称": name,
            "称号编号": 99 + level,
            "攻击": level * 10,
            "魔法": level * 10,
            "道术": level * 10,
            "HP": level * 1000,
            "MP": level * 1000,
            "基础爆率": level * 20,
            "材料A": "神秘符文",
            "材料A数量": level * 10,
            "货币A": "金币",
            "货币A数量": level * 20000,
            "货币B": "元宝",
            "货币B数量": level * 10,
        }
        if payment_mode:
            row["支付方式"] = payment_mode
        rows.append(row)
    return tuple(rows)


class SealTitleTests(unittest.TestCase):
    platform = Path(r"E:\XuanYuanDevPlatform")
    materials = platform / "所需材料表格汇总"

    def make_target(self, root: Path) -> Path:
        envir = root / "Mir200" / "Envir"
        (envir / "Market_Def" / "玄渊NPC").mkdir(parents=True)
        (envir / "MapQuest_Def").mkdir(parents=True)
        (root / "Mir200" / "Map").mkdir(parents=True)
        (root / "Mir200" / "M2Server.exe").write_bytes(b"M2")
        (root / "Mir200" / "!setup.txt").write_bytes(
            "[Setup]\r\nSendItemDescList=1\r\nSendTzItemDescList=1\r\n".encode("gb18030")
        )
        (envir / "MapInfo.txt").write_bytes(
            "[XY_NMGF_MAIN|test 宁姆格福]\r\n".encode("gb18030")
        )
        (envir / "MerChant.txt").write_bytes(
            "旧NPC/测试\tXY_NMGF_MAIN\t90\t70\t旧NPC\t0\t1\t0\r\n"
            "玄渊NPC/神树赐福\tXY_NMGF_MAIN\t76\t88\t神树赐福\t0\t244\t0\r\n".encode("gb18030")
        )
        (envir / "Market_Def" / "玄渊NPC" / "神树赐福-XY_NMGF_MAIN.txt").write_bytes(
            ("[@Main]\r\n#SAY\r\n愿神树的赐福与你同在。\\ " + "\\" + "\r\n<关闭/@exit>\r\n").encode("gb18030")
        )
        (envir / "MapQuest_Def" / "QManage.txt").write_bytes(
            "[@Login]\r\n#IF\r\n#ACT\r\n".encode("gb18030")
        )
        (envir / "Market_Def" / "QFunction-0.txt").write_bytes((
            "; XY_EQUIP_MAKER_DROP_ANCHOR\r\n"
            "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\r\n"
        ).encode("gb18030"))
        (envir / "ItemDescList.txt").write_bytes("旧物品=旧说明\r\n".encode("gb18030"))
        width, height, cell_size = 128, 128, 14
        map_data = bytearray(52 + width * height * cell_size)
        struct.pack_into("<HH", map_data, 0, width, height)
        (root / "Mir200" / "Map" / "test.map").write_bytes(map_data)
        database = root / "Mud2" / "DB" / "ApexM2.DB"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Shape INTEGER, Weight INTEGER, "
                "Anicount INTEGER, Source INTEGER, Reserved INTEGER, Looks INTEGER, DuraMax INTEGER, Ac INTEGER, Ac2 INTEGER, "
                "Mac INTEGER, Mac2 INTEGER, Dc INTEGER, Dc2 INTEGER, Mc INTEGER, Mc2 INTEGER, Sc INTEGER, Sc2 INTEGER, "
                "Need INTEGER, NeedLevel INTEGER, Price INTEGER, Stock INTEGER, Color INTEGER, OverLap INTEGER, HP INTEGER, "
                "MP INTEGER, Light INTEGER, Horse INTEGER)"
            )
            connection.execute(
                "INSERT INTO StdItems (Idx, Name, StdMode, Shape) VALUES (1, '旧称号', 70, 1)"
            )
            connection.commit()
        finally:
            connection.close()
        return root

    def make_client(self, root: Path) -> Path:
        (root / "data").mkdir(parents=True)
        (root / "data" / "fenghao.dat").write_bytes("旧称号=旧说明\r\n".encode("gb18030"))
        return root

    def test_seal_keeps_all_200_levels_and_uses_only_base_abilities(self):
        script = _seal_core(seal_rows(), "神印修行")
        self.assertIn("[@XY_SEAL_BASE_VIEW_200]", script)
        self.assertIn("[@XY_SEAL_BASE_ROUTE_0_19]", script)
        self.assertIn("CHECKVAR HUMAN XY_SEAL_BASE_LEVEL < 20", script)
        main = script[script.index("[@XY_SEAL_BASE_MAIN]"):script.index("[@XY_SEAL_BASE_ROUTE_0_19]")]
        self.assertNotIn("CHECKVAR HUMAN XY_SEAL_BASE_LEVEL = 199", main)
        self.assertIn("CHECKVAR HUMAN XY_SEAL_BASE_LEVEL = 0", script)
        self.assertIn("CALCVAR HUMAN XY_SEAL_BASE_LEVEL = 1", script)
        self.assertIn(
            r"SAVEVAR HUMAN XY_SEAL_BASE_LEVEL ..\QuestDiary\XY_System\XuanYuanHumanVar.txt",
            script,
        )
        self.assertNotIn("N$XY_SEAL_BASE_LEVEL", script)
        self.assertIn("ChangeHumAbilityEX 5 + 200", script)
        self.assertIn("ChangeHumAbilityEX 6 + 200", script)
        self.assertIn("ChangeHumAbilityEX 11 + 20000", script)
        self.assertNotIn("POWERRATE", script)
        self.assertNotIn("伤害系数", script)
        self.assertIn("锻体所需的物品或货币不足，请备齐后再来。", script)
        self.assertIn("修行记录异常，请联系游戏管理员。", script)
        self.assertNotIn("当前阶段或资源已经变化", script)
        self.assertNotIn("保护性停止", script)

    def test_title_names_and_safe_grant_deduct_recycle_order(self):
        rows = title_rows()
        _values, names, shapes = _title_configured(rows)
        self.assertEqual(names, TITLE_NAMES)
        self.assertEqual(shapes, list(range(100, 110)))
        script = _title_core(rows, "称号晋升")
        self.assertIn("[@XY_TITLE_ADVANCE_VIEW_10]", script)
        self.assertIn("黄金树下·初王", script)
        view = script[script.index("[@XY_TITLE_ADVANCE_VIEW_1]"):script.index("[@XY_TITLE_ADVANCE_APPLY_1]")]
        self.assertIn("当前称号:", view)
        self.assertIn("{无/SCOLOR=249}", view)
        self.assertIn("下一级称号:", view)
        self.assertIn("需要材料:", view)
        self.assertIn("神秘符文×10", view)
        self.assertIn("需要货币:", view)
        self.assertIn("金币×20000、元宝×10", view)
        self.assertLess(view.index("需要材料:"), view.index("攻魔道:"))
        grant = script.index("GIVEFENGHAO 失乡之魂 1")
        confirm = script.index("[@XY_TITLE_ADVANCE_CONFIRM_2]")
        deduct = script.index("TAKE 神秘符文 20", confirm)
        recycle = script.index("RECYCFENGHAO 漂泊余烬", deduct)
        self.assertLess(grant, confirm)
        self.assertLess(confirm, deduct)
        self.assertLess(deduct, recycle)
        self.assertIn("晋升所需的物品或货币不足，请备齐后再来。", script)
        self.assertIn("称号晋升未能完成，请稍后再试；本次未消耗物品和货币。", script)
        self.assertNotIn("当前称号阶段或资源不满足", script)
        self.assertNotIn("本次没有执行", script)

    def test_title_currency_a_or_b_generates_two_isolated_safe_routes(self):
        script = _title_core(title_rows("二选一"), "称号晋升")
        view_start = script.index("[@XY_TITLE_ADVANCE_VIEW_1]")
        apply_a_start = script.index("[@XY_TITLE_ADVANCE_APPLY_1_A]", view_start)
        apply_b_start = script.index("[@XY_TITLE_ADVANCE_APPLY_1_B]", apply_a_start)
        view = script[view_start:apply_a_start]
        route_a = script[apply_a_start:apply_b_start]
        route_b = script[apply_b_start:script.index("[@XY_TITLE_ADVANCE_VIEW_2]", apply_b_start)]

        self.assertIn("支付方式:", view)
        self.assertIn("二选一，任选一种", view)
        self.assertIn("货币A:", view)
        self.assertIn("金币×20000", view)
        self.assertIn("货币B:", view)
        self.assertIn("元宝×10", view)
        self.assertIn("使用金币晋升/@XY_TITLE_ADVANCE_APPLY_1_A", view)
        self.assertIn("使用元宝晋升/@XY_TITLE_ADVANCE_APPLY_1_B", view)

        self.assertIn("CHECKITEM 神秘符文 10", route_a)
        self.assertIn("CHECKGOLD 20000", route_a)
        self.assertIn("GOLDCOUNT - 20000", route_a)
        self.assertNotIn("CHECKGAMEGOLD", route_a)
        self.assertNotIn("GAMEGOLD -", route_a)

        self.assertIn("CHECKITEM 神秘符文 10", route_b)
        self.assertIn("CHECKGAMEGOLD > 9", route_b)
        self.assertIn("GAMEGOLD - 10", route_b)
        self.assertNotIn("CHECKGOLD", route_b)
        self.assertNotIn("GOLDCOUNT -", route_b)
        self.assertIn("RECYCFENGHAO 漂泊余烬", route_a)
        self.assertIn("RECYCFENGHAO 漂泊余烬", route_b)

    def test_title_currency_b_can_use_native_lingfu_without_materials(self):
        rows = tuple(
            {
                **row,
                "支付方式": "二选一B免材料",
                "货币B": "灵符",
            }
            for row in title_rows()
        )
        script = _title_core(rows, "称号晋升")
        view_start = script.index("[@XY_TITLE_ADVANCE_VIEW_1]")
        apply_a_start = script.index("[@XY_TITLE_ADVANCE_APPLY_1_A]", view_start)
        apply_b_start = script.index("[@XY_TITLE_ADVANCE_APPLY_1_B]", apply_a_start)
        view = script[view_start:apply_a_start]
        route_a = script[apply_a_start:apply_b_start]
        route_b = script[apply_b_start:script.index("[@XY_TITLE_ADVANCE_VIEW_2]", apply_b_start)]

        self.assertIn("货币A路线材料:", view)
        self.assertIn("货币A需材料；货币B免材料", view)
        self.assertIn("金币×20000", view)
        self.assertIn("灵符×10", view)
        self.assertIn("使用金币晋升/@XY_TITLE_ADVANCE_APPLY_1_A", view)
        self.assertIn("使用灵符晋升/@XY_TITLE_ADVANCE_APPLY_1_B", view)

        self.assertIn("CHECKITEM 神秘符文 10", route_a)
        self.assertIn("TAKE 神秘符文 10", route_a)
        self.assertIn("CHECKGOLD 20000", route_a)
        self.assertIn("GOLDCOUNT - 20000", route_a)
        self.assertNotIn("CHECKGAMEGIRD", route_a)
        self.assertNotIn("GAMEGIRD -", route_a)

        self.assertIn("CHECKGAMEGIRD > 9", route_b)
        self.assertIn("GAMEGIRD - 10", route_b)
        self.assertNotIn("CHECKITEM 神秘符文", route_b)
        self.assertNotIn("TAKE 神秘符文", route_b)
        self.assertNotIn("CHECKGOLD", route_b)
        self.assertNotIn("GOLDCOUNT -", route_b)

    def test_title_payment_mode_keeps_blank_as_legacy_and_blocks_invalid_or_routes(self):
        legacy = _title_core(title_rows(), "称号晋升")
        legacy_view = legacy[
            legacy.index("[@XY_TITLE_ADVANCE_VIEW_1]"):
            legacy.index("[@XY_TITLE_ADVANCE_APPLY_1]")
        ]
        self.assertIn("需要货币:", legacy_view)
        self.assertIn("金币×20000、元宝×10", legacy_view)
        self.assertNotIn("二选一", legacy_view)

        bad_mode = list(title_rows())
        bad_mode[0] = {**bad_mode[0], "支付方式": "随便扣"}
        with self.assertRaisesRegex(SealTitleError, "支付方式只允许填写"):
            _title_core(tuple(bad_mode), "称号晋升")

        missing_b = list(title_rows("二选一"))
        missing_b[0] = {**missing_b[0], "货币B": "", "货币B数量": 0}
        with self.assertRaisesRegex(SealTitleError, "货币A和货币B必须都填写"):
            _title_core(tuple(missing_b), "称号晋升")

    def test_current_workbooks_preflight_is_zero_write_and_title_is_configured(self):
        with tempfile.TemporaryDirectory(prefix="xydp-seal-title-") as td:
            server = self.make_target(Path(td) / "server")
            client = self.make_client(Path(td) / "client")
            tracked = [
                server / "Mir200/Envir/MerChant.txt",
                server / "Mir200/Envir/MapQuest_Def/QManage.txt",
                server / "Mir200/Envir/Market_Def/QFunction-0.txt",
                server / "Mir200/Envir/ItemDescList.txt",
                server / "Mud2/DB/ApexM2.DB",
                client / "data/fenghao.dat",
            ]
            before = {path: path.read_bytes() for path in tracked}
            plan = SealTitleService(self.platform).preflight(server, self.materials, client)
            self.assertEqual(plan.blockers, [])
            self.assertEqual({npc.state for npc in plan.npcs}, {"可安装"})
            title_npc = next(npc for npc in plan.npcs if npc.feature_id == "title")
            self.assertTrue(title_npc.reuse_existing)
            self.assertEqual(title_npc.script_path, "玄渊NPC/神树赐福")
            self.assertTrue(any(item.relative_path == SEAL_CORE_RELATIVE for item in plan.changes))
            self.assertTrue(any(item.relative_path == TITLE_CORE_RELATIVE for item in plan.changes))
            self.assertTrue(any("ApexM2.DB" in item.relative_path for item in plan.changes))
            self.assertTrue(any(item.scope == "client" for item in plan.changes))
            self.assertEqual(before, {path: path.read_bytes() for path in tracked})

    def test_generic_config_sync_redirects_both_workbooks_to_specialist_page(self):
        service = ConfigSyncService(self.platform)
        for filename in ("21_神印基础属性.xlsx", "22_称号晋升.xlsx"):
            plan = service.preflight(Path(r"D:\not-used"), [self.materials / filename])
            self.assertEqual(plan.route, "specialist")
            self.assertEqual(len(plan.blockers), 1)
            self.assertIn("神印与称号双NPC", plan.blockers[0])

    def test_login_hook_executes_and_reads_the_quest_diary_human_state_file(self):
        with tempfile.TemporaryDirectory(prefix="xydp-seal-title-login-") as td:
            server = self.make_target(Path(td) / "server")
            client = self.make_client(Path(td) / "client")
            service = SealTitleService(self.platform)
            service.install(service.preflight(server, self.materials, client))
            qmanage = server / "Mir200/Envir/MapQuest_Def/QManage.txt"
            text = qmanage.read_text(encoding="gb18030")
            match = re.search(
                r"(?m)^; XYDP-HOOK-BEGIN xy\.lab\.seal-title-v2 Login SHA256=[0-9a-f]{64}\n"
                r"(.*?)"
                r"^; XYDP-HOOK-END xy\.lab\.seal-title-v2 Login\s*$",
                text,
                re.DOTALL,
            )
            self.assertIsNotNone(match)
            self.assertEqual(
                match.group(1).splitlines(),
                [
                    "#IF",
                    "#ACT",
                    "VAR Integer HUMAN XY_SEAL_BASE_LEVEL",
                    r"LOADVAR HUMAN XY_SEAL_BASE_LEVEL ..\QuestDiary\XY_System\XuanYuanHumanVar.txt",
                ],
            )
            state_file = server / Path(SEAL_STATE_RELATIVE)
            self.assertTrue(state_file.is_file())
            self.assertEqual(state_file.read_bytes(), b"\xef\xbb\xbf")

    def test_legacy_market_def_state_is_copied_once_and_never_overwrites_human_state(self):
        with tempfile.TemporaryDirectory(prefix="xydp-seal-title-state-") as td:
            server = self.make_target(Path(td) / "server")
            client = self.make_client(Path(td) / "client")
            legacy = server / "Mir200/Envir/Market_Def/XY_Seal_Base_Level.txt"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy_bytes = "\ufeff[测试员]\r\nXY_SEAL_BASE_LEVEL=20\r\n".encode("utf-8")
            legacy.write_bytes(legacy_bytes)
            service = SealTitleService(self.platform)
            plan = service.preflight(server, self.materials, client)
            state_change = next(item for item in plan.changes if item.relative_path == SEAL_STATE_RELATIVE)
            self.assertIsNone(state_change.before)
            self.assertEqual(state_change.after, legacy_bytes)
            service.install(plan)
            human_state = server / Path(SEAL_STATE_RELATIVE)
            self.assertEqual(human_state.read_bytes(), legacy_bytes)
            human_state.write_bytes("\ufeff[测试员]\r\nXY_SEAL_BASE_LEVEL=21\r\n".encode("utf-8"))
            repeat = service.preflight(server, self.materials, client)
            self.assertFalse(any(item.relative_path == SEAL_STATE_RELATIVE for item in repeat.changes))

    def test_verified_install_is_self_contained_idempotent_and_rollback_restores_bytes(self):
        with tempfile.TemporaryDirectory(prefix="xydp-seal-title-") as td:
            server = self.make_target(Path(td) / "server")
            client = self.make_client(Path(td) / "client")
            merchant = server / "Mir200/Envir/MerChant.txt"
            seal_npc = server / "Mir200/Envir/Market_Def/玄渊成长/神印修行-XY_NMGF_MAIN.txt"
            title_npc = server / "Mir200/Envir/Market_Def/玄渊NPC/神树赐福-XY_NMGF_MAIN.txt"
            qmanage = server / "Mir200/Envir/MapQuest_Def/QManage.txt"
            qfunction = server / "Mir200/Envir/Market_Def/QFunction-0.txt"
            itemdesc = server / "Mir200/Envir/ItemDescList.txt"
            database = server / "Mud2/DB/ApexM2.DB"
            fenghao = client / "data/fenghao.dat"
            human_state = server / Path(SEAL_STATE_RELATIVE)
            tracked = [merchant, title_npc, qmanage, qfunction, itemdesc, database, fenghao]
            before = {path: path.read_bytes() for path in tracked}
            service = SealTitleService(self.platform)
            plan = service.preflight(server, self.materials, client)
            receipt = service.install(plan)
            seal_text = seal_npc.read_text(encoding="gb18030")
            title_text = title_npc.read_text(encoding="gb18030")
            self.assertIn("XYDP-FILE-BEGIN xy.lab.seal-title-v2 seal-self-contained", seal_text)
            self.assertEqual(seal_text.count("[@Main]"), 1)
            self.assertNotIn("[@XY_SEAL_BASE_MAIN]", seal_text)
            self.assertNotRegex(seal_text, r"(?im)^\s*[{}]\s*$")
            self.assertNotRegex(seal_text, r"(?im)^\s*#CALL\b")
            self.assertIn("[@XY_SEAL_BASE_VIEW_200]", seal_text)
            self.assertIn("所需资源:", seal_text)
            self.assertNotIn("愿神树的赐福与你同在", title_text)
            self.assertNotIn("<称号晋升/@XY_TITLE_ADVANCE_ENTRY>", title_text)
            self.assertNotIn("[@XY_TITLE_ADVANCE_ENTRY]", title_text)
            self.assertIn("XYDP-FILE-BEGIN xy.lab.seal-title-v2 title-self-contained", title_text)
            self.assertEqual(title_text.count("[@Main]"), 1)
            self.assertNotIn("[@XY_TITLE_ADVANCE_MAIN]", title_text)
            self.assertNotRegex(title_text, r"(?im)^\s*[{}]\s*$")
            self.assertNotRegex(title_text, r"(?im)^\s*#CALL\b")
            self.assertIn("当前称号:", title_text)
            self.assertIn("货币A路线材料:", title_text)
            self.assertIn("货币A需材料；货币B免材料", title_text)
            self.assertIn("支付方式:", title_text)
            self.assertIn("使用金币晋升/@XY_TITLE_ADVANCE_APPLY_1_A", title_text)
            self.assertIn("使用灵符晋升/@XY_TITLE_ADVANCE_APPLY_1_B", title_text)
            self.assertEqual(plan.install_plan.candidate_packages, ["xy.lab.seal-title-v2"])
            self.assertEqual(plan.install_plan.parameters["verification_status"], "candidate")
            merchant_text = merchant.read_text(encoding="gb18030")
            self.assertEqual(merchant_text.count("\t神树赐福\t"), 1)
            self.assertEqual(merchant_text.count("\t锻体\t"), 1)
            second = service.preflight(server, self.materials, client)
            self.assertEqual(second.blockers, [])
            self.assertEqual(second.changes, [])
            self.assertEqual(human_state.read_bytes(), b"\xef\xbb\xbf")
            service.rollback_latest(server)
            self.assertEqual(before, {path: path.read_bytes() for path in tracked})
            self.assertFalse((server / Path(SEAL_CORE_RELATIVE)).exists())
            self.assertFalse((server / Path(TITLE_CORE_RELATIVE)).exists())
            self.assertFalse(seal_npc.exists())
            self.assertFalse(human_state.exists())
            self.assertTrue(receipt.transaction_id)

    def test_candidate7_files_upgrade_to_verified_managed_files(self):
        with tempfile.TemporaryDirectory(prefix="xydp-seal-title-c7-") as td:
            server = self.make_target(Path(td) / "server")
            client = self.make_client(Path(td) / "client")
            service = SealTitleService(self.platform)
            service.install(service.preflight(server, self.materials, client))
            paths = (
                (
                    server / "Mir200/Envir/Market_Def/玄渊成长/神印修行-XY_NMGF_MAIN.txt",
                    "seal-self-contained",
                ),
                (
                    server / "Mir200/Envir/Market_Def/玄渊NPC/神树赐福-XY_NMGF_MAIN.txt",
                    "title-self-contained",
                ),
            )
            for path, kind in paths:
                text = path.read_text(encoding="gb18030")
                match = re.search(
                    rf"^; XYDP-FILE-BEGIN xy\.lab\.seal-title-v2 {kind} SHA256=[0-9a-f]{{64}}\n"
                    rf"(.*?)^; XYDP-FILE-END xy\.lab\.seal-title-v2 {kind}\s*$",
                    text,
                    re.MULTILINE | re.DOTALL,
                )
                self.assertIsNotNone(match)
                candidate7 = (
                    f"; XYDP-CANDIDATE7-BEGIN xy.lab.seal-title-v2 {kind}\n"
                    + match.group(1)
                    + f"; XYDP-CANDIDATE7-END xy.lab.seal-title-v2 {kind}\n"
                )
                path.write_text(candidate7, encoding="gb18030", newline="")
            upgrade = service.preflight(server, self.materials, client)
            self.assertEqual(upgrade.blockers, [])
            self.assertEqual(
                sum(change.operation in {"generate-seal-self-contained", "attach-title-to-existing-npc"} for change in upgrade.changes),
                2,
            )
            service.install(upgrade)
            repeat = service.preflight(server, self.materials, client)
            self.assertEqual(repeat.blockers, [])
            self.assertEqual(repeat.changes, [])

    def test_upgrade_preserves_existing_managed_seal_npc_appearance(self):
        with tempfile.TemporaryDirectory(prefix="xydp-seal-title-") as td:
            server = self.make_target(Path(td) / "server")
            client = self.make_client(Path(td) / "client")
            service = SealTitleService(self.platform)
            service.install(service.preflight(server, self.materials, client))
            merchant = server / "Mir200/Envir/MerChant.txt"
            text = merchant.read_text(encoding="gb18030")
            text = text.replace(
                "玄渊成长/神印修行\tXY_NMGF_MAIN\t98\t73\t锻体\t0\t222\t0",
                "玄渊成长/神印修行\tXY_NMGF_MAIN\t98\t73\t锻体\t0\t59\t0",
            )
            merchant.write_text(text, encoding="gb18030", newline="")
            plan = service.preflight(server, self.materials, client)
            seal = next(npc for npc in plan.npcs if npc.feature_id == "seal")
            self.assertTrue(seal.reuse_existing)
            self.assertEqual(seal.appearance, 59)
            self.assertFalse(any(change.relative_path == MERCHANT_RELATIVE for change in plan.changes))
            self.assertTrue(any("当前外观59" in warning for warning in plan.warnings))


if __name__ == "__main__":
    unittest.main()
