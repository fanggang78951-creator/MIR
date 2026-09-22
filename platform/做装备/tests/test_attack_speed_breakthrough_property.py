from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xyequip.legacy import xy_equip_maker


PACKAGE_MARKER = "; XY-AS-CAP-V1-BEGIN"
ANCHOR = "; XY_EQUIP_MAKER_ATTACK_SPEED_BREAK_ANCHOR"


class AttackSpeedBreakthroughPropertyTests(unittest.TestCase):
    def setUp(self):
        self.old_qfunction = xy_equip_maker.QFUNCTION
        self.old_qmanage = xy_equip_maker.QMANAGE

    def tearDown(self):
        xy_equip_maker.QFUNCTION = self.old_qfunction
        xy_equip_maker.QMANAGE = self.old_qmanage

    def _prepare(self, base: Path, installed: bool = True):
        xy_equip_maker.QFUNCTION = base / "QFunction-0.txt"
        xy_equip_maker.QMANAGE = base / "QManage.txt"
        prefix = PACKAGE_MARKER + "\r\n" if installed else ""
        xy_equip_maker.QFUNCTION.write_bytes((prefix + ("; XY-AS-CAP-V1-END\r\n" if installed else "") + ANCHOR + "\r\n; XY_EQUIP_MAKER_BLAST_ANCHOR\r\n; XY_EQUIP_MAKER_RUNTIME_BLAST_ANCHOR\r\n[@AddBag]\r\n#ACT\r\n").encode("gb18030"))
        xy_equip_maker.QMANAGE.write_bytes(b"")

    def test_registry_exposes_range_dependency_and_textvar_display(self):
        meta = xy_equip_maker.load_script_props()["properties"]["攻速突破"]
        self.assertEqual(meta["minimum"], 0)
        self.assertEqual(meta["maximum"], 30)
        self.assertEqual(meta["display"]["bind_type"], 60)
        self.assertEqual(meta["display"]["textvar_line"], 40)
        self.assertEqual(meta["requires"][0]["package"], "xy.optional.attack-speed-breakthrough")

    def test_0_20_30_are_allowed_but_31_is_rejected(self):
        registry = xy_equip_maker.load_script_props()
        for value in (0, 20, 30):
            entries = xy_equip_maker.script_display_entries(
                xy_equip_maker.EquipmentSpec(name=f"攻速装备{value}", script_attrs={"攻速突破": value}), registry
            )
            self.assertEqual(entries[0][1], value)
        with self.assertRaisesRegex(xy_equip_maker.EquipMakerError, "不能大于 30"):
            xy_equip_maker.script_display_entries(
                xy_equip_maker.EquipmentSpec(name="攻速装备31", script_attrs={"攻速突破": 31}), registry
            )

    def test_missing_package_dependency_blocks_instead_of_text_only_output(self):
        with tempfile.TemporaryDirectory() as td:
            self._prepare(Path(td), installed=False)
            with self.assertRaisesRegex(xy_equip_maker.EquipMakerError, "xy.optional.attack-speed-breakthrough") as caught:
                xy_equip_maker.build_script_texts(
                    xy_equip_maker.EquipmentSpec(name="缺包之刃", script_attrs={"攻速突破": 20}),
                    xy_equip_maker.load_script_props(),
                )
            message = str(caught.exception)
            self.assertIn("继续使用09_装备批量生成.xlsx", message)
            self.assertIn("无需改用依赖配置表", message)

    def test_multiple_items_accumulate_under_one_anchor_and_write_textvar_triplet(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._prepare(base)
            registry = xy_equip_maker.load_script_props()
            first = xy_equip_maker.build_script_texts(
                xy_equip_maker.EquipmentSpec(name="突破之刃A", script_attrs={"攻速突破": 20}), registry
            )
            xy_equip_maker.write_script_texts(first)
            second = xy_equip_maker.build_script_texts(
                xy_equip_maker.EquipmentSpec(name="突破之刃B", script_attrs={"攻速突破": 30}), registry
            )["qfunction"]
        self.assertIn("INC N$XY_AS_FIXED_BREAK 20", second)
        self.assertIn("INC N$XY_AS_FIXED_BREAK 30", second)
        self.assertEqual(second.count(ANCHOR), 1)
        self.assertIn("SetCustomItemValueEx -1 0 = 40 30 0", second)

    def test_existing_display_mode_regression_still_uses_setcustomitemvalue(self):
        with tempfile.TemporaryDirectory() as td:
            self._prepare(Path(td))
            text = xy_equip_maker.build_script_texts(
                xy_equip_maker.EquipmentSpec(name="旧暴击装备", script_attrs={"暴击伤害": 9}),
                xy_equip_maker.load_script_props(),
            )["qfunction"]
        self.assertIn("SetCustomItemValue -1 0 = 9", text)
        self.assertNotIn("SetCustomItemValueEx -1 0", text)


if __name__ == "__main__":
    unittest.main()
