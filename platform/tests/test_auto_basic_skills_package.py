import json
import tempfile
import unittest
from pathlib import Path

from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.validator import validate_package


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PLATFORM_ROOT / "packages/candidate/xy.native.auto-basic-skills"
PACKAGE_ID = "xy.native.auto-basic-skills"


class AutoBasicSkillsPackageTests(unittest.TestCase):
    def test_manifest_is_resident_candidate_with_two_managed_entries(self):
        manifest = validate_package(PACKAGE_ROOT)
        self.assertEqual(manifest.id, PACKAGE_ID)
        self.assertEqual(manifest.status, "candidate")
        self.assertEqual(manifest.residency, "resident")
        operations = list(manifest.operations)
        hooks = [item for item in operations if item["type"] == "event_hook"]
        self.assertEqual(
            {(item["target"], item["label"]) for item in hooks},
            {
                ("Mir200/Envir/MapQuest_Def/QManage.txt", "MAIN1"),
                ("Mir200/Envir/Market_Def/QFunction-0.txt", "PLAYLEVELUP"),
            },
        )
        self.assertTrue(all("@XYDP_AUTO_BASIC_SKILLS" in item["content"] for item in hooks))

    def test_payload_only_writes_normal_level_three_for_33_skills(self):
        payload = (PACKAGE_ROOT / "payload/升级自动三级基础技能.txt").read_text(encoding="utf-8")
        self.assertEqual(payload.count("\nADDSKILL "), 33)
        self.assertEqual(payload.count(" = 3 0"), 33)
        self.assertEqual(payload.count(" < 3 0"), 33)
        self.assertNotIn(" = 3 1", payload)
        self.assertNotIn(" < 3 1", payload)
        self.assertNotIn("强化三重误发修复名单", payload)
        self.assertEqual(payload.count("\nCHECKJOB WARRIOR"), 12)
        self.assertEqual(payload.count("\nCHECKJOB WIZARD"), 28)
        self.assertEqual(payload.count("\nCHECKJOB TAOIST"), 26)

    def test_fixture_install_is_idempotent_and_byte_rollback_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "server"
            envir = target / "Mir200/Envir"
            (envir / "MapQuest_Def").mkdir(parents=True)
            (envir / "Market_Def").mkdir(parents=True)
            (target / "Mir200/M2Server.exe").write_bytes(b"M2")
            (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
            qmanage = envir / "MapQuest_Def/QManage.txt"
            qfunction = envir / "Market_Def/QFunction-0.txt"
            qmanage_before = "[@MAIN1]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
            qfunction_before = "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
            qmanage.write_bytes(qmanage_before)
            qfunction.write_bytes(qfunction_before)

            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")
            plan = installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(len(plan.changes), 3)
            receipt = installer.install(plan)

            installed_qmanage = qmanage.read_bytes().decode("gb18030")
            installed_qfunction = qfunction.read_bytes().decode("gb18030")
            installed_payload = (
                envir / "QuestDiary/玄渊功能/常驻基础/升级自动三级基础技能.txt"
            ).read_bytes().decode("gb18030")
            self.assertEqual(installed_qmanage.count("@XYDP_AUTO_BASIC_SKILLS"), 1)
            self.assertEqual(installed_qfunction.count("@XYDP_AUTO_BASIC_SKILLS"), 1)
            self.assertEqual(installed_payload.count("\r\nADDSKILL "), 33)
            self.assertNotIn(" = 3 1", installed_payload)
            self.assertEqual(installer.preflight(target, [PACKAGE_ID], {}).changes, [])

            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(qmanage.read_bytes(), qmanage_before)
            self.assertEqual(qfunction.read_bytes(), qfunction_before)
            self.assertFalse(
                (envir / "QuestDiary/玄渊功能/常驻基础/升级自动三级基础技能.txt").exists()
            )


if __name__ == "__main__":
    unittest.main()
