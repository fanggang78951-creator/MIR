import json
import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.manifest import ManifestError, PackageManifest
from xydp.repository import PackageRepository


def manifest(package_id: str, dependencies=None, status="verified", install_route=None):
    return {
        "schema_version": 1,
        "id": package_id,
        "version": "1.0.0",
        "display_name": package_id,
        "status": status,
        "engine": "LFM2",
        "bundle": None,
        "dependencies": dependencies or [],
        "parameters": {},
        "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
        "operations": [],
        "preflight_checks": [],
        "post_checks": [],
        "evidence": [],
    } | ({"install_route": install_route} if install_route else {})


class ManifestRepositoryTests(unittest.TestCase):
    def test_manifest_rejects_unknown_status(self):
        data = manifest("xy.bad", status="released")
        with self.assertRaisesRegex(ManifestError, "status"):
            PackageManifest.from_dict(data, Path("manifest.json"))

    def test_manifest_accepts_equipment_collection_specialized_route(self):
        data = manifest(
            "xy.optional.equipment-collection",
            status="candidate",
            install_route="equipment-collection",
        )
        item = PackageManifest.from_dict(data, Path("manifest.json"))
        self.assertEqual(item.install_route, "equipment-collection")
        self.assertEqual(item.residency, "optional")

    def test_repository_discovers_packages_and_orders_dependencies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for package_id, deps in (("xy.core", []), ("xy.feature", ["xy.core"])):
                package_dir = root / "verified" / package_id
                package_dir.mkdir(parents=True)
                (package_dir / "manifest.json").write_text(
                    json.dumps(manifest(package_id, deps), ensure_ascii=False),
                    encoding="utf-8",
                )
            repo = PackageRepository(root)
            repo.refresh()
            self.assertEqual([p.id for p in repo.resolve(["xy.feature"])], ["xy.core", "xy.feature"])

    def test_repository_rejects_dependency_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for package_id, deps in (("xy.a", ["xy.b"]), ("xy.b", ["xy.a"])):
                package_dir = root / "candidate" / package_id
                package_dir.mkdir(parents=True)
                (package_dir / "manifest.json").write_text(
                    json.dumps(manifest(package_id, deps, "candidate")), encoding="utf-8"
                )
            repo = PackageRepository(root)
            repo.refresh()
            with self.assertRaisesRegex(ManifestError, "循环依赖"):
                repo.resolve(["xy.a"])

    def test_repository_discovers_equipment_collection_candidate_marker(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package_dir = root / "candidate" / "xy.optional.equipment-collection"
            package_dir.mkdir(parents=True)
            data = manifest(
                "xy.optional.equipment-collection",
                status="candidate",
                install_route="equipment-collection",
            )
            data["version"] = "1.0.0-candidate.10"
            data["residency"] = "optional"
            (package_dir / "manifest.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            repo = PackageRepository(root)
            repo.refresh()
            item = repo.packages["xy.optional.equipment-collection"]
            self.assertEqual(item.version, "1.0.0-candidate.10")
            self.assertEqual(item.install_route, "equipment-collection")
            self.assertEqual(item.status, "candidate")

    def test_generic_installer_redirects_equipment_collection_to_specialized_route(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package_dir = root / "packages" / "candidate" / "xy.optional.equipment-collection"
            package_dir.mkdir(parents=True)
            data = manifest(
                "xy.optional.equipment-collection",
                status="candidate",
                install_route="equipment-collection",
            )
            (package_dir / "manifest.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            target = root / "server"
            envir = target / "Mir200" / "Envir"
            envir.mkdir(parents=True)
            (target / "Mir200" / "M2Server.exe").write_bytes(b"")
            (envir / "MapInfo.txt").write_text("", encoding="utf-8")
            repository = PackageRepository(root / "packages")
            repository.refresh()
            installer = Installer(repository, root / "backups")
            with self.assertRaisesRegex(
                InstallError,
                "配置型成果包必须使用对应专项页面安装.*equipment-collection",
            ):
                installer.preflight(
                    target,
                    ["xy.optional.equipment-collection"],
                    {},
                )


if __name__ == "__main__":
    unittest.main()
