from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xyequip.legacy import xy_equip_maker


PACKAGE_MARKER = "; XY-LB-V1-BEGIN"
ANCHOR = "; XY_EQUIP_MAKER_LEVEL_BONUS_ANCHOR"


class EquipmentLevelBonusPropertyTests(unittest.TestCase):
    def setUp(self):
        self.old_qfunction = xy_equip_maker.QFUNCTION
        self.old_qmanage = xy_equip_maker.QMANAGE

    def tearDown(self):
        xy_equip_maker.QFUNCTION = self.old_qfunction
        xy_equip_maker.QMANAGE = self.old_qmanage

    def _prepare(self, base: Path, installed: bool = True) -> None:
        xy_equip_maker.QFUNCTION = base / "QFunction-0.txt"
        xy_equip_maker.QMANAGE = base / "QManage.txt"
        marker = PACKAGE_MARKER + "\r\n; XY-LB-V1-END\r\n" if installed else ""
        xy_equip_maker.QFUNCTION.write_bytes((
            marker
            + ANCHOR + "\r\n"
            + "; XY_EQUIP_MAKER_BLAST_ANCHOR\r\n"
            + "; XY_EQUIP_MAKER_RUNTIME_BLAST_ANCHOR\r\n"
            + "[@AddBag]\r\n#ACT\r\n"
        ).encode("gb18030"))
        xy_equip_maker.QMANAGE.write_bytes(b"")

    def test_registry_exposes_0_to_10_dependency_and_textvar41(self):
        properties = xy_equip_maker.load_script_props()["properties"]
        self.assertIn("等级增加", properties)
        meta = properties["等级增加"]
        self.assertEqual((meta["minimum"], meta["maximum"]), (0, 10))
        self.assertEqual(meta["display"]["bind_type"], 60)
        self.assertEqual(meta["display"]["textvar_line"], 41)
        self.assertEqual(meta["requires"][0]["package"], "xy.resident.equipment-level-bonus")

    def test_0_1_10_are_allowed_but_11_is_rejected(self):
        registry = xy_equip_maker.load_script_props()
        self.assertIn("等级增加", registry["properties"])
        for value in (0, 1, 10):
            entries = xy_equip_maker.script_display_entries(
                xy_equip_maker.EquipmentSpec(
                    name=f"等级装备{value}", script_attrs={"等级增加": value}
                ),
                registry,
            )
            self.assertEqual(entries[0][1], value)
        with self.assertRaisesRegex(xy_equip_maker.EquipMakerError, "不能大于 10"):
            xy_equip_maker.script_display_entries(
                xy_equip_maker.EquipmentSpec(name="等级装备11", script_attrs={"等级增加": 11}),
                registry,
            )

    def test_missing_resident_dependency_blocks_instead_of_display_only_output(self):
        properties = xy_equip_maker.load_script_props()["properties"]
        self.assertIn("等级增加", properties)
        with tempfile.TemporaryDirectory() as td:
            self._prepare(Path(td), installed=False)
            with self.assertRaisesRegex(
                xy_equip_maker.EquipMakerError, "xy.resident.equipment-level-bonus"
            ):
                xy_equip_maker.build_script_texts(
                    xy_equip_maker.EquipmentSpec(
                        name="缺包等级剑", script_attrs={"等级增加": 1}
                    ),
                    xy_equip_maker.load_script_props(),
                )

    def test_multiple_fixed_items_accumulate_and_value_ex_uses_textvar41(self):
        properties = xy_equip_maker.load_script_props()["properties"]
        self.assertIn("等级增加", properties)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._prepare(base)
            registry = xy_equip_maker.load_script_props()
            first = xy_equip_maker.build_script_texts(
                xy_equip_maker.EquipmentSpec(name="等级之刃A", script_attrs={"等级增加": 3}),
                registry,
            )
            xy_equip_maker.write_script_texts(first)
            second = xy_equip_maker.build_script_texts(
                xy_equip_maker.EquipmentSpec(name="等级之刃B", script_attrs={"等级增加": 10}),
                registry,
            )["qfunction"]
        self.assertIn("INC N$XY_LB_FIXED 3", second)
        self.assertIn("INC N$XY_LB_FIXED 10", second)
        self.assertEqual(second.count(ANCHOR), 1)
        self.assertIn("SetCustomItemValueEx -1 0 = 41 10 0", second)


if __name__ == "__main__":
    unittest.main()
