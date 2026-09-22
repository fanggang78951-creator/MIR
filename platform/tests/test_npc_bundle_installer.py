from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallPlan, Installer, PlannedChange


class BundleLauncherTransactionTests(unittest.TestCase):
    def test_one_transaction_installs_and_rolls_back_server_client_and_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            server = root / "server"
            client = root / "client"
            launcher = root / "launcher"
            backups = root / "backups"
            (server / "Mir200" / "Envir").mkdir(parents=True)
            (server / "Mir200" / "M2Server.exe").write_bytes(b"")
            (server / "Mir200" / "Envir" / "MapInfo.txt").write_bytes(b"")
            client.mkdir()
            launcher.mkdir()
            (server / "server.txt").write_bytes(b"old-server")
            (client / "data.txt").write_bytes(b"old-client")
            (launcher / "patch.txt").write_bytes(b"old-launcher")

            plan = InstallPlan(
                target_root=str(server),
                client_root=str(client),
                package_ids=["xy.bundle.test"],
                package_versions={"xy.bundle.test": "1"},
                parameters={},
                changes=[
                    PlannedChange("server.txt", b"old-server", b"new-server", "test", "xy.bundle.test"),
                    PlannedChange("data.txt", b"old-client", b"new-client", "test", "xy.bundle.test", "client"),
                    PlannedChange("patch.txt", b"old-launcher", b"new-launcher", "test", "xy.bundle.test", "launcher"),
                ],
                launcher_root=str(launcher),
            )
            installer = Installer(object(), backups)
            receipt = installer.install(plan)

            self.assertEqual((server / "server.txt").read_bytes(), b"new-server")
            self.assertEqual((client / "data.txt").read_bytes(), b"new-client")
            self.assertEqual((launcher / "patch.txt").read_bytes(), b"new-launcher")
            self.assertEqual(receipt.launcher_root, str(launcher))

            installer.rollback(server, receipt.transaction_id)
            self.assertEqual((server / "server.txt").read_bytes(), b"old-server")
            self.assertEqual((client / "data.txt").read_bytes(), b"old-client")
            self.assertEqual((launcher / "patch.txt").read_bytes(), b"old-launcher")


if __name__ == "__main__":
    unittest.main()
