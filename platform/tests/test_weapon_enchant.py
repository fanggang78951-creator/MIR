from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

from xydp.config_sync import ConfigSyncService
from xydp.weapon_enchant import (
    CORE_RELATIVE,
    PACKAGE_ID,
    ROUTE,
    RUNTIME_RELATIVE,
    WeaponEnchantService,
    WarAshCost,
    load_weapon_enchant_workbook,
    render_elden_war_ash_core,
)
from xydp.validator import validate_package


ROOT = Path(__file__).resolve().parents[1]
LEGACY_WASH_TEMPLATE = ROOT / "packages/verified/xy.optional.equipment-wash-opening/payload/server/npc/装备洗练.txt"
LEGACY_WASH_PACKAGE = ROOT / "packages/verified/xy.optional.equipment-wash-opening"


def make_workbook(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "系统设置"
    ws.append(("配置项", "配置值"))
    for row in (
        ("系统编号", "weapon_enchant"), ("目标装备部位", "武器"),
        ("附魔槽位数", 3), ("受管属性起始行", 9),
        ("NPC脚本相对路径", "Mir200/Envir/Market_Def/玄渊武器附魔/武器附魔-3.txt"),
        ("NPC地图", "3"), ("NPC坐标X", 325), ("NPC坐标Y", 339),
        ("NPC名称", "武器附魔"), ("NPC外观", 220), ("物品框编号", 29),
    ):
        ws.append(row)
    ws = wb.create_sheet("附魔槽位")
    ws.append(("槽位", "启用", "显示名称", "开放条件", "条件值"))
    ws.append((1, "是", "附魔1", "无条件", 0))
    ws.append((2, "是", "附魔2", "等级", 50))
    ws.append((3, "是", "附魔3", "等级", 60))
    ws = wb.create_sheet("洗练规则")
    ws.append(("规则ID", "启用", "名称", "次数", "消耗类型", "消耗名称", "消耗数量", "候选池"))
    ws.append((1, "是", "单次附魔", 1, "元宝", "", 100, "默认池"))
    ws.append((2, "是", "十次附魔", 10, "元宝", "", 1000, "默认池"))
    ws = wb.create_sheet("品质规则")
    ws.append(("品质", "权重", "保底次数", "颜色"))
    ws.append(("稀有", 100, 0, 249))
    ws = wb.create_sheet("词条候选")
    ws.append(("词条名称", "适用技能", "效果类型", "效果值", "品质", "权重", "颜色", "是否启用"))
    for skill in ("开天斩", "逐日剑法", "烈火剑法"):
        ws.append((f"{skill}必定暴击", skill, "必定暴击", 100, "稀有", 10, 249, "是"))
        ws.append((f"{skill}致命一击", skill, "致命一击", 200, "稀有", 5, 249, "是"))
    wb.save(path)
    return path


def make_v2_workbook(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "基础设置"
    ws.append(("配置项", "配置值"))
    for row in (
        ("配置版本", 2),
        ("系统编号", "weapon_enchant"),
        ("目标装备部位", "武器"),
        ("允许StdMode", "5,6"),
        ("受管身份行", 9),
        ("兼容清理行", "9-11"),
        ("NPC脚本相对路径", "Mir200/Envir/Market_Def/玄渊武器附魔/武器附魔-3.txt"),
        ("NPC地图", "3"),
        ("NPC坐标X", 325),
        ("NPC坐标Y", 339),
        ("NPC名称", "武器附魔"),
        ("NPC外观", 220),
        ("物品框编号", 27),
        ("消耗类型", "元宝"),
        ("消耗名称", ""),
        ("消耗数量", 100),
        ("显示前缀", "附魔属性："),
        ("复用母版包ID", "xy.optional.equipment-wash-opening"),
    ):
        ws.append(row)

    ws = wb.create_sheet("结果候选")
    ws.append(("词条编码", "显示名称", "属性来源", "属性名称", "适用技能", "效果类型", "效果值", "概率权重", "实际概率", "颜色", "是否启用"))
    ws.append(("LEGACY_POOL", "现有装备洗练池", "现有洗练池", "", "", "", 0, 94, "=H2/SUMIF($K$2:$K$1000,\"是\",$H$2:$H$1000)", 151, "是"))
    row = 3
    for skill in ("开天斩", "逐日剑法", "烈火剑法"):
        for effect, value, color in (("必定暴击", 100, 249), ("致命一击", 200, 253)):
            code = f"SKILL_{skill}_{effect}"
            ws.append((code, f"{skill}{effect}", "技能伤害", effect, skill, effect, value, 1, f"=H{row}/SUMIF($K$2:$K$1000,\"是\",$H$2:$H$1000)", color, "是"))
            row += 1
    ws.append(("NATIVE_BLAST", "暴击伤害+9%", "已有洗练词条", "暴击伤害", "", "固定值", 9, 1, f"=H{row}/SUMIF($K$2:$K$1000,\"是\",$H$2:$H$1000)", 249, "否"))

    ws = wb.create_sheet("普通洗练设置")
    ws.append(("结果名称", "是否启用", "触发分母", "颜色", "说明"))
    for values in (
        ("神佑", "是", 350, 125, "沿用已验收母版"),
        ("天赐", "是", 300, 31, "沿用已验收母版"),
        ("圣级", "是", 250, 70, "沿用已验收母版"),
        ("仙级", "是", 150, 253, "沿用已验收母版"),
        ("传说", "是", 10, 70, "沿用已验收母版"),
        ("上古", "是", 5, 253, "沿用已验收母版"),
        ("灵级", "是", 3, 215, "沿用已验收母版"),
    ):
        ws.append(values)

    ws = wb.create_sheet("词条路由库")
    ws.append(("属性来源", "属性名称", "路由", "状态", "单位", "适用范围", "说明"))
    ws.append(("现有洗练池", "", "legacy_pool", "verified", "", "武器", "复用verified装备洗练母版"))
    ws.append(("技能伤害", "必定暴击", "skill_damage_runtime", "verified", "%", "武器", "按技能ID修改伤害"))
    ws.append(("技能伤害", "致命一击", "skill_damage_runtime", "verified", "%", "武器", "按技能ID修改伤害"))
    ws.append(("已有洗练词条", "暴击伤害", "native_bind", "verified", "%", "武器", "母版绑定8"))
    ws.append(("预留属性", "人物等级加成", "candidate", "candidate", "级", "武器", "待验证"))
    ws.append(("预留属性", "人物等级上限加成", "candidate", "candidate", "级", "武器", "待验证"))

    ws = wb.create_sheet("填写说明")
    ws.append(("项目", "说明"))
    ws.append(("结果候选", "可增加任意行；词条编码必须唯一且保存后不要修改。"))
    ws.append(("概率权重", "所有启用行按权重自动计算实际概率。"))
    ws.append(("等级预留", "人物等级与等级上限没有当前端实例实效证据，启用时必须阻止。"))
    wb.save(path)
    return path


def make_server(root: Path) -> Path:
    envir = root / "Mir200/Envir"
    (envir / "Market_Def").mkdir(parents=True)
    (root / "Mir200/M2Server.exe").write_bytes(b"M2")
    (envir / "Market_Def/QFunction-0.txt").write_bytes(
        "[@AttackDamage]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
    )
    (envir / "MerChant.txt").write_bytes(b"")
    return root


def make_v2_server(root: Path) -> Path:
    server = make_server(root)
    envir = server / "Mir200/Envir"
    (envir / "EffectImageList.txt").write_bytes("XY_EquipmentWorkbench.wz\r\n".encode("gb18030"))
    for name in ("仙级直出.txt", "圣级直出.txt"):
        source = LEGACY_WASH_PACKAGE / "payload/server/core" / name
        target = envir / "QuestDiary/玄渊实验室/装备洗练" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return server


class WeaponEnchantTests(unittest.TestCase):
    def test_bundle_overrides_only_placeholder_settings_and_keeps_affix_data(self):
        with tempfile.TemporaryDirectory() as td:
            source = make_v2_workbook(Path(td) / "42_bundle.xlsx")
            wb = load_workbook(source)
            ws = wb["基础设置"]
            values = {ws.cell(row, 1).value: row for row in range(2, ws.max_row + 1)}
            ws.cell(values["NPC脚本相对路径"], 2, "待平台扩展：战灰刻印师")
            ws.cell(values["NPC坐标X"], 2, None)
            ws.cell(values["NPC坐标Y"], 2, None)
            ws.cell(values["消耗类型"], 2, "待平台扩展多材料")
            ws.cell(values["消耗数量"], 2, None)
            wb.save(source)
            wb.close()
            book = load_weapon_enchant_workbook(source, setting_overrides={
                "NPC脚本相对路径": "Mir200/Envir/Market_Def/玄渊法环/战灰刻印师-XY_NMGF_MAIN.txt",
                "NPC坐标X": 100,
                "NPC坐标Y": 100,
                "消耗类型": "元宝",
                "消耗数量": 0,
            })
        self.assertEqual(len(book.affixes), 7)
        self.assertEqual(len([item for item in book.affixes if item.route == "skill_damage_runtime"]), 6)

    def test_elden_war_ash_has_three_atomic_operations(self):
        template = "\n".join((
            "[@main]", "#ACT", "OPENMERCHANTBIGDLG 12 0 1 4 0 0 1 618 8 1", "#SAY",
            "<ITEMBOX:27:12:1:158:140:76:76:15,19,22,23,24,26,64,62,53,63,51,28:放入需要洗练的装备>",
            "<&Text:装备洗练:24:10{FCOLOR=253}>",
            "<&Text:请将需要洗练的装备放入左侧法阵。:382:64{FCOLOR=250}>",
            "<&Text:每次消耗：100元宝:382:108{FCOLOR=243}>",
            "<&Text:洗练会覆盖装备原有洗练词条。:382:152{FCOLOR=146}>",
            "<&Text:天赐、神佑装备洗练后需要开光。:382:196{FCOLOR=161}>",
            "<&Text:放入装备:167:266{FCOLOR=250}>",
            "<&Text:确认洗练:420:315{FCOLOR=243}/@XYEW_WASH_EXEC>",
            "<&Text:关闭:540:315{FCOLOR=161}/@exit>",
            "[@ItemIntoBox27]", "#IF", "#ACT", "BREAK",
            "[@XYEW_WASH_EXEC]", "#IF", "EQUAL <$BOXITEM[27].NAME>", "#ACT", "MESSAGEBOX 请先放入装备在洗练!", "BREAK",
            "#IF", "NOT CHECKGAMEGOLD > 99", "#ACT", "MESSAGEBOX 洗练装备需要100元宝", "BREAK",
            "#IF", "#ACT", "GOTO @区分级别洗练", "BREAK",
            "[@区分级别洗练]", "#IF", "#ACT", "GOTO @洗练给予属性", "BREAK",
            "[@洗练给予属性]", "#IF", "NOT CHECKGAMEGOLD > 99", "#ACT", "MESSAGEBOX 洗练装备需要100元宝，本次未修改装备。", "BREAK",
            "#IF", "#ACT", "GAMEGOLD - 100", "LockUpdateItem boxitem27", "UpdateItem boxitem27", "BREAK",
        ))
        with tempfile.TemporaryDirectory() as td:
            book = load_weapon_enchant_workbook(make_v2_workbook(Path(td) / "42_v2.xlsx"))
        normal = WarAshCost("C02-ASH-NORMAL", (("风暴石片", 20), ("失色锻造石", 3)), 0, 15000)
        rare = WarAshCost("C02-ASH-HIGH", (("风暴石片", 50), ("黄金树芽", 5), ("接肢王印", 1), ("失色锻造石", 8)), 0, 50000)
        clear = WarAshCost("C02-ASH-OVERWRITE", (("失色锻造石", 2),), 100000, 0)
        rendered = render_elden_war_ash_core(template, book, normal, rare, clear)
        self.assertIn("[@XY_ASH_NORMAL]", rendered)
        self.assertIn("[@XY_ASH_RARE]", rendered)
        self.assertIn("[@XY_ASH_CLEAR]", rendered)
        self.assertEqual(rendered.count("TAKE 风暴石片 20"), 1)
        self.assertEqual(rendered.count("TAKE 风暴石片 50"), 1)
        self.assertEqual(rendered.count("TAKE 失色锻造石 2"), 1)
        self.assertEqual(rendered.count("GAMEGOLD - 15000"), 1)
        self.assertEqual(rendered.count("GAMEGOLD - 50000"), 1)
        self.assertEqual(rendered.count("TAKE 金币 100000"), 1)
        self.assertIn("SetCustomItemValueEx boxitem27 9 = <$STR(N$XY_WE_PICK_ID)>", rendered)
        self.assertIn("所需战灰材料或货币不足", rendered)
        self.assertNotIn("待平台", rendered)
        configured_template = template.replace(
            "每次消耗：100元宝",
            "每次消耗：失色锻造石1个和1200元宝",
        ).replace(
            "NOT CHECKGAMEGOLD > 99",
            "NOT CHECKITEM 失色锻造石 1\n#ACT\n"
            "MESSAGEBOX 洗练装备需要失色锻造石1个和1200元宝。\nBREAK\n#IF\n"
            "NOT CHECKGAMEGOLD > 1199",
        ).replace(
            "MESSAGEBOX 洗练装备需要100元宝",
            "MESSAGEBOX 洗练装备需要失色锻造石1个和1200元宝。",
        ).replace(
            "GAMEGOLD - 100",
            "TAKE 失色锻造石 1\nGAMEGOLD - 1200",
        )

        configured_rendered = render_elden_war_ash_core(
            configured_template, book, normal, rare, clear,
        )

        self.assertEqual(configured_rendered, rendered)

    def test_v2_workbook_reuses_verified_wash_and_routes_unlimited_results(self):
        with tempfile.TemporaryDirectory() as td:
            source = make_v2_workbook(Path(td) / "42_v2.xlsx")
            try:
                book = load_weapon_enchant_workbook(source)
            except Exception as exc:  # RED: V1 loader currently rejects the V2 sheets.
                self.fail(f"V2工作簿应可解析：{exc}")
        self.assertEqual(book.schema_version, 2)
        self.assertEqual(book.settings.allowed_std_modes, (5, 6))
        self.assertEqual(len(book.affixes), 7)
        self.assertEqual({item.route for item in book.affixes}, {"legacy_pool", "skill_damage_runtime"})
        self.assertEqual(sum(item.weight for item in book.affixes), 100)
        self.assertEqual(len({item.stable_id for item in book.affixes}), 7)

    def test_verified_wash_template_is_the_immutable_derivation_source(self):
        self.assertTrue(LEGACY_WASH_TEMPLATE.is_file())
        self.assertEqual(
            __import__("hashlib").sha256(LEGACY_WASH_TEMPLATE.read_bytes()).hexdigest().upper(),
            "2775B933E0EE97319E31357FB855DBCF1FC96406F874A03B612D78A4255FED2B",
        )

    def test_v2_template_resolves_from_service_platform_root_not_frozen_module_path(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with patch("xydp.weapon_enchant.LEGACY_WASH_TEMPLATE", base / "_MEI-frozen/missing.txt"):
                plan = WeaponEnchantService(ROOT).preflight(
                    make_v2_server(base / "server"),
                    make_v2_workbook(base / "42_v2.xlsx"),
                )
        self.assertFalse(plan.blockers)

    def test_v2_preflight_derives_legacy_pool_and_adds_skill_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            plan = WeaponEnchantService(ROOT).preflight(
                make_v2_server(base / "server"),
                make_v2_workbook(base / "42_v2.xlsx"),
            )
        self.assertFalse(plan.blockers)
        rendered = {Path(change.relative_path): change.after.decode("gb18030") for change in plan.changes}
        core = rendered[CORE_RELATIVE]
        runtime = rendered[RUNTIME_RELATIVE]
        self.assertIn("XY-WEAPON-ENCHANT-V2-DERIVED", core)
        self.assertIn("[@区分级别洗练]", core)
        self.assertIn("[@获取属性八]", core)
        self.assertIn("<ITEMBOX:27:12:1:158:140:76:76:5,6:", core)
        self.assertIn("RANDOMEX 94 100", core)
        self.assertIn("RANDOMEX 1 6", core)
        self.assertIn("GOTO @XY_WE_SPECIAL_WRITE\r\nBREAK", core)
        self.assertIn("SetCustomItemAbil boxitem27 9 1 60", core)
        self.assertIn("SetCustomItemAbil boxitem27 9 4 9", core)
        self.assertIn("SetCustomItemText boxitem27 [附魔属性：", core)
        self.assertIn("<$CURRRUSEMAGICID>", runtime)
        self.assertNotIn("sqlite", (core + runtime).casefold())
        self.assertNotIn("ApexM2.DB", core + runtime)

    def test_v2_native_existing_affix_can_be_enabled_as_an_extra_result(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            workbook = make_v2_workbook(base / "42_v2.xlsx")
            wb = load_workbook(workbook)
            ws = wb["结果候选"]
            ws.cell(ws.max_row, 11, "是")
            wb.save(workbook)
            wb.close()
            plan = WeaponEnchantService(ROOT).preflight(make_v2_server(base / "server"), workbook)
        self.assertFalse(plan.blockers)
        core = next(change.after.decode("gb18030") for change in plan.changes if Path(change.relative_path) == CORE_RELATIVE)
        self.assertIn("MOV N$XY_WE_PICK_BIND 8", core)
        self.assertIn("SetCustomItemAbil boxitem27 0 1 <$STR(N$XY_WE_PICK_BIND)>", core)
        self.assertIn("暴击伤害+9%", core)

    def test_v2_candidate_route_is_blocked_instead_of_becoming_display_only(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            workbook = make_v2_workbook(base / "42_v2.xlsx")
            wb = load_workbook(workbook)
            ws = wb["结果候选"]
            ws.append(("LEVEL_PLUS", "人物等级+1", "预留属性", "人物等级加成", "", "固定值", 1, 1, 0, 250, "是"))
            wb.save(workbook)
            wb.close()
            plan = WeaponEnchantService(ROOT).preflight(make_server(base / "server"), workbook)
        self.assertFalse(plan.changes)
        self.assertTrue(any("人物等级加成" in blocker and "待验证" in blocker for blocker in plan.blockers))

    def test_v2_requires_the_verified_wash_dependency_instead_of_copying_it(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            plan = WeaponEnchantService(ROOT).preflight(
                make_server(base / "server"),
                make_v2_workbook(base / "42_v2.xlsx"),
            )
        self.assertFalse(plan.changes)
        self.assertTrue(any("装备洗练底座" in blocker for blocker in plan.blockers))

    def test_v2_exact_qfunction_hook_without_final_newline_is_a_semantic_noop(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            server = make_v2_server(base / "server")
            workbook = make_v2_workbook(base / "42_v2.xlsx")
            service = WeaponEnchantService(ROOT)
            service.install(service.preflight(server, workbook))
            qfunction = server / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_bytes(qfunction.read_bytes().rstrip(b"\r\n"))
            plan = service.preflight(server, workbook)
        self.assertFalse(plan.blockers)
        self.assertNotIn(Path("Mir200/Envir/Market_Def/QFunction-0.txt"), {Path(change.relative_path) for change in plan.changes})

    def test_current_workbook_and_candidate_package_contract(self):
        workbook_path = ROOT / "所需材料表格汇总/42_武器附魔.xlsx"
        book = load_weapon_enchant_workbook(workbook_path)
        self.assertEqual(book.schema_version, 2)
        self.assertEqual(book.settings.allowed_std_modes, (5, 6))
        self.assertEqual(len(book.affixes), 7)
        self.assertEqual(sum(item.weight for item in book.affixes), 100)
        self.assertEqual(len({item.stable_id for item in book.affixes}), 7)
        self.assertEqual({item.route for item in book.affixes}, {"legacy_pool", "skill_damage_runtime"})
        package = validate_package(ROOT / "packages/candidate" / PACKAGE_ID)
        self.assertEqual(package.install_route, ROUTE)
        self.assertEqual(package.status, "candidate")
        self.assertIn("xy.optional.equipment-wash-opening", package.dependencies)
        rendered = load_workbook(workbook_path, data_only=True)
        try:
            ws = rendered["结果候选"]
            self.assertEqual([ws.cell(row, 9).value for row in range(2, 9)], [0.94, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01])
            self.assertEqual([ws.cell(row, 9).value for row in range(9, 14)], [0, 0, 0, 0, 0])
        finally:
            rendered.close()

    def test_workbook_builder_targets_v2_single_click_schema(self):
        builder = (ROOT / "tools/build_weapon_enchant_workbook.mjs").read_text(encoding="utf-8")
        self.assertIn('"基础设置"', builder)
        self.assertIn('"结果候选"', builder)
        self.assertIn('"复用母版包ID"', builder)
        self.assertIn('"LEGACY_POOL"', builder)
        self.assertNotIn("十次附魔", builder)

    def test_six_examples_are_data_driven_and_have_stable_ids(self):
        with tempfile.TemporaryDirectory() as td:
            book = load_weapon_enchant_workbook(make_workbook(Path(td) / "42.xlsx"))
        self.assertEqual(len(book.affixes), 6)
        self.assertEqual({a.skill for a in book.affixes}, {"开天斩", "逐日剑法", "烈火剑法"})
        self.assertEqual({a.effect_type for a in book.affixes}, {"必定暴击", "致命一击"})
        self.assertTrue(all(a.route == "textline_runtime" for a in book.affixes))
        self.assertTrue(all(a.effect_status == "candidate" for a in book.affixes))
        self.assertTrue(all(a.quality_weight == 100 for a in book.affixes))
        self.assertEqual(len({a.stable_id for a in book.affixes}), 6)

    def test_preflight_generates_independent_transaction_without_database(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            workbook = make_workbook(base / "42.xlsx")
            server = make_server(base / "server")
            plan = WeaponEnchantService(ROOT).preflight(server, workbook)
            self.assertFalse(plan.blockers)
            self.assertEqual(plan.route, ROUTE)
            self.assertEqual(plan.package_id, PACKAGE_ID)
            text = "\n".join(change.after.decode("gb18030") for change in plan.changes)
            self.assertNotIn("sqlite", text.casefold())
            self.assertNotIn("ApexM2.DB", text)
            self.assertIn("LockUpdateItem boxitem29", text)
            self.assertEqual(text.count("LockUpdateItem boxitem29"), 1)
            self.assertEqual(sum(line == "UpdateItem boxitem29" for line in text.splitlines()), 1)
            self.assertIn("SetCustomItemValueEx boxitem29 9", text)
            self.assertIn("SetCustomItemValueEx boxitem29 11", text)
            self.assertIn("SetCustomItemText boxitem29", text)
            self.assertIn("MOV N$XY_WE_PICK_COLOR 249", text)
            self.assertIn("SetCustomItemTextColor boxitem29 <$STR(N$XY_WE_DISPLAY_COLOR)>", text)
            self.assertIn("<$CURRRUSEMAGICID>", text)
            self.assertTrue(all(change.after.endswith(b"\r\n") for change in plan.changes))
            self.assertTrue(any("持久保底" in warning for warning in plan.warnings))

    def test_external_call_targets_use_required_whole_file_braces(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            plan = WeaponEnchantService(ROOT).preflight(
                make_server(base / "server"),
                make_workbook(base / "42.xlsx"),
            )
        rendered = {Path(change.relative_path): change.after.decode("gb18030") for change in plan.changes}
        for relative in (CORE_RELATIVE, RUNTIME_RELATIVE):
            lines = rendered[relative].splitlines()
            self.assertEqual(lines[0], "{")
            self.assertEqual(lines[-1], "}")
            self.assertEqual(lines.count("{"), 1)
            self.assertEqual(lines.count("}"), 1)

    def test_install_is_idempotent_and_rollback_is_byte_exact(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            workbook = make_workbook(base / "42.xlsx")
            server = make_server(base / "server")
            before = {p.relative_to(server): p.read_bytes() for p in server.rglob("*") if p.is_file()}
            service = WeaponEnchantService(base / "platform")
            receipt = service.install(service.preflight(server, workbook))
            self.assertFalse(service.preflight(server, workbook).changes)
            service.rollback(server, receipt.transaction_id)
            after = {p.relative_to(server): p.read_bytes() for p in server.rglob("*") if p.is_file() and ".xydp" not in p.parts}
            self.assertEqual(after, before)

    def test_positive_pity_blocks_without_guessing_persistent_storage(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            workbook = make_workbook(base / "42.xlsx")
            wb = load_workbook(workbook)
            wb["品质规则"]["C2"] = 20
            wb.save(workbook)
            wb.close()
            plan = WeaponEnchantService(ROOT).preflight(make_server(base / "server"), workbook)
            self.assertFalse(plan.changes)
            self.assertTrue(any("保底持久化路线待验证" in blocker for blocker in plan.blockers))

    def test_registered_document_routes_to_weapon_enchant(self):
        self.assertEqual(ConfigSyncService._route([type("D", (), {"id": "weapon_enchant"})()]), ROUTE)


if __name__ == "__main__":
    unittest.main()
