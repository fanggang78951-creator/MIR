from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path


EQUIPMENT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EQUIPMENT_ROOT / "src"
OLD_ROOT = EQUIPMENT_ROOT / "legacy_archive" / "source_snapshot_20260710" / "xy_equip_maker"


def load_old_core():
    spec = importlib.util.spec_from_file_location("xy_equip_maker_source", OLD_ROOT / "xy_equip_maker.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MigratedCoreParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SOURCE_ROOT))
        cls.old = load_old_core()
        from xyequip.legacy import xy_equip_maker as migrated_core
        from xyequip.legacy import xy_batch_equip_maker as migrated_batch

        cls.migrated = migrated_core
        cls.batch = migrated_batch

    def test_registry_keeps_legacy_effect_entries_before_managed_extensions(self):
        source = json.loads((OLD_ROOT / "script_properties.json").read_text(encoding="utf-8"))
        target = json.loads((EQUIPMENT_ROOT / "profiles/script_properties.json").read_text(encoding="utf-8"))
        legacy_names = list(source["properties"])
        self.assertEqual(legacy_names, list(target["properties"])[:len(legacy_names)])
        for name, legacy in source["properties"].items():
            current = target["properties"][name]
            self.assertEqual(legacy["label"], current["label"])
            self.assertEqual(legacy["unit"], current["unit"])
            self.assertEqual(legacy["outlets"], current["outlets"][:len(legacy["outlets"])])
            self.assertIn("display", current)
        self.assertEqual(
            set(target["properties"]) - set(source["properties"]),
            {
                "处决概率", "韧性", "处决倍率", "处决时间", "伤害系数",
                "对怪伤害吸收", "伤害吸收上限", "吸血", "每秒回血", "回收增加", "攻速突破", "等级增加",
            },
        )

    def test_parse_spec_preserves_legacy_fields_except_target_selected_template(self):
        text = """[装备]
名称=迁移契约头盔
部位=头盔
防御=0-2
HP=7

[原生属性]
暴击几率=10
致命伤害=40

[固定表属性]
攻击加成=11

[特殊属性]
神力倍攻=22
爆率=30
最大爆率=40
首刀斩杀=10
尾刀斩杀=30
鞭尸概率=15
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "item.txt"
            path.write_text(text, encoding="utf-8")
            old_spec = asdict(self.old.parse_spec(path))
            migrated_spec = asdict(self.migrated.parse_spec(path))
            self.assertEqual(old_spec.pop("template"), "青铜头盔")
            self.assertEqual(migrated_spec.pop("template"), "")
            self.assertEqual(migrated_spec.pop("base_template_kind"), "")
            self.assertEqual(migrated_spec.pop("base_template_label"), "")
            self.assertEqual(migrated_spec.pop("remark"), "")
            self.assertEqual(old_spec, migrated_spec)

    def test_batch_text_matches_legacy_conversion_contract(self):
        row = {
            "名称": "迁移批量头盔",
            "部位": "头盔",
            "防御": "0-1",
            "暴击几率": "10",
            "攻击加成": "11",
            "神力倍攻": "20",
            "爆率": "30",
            "最大爆率": "40",
            "首刀斩杀": "10",
            "尾刀斩杀": "30",
            "鞭尸概率": "15",
        }
        self.assertIn("名称=迁移批量头盔", self.batch.row_to_equipment_txt(row))
        self.assertIn("神力倍攻=20", self.batch.row_to_equipment_txt(row))


if __name__ == "__main__":
    unittest.main()
