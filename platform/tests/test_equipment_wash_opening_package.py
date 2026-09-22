import tempfile
import unittest
from pathlib import Path

from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.validator import validate_package
from xydp.equipment_wash import EquipmentWashImportService
from tests.test_equipment_wash_deployment import fixture


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ID = "xy.optional.equipment-wash-opening"
PACKAGE_ROOT = ROOT / "packages" / "verified" / PACKAGE_ID


def make_target(base: Path) -> tuple[Path, Path]:
    target = base / "server"
    client = base / "client"
    envir = target / "Mir200" / "Envir"
    (envir / "Market_Def").mkdir(parents=True)
    (target / "Mir200" / "M2Server.exe").write_bytes(b"M2")
    (envir / "Market_Def" / "QFunction-0.txt").write_bytes(
        "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
    )
    (envir / "MerChant.txt").write_bytes(b"")
    (envir / "EffectImageList.txt").write_bytes(b"")
    (envir / "MapInfo.txt").write_bytes(
        "[XY_NMGF_MAIN|宁姆格福]\r\n".encode("gb18030")
    )
    client.mkdir(parents=True)
    return target, client


def snapshot(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".xydp" not in path.parts
    }


class EquipmentWashOpeningPackageTests(unittest.TestCase):
    def test_candidate_manifest_and_resource_contract(self):
        package = validate_package(PACKAGE_ROOT)
        self.assertEqual(package.id, PACKAGE_ID)
        self.assertEqual(package.version, "1.2.0-candidate.3")
        self.assertEqual(package.status, "candidate")
        self.assertEqual(package.install_route, "equipment-wash-import")
        self.assertEqual(package.residency, "optional")
        manifest = package.operations
        client_copies = [item for item in manifest if item.get("scope") == "client"]
        self.assertEqual(list(manifest), [])
        self.assertTrue((PACKAGE_ROOT / "payload/client/XY_EquipmentWorkbench.wzl").is_file())
        self.assertTrue((PACKAGE_ROOT / "payload/client/XY_EquipmentWorkbench.wzx").is_file())
        self.assertTrue((PACKAGE_ROOT / "evidence" / "game_acceptance_20260808.md").is_file())
        self.assertTrue((ROOT / "所需材料表格汇总" / "洗练属性.txt").is_file())

    def test_scripts_use_accepted_absolute_layout(self):
        for name, box_id, text_count in (
            ("装备洗练.txt", 27, 8),
            ("装备开光.txt", 28, 7),
        ):
            text = (PACKAGE_ROOT / "payload" / "server" / "npc" / name).read_text(
                encoding="utf-8"
            )
            ui = text.split("[@XYEW_", 1)[0]
            self.assertIn(f"#SAY\n<ITEMBOX:{box_id}:12:1:158:140:76:76:", ui)
            self.assertEqual(ui.count("<&Text:"), text_count)
            self.assertNotIn("<Text:", ui)
            into = ui.split(f"[@ItemIntoBox{box_id}]", 1)[1]
            self.assertIn("BREAK", into)
            self.assertNotIn("OPENMERCHANTBIGDLG", into)
            self.assertNotIn("#SAY", into)

    def test_isolated_install_is_idempotent_and_byte_rollback_safe(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            platform, target, client, source = fixture(base)
            before_server = snapshot(target)
            before_client = snapshot(client)
            installer = EquipmentWashImportService(platform)
            plan = installer.preflight(target, source, client=client)
            self.assertFalse(plan.blockers, plan.blockers)
            self.assertGreaterEqual(len(plan.changes), 10)
            receipt = installer.install(plan)

            wash = (
                target
                / "Mir200/Envir/Market_Def/玄渊实验室/装备洗练-XY_NMGF_MAIN.txt"
            ).read_text(encoding="gb18030")
            opening = (
                target
                / "Mir200/Envir/Market_Def/玄渊实验室/装备开光-XY_NMGF_MAIN.txt"
            ).read_text(encoding="gb18030")
            self.assertIn("<&Text:确认洗练:420:315", wash)
            self.assertIn("<&Text:确认开光:420:315", opening)
            self.assertEqual(
                (target / "Mir200/Envir/EffectImageList.txt").read_text(
                    encoding="gb18030"
                ).strip(),
                "OtherResource.wz\nXY_EquipmentWorkbench.wz",
            )
            self.assertEqual(
                (client / "data/XY_EquipmentWorkbench.wzl").read_bytes(),
                (PACKAGE_ROOT / "payload/client/XY_EquipmentWorkbench.wzl").read_bytes(),
            )
            self.assertEqual(
                (client / "data/XY_EquipmentWorkbench.wzx").read_bytes(),
                (PACKAGE_ROOT / "payload/client/XY_EquipmentWorkbench.wzx").read_bytes(),
            )
            self.assertEqual(
                installer.preflight(target, source, client=client).changes,
                (),
            )

            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(snapshot(target), before_server)
            self.assertEqual(snapshot(client), before_client)

    def test_missing_client_root_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            platform, target, _, source = fixture(base)
            plan = EquipmentWashImportService(platform).preflight(target, source)
            self.assertTrue(any("客户端" in blocker for blocker in plan.blockers))
            self.assertFalse(plan.changes)


if __name__ == "__main__":
    unittest.main()
