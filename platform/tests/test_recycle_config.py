from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Always exercise the candidate module, even when the platform source directory
# is supplied first on PYTHONPATH by the test command.
CANDIDATE_ROOT = Path(__file__).resolve().parents[1]
import xydp
xydp.__path__.insert(0, str(CANDIDATE_ROOT / "src" / "xydp"))

from xydp.recycle_config import (
    DEFAULT_WORKBOOK,
    RecycleCategory,
    RecycleConfigError,
    RecycleConfigService,
    RecycleRule,
    RecycleWorkbook,
    _equipment_bonus_blocks,
    _repair_known_stale_managed_digest,
    _reward_lines,
    compile_qfunction,
    compile_qmanage,
    read_recycle_workbook,
)
from xydp.encoding import read_text_document


class MaterialRecycleCandidateTests(unittest.TestCase):
    def _book(self, rows):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = folder / "19B.xlsx"
        path.write_bytes(b"material-fixture")
        return path, {
            "基础设置": [
                ["设置项", "值", "说明"],
                ["面板标题", "材料回收", ""],
                ["回收模式", "自动+手动", ""],
                ["每次回收单位", 1, ""],
                ["货币回收增加适用", "否", ""],
                ["自动回收触发空余格数", 40, ""],
                ["自动回收默认开启", "否", ""],
                ["默认分类勾选", "否", ""],
                ["面板背景图库", "XY_TreeBlessingDialog.wzl", ""],
                ["面板背景帧", 0, ""],
            ],
            "回收明细": [[
                "启用", "分类ID", "分类名称", "材料名称", "奖励类型", "奖励名称", "单件奖励",
                "附加奖励类型", "附加奖励名称", "附加单件奖励", "分类排序", "材料排序", "默认勾选", "备注",
            ], *rows],
        }

    def test_material_workbook_excludes_disabled_entries_from_whitelist(self):
        path, sheets = self._book([
            ["否", "M", "材料回收", "失色锻造石", "原生金币", "", 1, "原生元宝", "", 2, 1, 1, "否", ""],
            ["是", "M", "材料回收", "野兽骨片", "原生金币", "", 1, "原生元宝", "", 2, 1, 2, "否", ""],
        ])
        with patch("xydp.recycle_config._read_xlsx", return_value=(sheets, "a" * 64)):
            book = read_recycle_workbook(path)
        self.assertEqual(book.mode, "自动+手动")
        self.assertFalse(book.auto_enabled_default)
        self.assertEqual([rule.item_name for rule in book.rules], ["野兽骨片"])

    def test_material_panel_uses_one_dynamic_three_column_view_and_no_equipment_bonus(self):
        path, sheets = self._book([
            ["是", "M", "材料回收", "野兽骨片", "原生金币", "", 1, "原生元宝", "", 2, 1, 1, "否", ""],
        ])
        with patch("xydp.recycle_config._read_xlsx", return_value=(sheets, "a" * 64)):
            book = read_recycle_workbook(path)
        from xydp.recycle_config import compile_material_qfunction
        script = compile_material_qfunction(book, {"M": 31}, 32, background_index=28)
        self.assertIn("OPENMERCHANTBIGDLG 28 0 1 4 0 -50 1 536 25 1", script)
        self.assertIn("S$XYMaterialRecycleMark001", script)
        self.assertIn("第1页 共1页", script)
        self.assertNotIn("_STATE_", script)
        self.assertIn("TAKE 野兽骨片 <$STR(N$XY_MaterialRecycleBefore)>", script)
        self.assertIn("GOLDCOUNT + <$STR(N$XY_MaterialRecycleReward)>", script)
        self.assertIn("GAMEGOLD + <$STR(N$XY_MaterialRecycleReward)>", script)
        self.assertLess(script.index("MOV N$XY_MaterialRecycleRemoved 0"), script.index("CHECKITEM 野兽骨片 1"))
        self.assertLess(script.index("TAKE 野兽骨片 <$STR(N$XY_MaterialRecycleBefore)>"), script.index("GOLDCOUNT +"))
        for forbidden in ("N$XY_RecycleEquipBonus", "XY_EQUIP_MAKER"):
            self.assertNotIn(forbidden, script)

    def test_material_auto_timer_requires_its_own_auto_flag_and_threshold(self):
        rows = [
            ["是", "M", "材料回收", f"材料{i:03d}", "原生金币", "", 1, "", "", "", 1, i, "否", ""]
            for i in range(1, 12)
        ]
        path, sheets = self._book(rows)
        with patch("xydp.recycle_config._read_xlsx", return_value=(sheets, "a" * 64)):
            book = read_recycle_workbook(path)
        from xydp.recycle_config import compile_material_qmanage
        script = compile_material_qmanage(book, {"M": 31}, 47)
        self.assertIn("[@OnTimer21]", script)
        self.assertIn("CHECK [47] 0", script)
        self.assertIn("CHECKBAGSIZE 40", script)
        self.assertIn("CHECK [31] 1", script)
        self.assertIn("TAKE 材料001 <$STR(N$XY_MaterialRecycleBefore)>", script)
        self.assertNotIn("N$XY_RecycleEquipBonus", script)

    def test_equipment_checkbox_does_not_start_auto_or_expand_to_selection_state_labels(self):
        categories = tuple(
            RecycleCategory(f"C{index}", f"分类{index}", index, (rule(f"C{index}", index, f"装备{index}"),))
            for index in range(1, 13)
        )
        workbook = RecycleWorkbook("fixture", "0" * 64, 40, 3, 21, 20, "装备回收", categories)
        flags = {category.id: 30 + index for index, category in enumerate(categories, start=1)}
        script = compile_qfunction(workbook, flags, flags, auto_flag=78, background_index=28)
        self.assertIn("[@XY_RECYCLE_PANEL_MAIN]", script)
        self.assertNotIn("_STATE_", script)
        self.assertEqual(script.count("S$XYRecycleMark"), 36)
        toggle = script[script.index("[@XY_RECYCLE_TOGGLE_001]"):script.index("[@XY_RECYCLE_TOGGLE_002]")]
        self.assertNotIn("SetOnTimer", toggle)
        self.assertIn("SET [31] 0", toggle)
        self.assertIn("SET [31] 1", toggle)
        disabled = script[script.index("[@XY_RECYCLE_AUTO_DISABLE]"):script.index("[@XY_RECYCLE_CLEAR_SELECTIONS]")]
        self.assertIn("SET [78] 0", disabled)
        self.assertNotIn("SET [31] 0", disabled)
        cross_mode = compile_qfunction(workbook, flags, flags, auto_flag=78, material_available=True)
        self.assertIn("材料回收:364:350{FCOLOR=218}/@XY_MATERIAL_RECYCLE_COMMAND", cross_mode)
        self.assertNotIn("/@材料回收", cross_mode)

    def test_material_renderer_keeps_retired_mapping_and_uses_real_equipment_entry_label(self):
        path, sheets = self._book([
            ["是", "NEW", "新材料", "野兽骨片", "原生金币", "", 1, "", "", "", 1, 1, "否", ""],
        ])
        with patch("xydp.recycle_config._read_xlsx", return_value=(sheets, "a" * 64)):
            book = read_recycle_workbook(path)
        from xydp.recycle_config import compile_material_qfunction
        script = compile_material_qfunction(book, {"NEW": 62}, all_mapping={"OLD": 61, "NEW": 62}, equipment_available=True)
        self.assertIn("XY-MATERIAL-RECYCLE-CATEGORY OLD FLAG=61 STATUS=RETIRED", script)
        self.assertIn("XY-MATERIAL-RECYCLE-CATEGORY NEW FLAG=62 STATUS=ACTIVE", script)
        self.assertIn("装备回收:364:350{FCOLOR=218}/@XY_RECYCLE_COMMAND", script)
        self.assertNotIn("/@装备回收", script)


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if not (PLATFORM_ROOT / "所需材料表格汇总" / DEFAULT_WORKBOOK).exists():
    PLATFORM_ROOT = Path(r"E:\XuanYuanDevPlatform")
WORKBOOK = PLATFORM_ROOT / "所需材料表格汇总" / DEFAULT_WORKBOOK


def rule(
    category: str,
    order: int,
    item: str,
    reward_type: str = "原生金币",
    *,
    extra_reward_type: str = "",
    extra_reward_name: str = "",
    extra_unit_reward: int = 0,
) -> RecycleRule:
    return RecycleRule(
        category,
        f"分类{category}",
        item,
        reward_type,
        "",
        1000,
        order,
        1,
        extra_reward_type=extra_reward_type,
        extra_reward_name=extra_reward_name,
        extra_unit_reward=extra_unit_reward,
    )


class RecycleConfigTests(unittest.TestCase):
    def test_exact_accepted_stale_digest_can_be_repaired_without_changing_body(self):
        body = "[@XY_RECYCLE_PANEL_MAIN]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        actual = hashlib.sha256(body.replace("\r\n", "\n").strip("\r\n").encode()).hexdigest()
        marker = "0" * 64
        text = (
            f"; XYDP-BEGIN xy.optional.recycle.configurable SHA256={marker}\r\n"
            + body
            + "; XYDP-END xy.optional.recycle.configurable\r\n"
            + "; KEEP\r\n"
        )

        with patch("xydp.recycle_config._ACCEPTED_STALE_MANAGED_DIGESTS", {"qfunction-main": {(marker, actual)}}):
            repaired = _repair_known_stale_managed_digest(text, "qfunction-main")

        self.assertIn(f"SHA256={actual}", repaired)
        self.assertIn(body, repaired)
        self.assertIn("; KEEP", repaired)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.platform = self.root / "platform"
        (self.platform / "packages").mkdir(parents=True)
        self.server = self.root / "server"
        envir = self.server / "Mir200" / "Envir"
        (envir / "Market_Def").mkdir(parents=True)
        (envir / "MapQuest_Def").mkdir(parents=True)
        (self.server / "Mud2" / "DB").mkdir(parents=True)
        (self.server / "Mir200" / "M2Server.exe").write_bytes(b"")
        (envir / "MapInfo.txt").write_text("[0 test]", encoding="gb18030")
        self.qfunction = envir / "Market_Def" / "QFunction-0.txt"
        self.qmanage = envir / "MapQuest_Def" / "QManage.txt"
        self.usercmd = envir / "UserCmd.txt"
        self.qfunction.write_text(
            "; 中文夹具\n[@PlayLogin]\n#IF\n#ACT\nBREAK\n\n"
            "[@PickUpItemEX]\n#IF\n#ACT\nBREAK\n\n"
            "[@CustomButtonClick]\n#IF\n#ACT\nBREAK\n",
            encoding="gb18030",
            newline="\r\n",
        )
        self.qmanage.write_text("; 中文空白夹具\n", encoding="gb18030", newline="\r\n")
        self.usercmd.write_text("测试\t99\n", encoding="gb18030", newline="\r\n")
        db = self.server / "Mud2" / "DB" / "ApexM2.DB"
        connection = sqlite3.connect(db)
        try:
            connection.execute("CREATE TABLE StdItems (Idx INTEGER PRIMARY KEY, Name TEXT, OverLap INTEGER)")
            connection.executemany(
                "INSERT INTO StdItems (Name, OverLap) VALUES (?, ?)",
                [("木剑", 0), ("铁剑", 0), ("青铜剑", 0), ("测试材料", 99)],
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_fixed_fixture_accepts_legacy_three_column_setting_but_renders_one_eighteen_category_canvas(self) -> None:
        workbook = self._three_item_workbook()
        self.assertEqual([item.id for item in workbook.categories], ["A", "B", "C"])
        self.assertEqual(workbook.page_size, 18)
        self.assertEqual(workbook.button_id, 21)
        self.assertEqual(workbook.timer_id, 20)

    def _read_compact_fixture(self, rows: list[list[object]], *, include_extra: bool = False):
        path = self.root / "compact.xlsx"
        path.write_bytes(b"fixture")
        headers = ["启用", "分类ID", "分类名称", "装备名称", "奖励类型", "奖励名称", "单件奖励"]
        if include_extra:
            headers.extend(["附加奖励类型", "附加奖励名称", "附加单件奖励"])
        headers.extend(["分类排序", "装备排序", "备注"])
        sheets = {
            "基础设置": [["设置项", "值", "说明"]],
            "回收明细": [
                headers,
                *rows,
            ],
        }
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with patch("xydp.recycle_config._read_xlsx", return_value=(sheets, digest)):
            return read_recycle_workbook(path)

    def _three_item_workbook(self):
        return self._read_compact_fixture([
            ["是", "A", "回收A", "木剑", "原生金币", "", 1000, 1, 1, ""],
            ["是", "B", "回收B", "铁剑", "原生金币", "", 1000, 2, 1, ""],
            ["是", "C", "回收C", "青铜剑", "原生金币", "", 1000, 3, 1, ""],
        ])

    def _one_material_workbook(self):
        path = self.root / "19B.xlsx"
        path.write_bytes(b"material-fixture")
        sheets = {
            "基础设置": [["设置项", "值", "说明"], ["面板标题", "材料回收", ""],
                         ["回收模式", "自动+手动", ""], ["每次回收单位", 1, ""],
                         ["货币回收增加适用", "否", ""]],
            "回收明细": [["启用", "分类ID", "分类名称", "材料名称", "奖励类型", "奖励名称", "单件奖励",
                          "附加奖励类型", "附加奖励名称", "附加单件奖励", "分类排序", "材料排序", "默认勾选", "备注"],
                         ["是", "M", "材料回收", "测试材料", "原生金币", "", 100, "原生元宝", "", 2, 1, 1, "否", ""]],
        }
        with patch("xydp.recycle_config._read_xlsx", return_value=(sheets, hashlib.sha256(path.read_bytes()).hexdigest())):
            return read_recycle_workbook(path)

    def test_one_cell_expands_pipe_and_newline_names(self) -> None:
        workbook = self._read_compact_fixture([
            ["是", "A", "回收A", "木剑|青铜剑\n铁剑", "原生金币", "", 1000, 1, 1, ""],
        ])
        self.assertEqual(len(workbook.categories), 1)
        self.assertEqual(workbook.categories[0].id, "A")
        self.assertEqual([item.item_name for item in workbook.rules], ["木剑", "铁剑", "青铜剑"])
        self.assertTrue(all(item.unit_reward == 1000 for item in workbook.rules))

    def test_more_than_five_hundred_rules_are_supported(self) -> None:
        names = "|".join(f"测试装备{index:03d}" for index in range(501))
        workbook = self._read_compact_fixture([
            ["是", "A", "回收A", names, "原生金币", "", 1000, 1, 1, ""],
        ])
        self.assertEqual(len(workbook.rules), 501)

    def test_old_one_item_per_row_format_remains_supported(self) -> None:
        workbook = self._read_compact_fixture([
            ["是", "A", "回收A", "木剑", "原生金币", "", 1000, 1, 1, ""],
            ["是", "A", "回收A", "铁剑", "原生金币", "", 1000, 1, 2, ""],
        ])
        self.assertEqual([item.item_name for item in workbook.rules], ["木剑", "铁剑"])

    def test_expanded_duplicate_name_is_blocked(self) -> None:
        with self.assertRaisesRegex(RecycleConfigError, "装备名称重复登记：铁剑"):
            self._read_compact_fixture([
                ["是", "A", "回收A", "木剑|铁剑", "原生金币", "", 1000, 1, 1, ""],
                ["是", "B", "回收B", "铁剑", "原生金币", "", 1000, 2, 1, ""],
            ])

    def test_empty_item_between_separators_is_blocked(self) -> None:
        with self.assertRaisesRegex(RecycleConfigError, "装备名称存在空项"):
            self._read_compact_fixture([
                ["是", "A", "回收A", "木剑||铁剑", "原生金币", "", 1000, 1, 1, ""],
            ])

    def test_new_categories_stay_on_one_dynamic_canvas_without_state_tree(self) -> None:
        categories = tuple(
            RecycleCategory(letter, f"分类{letter}", index, (rule(letter, index, f"装备{letter}"),))
            for index, letter in enumerate("ABCDE", start=1)
        )
        workbook = RecycleWorkbook("fixture", "0" * 64, 40, 3, 21, 20, "装备自动回收", categories)
        flags = {letter: 10 + index for index, letter in enumerate("ABCDE", start=1)}
        script = compile_qfunction(workbook, flags, flags)
        self.assertNotIn("_STATE_", script)
        self.assertIn("分类E", script)
        self.assertIn("[@XY_RECYCLE_TOGGLE_005]", script)
        self.assertNotIn("下一页", script)

    def test_reward_type_uses_native_currency_command(self) -> None:
        reward = "\n".join(_reward_lines(rule("A", 1, "木剑")))
        self.assertIn("GOLDCOUNT +", reward)
        self.assertIn(
            "(<$STR(N$XY_RecycleBatchReward)>*<$STR(N$XY_RecycleEquipBonus)>)/100",
            reward,
        )
        self.assertIn(
            "INC N$XY_RecycleBatchReward <$STR(N$XY_RecycleBatchBonusReward)>",
            reward,
        )
        self.assertIn("GAMEGOLD +", "\n".join(_reward_lines(rule("A", 1, "木剑", "原生元宝"))))
        self.assertIn("GAMEGIRD +", "\n".join(_reward_lines(rule("A", 1, "木剑", "原生灵符"))))
        self.assertIn("GAMEDIAMOND +", "\n".join(_reward_lines(rule("A", 1, "木剑", "原生金刚石"))))

    def test_manual_and_auto_recycle_recalculate_equipment_bonus(self) -> None:
        categories = (RecycleCategory("A", "分类A", 1, (rule("A", 1, "木剑"),)),)
        workbook = RecycleWorkbook("fixture", "0" * 64, 40, 3, 21, 20, "装备自动回收", categories)
        block = (
            "; XY-EQUIP-MAKER 回收戒指: 回收增加+20%\n"
            "#IF\n"
            "CHECKITEMW 回收戒指 1\n"
            "#ACT\n"
            "INC N$XY_RecycleEquipBonus 20"
        )
        qfunction = compile_qfunction(workbook, {"A": 11}, {"A": 11}, (block,))
        qmanage = compile_qmanage(workbook, {"A": 11}, (block,))
        for script, anchor in (
            (qfunction, "; XY_EQUIP_MAKER_RECYCLE_BONUS_QFUNCTION_ANCHOR"),
            (qmanage, "; XY_EQUIP_MAKER_RECYCLE_BONUS_QMANAGE_ANCHOR"),
        ):
            self.assertIn("MOV N$XY_RecycleEquipBonus 0", script)
            self.assertIn(anchor, script)
            self.assertEqual(script.count("CHECKITEMW 回收戒指 1"), 1)
            self.assertIn("INC N$XY_RecycleEquipBonus 20", script)

    def test_equipment_bonus_block_reader_rejects_hand_edits(self) -> None:
        valid = (
            "; XY-EQUIP-MAKER 回收戒指: 回收增加+20%\n"
            "#IF\nCHECKITEMW 回收戒指 1\n#ACT\nINC N$XY_RecycleEquipBonus 20\n"
        )
        self.assertEqual(len(_equipment_bonus_blocks(valid)), 1)
        with self.assertRaisesRegex(RecycleConfigError, "已被修改"):
            _equipment_bonus_blocks(valid.replace(" 20\n", " 21\n"))

    def test_one_item_can_pay_primary_gold_and_extra_gamegold_after_one_take(self) -> None:
        workbook = self._read_compact_fixture([
            ["是", "A", "回收A", "木剑", "原生金币", "", 1000, "原生元宝", "", 10, 1, 1, ""],
        ], include_extra=True)
        compiled = compile_qfunction(workbook, {"A": 11}, {"A": 11})
        self.assertEqual(compiled.count("TAKE 木剑"), 1)
        self.assertIn("GOLDCOUNT +", compiled)
        self.assertIn("GAMEGOLD +", compiled)
        self.assertEqual(workbook.rules[0].extra_reward_type, "原生元宝")
        self.assertEqual(workbook.rules[0].extra_unit_reward, 10)

    def test_every_item_resets_removed_before_presence_check_for_manual_or_auto_reward(self) -> None:
        categories = (RecycleCategory("A", "分类A", 1, (rule("A", 1, "木剑"),)),)
        workbook = RecycleWorkbook("fixture", "0" * 64, 40, 3, 21, 20, "装备自动回收", categories)
        expected_guard = (
            "; 分类A => 木剑\n"
            "#IF\n"
            "#ACT\n"
            "MOV N$XY_RecycleBatchBefore 0\n"
            "MOV N$XY_RecycleBatchAfter 0\n"
            "MOV N$XY_RecycleBatchRemoved 0\n"
            "#IF\n"
            "CHECK [11] 1\n"
            "CHECKITEM 木剑 1\n"
            "#ACT\n"
            "GetItemCount 0 木剑 N$XY_RecycleBatchBefore\n"
            "TAKE 木剑 <$STR(N$XY_RecycleBatchBefore)>\n"
            "GetItemCount 0 木剑 N$XY_RecycleBatchAfter\n"
            "FORMULATION <$STR(N$XY_RecycleBatchBefore)>-<$STR(N$XY_RecycleBatchAfter)> "
            "N$XY_RecycleBatchRemoved"
        )
        for compiled in (
            compile_qfunction(workbook, {"A": 11}, {"A": 11}),
            compile_qmanage(workbook, {"A": 11}),
        ):
            self.assertIn(expected_guard, compiled)
            self.assertEqual(compiled.count("CHECKITEM 木剑 1"), 1)
            self.assertLess(
                compiled.index("LARGE N$XY_RecycleBatchRemoved 0"),
                compiled.index("GOLDCOUNT +"),
            )
            self.assertLess(
                compiled.index("MOV N$XY_RecycleBatchReward 0"),
                compiled.index("FORMULATION <$STR(N$XY_RecycleBatchRemoved)>*1000"),
            )
            self.assertLess(
                compiled.index("MOV N$XY_RecycleBatchBonusReward 0"),
                compiled.index("FORMULATION (<$STR(N$XY_RecycleBatchReward)>"),
            )

    def test_blank_extra_reward_keeps_old_single_reward_behavior(self) -> None:
        workbook = self._read_compact_fixture([
            ["是", "A", "回收A", "木剑", "原生金币", "", 1000, "", "", "", 1, 1, ""],
        ], include_extra=True)
        reward_text = "\n".join(_reward_lines(workbook.rules[0]))
        self.assertIn("GOLDCOUNT +", reward_text)
        self.assertNotIn("GAMEGOLD +", reward_text)
        self.assertEqual(len(workbook.rules[0].reward_specs), 1)

    def test_partial_extra_reward_is_blocked(self) -> None:
        with self.assertRaisesRegex(RecycleConfigError, "附加单件奖励必须填写整数"):
            self._read_compact_fixture([
                ["是", "A", "回收A", "木剑", "原生金币", "", 1000, "原生元宝", "", "", 1, 1, ""],
            ], include_extra=True)

    def test_preflight_is_read_only_and_install_rollback_is_byte_exact(self) -> None:
        service = RecycleConfigService(self.platform)
        workbook = self._three_item_workbook()
        before = {
            self.qfunction: self.qfunction.read_bytes(),
            self.qmanage: self.qmanage.read_bytes(),
            self.usercmd: self.usercmd.read_bytes(),
        }
        with patch("xydp.recycle_config.read_recycle_workbook", return_value=workbook):
            plan = service.preflight(Path(workbook.path), self.server)
        self.assertEqual(plan.blockers, [])
        self.assertEqual([item.flag for item in plan.categories], [11, 12, 13])
        self.assertEqual(plan.page_count, 1)
        self.assertTrue(all(item.page == 1 for item in plan.categories))
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        receipt = service.install(plan)
        self.assertIn("XY-RECYCLE-CATEGORY A FLAG=11 STATUS=ACTIVE", read_text_document(self.qfunction).text)
        self.assertIn("[@OnTimer20]", read_text_document(self.qmanage).text)
        self.assertIn("快捷回收", read_text_document(self.usercmd).text)
        service.rollback(self.server, receipt.transaction_id)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_material_install_is_idempotent_and_rollback_restores_its_three_files(self) -> None:
        service = RecycleConfigService(self.platform)
        workbook = self._one_material_workbook()
        before = {path: path.read_bytes() for path in (self.qfunction, self.qmanage, self.usercmd)}
        with patch("xydp.recycle_config.read_recycle_workbook", return_value=workbook):
            first = service.preflight(Path(workbook.path), self.server)
        self.assertEqual(first.blockers, [])
        self.assertEqual(first.install_plan.parameters["user_command"], 32)
        self.assertEqual(
            {change.relative_path for change in first.changes},
            {"Mir200/Envir/Market_Def/QFunction-0.txt", "Mir200/Envir/MapQuest_Def/QManage.txt", "Mir200/Envir/UserCmd.txt"},
        )
        receipt = service.install(first)
        self.assertIn("[@XY_MATERIAL_RECYCLE_COMMAND]", read_text_document(self.qfunction).text)
        self.assertIn("[@OnTimer21]", read_text_document(self.qmanage).text)
        with patch("xydp.recycle_config.read_recycle_workbook", return_value=workbook):
            second = service.preflight(Path(workbook.path), self.server)
        self.assertEqual(second.blockers, [])
        self.assertEqual(second.changes, [])
        service.rollback(self.server, receipt.transaction_id)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_two_recycle_modes_reserve_each_others_category_and_auto_flags_across_repreflight(self) -> None:
        service = RecycleConfigService(self.platform)
        equipment = self._three_item_workbook()
        material = self._one_material_workbook()
        with patch("xydp.recycle_config.read_recycle_workbook", return_value=equipment):
            equipment_plan = service.preflight(Path(equipment.path), self.server)
        self.assertEqual(equipment_plan.blockers, [])
        equipment_receipt = service.install(equipment_plan)
        with patch("xydp.recycle_config.read_recycle_workbook", return_value=material):
            material_plan = service.preflight(Path(material.path), self.server)
        self.assertEqual(material_plan.blockers, [])
        equipment_flags = set(equipment_plan.install_plan.parameters["category_flags"].values()) | {equipment_plan.install_plan.parameters["auto_flag"]}
        material_flags = set(material_plan.install_plan.parameters["category_flags"].values()) | {material_plan.install_plan.parameters["auto_flag"]}
        self.assertFalse(equipment_flags & material_flags)
        material_receipt = service.install(material_plan)
        with patch("xydp.recycle_config.read_recycle_workbook", return_value=equipment):
            rechecked = service.preflight(Path(equipment.path), self.server)
        self.assertEqual(rechecked.blockers, [])
        self.assertEqual(rechecked.install_plan.parameters["auto_flag"], equipment_plan.install_plan.parameters["auto_flag"])
        service.rollback(self.server, material_receipt.transaction_id)
        service.rollback(self.server, equipment_receipt.transaction_id)

    def test_recycle_config_update_preserves_equipment_bonus_blocks(self) -> None:
        service = RecycleConfigService(self.platform)
        workbook = self._three_item_workbook()
        with patch("xydp.recycle_config.read_recycle_workbook", return_value=workbook):
            first = service.preflight(Path(workbook.path), self.server)
        self.assertEqual(first.blockers, [])
        service.install(first)
        block = (
            "; XY-EQUIP-MAKER 回收戒指: 回收增加+20%\r\n"
            "#IF\r\nCHECKITEMW 回收戒指 1\r\n#ACT\r\n"
            "INC N$XY_RecycleEquipBonus 20\r\n"
        )
        for path, anchor in (
            (self.qfunction, "; XY_EQUIP_MAKER_RECYCLE_BONUS_QFUNCTION_ANCHOR"),
            (self.qmanage, "; XY_EQUIP_MAKER_RECYCLE_BONUS_QMANAGE_ANCHOR"),
        ):
            text = read_text_document(path).text
            text = text.replace(anchor, anchor + "\r\n" + block.rstrip("\r\n"), 1)
            path.write_text(text, encoding="gb18030", newline="")
        self.usercmd.write_text("测试\t99\r\n", encoding="gb18030", newline="")
        with patch("xydp.recycle_config.read_recycle_workbook", return_value=workbook):
            second = service.preflight(Path(workbook.path), self.server)
        self.assertEqual(second.blockers, [])
        service.install(second)
        self.assertEqual(read_text_document(self.qfunction).text.count("CHECKITEMW 回收戒指 1"), 1)
        self.assertEqual(read_text_document(self.qmanage).text.count("CHECKITEMW 回收戒指 1"), 1)


if __name__ == "__main__":
    unittest.main()
