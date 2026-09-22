from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


EQUIPMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EQUIPMENT_ROOT / "src"))


class EquipmentPathTests(unittest.TestCase):
    def test_default_target_is_mirserver(self):
        from xyequip.paths import EquipmentPaths

        paths = EquipmentPaths.default(EQUIPMENT_ROOT.parent)
        self.assertEqual(paths.server_root, Path(r"D:\MirServer"))
        self.assertEqual(paths.output_root, EQUIPMENT_ROOT / "outputs")

    def test_all_target_paths_follow_selected_server(self):
        from xyequip.paths import EquipmentPaths

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "NewServer"
            paths = EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target)
            target = target.resolve()
            self.assertEqual(paths.db_path, target / "Mud2/DB/ApexM2.DB")
            self.assertEqual(paths.qfunction, target / "Mir200/Envir/Market_Def/QFunction-0.txt")
            self.assertEqual(paths.item_desc, target / "Mir200/Envir/ItemDescList.txt")
            self.assertNotIn("MirServer旧", repr(paths))

    def test_platform_assets_never_resolve_from_target_ai_handoff(self):
        from xyequip.paths import EquipmentPaths

        with tempfile.TemporaryDirectory() as directory:
            paths = EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, Path(directory) / "Server")
            self.assertEqual(paths.script_properties, EQUIPMENT_ROOT / "profiles/script_properties.json")
            self.assertEqual(paths.resource_map, EQUIPMENT_ROOT / "profiles/装备资源映射表.csv")
            self.assertEqual(paths.static_icon_importer, EQUIPMENT_ROOT / "src/xyequip/resources/static_icon_from_wzl.py")

    def test_legacy_core_can_be_reconfigured_without_changing_rules(self):
        from xyequip.legacy import xy_equip_maker
        from xyequip.paths import EquipmentPaths

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Server"
            paths = EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, target, Path(directory) / "ClientData")
            xy_equip_maker.configure_paths(paths)
            self.assertEqual(xy_equip_maker.SERVER_ROOT, target.resolve())
            self.assertEqual(xy_equip_maker.DB_PATH, paths.db_path)
            self.assertEqual(xy_equip_maker.CLIENT_DATA, paths.client_data)
            self.assertEqual(xy_equip_maker.SCRIPT_PROPS, paths.script_properties)


if __name__ == "__main__":
    unittest.main()
