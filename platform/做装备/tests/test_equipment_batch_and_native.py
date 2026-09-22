import tempfile
import unittest
from pathlib import Path
import sys
import html
import zipfile


EQUIPMENT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EQUIPMENT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from xyequip.legacy import xy_equip_maker  # noqa: E402
from xyequip.paths import EquipmentPaths  # noqa: E402


class EquipmentNativeAndBatchTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        server = Path(self._temporary.name) / "Server"
        qfunction = server / "Mir200/Envir/Market_Def/QFunction-0.txt"
        qfunction.parent.mkdir(parents=True)
        qfunction.write_bytes(
            (
                "; XY_EQUIP_MAKER_POWER_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_ATTACK_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_BLAST_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_DROP_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_CORPSE_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_MONSTER_ABSORB_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_MONSTER_ABSORB_CAP_ANCHOR\r\n"
                "; XY_EXECUTION_LAB_CHANCE_ANCHOR\r\n"
                "; XY_EXECUTION_LAB_PVE_BONUS_ANCHOR\r\n"
                "; XY_EXECUTION_LAB_PVE_DURATION_ANCHOR\r\n"
                "MOV N$XY_PVE_Damage 0\r\n"
                "#IF\r\nLARGE N$XY_PVE_Extra 0\r\n"
            ).encode("gb18030")
        )
        attribute_panel = server / "Mir200/Envir/QuestDiary/玄渊功能/非常驻/属性总览/玄渊三属性按钮.txt"
        attribute_panel.parent.mkdir(parents=True)
        attribute_panel.write_bytes(
            (
                "; XY-EQUIPMENT-WASH-UI-END TEXT47_EXEC_CHANCE\r\n"
                "; XY-EQUIPMENT-WASH-UI-END TEXT48_EXEC_TIME\r\n"
                "; XY-EQUIPMENT-WASH-UI-END TEXT49_EXEC_DAMAGE\r\n"
            ).encode("gb18030")
        )
        xy_equip_maker.configure_paths(EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, server))

    def tearDown(self):
        self._temporary.cleanup()

    def write_minimal_xlsx(self, path: Path, rows: list[list[str]]) -> None:
        def col_name(index: int) -> str:
            index += 1
            out = ""
            while index:
                index, rem = divmod(index - 1, 26)
                out = chr(65 + rem) + out
            return out

        sheet = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
        sheet.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
        for row_index, row in enumerate(rows, 1):
            sheet.append(f'<row r="{row_index}">')
            for col_index, value in enumerate(row, 1):
                if value == "":
                    continue
                ref = f"{col_name(col_index - 1)}{row_index}"
                sheet.append(f'<c r="{ref}" t="inlineStr"><is><t>{html.escape(value, quote=False)}</t></is></c>')
            sheet.append("</row>")
        sheet.append("</sheetData></worksheet>")

        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                "</Types>",
            )
            zf.writestr(
                "_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                "</Relationships>",
            )
            zf.writestr(
                "xl/workbook.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="装备源表" sheetId="1" r:id="rId1"/></sheets></workbook>',
            )
            zf.writestr(
                "xl/_rels/workbook.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                "</Relationships>",
            )
            zf.writestr("xl/worksheets/sheet1.xml", "".join(sheet))

    def test_parse_spec_maps_native_element_fields_without_old_server_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "native_item.txt"
            spec_path.write_text(
                """[装备]
名称=单测头盔N
部位=头盔
防御=0-1

[原生属性]
暴击几率=10
攻击伤害=20
防止麻痹=30
致命伤害=40
杀怪经验倍数=50
""",
                encoding="utf-8",
            )

            spec = xy_equip_maker.parse_spec(spec_path)

            self.assertEqual(spec.template, "")
            self.assertEqual(spec.fields["StdMode"], 15)
            self.assertEqual(spec.fields["Ac"], 0)
            self.assertEqual(spec.fields["Ac2"], 1)
            self.assertEqual(spec.fields["Element"], 10)
            self.assertEqual(spec.fields["Element1"], 20)
            self.assertEqual(spec.fields["Element13"], 30)
            self.assertEqual(spec.fields["Element22"], 40)
            self.assertEqual(spec.fields["Element26"], 50)

    def parse_slot_spec(self, slot: str):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "slot.txt"
            spec_path.write_text(
                f"[装备]\n名称=部位单测\n部位={slot}\n",
                encoding="utf-8",
            )
            return xy_equip_maker.parse_spec(spec_path)

    def test_extended_slots_follow_existing_slot_to_stdmode_mapping(self):
        expected = {
            "照明物": 30,
            "左手镯": 26,
            "右手镯": 26,
            "左戒指": 22,
            "右戒指": 22,
            "护身符": 25,
            "宝石": 63,
            "军鼓": 65,
            "马牌": 28,
            "盾牌": 12,
            "灵玉": 90,
            "时装衣服": 66,
            "时装男衣服": 66,
            "时装女衣服": 67,
            "时装武器": 68,
            "时装项链": 75,
            "时装头盔": 78,
            "时装左手镯": 79,
            "时装右手镯": 79,
            "时装左戒指": 81,
            "时装右戒指": 81,
            "时装勋章": 83,
            "时装腰带": 84,
            "时装靴子": 86,
            "时装宝石": 88,
        }

        for slot, stdmode in expected.items():
            with self.subTest(slot=slot):
                spec = self.parse_slot_spec(slot)
                self.assertEqual(spec.fields["StdMode"], stdmode)
                self.assertNotIn("OverLap", spec.fields)
                self.assertNotIn("Expand1", spec.fields)

        self.assertIn("时装衣服", xy_equip_maker.ACTION_SLOTS)
        self.assertIn("时装武器", xy_equip_maker.ACTION_SLOTS)

    def test_jewelry_and_zodiac_slots_use_ring_stdmode_with_native_position_fields(self):
        expected = {
            "首饰盒": (22, 2, 0),
            "普通首饰盒3": (22, 2, 3),
            "生肖": (22, 4, 13),
            "普通生肖12": (22, 4, 12),
            "时装首饰盒6": (22, 8, 6),
            "时装生肖1": (22, 16, 1),
            "时装生肖盒12": (22, 16, 12),
        }

        for slot, values in expected.items():
            with self.subTest(slot=slot):
                spec = self.parse_slot_spec(slot)
                self.assertEqual(
                    (spec.fields["StdMode"], spec.fields["OverLap"], spec.fields["Expand1"]),
                    values,
                )

    def test_container_position_codes_are_not_misused_as_stdmode(self):
        modes = {
            self.parse_slot_spec("首饰盒6").fields["StdMode"],
            self.parse_slot_spec("生肖12").fields["StdMode"],
            self.parse_slot_spec("时装首饰盒6").fields["StdMode"],
            self.parse_slot_spec("时装生肖12").fields["StdMode"],
        }
        self.assertEqual(modes, {22})
        self.assertFalse(modes & set(range(30, 52)))
        self.assertFalse(modes & set(range(70, 92)))

    def test_parse_spec_keeps_explicit_zero_native_element_for_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "zero_native.txt"
            spec_path.write_text(
                """[装备]
名称=清零元素头盔
部位=头盔

[原生属性]
暴击几率=0
""",
                encoding="utf-8",
            )
            spec = xy_equip_maker.parse_spec(spec_path)
            self.assertIn("Element", spec.fields)
            self.assertEqual(spec.fields["Element"], 0)

    def test_weapon_attack_speed_uses_engine_offset_encoding(self):
        for workbook_value, expected_mac2 in ((0, 0), (10, 20), (11, 21)):
            with self.subTest(workbook_value=workbook_value):
                with tempfile.TemporaryDirectory() as tmp:
                    spec_path = Path(tmp) / "speed_weapon.txt"
                    spec_path.write_text(
                        "[装备]\n"
                        f"名称=单测攻速武器{workbook_value}\n"
                        "部位=武器\n"
                        f"攻击速度={workbook_value}\n",
                        encoding="utf-8",
                    )

                    spec = xy_equip_maker.parse_spec(spec_path)

                self.assertEqual(spec.fields["Mac2"], expected_mac2)

    def test_slot_attribute_contract_blocks_field_collisions(self):
        invalid_cases = (
            ("武器", "防御", "1-2"),
            ("时装武器", "魔御", "3-4"),
            ("项链", "防御", "1-2"),
            ("时装项链", "魔御", "3-4"),
            ("头盔", "幸运", "1"),
            ("戒指", "攻击速度", "1"),
            ("衣服", "强度", "1"),
        )
        for index, (slot, property_name, value) in enumerate(invalid_cases):
            with self.subTest(slot=slot, property_name=property_name):
                with tempfile.TemporaryDirectory() as tmp:
                    spec_path = Path(tmp) / f"invalid_{index}.txt"
                    spec_path.write_text(
                        f"[装备]\n名称=冲突装备{index}\n部位={slot}\n{property_name}={value}\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(xy_equip_maker.EquipMakerError, "部位=.*不允许填写"):
                        xy_equip_maker.parse_spec(spec_path)

    def test_slot_attribute_contract_allows_zero_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "zero_placeholders.txt"
            spec_path.write_text(
                "[装备]\n名称=零值占位头盔\n部位=头盔\n幸运=0\n攻击速度=0\n强度=0\n",
                encoding="utf-8",
            )
            spec = xy_equip_maker.parse_spec(spec_path)

        self.assertEqual(spec.fields["StdMode"], 15)

    def test_necklace_luck_uses_mac2_instead_of_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "lucky_necklace.txt"
            spec_path.write_text(
                "[装备]\n名称=幸运项链\n部位=项链\n幸运=7\n",
                encoding="utf-8",
            )
            spec = xy_equip_maker.parse_spec(spec_path)

        self.assertEqual(spec.fields["StdMode"], 19)
        self.assertEqual(spec.fields["Mac2"], 7)
        self.assertNotIn("Source", spec.fields)

    def test_update_necklace_luck_clear_targets_mac2_and_variant_is_blocked(self):
        from xyequip import update

        prepared = update.prepare_update({"名称": "幸运项链", "幸运": ""}, 19)
        self.assertEqual(prepared.base_zero_fields.get("Mac2"), 0)
        self.assertNotIn("Source", prepared.base_zero_fields)
        with self.assertRaisesRegex(update.EquipmentUpdateError, "不是幸运型"):
            update.prepare_update({"名称": "准确项链", "幸运": "1"}, 20)

    def test_fashion_weapon_keeps_original_weapon_field_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "fashion_weapon.txt"
            spec_path.write_text(
                """[装备]
名称=单测时装武器
部位=时装武器
幸运=7
准确=8
攻击速度=9
""",
                encoding="utf-8",
            )

            spec = xy_equip_maker.parse_spec(spec_path)

            self.assertEqual(spec.fields["StdMode"], 68)
            self.assertEqual(spec.fields["Ac"], 7)
            self.assertEqual(spec.fields["Ac2"], 8)
            self.assertEqual(spec.fields["Mac2"], 19)

    def test_update_weapon_blank_defence_does_not_clear_accuracy_or_attack_speed(self):
        from xyequip import update

        prepared = update.prepare_update(
            {
                "名称": "更新武器",
                "防御": "",
                "魔御": "",
                "幸运": "",
                "准确": "55",
                "攻击速度": "4",
            },
            5,
        )

        self.assertNotIn("Ac2", prepared.base_zero_fields)
        self.assertNotIn("Mac2", prepared.base_zero_fields)
        with tempfile.TemporaryDirectory() as tmp:
            spec = update.build_spec_from_prepared(prepared, Path(tmp) / "weapon-update.txt")
        spec.fields.update(prepared.base_zero_fields)
        self.assertEqual(spec.fields["Ac2"], 55)
        self.assertEqual(spec.fields["Mac2"], 14)

    def test_fixed_table_attrs_build_rule_and_group_lines(self):
        spec = xy_equip_maker.EquipmentSpec(
            name="固定表单测链N",
            fixed_attrs={"攻击加成": 11, "魔法加成": 12, "道术加成": 13},
        )

        rule = xy_equip_maker.fixed_rule_line(spec)
        group = xy_equip_maker.fixed_group_line(spec, 999)

        self.assertIn("固定表单测链N", rule)
        self.assertIn("固定表单测链N", group)
        self.assertEqual(rule.split("\t")[1].split()[12], "1")
        self.assertEqual(rule.split("\t")[1].split()[21], "1")
        self.assertEqual(rule.split("\t")[1].split()[26], "1")
        parts = group.split("\t")
        group2 = parts[5].split("|")
        self.assertEqual(group2[16], "11")
        self.assertEqual(group2[17], "12")
        self.assertEqual(group2[18], "13")

    def test_desc_line_uses_verified_mir_color_codes(self):
        spec = xy_equip_maker.EquipmentSpec(
            name="颜色单测",
            fixed_attrs={"攻击加成": 11},
            script_attrs={"神力倍攻": 22},
            desc_attrs={"攻击加成": 11, "神力倍攻": 22},
        )
        registry = {"properties": {"神力倍攻": {"label": "神力倍攻", "unit": "%"}}}

        line = xy_equip_maker.desc_line(spec, registry)

        self.assertIn("\\242/　玄渊固定装备", line)
        self.assertIn("\\254/　攻击加成+11%", line)
        self.assertIn("\\146/　[隐藏触发]：", line)
        self.assertIn("\\251/　神力倍攻+22%", line)
        self.assertNotIn("脚本触发", line)
        self.assertNotIn("\x1b[", line)

    def test_xlsx_remark_becomes_first_item_description_text(self):
        from xyequip.legacy import xy_batch_equip_maker  # noqa: E402

        text = xy_batch_equip_maker.row_to_equipment_txt({
            "名称": "备注测试刀",
            "部位": "武器",
            "备注": "一阶·战士·参照屠龙/雷霆系列",
        })
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "remark.txt"
            path.write_text(text, encoding="utf-8")
            spec = xy_equip_maker.parse_spec(path)

        line = xy_equip_maker.desc_line(spec, {"properties": {}})
        self.assertIn("\\242/　一阶·战士·参照屠龙/雷霆系列", line)
        self.assertNotIn("玄渊固定装备", line)

    def test_empty_remark_keeps_default_item_description(self):
        spec = xy_equip_maker.EquipmentSpec(name="默认备注刀")
        self.assertIn("\\242/　玄渊固定装备", xy_equip_maker.desc_line(spec, {"properties": {}}))

    def test_long_remark_wraps_by_display_width_and_repeats_color(self):
        remark = (
            "断桨弩手专属。弩手把断裂的船桨削成骨节，串上每一名未能登船者的铜牌。"
            "传说弩弦突然变重时，说明海雾里又少了一个归乡的人。"
        )
        lines = xy_equip_maker.wrap_item_remark(remark)

        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual("".join(lines), remark)
        self.assertTrue(all(line[0] not in xy_equip_maker.ITEM_REMARK_FORBIDDEN_LINE_START for line in lines))
        self.assertTrue(all(line[-1] not in xy_equip_maker.ITEM_REMARK_FORBIDDEN_LINE_END for line in lines))

        spec = xy_equip_maker.EquipmentSpec(name="自动断行弩", remark=remark)
        desc = xy_equip_maker.desc_line(spec, {"properties": {}})
        self.assertEqual(desc.count("\\242/　"), len(lines))
        self.assertNotIn("\r", desc)
        self.assertNotIn("\n", desc)

    def test_remark_wrap_uses_mixed_character_display_width(self):
        lines = xy_equip_maker.wrap_item_remark("ABCD玄渊EFGH测试IJKL", max_columns=12)

        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), "ABCD玄渊EFGH测试IJKL")
        self.assertTrue(all(xy_equip_maker.item_remark_display_width(line) <= 12 for line in lines))

    def test_batch_csv_row_converts_to_single_equipment_txt(self):
        from xyequip.legacy import xy_batch_equip_maker  # noqa: E402

        row = {
            "名称": "批量头盔N",
            "部位": "头盔",
            "来源编号": "4460",
            "防御": "0-1",
            "暴击几率": "10",
            "攻击加成": "11",
            "魔法加成": "12",
            "道术加成": "13",
            "HP百分比": "14",
            "神力倍攻": "20",
            "伤害系数": "25",
            "对怪伤害吸收": "30",
            "伤害吸收上限": "5",
            "爆率": "30",
            "最大爆率": "40",
            "首刀斩杀": "10",
            "尾刀斩杀": "30",
            "鞭尸概率": "15",
            "备注": "剧情说明文本",
        }

        text = xy_batch_equip_maker.row_to_equipment_txt(row)

        self.assertIn("名称=批量头盔N", text)
        self.assertIn("部位=头盔", text)
        self.assertNotIn("模板=", text)
        self.assertIn("[图标来源]", text)
        self.assertIn("来源编号=4460", text)
        self.assertIn("[原生属性]", text)
        self.assertIn("暴击几率=10", text)
        self.assertIn("[显示属性]", text)
        self.assertIn("暴击几率=10", text.split("[显示属性]", 1)[1])
        self.assertIn("[固定表属性]", text)
        self.assertIn("攻击加成=11", text)
        self.assertIn("魔法加成=12", text)
        self.assertIn("道术加成=13", text)
        self.assertIn("[预留属性]", text)
        self.assertIn("HP百分比=14", text)
        self.assertIn("[特殊属性]", text)
        self.assertIn("神力倍攻=20", text)
        self.assertIn("伤害系数=25", text)
        self.assertIn("对怪伤害吸收=30", text)
        self.assertIn("伤害吸收上限=5", text)
        self.assertIn("爆率=30", text)
        self.assertIn("最大爆率=40", text)
        self.assertIn("首刀斩杀=10", text)
        self.assertIn("尾刀斩杀=30", text)
        self.assertIn("鞭尸概率=15", text)
        self.assertIn("[备注]", text)
        self.assertIn("说明=剧情说明文本", text)

    def test_batch_xlsx_header_鞭尸_maps_to_registered_script_property(self):
        from xyequip.legacy import xy_batch_equip_maker  # noqa: E402

        text = xy_batch_equip_maker.row_to_equipment_txt(
            {"名称": "鞭尸表头兼容甲", "部位": "衣服", "鞭尸": "100"}
        )

        self.assertIn("[特殊属性]", text)
        self.assertIn("鞭尸概率=100", text)

    def test_batch_reads_xlsx_rows(self):
        from xyequip.legacy import xy_batch_equip_maker  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "items.xlsx"
            self.write_minimal_xlsx(
                xlsx_path,
                [
                    ["名称", "部位", "防御", "神力倍攻", "备注"],
                    ["XLSX头盔N", "头盔", "0-1", "20", "xlsx读取"],
                ],
            )

            rows = xy_batch_equip_maker.read_table_rows(xlsx_path)
            text = xy_batch_equip_maker.row_to_equipment_txt(rows[0])

        self.assertEqual(rows[0]["名称"], "XLSX头盔N")
        self.assertIn("名称=XLSX头盔N", text)
        self.assertIn("神力倍攻=20", text)
        self.assertIn("说明=xlsx读取", text)

    def test_drop_rate_script_properties_build_qfunction_text(self):
        spec = xy_equip_maker.EquipmentSpec(
            name="单测爆率装备N",
            script_attrs={"爆率": 30, "最大爆率": 40},
        )

        text = xy_equip_maker.build_qfunction_text(spec, xy_equip_maker.load_script_props())

        self.assertIsNotNone(text)
        self.assertIn("; XY_EQUIP_MAKER_DROP_ANCHOR", text)
        self.assertIn("CHECKITEMW 单测爆率装备N 1", text)
        self.assertIn("INC N$XY_最终爆率 30", text)
        self.assertIn("INC N$XY_最大爆率 40", text)

    def test_damage_coefficient_builds_runtime_branch_and_display_mapping(self):
        spec = xy_equip_maker.EquipmentSpec(
            name="单测伤害系数刀N",
            script_attrs={"伤害系数": 25},
        )

        text = xy_equip_maker.build_qfunction_text(spec, xy_equip_maker.load_script_props())

        self.assertIsNotNone(text)
        self.assertIn("; XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR", text)
        self.assertIn("CHECKITEMW 单测伤害系数刀N 1", text)
        self.assertIn("INC N$XY_RT_DamageCoeff 25", text)
        self.assertIn("SetCustomItemAbil -1 0 1 53", text)
        self.assertIn("SetCustomItemValue -1 0 = 25", text)

    def test_monster_absorb_properties_build_two_anchors_and_static_descriptions(self):
        spec = xy_equip_maker.EquipmentSpec(
            name="单测怪伤吸收甲N",
            script_attrs={"对怪伤害吸收": 30, "伤害吸收上限": 5},
            desc_attrs={"对怪伤害吸收": 30, "伤害吸收上限": 5},
        )

        text = xy_equip_maker.build_qfunction_text(spec, xy_equip_maker.load_script_props())

        self.assertIsNotNone(text)
        self.assertIn("; XY_EQUIP_MAKER_MONSTER_ABSORB_ANCHOR", text)
        self.assertIn("; XY_EQUIP_MAKER_MONSTER_ABSORB_CAP_ANCHOR", text)
        self.assertIn("CHECKITEMW 单测怪伤吸收甲N 1", text)
        self.assertIn("INC N$XY_MDA_Raw 30", text)
        self.assertIn("INC N$XY_MDA_CapBonus 5", text)
        self.assertNotIn("SetCustomItemAbil -1 0 1 54", text)
        self.assertNotIn("SetCustomItemAbil -1 1 1 55", text)
        description = xy_equip_maker.desc_line(spec, xy_equip_maker.load_script_props())
        self.assertIn("对怪伤害吸收+30%", description)
        self.assertIn("伤害吸收上限+5%", description)

    def test_first_tail_and_corpse_script_properties_build_qfunction_text(self):
        spec = xy_equip_maker.EquipmentSpec(
            name="\u5355\u6d4b\u65a9\u6740\u88c5\u5907N",
            script_attrs={"\u9996\u5200\u65a9\u6740": 10, "\u5c3e\u5200\u65a9\u6740": 30, "\u97ad\u5c38\u6982\u7387": 15},
        )

        text = xy_equip_maker.build_qfunction_text(spec, xy_equip_maker.load_script_props())

        self.assertIsNotNone(text)
        self.assertIn("; XY_EQUIP_MAKER_ATTACK_ANCHOR", text)
        self.assertIn("; XY_EQUIP_MAKER_CORPSE_ANCHOR", text)
        self.assertIn("CHECKITEMW \u5355\u6d4b\u65a9\u6740\u88c5\u5907N 1", text)
        self.assertIn("INC N$XY_FirstKillRate 10", text)
        self.assertIn("INC N$XY_TailKillRate 30", text)
        self.assertIn("; XY_EQUIP_MAKER_KILL_RESET", text)
        self.assertIn("; XY_EQUIP_MAKER_KILL_FINAL", text)
        self.assertIn("M.CheckHpPer < <$STR(N$XY_TailKillRate)>", text)
        self.assertIn("M.AddhpPer - <$STR(N$XY_FirstKillRate)>", text)
        self.assertIn("INC N$XY_CorpseRate 15", text)

    def test_execution_properties_build_matching_attribute_panel_branches(self):
        spec = xy_equip_maker.EquipmentSpec(
            name="单测处决同步刀N",
            script_attrs={"处决概率": 2, "处决倍率": 3, "处决时间": 1},
        )

        texts = xy_equip_maker.build_script_texts(spec, xy_equip_maker.load_script_props())

        panel = texts["attribute_panel"]
        self.assertIn("; XY-ATTR-PANEL 单测处决同步刀N: 处决概率+2%", panel)
        self.assertIn("INC N$XY_UI_C_Value02 2", panel)
        self.assertIn("; XY-ATTR-PANEL 单测处决同步刀N: PVE处决额外伤害+3%", panel)
        self.assertIn("INC N$XY_UI_C_Value04 3", panel)
        self.assertIn("; XY-ATTR-PANEL 单测处决同步刀N: PVE处决持续时间+1秒", panel)
        self.assertIn("INC N$XY_UI_C_Value03 1", panel)

    def test_qfunction_requires_only_anchors_used_by_current_item(self):
        xy_equip_maker.QFUNCTION.write_bytes(
            (
                "; XY_EQUIP_MAKER_POWER_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_ATTACK_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_BLAST_ANCHOR\r\n"
                "; XY_EQUIP_MAKER_DROP_ANCHOR\r\n"
                "MOV N$XY_PVE_Damage 0\r\n"
                "#IF\r\nLARGE N$XY_PVE_Extra 0\r\n"
            ).encode("gb18030")
        )
        spec = xy_equip_maker.EquipmentSpec(
            name="无鞭尸装备",
            script_attrs={
                "神力倍攻": 20, "打怪伤害": 30, "暴击伤害": 40,
                "固定切割": 5555, "爆率": 50, "最大爆率": 15,
                "首刀斩杀": 15, "尾刀斩杀": 60,
            },
        )
        text = xy_equip_maker.build_qfunction_text(spec, xy_equip_maker.load_script_props())
        self.assertIsNotNone(text)
        self.assertNotIn("XY_EQUIP_MAKER_CORPSE_ANCHOR", text)


if __name__ == "__main__":
    unittest.main()
