from __future__ import annotations

import json
import sys
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


EQUIPMENT_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = EQUIPMENT_ROOT.parent
SOURCE_SNAPSHOT = EQUIPMENT_ROOT / "legacy_archive" / "source_snapshot_20260710"
OLD_TOOL = SOURCE_SNAPSHOT / "xy_equip_maker"
OLD_TABLES = SOURCE_SNAPSHOT / "装备源表"


def workbook_headers(path: Path) -> list[str]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", ns):
                shared.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        row = sheet.find(".//m:sheetData/m:row", ns)
        assert row is not None
        values: list[str] = []
        for cell in row.findall("m:c", ns):
            kind = cell.attrib.get("t")
            value = cell.find("m:v", ns)
            if kind == "inlineStr":
                values.append("".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t")))
            elif kind == "s" and value is not None:
                values.append(shared[int(value.text or "0")])
            else:
                values.append(value.text if value is not None and value.text else "")
        while values and values[-1] == "":
            values.pop()
        return values


class LegacyContractTests(unittest.TestCase):
    def test_required_source_artifacts_are_registered(self):
        inventory = json.loads((EQUIPMENT_ROOT / "migration/source_inventory.json").read_text(encoding="utf-8"))
        by_name = {Path(item["source_path"]).name: item for item in inventory["artifacts"]}
        self.assertTrue(by_name["script_properties.json"]["sha256"])
        self.assertTrue(by_name["XuanYuanItems.xlsx"]["sha256"])
        self.assertEqual(inventory["output_history"]["migration_state"], "moved_with_tool_archive")
        self.assertTrue(Path(inventory["output_history"]["migrated_to"]).is_dir())

    def test_xlsx_header_contract_is_frozen(self):
        contract = json.loads((EQUIPMENT_ROOT / "evidence/baseline/golden_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(
            workbook_headers(OLD_TABLES / "XuanYuanItems.xlsx"),
            contract["xlsx_headers"],
        )

    def test_current_workbooks_put_fixed_bonus_then_platform_properties_after_attack_magic_tao(self):
        fixed_bonus_headers = ["攻击加成", "魔法加成", "道术加成"]
        script_headers = [
            "神力倍攻", "伤害系数", "打怪伤害", "暴击伤害", "固定切割", "爆率", "最大爆率",
            "首刀斩杀", "尾刀斩杀", "鞭尸", "处决概率", "韧性", "处决倍率", "处决时间",
            "对怪伤害吸收", "伤害吸收上限", "吸血", "每秒回血", "回收增加",
        ]
        generated = workbook_headers(EQUIPMENT_ROOT / "templates/XuanYuanItems.xlsx")
        self.assertEqual(generated[:6], ["名称", "部位", "来源编号", "攻击", "魔法", "道术"])
        self.assertEqual(generated[6:9], fixed_bonus_headers)
        self.assertEqual(generated[9:28], script_headers)
        self.assertEqual(generated[28:30], ["暴击几率", "攻击伤害"])
        self.assertEqual(generated[-2:], ["备注", "悬浮分类"])
        self.assertIn("部位", generated)
        self.assertIn("来源编号", generated)
        self.assertNotIn("持久", generated)

    def test_property_registry_preserves_legacy_entries_and_allows_managed_extensions(self):
        source = json.loads((OLD_TOOL / "script_properties.json").read_text(encoding="utf-8"))
        migrated = json.loads((EQUIPMENT_ROOT / "profiles/script_properties.json").read_text(encoding="utf-8"))
        self.assertEqual(source["version"], migrated["version"])
        self.assertEqual(source["encoding"], migrated["encoding"])
        legacy_names = list(source["properties"])
        self.assertEqual(legacy_names, list(migrated["properties"])[:len(legacy_names)])
        for name, legacy in source["properties"].items():
            current = migrated["properties"][name]
            self.assertEqual(legacy["label"], current["label"])
            self.assertEqual(legacy["unit"], current["unit"])
            self.assertEqual(legacy["outlets"], current["outlets"][:len(legacy["outlets"])])
            self.assertIn("display", current)
        self.assertEqual(
            set(migrated["properties"]) - set(source["properties"]),
            {
                "处决概率", "韧性", "处决倍率", "处决时间", "伤害系数",
                "对怪伤害吸收", "伤害吸收上限", "吸血", "每秒回血", "回收增加", "攻速突破", "等级增加",
            },
        )

        damage = migrated["properties"]["伤害系数"]
        self.assertEqual(damage["display"]["bind_type"], 53)
        self.assertEqual(
            damage["outlets"][0]["anchor"],
            "; XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR",
        )
        self.assertIn("INC N$XY_RT_DamageCoeff {value}", damage["outlets"][0]["block"])

        life_steal = migrated["properties"]["吸血"]
        self.assertEqual(life_steal["display"]["bind_type"], 54)
        self.assertEqual(life_steal["outlets"][0]["anchor"], "; XY_EQUIP_MAKER_LIFESTEAL_ANCHOR")
        self.assertIn("INC N$XY_SUS_LifeSteal {value}", life_steal["outlets"][0]["block"])

        hp_regen = migrated["properties"]["每秒回血"]
        self.assertEqual(hp_regen["display"]["bind_type"], 55)
        self.assertEqual(len(hp_regen["outlets"]), 2)
        self.assertEqual(
            hp_regen["outlets"][0]["anchor"],
            "; XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR",
        )
        self.assertIn("MOV N$XY_SUS_HPActive 1", hp_regen["outlets"][0]["block"])
        self.assertEqual(hp_regen["outlets"][1]["target"], "qmanage")
        self.assertEqual(
            hp_regen["outlets"][1]["anchor"],
            "; XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR",
        )
        self.assertIn("HumanHP + {value}", hp_regen["outlets"][1]["block"])

        recycle_bonus = migrated["properties"]["回收增加"]
        self.assertEqual(recycle_bonus["display"]["mode"], "item_desc_only")
        self.assertEqual(recycle_bonus["minimum"], 0)
        self.assertEqual(
            [outlet["target"] for outlet in recycle_bonus["outlets"]],
            ["qfunction", "qmanage"],
        )
        self.assertTrue(all("N$XY_RecycleEquipBonus" in outlet["block"][-1] for outlet in recycle_bonus["outlets"]))

    def test_failed_runtime_properties_have_attack_refresh_outlets(self):
        registry = json.loads((EQUIPMENT_ROOT / "profiles/script_properties.json").read_text(encoding="utf-8"))
        expected = {
            "神力倍攻": ("XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR", "N$XY_RT_Power"),
            "暴击伤害": ("XY_EQUIP_MAKER_RUNTIME_BLAST_ANCHOR", "N$XY_RT_Blast"),
            "爆率": ("XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR", "N$XY_RT_Drop"),
            "最大爆率": ("XY_EQUIP_MAKER_RUNTIME_DROP_MAX_ANCHOR", "N$XY_RT_DropMax"),
        }
        for name, (anchor, variable) in expected.items():
            outlets = registry["properties"][name]["outlets"]
            runtime = [item for item in outlets if item["name"].startswith("runtime-")]
            self.assertEqual(len(runtime), 1, name)
            self.assertEqual(runtime[0]["anchor"], f"; {anchor}")
            self.assertIn(f"INC {variable} {{value}}", runtime[0]["block"])

    def test_source_hash_file_covers_inventory(self):
        inventory = json.loads((EQUIPMENT_ROOT / "migration/source_inventory.json").read_text(encoding="utf-8"))
        hashes = json.loads((EQUIPMENT_ROOT / "evidence/baseline/source_hashes.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {item["source_path"]: item["sha256"] for item in inventory["artifacts"]},
            hashes,
        )

    def test_runtime_scaffold_uses_verified_drop_multiplier_formula(self):
        source = (EQUIPMENT_ROOT / "src/xyequip/legacy/xy_equip_maker.py").read_text(encoding="utf-8")
        self.assertIn('"MOV N$XY_RT_DropMax 100\\r\\n"', source)
        self.assertIn('"MOV N$XY_RT_DropFinal 100\\r\\n"', source)
        self.assertIn(
            '"CalcPercent <$STR(N$XY_RT_Drop)> <$STR(N$XY_RT_DropMax)> N$XY_RT_DropFinal\\r\\n"',
            source,
        )
        self.assertIn('"KILLMONBURSTRATE <$STR(N$XY_RT_DropFinal)>\\r\\n"', source)
        self.assertNotIn('"MOV N$XY_RT_DropMax 1000\\r\\n"', source)
        self.assertNotIn('"LARGE N$XY_RT_Drop <$STR(N$XY_RT_DropMax)>\\r\\n"', source)


if __name__ == "__main__":
    unittest.main()
