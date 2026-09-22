from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository
from xydp.validator import validate_package


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PLATFORM_ROOT / "packages/verified/xy.combat.monster-damage-absorb"
PACKAGE_ID = "xy.combat.monster-damage-absorb"


def make_target(root: Path, duplicate_label: bool = False) -> tuple[Path, Path, bytes]:
    target = root / "server"
    envir = target / "Mir200/Envir"
    (envir / "Market_Def").mkdir(parents=True)
    (target / "Mir200/M2Server.exe").write_bytes(b"M2")
    (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
    qfunction = envir / "Market_Def/QFunction-0.txt"
    text = (
        "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        "[@TakeOnEx]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        "[@TakeOffEx]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        "[@AttackDamage]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        "[@KillMon]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
    )
    if duplicate_label:
        text += "[@XYDP_RecalcMonsterAbsorb]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
    before = text.encode("gb18030")
    qfunction.write_bytes(before)
    (target / "Mir200/!setup.txt").write_bytes(b"[Setup]\r\n")
    return target, qfunction, before


class MonsterDamageAbsorbPackageTests(unittest.TestCase):
    def test_manifest_is_verified_resident_and_has_no_lab_route(self):
        package = validate_package(PACKAGE_ROOT)
        self.assertEqual(package.id, PACKAGE_ID)
        self.assertEqual(package.status, "verified")
        self.assertEqual(package.residency, "resident")
        self.assertIn("xy.combat.core", package.dependencies)
        content = "\n".join(str(item.get("content", "")) for item in package.operations)
        self.assertNotIn("[@UserCmd", content)
        self.assertEqual(content.count("StruckDamageAbsorb"), 2)
        self.assertIn("StruckDamageAbsorb * 100 <$STR(N$XY_MDA_Final)> 300", content)
        self.assertIn("StruckDamageAbsorb * 100 1 1", content)

    def test_formula_caps_bonus_at_25_and_final_absorb_at_85(self):
        package = validate_package(PACKAGE_ROOT)
        managed = next(item for item in package.operations if item.get("type") == "managed_block")
        content = managed["content"]
        self.assertIn("MOV N$XY_MDA_Cap 60", content)
        self.assertIn("LARGE N$XY_MDA_CapBonus 25", content)
        self.assertIn("MOV N$XY_MDA_CapBonus 25", content)
        self.assertIn("LARGE N$XY_MDA_Final <$STR(N$XY_MDA_Cap)>", content)
        self.assertIn("MOV N$XY_MDA_Final <$STR(N$XY_MDA_Cap)>", content)
        self.assertEqual(content.count("XY_EQUIP_MAKER_MONSTER_ABSORB_ANCHOR"), 1)
        self.assertEqual(content.count("XY_EQUIP_MAKER_MONSTER_ABSORB_CAP_ANCHOR"), 1)

    def test_refresh_loop_has_one_pending_loop_guard(self):
        package = validate_package(PACKAGE_ROOT)
        managed = next(item for item in package.operations if item.get("type") == "managed_block")
        content = managed["content"]
        self.assertIn("N$XY_MDA_TimerLoop", package.claims["variables"])
        self.assertIn("EQUAL N$XY_MDA_TimerLoop 0", content)
        self.assertIn("MOV N$XY_MDA_TimerLoop 1", content)
        self.assertIn("DELAYGOTO 240 @XYDP_MonsterAbsorbTick", content)
        self.assertIn("MOV N$XY_MDA_TimerLoop 0", content)

    def test_install_is_idempotent_and_byte_rollback_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, qfunction, before = make_target(root)
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            plan = installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(set(plan.package_ids), {"xy.combat.core", PACKAGE_ID})
            receipt = installer.install(plan)
            installed = qfunction.read_text(encoding="gb18030")
            self.assertEqual(installed.count("[@XYDP_RecalcMonsterAbsorb]"), 1)
            self.assertEqual(installed.count("[@XYDP_MonsterAbsorbTick]"), 1)
            self.assertEqual(installed.count("XY_EQUIP_MAKER_MONSTER_ABSORB_ANCHOR"), 1)
            self.assertEqual(installed.count("XY_EQUIP_MAKER_MONSTER_ABSORB_CAP_ANCHOR"), 1)
            self.assertEqual(installer.preflight(target, [PACKAGE_ID], {}).changes, [])

            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(qfunction.read_bytes(), before)

    def test_duplicate_business_label_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, qfunction, before = make_target(root, duplicate_label=True)
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            with self.assertRaisesRegex(InstallError, "标签占用冲突|事件标签重复"):
                installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(qfunction.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
