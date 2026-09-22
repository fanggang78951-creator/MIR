from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository
from xydp.validator import validate_package


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PLATFORM_ROOT / "packages/verified/xy.combat.damage-coefficient"
PACKAGE_ID = "xy.combat.damage-coefficient"


def make_target(root: Path, duplicate_anchor: bool = False) -> tuple[Path, Path, bytes]:
    target = root / "server"
    envir = target / "Mir200/Envir"
    (envir / "Market_Def").mkdir(parents=True)
    (target / "Mir200/M2Server.exe").write_bytes(b"M2")
    (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
    qfunction = envir / "Market_Def/QFunction-0.txt"
    text = "[@AttackDamage]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
    if duplicate_anchor:
        text += "; XY_DAMAGE_COEFFICIENT_PACKAGE_ANCHOR\r\n"
    before = text.encode("gb18030")
    qfunction.write_bytes(before)
    return target, qfunction, before


class DamageCoefficientPackageTests(unittest.TestCase):
    def test_manifest_is_verified_resident_and_has_no_test_route(self):
        package = validate_package(PACKAGE_ROOT)
        self.assertEqual(package.id, PACKAGE_ID)
        self.assertEqual(package.status, "verified")
        self.assertEqual(package.residency, "resident")
        content = "\n".join(str(item.get("content", "")) for item in package.operations)
        self.assertNotIn("[@UserCmd", content)
        self.assertNotIn("POWERRATE", content)

    def test_install_is_idempotent_and_byte_rollback_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, qfunction, before = make_target(root)
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            plan = installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(set(plan.package_ids), {
                "xy.combat.runtime-refresh",
                PACKAGE_ID,
            })
            receipt = installer.install(plan)
            installed = qfunction.read_text(encoding="gb18030")
            self.assertEqual(installed.count("XY_DAMAGE_COEFFICIENT_PACKAGE_ANCHOR"), 3)
            self.assertEqual(installed.count("XY_EQUIP_MAKER_RUNTIME_DAMAGE_COEFFICIENT_ANCHOR"), 1)
            self.assertEqual(installed.count("POWERRATE <$STR(N$XY_RT_Power)> 0 0 1 0"), 1)
            self.assertEqual(installer.preflight(target, [PACKAGE_ID], {}).changes, [])

            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(qfunction.read_bytes(), before)

    def test_duplicate_package_anchor_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target, qfunction, before = make_target(root, duplicate_anchor=True)
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            with self.assertRaisesRegex(InstallError, "受管锚点不唯一"):
                installer.preflight(target, [PACKAGE_ID], {})
            self.assertEqual(qfunction.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
