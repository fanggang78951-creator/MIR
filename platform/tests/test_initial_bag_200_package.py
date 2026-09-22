import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository
from xydp.resident import ResidentService
from xydp.validator import validate_package


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PLATFORM_ROOT / "packages/candidate/xy.native.initial-bag-200"
PACKAGE_ID = "xy.native.initial-bag-200"


class InitialBag200PackageTests(unittest.TestCase):
    def setUp(self):
        self.repository = PackageRepository(PLATFORM_ROOT / "packages")
        self.repository.refresh()

    def _make_target(self, root: Path, login_text: str) -> tuple[Path, Path, bytes]:
        target = root / "server"
        envir = target / "Mir200/Envir"
        login = envir / "QuestDiary/游戏登陆/登陆脚本.txt"
        login.parent.mkdir(parents=True)
        (target / "Mir200/M2Server.exe").write_bytes(b"M2")
        (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
        before = login_text.encode("gb18030")
        login.write_bytes(before)
        return target, login, before

    def test_manifest_is_resident_candidate_and_uses_direct_login_event(self):
        manifest = validate_package(PACKAGE_ROOT)
        self.assertEqual(manifest.id, PACKAGE_ID)
        self.assertEqual(manifest.status, "candidate")
        self.assertEqual(manifest.residency, "resident")
        self.assertEqual(manifest.version, "2.0.0-candidate.1")
        self.assertEqual(len(manifest.operations), 1)
        operation = manifest.operations[0]
        self.assertEqual(operation["type"], "event_hook")
        self.assertEqual(operation["target"], "Mir200/Envir/QuestDiary/游戏登陆/登陆脚本.txt")
        self.assertEqual(operation["label"], "登陆设置")
        self.assertEqual(operation.get("target_encoding"), "gb18030")
        self.assertEqual(
            operation["content"],
            "#IF\n#ACT\nExtBagPageCount = 4\nExtBagOpenItemCount + 160",
        )
        all_text = "\n".join(str(item) for item in manifest.operations)
        self.assertNotIn("ExtBagOpenItemCount =", all_text)
        self.assertNotIn("QManage.txt", all_text)

    def test_package_is_collected_by_resident_base(self):
        service = ResidentService(self.repository, PLATFORM_ROOT / "backups")
        self.assertIn(PACKAGE_ID, service.package_ids())

    def test_fixture_install_is_idempotent_and_byte_rollback_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, login, before = self._make_target(
                root,
                "[@登陆设置]\r\n#IF\r\n#ACT\r\nSENDMSG 6 欢迎\r\nBREAK\r\n",
            )
            installer = Installer(self.repository, root / "backups")
            plan = installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(len(plan.changes), 1)
            self.assertEqual(login.read_bytes(), before, "预检不得写目标文件")
            receipt = installer.install(plan)

            installed = login.read_bytes().decode("gb18030")
            self.assertEqual(installed.count("ExtBagPageCount = 4"), 1)
            self.assertEqual(installed.count("ExtBagOpenItemCount + 160"), 1)
            self.assertNotIn("ExtBagOpenItemCount =", installed)
            self.assertEqual(installer.preflight(target, [PACKAGE_ID], {}).changes, [])

            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(login.read_bytes(), before)

    def test_missing_real_login_label_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, login, before = self._make_target(
                root,
                "[@其他登录]\r\n#IF\r\n#ACT\r\nBREAK\r\n",
            )
            installer = Installer(self.repository, root / "backups")
            with self.assertRaisesRegex(InstallError, "标签不存在"):
                installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(login.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
