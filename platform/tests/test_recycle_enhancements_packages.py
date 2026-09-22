from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.runtime import platform_root
from xydp.validator import validate_package


BONUS = "xy.optional.recycle.bonus"
AUTO = "xy.optional.recycle.auto"
FILTER = "xy.optional.recycle.drop-filter"


class RecycleEnhancementPackageTests(unittest.TestCase):
    def package(self, package_id: str):
        return validate_package(
            platform_root() / "packages" / "candidate" / package_id
        )

    def make_server(self, root: Path) -> Path:
        server = root / "server"
        envir = server / "Mir200" / "Envir"
        market = envir / "Market_Def"
        market.mkdir(parents=True)
        (server / "Mir200" / "M2Server.exe").write_bytes(b"M2")
        (server / "Mud2" / "DB").mkdir(parents=True)
        (server / "Mud2" / "DB" / "StdItems.DB").write_bytes(b"fixture")
        (envir / "MapInfo.txt").write_bytes("[0 盟重]\r\n".encode("gb18030"))
        (envir / "MerChant.txt").write_bytes(b"")
        (envir / "UserCmd.txt").write_bytes("传\t3\r\n".encode("gb18030"))
        qfunction = (
            "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n\r\n"
            "[@PickUpItemEX]\r\n#IF\r\n#ACT\r\nLINKPICKUPITEM\r\n"
        )
        (market / "QFunction-0.txt").write_bytes(qfunction.encode("gb18030"))
        return server

    def test_packages_are_optional_candidates_with_safe_dependencies(self):
        bonus = self.package(BONUS)
        auto = self.package(AUTO)
        drop_filter = self.package(FILTER)
        self.assertEqual((bonus.status, bonus.residency), ("candidate", "optional"))
        self.assertEqual((auto.status, auto.residency), ("candidate", "optional"))
        self.assertEqual((drop_filter.status, drop_filter.residency), ("candidate", "optional"))
        self.assertEqual(bonus.dependencies, ("xy.optional.recycle.core",))
        self.assertEqual(auto.dependencies, (BONUS,))
        self.assertEqual(drop_filter.dependencies, ())

    def test_auto_uses_pickup_event_exact_40_threshold_and_shared_exit(self):
        package = self.package(AUTO)
        hooks = [item for item in package.operations if item["type"] == "event_hook"]
        pickup = next(item for item in hooks if item["label"] == "PickUpItemEX")
        self.assertIn("EQUAL N$XY_RecycleAutoEnabled 1", pickup["content"])
        self.assertIn("NOT CHECKBAGSIZE 40", pickup["content"])
        self.assertIn("GOTO @XY_RECYCLE_ENHANCED_APPLY", pickup["content"])
        self.assertNotIn("BREAK", pickup["content"])
        all_text = "\n".join(str(item.get("content", "")) for item in package.operations)
        for forbidden in ("CHECKITEM 木剑", "TAKE 木剑", "TakeBagItem", "DELAYGOTO"):
            self.assertNotIn(forbidden, all_text)

    def test_bonus_uses_actual_gold_delta_and_defaults_to_zero(self):
        package = self.package(BONUS)
        self.assertEqual(package.parameters["recycle_bonus_percent"]["default"], 0)
        text = "\n".join(str(item.get("content", "")) for item in package.operations)
        self.assertIn("MOV N$XY_RecycleGoldBefore <$GOLDCOUNT>", text)
        self.assertIn("GOTO @XY_RECYCLE_APPLY", text)
        self.assertIn("MOV N$XY_RecycleGoldBase <$GOLDCOUNT>", text)
        self.assertIn("DEC N$XY_RecycleGoldBase <$STR(N$XY_RecycleGoldBefore)>", text)
        self.assertIn("CalcPercent <$STR(N$XY_RecycleGoldBase)> <$STR(N$XY_RecycleBonusPercent)>", text)
        self.assertIn("GOLDCOUNT + <$STR(N$XY_RecycleGoldBonus)>", text)
        self.assertNotIn("GAMEGOLD", text)
        self.assertNotIn("CHECKFENGHAO", text)

    def test_filter_wraps_official_on_and_off_commands_only(self):
        package = self.package(FILTER)
        text = "\n".join(str(item.get("content", "")) for item in package.operations)
        self.assertEqual(text.count("FILTERGLOBALMSG 1 1"), 1)
        self.assertEqual(text.count("FILTERGLOBALMSG 1 0"), 1)
        for forbidden in ("KILLMONBURSTRATE", "TakeBagItem", "CHECKITEM", "TAKE "):
            self.assertNotIn(forbidden, text)

    def test_combined_preflight_render_idempotency_and_byte_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            server = self.make_server(root)
            before = {
                path.relative_to(server): path.read_bytes()
                for path in server.rglob("*")
                if path.is_file()
            }
            repository = PackageRepository(platform_root() / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")

            plan = installer.preflight(
                server,
                [AUTO, FILTER],
                {"recycle_bonus_percent": 20},
            )
            self.assertEqual(
                plan.package_ids,
                ["xy.optional.recycle.core", BONUS, AUTO, FILTER],
            )
            self.assertEqual(plan.parameters["recycle_bonus_percent"], 20)
            self.assertEqual(
                {item.relative_path for item in plan.changes},
                {
                    "Mir200/Envir/UserCmd.txt",
                    "Mir200/Envir/Market_Def/QFunction-0.txt",
                },
            )
            qchange = next(
                item for item in plan.changes
                if item.relative_path.endswith("QFunction-0.txt")
            )
            rendered = qchange.after.decode("gb18030")
            self.assertIn("MOV N$XY_RecycleBonusPercent 20", rendered)
            self.assertIn("NOT CHECKBAGSIZE 40", rendered)
            self.assertIn("FILTERGLOBALMSG 1 1", rendered)
            self.assertEqual(rendered.count("[@PickUpItemEX]"), 1)

            receipt = installer.install(plan)
            self.assertEqual(
                installer.preflight(
                    server,
                    [AUTO, FILTER],
                    {"recycle_bonus_percent": 20},
                ).changes,
                [],
            )
            installer.rollback(server, receipt.transaction_id)
            after = {
                path.relative_to(server): path.read_bytes()
                for path in server.rglob("*")
                if path.is_file() and ".xydp" not in path.parts
            }
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
