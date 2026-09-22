from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository
from xydp.validator import validate_package


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PLATFORM_ROOT / "packages/candidate/xy.combat.sustain"
PACKAGE_ID = "xy.combat.sustain"


def make_target(
    root: Path,
    duplicate_label: bool = False,
    duplicate_attack: bool = False,
    include_attack: bool = True,
) -> tuple[Path, Path, Path, bytes, bytes]:
    target = root / "server"
    envir = target / "Mir200/Envir"
    (envir / "Market_Def").mkdir(parents=True)
    (envir / "MapQuest_Def").mkdir(parents=True)
    (target / "Mir200/M2Server.exe").write_bytes(b"M2")
    (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
    qfunction = envir / "Market_Def/QFunction-0.txt"
    attack = (
        "[@Attack]\r\n#IF\r\nEQUAL N$XY_PATROL_ACTIVE 1\r\n#ACT\r\nMOV N$XY_PATROL_CD 60\r\n"
        if include_attack
        else ""
    )
    text = (
        "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        "[@TakeOnEx]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        "[@TakeOffEx]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        + attack
        + "[@AttackDamage]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
          "[@KillMon]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
    )
    if duplicate_label:
        text += "[@XYDP_RecalcSustain]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
    if duplicate_attack:
        text += "[@Attack]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
    before = text.encode("gb18030")
    qfunction.write_bytes(before)
    qmanage = envir / "MapQuest_Def/QManage.txt"
    qmanage_before = "[@MAIN1]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
    qmanage.write_bytes(qmanage_before)
    (target / "Mir200/!setup.txt").write_bytes(b"[Setup]\r\n")
    return target, qfunction, qmanage, before, qmanage_before


class SustainPackageTests(unittest.TestCase):
    def test_manifest_is_candidate_resident_and_uses_mingyue_pve_hit_lifesteal(self):
        package = validate_package(PACKAGE_ROOT)
        self.assertEqual(package.id, PACKAGE_ID)
        self.assertEqual(package.status, "candidate")
        self.assertEqual(package.residency, "resident")
        self.assertEqual(package.dependencies, ())
        content = "\n".join(str(item.get("content", "")) for item in package.operations)
        self.assertNotIn("[@UserCmd", content)
        self.assertNotIn("ChangeState 10", content)
        self.assertNotIn("AniCount", content)
        self.assertNotIn("Weight", content)
        attack_hook = next(
            item for item in package.operations
            if item.get("type") == "event_hook" and item.get("label") == "Attack"
        )["content"]
        self.assertIn("NOT CHECKCURRTARGETRACE = 0", attack_hook)
        self.assertIn("LARGE N$XY_SUS_LifeSteal 0", attack_hook)
        self.assertIn("CHECKHPPER < 100", attack_hook)
        self.assertIn(
            "CALCPERCENT <$PKPOWER> <$STR(N$XY_SUS_LifeSteal)> N$XY_SUS_LifeStealHeal",
            attack_hook,
        )
        self.assertIn("HUMANHP + <$STR(N$XY_SUS_LifeStealHeal)>", attack_hook)
        self.assertNotIn("BREAK", attack_hook)

    def test_regen_uses_verified_fixed_value_personal_timer_route(self):
        package = validate_package(PACKAGE_ROOT)
        managed = next(item for item in package.operations if item.get("type") == "managed_block")
        content = managed["content"]
        self.assertEqual(content.count("XY_EQUIP_MAKER_LIFESTEAL_ANCHOR"), 1)
        self.assertEqual(content.count("XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR"), 1)
        self.assertIn("SetOnTimer 19 1", content)
        self.assertIn("SetOffTimer 19", content)
        self.assertNotIn("DELAYGOTO 1000", content)
        self.assertNotIn("N$XY_SUS_HPPerSec", content)
        timer_hook = next(
            item for item in package.operations
            if item.get("type") == "managed_block"
            and item.get("target") == "Mir200/Envir/MapQuest_Def/QManage.txt"
        )["content"]
        self.assertIn("[@OnTimer19]", timer_hook)
        self.assertIn("XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR", timer_hook)
        self.assertNotIn("HumanHP + <$STR", timer_hook)
        self.assertNotIn("N$XY_SUS_HPPerSec", timer_hook)

    def test_install_is_idempotent_and_byte_rollback_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, qfunction, qmanage, before, qmanage_before = make_target(root)
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            plan = installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(plan.package_ids, [PACKAGE_ID])
            receipt = installer.install(plan)
            installed = qfunction.read_text(encoding="gb18030")
            self.assertEqual(installed.count("[@XYDP_RecalcSustain]"), 1)
            self.assertEqual(installed.count("XY_EQUIP_MAKER_LIFESTEAL_ANCHOR"), 1)
            self.assertEqual(installed.count("XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR"), 1)
            self.assertEqual(installed.count("[@Attack]"), 1)
            self.assertEqual(installed.count("XYDP-HOOK-BEGIN xy.combat.sustain Attack"), 1)
            self.assertEqual(installed.count("MOV N$XY_PATROL_CD 60"), 1)
            self.assertIn("CALCPERCENT <$PKPOWER> <$STR(N$XY_SUS_LifeSteal)>", installed)
            self.assertNotIn("ChangeState 10", installed)
            installed_qmanage = qmanage.read_text(encoding="gb18030")
            self.assertEqual(installed_qmanage.count("[@OnTimer19]"), 1)
            self.assertEqual(installed_qmanage.count("XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR"), 1)
            self.assertEqual(installer.preflight(target, [PACKAGE_ID], {}).changes, [])

            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(qfunction.read_bytes(), before)
            self.assertEqual(qmanage.read_bytes(), qmanage_before)

    def test_duplicate_business_label_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, qfunction, _qmanage, before, _qmanage_before = make_target(root, duplicate_label=True)
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            with self.assertRaisesRegex(InstallError, "标签占用冲突|事件标签重复"):
                installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(qfunction.read_bytes(), before)

    def test_existing_timer_19_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, qfunction, qmanage, before, _qmanage_before = make_target(root)
            occupied = qmanage.read_text(encoding="gb18030") + "[@OnTimer19]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
            qmanage.write_text(occupied, encoding="gb18030", newline="")
            qmanage_occupied = qmanage.read_bytes()
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            with self.assertRaisesRegex(InstallError, "标签占用冲突|事件标签重复"):
                installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(qfunction.read_bytes(), before)
            self.assertEqual(qmanage.read_bytes(), qmanage_occupied)

    def test_duplicate_attack_label_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, qfunction, _qmanage, before, _qmanage_before = make_target(
                root, duplicate_attack=True
            )
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            with self.assertRaisesRegex(InstallError, "目标脚本存在重复标签|事件标签重复"):
                installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(qfunction.read_bytes(), before)

    def test_sustain_bootstraps_missing_attack_label_before_hook_install(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, qfunction, _qmanage, before, _qmanage_before = make_target(
                root, include_attack=False
            )
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            receipt = installer.install(installer.preflight(target, [PACKAGE_ID], {}))
            installed = qfunction.read_text(encoding="gb18030")
            self.assertEqual(installed.count("[@Attack]"), 1)
            self.assertEqual(installed.count("XYDP-HOOK-BEGIN xy.combat.sustain Attack"), 1)

            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(qfunction.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
