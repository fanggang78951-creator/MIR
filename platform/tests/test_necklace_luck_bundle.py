from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from xydp.npc_bundle import load_necklace_luck_bundle


ROOT = Path(r"D:\codex临时工作区\elden-npc-v21") / (
    "艾尔登法环_全NPC平台填写_V2.1_20260920-normalized"
)
PLATFORM = Path(r"E:\XuanYuanDevPlatform")


class NecklaceLuckBundleTests(unittest.TestCase):
    def test_bundle_uses_the_existing_generator_with_assigned_coordinates_and_paid_tiers(self):
        module, base, tiers = load_necklace_luck_bundle(
            PLATFORM,
            ROOT / "00_全局系统" / "17_项链幸运强化.xlsx",
            x=92,
            y=88,
        )

        self.assertEqual((base["坐标X"], base["坐标Y"]), ("92", "88"))
        self.assertEqual(len(tiers), 8)
        npc = module.build_package_npc(tiers)
        self.assertIn("黄金树芽×1，元宝×2000", npc)
        self.assertNotIn("测试人物清零", npc)
        self.assertNotIn("XY_VERIFY", npc)

    def test_dynamic_merchant_line_replaces_only_the_managed_npc(self):
        module, base, _tiers = load_necklace_luck_bundle(
            PLATFORM,
            ROOT / "00_全局系统" / "17_项链幸运强化.xlsx",
            x=92,
            y=88,
        )
        old = "玄渊实验室/项链幸运\tXY_NMGF_MAIN\t102\t75\t项链幸运\t0\t220\t0\r\n"
        changed = module.ensure_merchant(old, "\r\n", module._npc_line(base))

        self.assertIn("\t92\t88\t", changed)
        self.assertNotIn("\t102\t75\t", changed)


if __name__ == "__main__":
    unittest.main()
