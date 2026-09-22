import json
import tempfile
import unittest
from pathlib import Path

from xydp.manifest import PackageManifest
from xydp.repository import PackageRepository


def package_data(package_id: str, *, status: str = "candidate", residency=None, dependencies=None):
    data = {
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
    }
    if residency is not None:
        data["residency"] = residency
    return data


def write_package(root: Path, data: dict) -> Path:
    folder = root / "packages" / data["status"] / data["id"]
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return folder


class ResidentAndOptionalScriptTests(unittest.TestCase):
    def test_manifest_defaults_to_optional_and_rejects_unknown_residency(self):
        default = PackageManifest.from_dict(package_data("xy.default"), Path("manifest.json"))
        self.assertEqual(getattr(default, "residency", None), "optional")
        bad = package_data("xy.bad", residency="always")
        with self.assertRaisesRegex(Exception, "residency"):
            PackageManifest.from_dict(bad, Path("manifest.json"))

    def test_resident_service_collects_verified_and_candidate_but_not_optional(self):
        from xydp.resident import ResidentService

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_package(root, package_data("xy.core", status="verified", residency="resident"))
            write_package(root, package_data("xy.candidate", residency="resident", dependencies=["xy.core"]))
            write_package(root, package_data("xy.optional", status="verified", residency="optional"))
            repository = PackageRepository(root / "packages")
            repository.refresh()
            service = ResidentService(repository, root / "backups")
            self.assertEqual(service.package_ids(), ["xy.candidate", "xy.core"])
            self.assertEqual([item.id for item in repository.resolve(service.package_ids())], ["xy.core", "xy.candidate"])

    def test_resident_transaction_records_operation_and_candidate_packages_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            server = root / "server"
            envir = server / "Mir200/Envir"
            envir.mkdir(parents=True)
            (server / "Mir200/M2Server.exe").write_bytes(b"M2")
            (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
            data = package_data("xy.resident.demo", residency="resident")
            data["operations"] = [{"type": "copy", "source": "payload/demo.txt", "target": "Mir200/Envir/demo.txt"}]
            folder = write_package(root, data)
            (folder / "payload").mkdir()
            (folder / "payload/demo.txt").write_text("resident", encoding="utf-8")
            repository = PackageRepository(root / "packages"); repository.refresh()
            from xydp.resident import ResidentService
            service = ResidentService(repository, root / "backups")
            plan = service.preflight(server)
            self.assertEqual(plan.operation_type, "resident-base")
            self.assertEqual(getattr(plan, "candidate_packages", None), ["xy.resident.demo"])
            receipt = service.install(plan)
            self.assertEqual(receipt.operation_type, "resident-base")
            self.assertEqual(getattr(receipt, "candidate_packages", None), ["xy.resident.demo"])
            self.assertTrue((envir / "demo.txt").exists())
            service.installer.rollback(server, receipt.transaction_id)
            self.assertFalse((envir / "demo.txt").exists())

    def test_register_raw_folder_copies_source_and_reads_instructions(self):
        from xydp.optional_scripts import OptionalScriptLibrary

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "来源" / "副本传送"
            source.mkdir(parents=True)
            (source / "使用说明.md").write_text("# 副本传送\n首次由 Codex 验证。", encoding="utf-8")
            (source / "QFunction片段.txt").write_text("[@XY_DEMO]", encoding="utf-8")
            library = OptionalScriptLibrary(root / "platform")
            record = library.register(source)
            self.assertEqual(record.script_id, "副本传送")
            self.assertEqual(record.kind, "raw")
            self.assertEqual(record.status, "pending")
            self.assertIn("首次由 Codex 验证", record.instructions)
            self.assertTrue(Path(record.platform_path, "QFunction片段.txt").exists())
            self.assertEqual(len(record.source_hash), 64)
            self.assertEqual(library.list()[0].script_id, "副本传送")

    def test_register_raw_folder_requires_instructions_and_rejects_executable(self):
        from xydp.optional_scripts import OptionalScriptError, OptionalScriptLibrary

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            missing = root / "missing"; missing.mkdir()
            (missing / "script.txt").write_text("safe", encoding="utf-8")
            library = OptionalScriptLibrary(root / "platform")
            with self.assertRaisesRegex(OptionalScriptError, "使用说明"):
                library.register(missing)
            unsafe = root / "unsafe"; unsafe.mkdir()
            (unsafe / "使用说明.txt").write_text("说明", encoding="utf-8")
            (unsafe / "run.ps1").write_text("Write-Host unsafe", encoding="utf-8")
            with self.assertRaisesRegex(OptionalScriptError, "禁止"):
                library.register(unsafe)

    def test_duplicate_raw_folder_is_idempotent_but_changed_content_is_blocked(self):
        from xydp.optional_scripts import OptionalScriptError, OptionalScriptLibrary

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "demo"; source.mkdir()
            (source / "使用说明.txt").write_text("说明", encoding="utf-8")
            (source / "script.txt").write_text("v1", encoding="utf-8")
            library = OptionalScriptLibrary(root / "platform")
            first = library.register(source)
            second = library.register(source)
            self.assertEqual(first.source_hash, second.source_hash)
            (source / "script.txt").write_text("v2", encoding="utf-8")
            with self.assertRaisesRegex(OptionalScriptError, "版本"):
                library.register(source)

    def test_register_complete_package_folder_imports_as_optional_package(self):
        from xydp.optional_scripts import OptionalScriptLibrary

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "complete"
            source.mkdir()
            data = package_data("xy.optional.demo")
            (source / "manifest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            library = OptionalScriptLibrary(root / "platform")
            record = library.register(source)
            self.assertEqual(record.kind, "package")
            self.assertEqual(record.package_id, "xy.optional.demo")
            imported = root / "platform/packages/candidate/xy.optional.demo/manifest.json"
            self.assertTrue(imported.exists())
            self.assertEqual(json.loads(imported.read_text(encoding="utf-8"))["residency"], "optional")

    def test_pending_raw_script_can_be_linked_to_a_validated_optional_package(self):
        from xydp.optional_scripts import OptionalScriptLibrary

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "demo"; source.mkdir()
            (source / "使用说明.txt").write_text("首次验证说明", encoding="utf-8")
            (source / "script.txt").write_text("[@DEMO]", encoding="utf-8")
            library = OptionalScriptLibrary(root / "platform")
            library.register(source)
            package = root / "platform/packages/verified/xy.optional.demo"
            package.mkdir(parents=True)
            data = package_data("xy.optional.demo", status="verified", residency="optional")
            data["evidence"] = ["game:test-accepted", "rollback:test-accepted"]
            (package / "manifest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            linked = library.link_package("demo", "xy.optional.demo")
            self.assertEqual(linked.status, "packaged")
            self.assertEqual(linked.package_id, "xy.optional.demo")
            self.assertTrue((root / "platform/非常驻脚本/packaged/demo/link.json").exists())


if __name__ == "__main__":
    unittest.main()
