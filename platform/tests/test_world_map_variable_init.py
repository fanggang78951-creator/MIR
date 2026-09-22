import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packages" / "candidate" / "xy.ui.world-map" / "manifest.json"


class WorldMapVariableInitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_world_map_declares_each_human_variable_once_at_login(self):
        self.assertEqual(self.manifest["version"], "1.0.0-candidate.21")
        managed = next(
            op for op in self.manifest["operations"]
            if op["type"] == "managed_block" and op["target"].endswith("QFunction-0.txt")
        )["content"]
        login_hook = next(
            op for op in self.manifest["operations"]
            if op["type"] == "event_hook"
            and op["target"].endswith("QManage.txt")
            and op["label"] == "MAIN1"
        )["content"]
        self.assertNotIn("VAR Integer HUMAN XY_WORLD_MAP_", managed)
        declared = re.findall(r"^VAR Integer HUMAN (XY_WORLD_MAP_[A-Z_]+_ACCESS)$", login_hook, re.M)
        loaded = re.findall(r"^LOADVAR HUMAN (XY_WORLD_MAP_[A-Z_]+_ACCESS) ", login_hook, re.M)
        self.assertEqual(len(declared), 13)
        self.assertEqual(len(set(declared)), 13)
        self.assertEqual(set(loaded), set(declared))
        paths = re.findall(
            r"^LOADVAR HUMAN XY_WORLD_MAP_[A-Z_]+_ACCESS (.+_Access\.txt)$",
            login_hook,
            re.M,
        )
        self.assertEqual(len(paths), 13)
        self.assertTrue(all(path.startswith(r"..\Market_Def\XY_WorldMap_") for path in paths))

    def test_authorization_and_teleport_chain_remains_in_managed_block(self):
        managed = next(
            op for op in self.manifest["operations"]
            if op["type"] == "managed_block" and op["target"].endswith("QFunction-0.txt")
        )["content"]
        for token in (
            "CHECKVAR HUMAN XY_WORLD_MAP_NMGF_MAIN_ACCESS > 0",
            "CALCVAR HUMAN XY_WORLD_MAP_NMGF_MAIN_ACCESS = 1",
            "SAVEVAR HUMAN XY_WORLD_MAP_NMGF_MAIN_ACCESS XY_WorldMap_NMGF_MAIN_Access.txt",
            "MAPMOVE XY_NMGF_MAIN 100 76",
        ):
            self.assertIn(token, managed)


if __name__ == "__main__":
    unittest.main()
