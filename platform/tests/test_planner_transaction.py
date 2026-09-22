import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository
from xydp.runtime import platform_root
from xydp.textpatch import install_managed_block


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PlannerTransactionTests(unittest.TestCase):
    def make_target(self, root: Path):
        envir = root / "Mir200" / "Envir"
        (root / "Mir200").mkdir(parents=True, exist_ok=True)
        (root / "Mir200" / "M2Server.exe").write_bytes(b"M2")
        (root / "Mir200" / "!setup.txt").write_bytes(
            b"SendItemDescList=0\r\nSendTzItemDescList=0\r\n"
        )
        envir.mkdir(parents=True, exist_ok=True)
        (envir / "MapInfo.txt").write_bytes("[0 盟重]\r\n".encode("gb18030"))
        (envir / "MerChant.txt").write_bytes(b"")
        (envir / "Market_Def").mkdir()
        (envir / "Market_Def" / "QFunction-0.txt").write_bytes(
            "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
        )

    def make_package(self, packages: Path):
        package = packages / "verified" / "xy.demo"
        (package / "payload").mkdir(parents=True)
        (package / "payload" / "npc.txt").write_text("[@Main]\n#ACT\nSENDMSG 6 玄渊\nBREAK\n", encoding="utf-8")
        data = {
            "schema_version": 1,
            "id": "xy.demo",
            "version": "1.0.0",
            "display_name": "演示包",
            "status": "verified",
            "engine": "LFM2",
            "bundle": None,
            "dependencies": [],
            "parameters": {"npc_map": {"type": "string", "required": True}},
            "claims": {"labels": ["XY_DEMO"], "variables": ["N$XY_Demo"], "maps": [], "npcs": []},
            "operations": [
                {"type": "managed_block", "target": "Mir200/Envir/Market_Def/QFunction-0.txt", "content": "[@XY_DEMO]\n#IF\n#ACT\nMOV N$XY_Demo 1\nBREAK"},
                {"type": "event_hook", "target": "Mir200/Envir/Market_Def/QFunction-0.txt", "label": "PlayLogin", "content": "#IF\n#ACT\nDELAYGOTO 1 @XY_DEMO"},
                {"type": "unique_line", "target": "Mir200/Envir/MerChant.txt", "line": "演示NPC\t{npc_map}\t10\t10\t演示\t0\t71\t0", "key_fields": [0, 1]},
                {"type": "mapinfo_flag", "target": "Mir200/Envir/MapInfo.txt", "map_id": "0", "flag": "SAFE"},
                {"type": "mapinfo_title", "target": "Mir200/Envir/MapInfo.txt", "map_id": "0", "display_name": "演示地图"},
                {"type": "render", "source": "payload/npc.txt", "target": "Mir200/Envir/Market_Def/演示NPC-{npc_map}.txt", "target_encoding": "gb18030"},
            ],
            "preflight_checks": [],
            "post_checks": [{"type": "file_exists", "path": "Mir200/Envir/Market_Def/演示NPC-{npc_map}.txt"}],
            "evidence": ["static:test"],
        }
        (package / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_preflight_has_no_side_effects_and_install_can_rollback_byte_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            packages = base / "packages"
            backups = base / "backups"
            self.make_target(target)
            self.make_package(packages)
            before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            repo = PackageRepository(packages)
            repo.refresh()
            installer = Installer(repo, backups)
            plan = installer.preflight(target, ["xy.demo"], {"npc_map": "map9"})
            after_preflight = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            self.assertEqual(before, after_preflight)
            receipt = installer.install(plan)
            self.assertTrue((target / "Mir200/Envir/Market_Def/演示NPC-map9.txt").exists())
            self.assertEqual((target / "Mir200/Envir/MapInfo.txt").read_text(encoding="gb18030"), "[0 演示地图] SAFE\n")
            installer.rollback(target, receipt.transaction_id)
            after_rollback = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file() and ".xydp" not in p.parts}
            self.assertEqual(before, after_rollback)

    def test_exclusive_map_npc_removes_other_registrations_and_rolls_back_byte_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            packages = base / "packages"
            backups = base / "backups"
            self.make_target(target)
            self.make_package(packages)
            manifest_path = packages / "verified/xy.demo/manifest.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            npc_operation = next(operation for operation in data["operations"] if operation["type"] == "unique_line")
            npc_operation["type"] = "exclusive_unique_line"
            npc_operation["key_fields"] = [1]
            manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            merchant = target / "Mir200/Envir/MerChant.txt"
            original = (
                "其他地图NPC\tmap8\t1\t1\t其他\t0\t8\t0\r\n"
                "旧NPC甲\tmap9\t2\t2\t旧甲\t0\t8\t0\r\n"
                "旧NPC乙\tmap9\t3\t3\t旧乙\t0\t8\t0\r\n"
            ).encode("gb18030")
            merchant.write_bytes(original)
            repo = PackageRepository(packages)
            repo.refresh()
            installer = Installer(repo, backups)

            plan = installer.preflight(target, ["xy.demo"], {"npc_map": "map9"})
            self.assertEqual(merchant.read_bytes(), original)
            receipt = installer.install(plan)
            installed = merchant.read_text(encoding="gb18030")
            self.assertEqual(installed.count("\tmap9\t"), 1)
            self.assertIn("演示NPC\tmap9\t10\t10", installed)
            self.assertIn("其他地图NPC\tmap8", installed)
            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(merchant.read_bytes(), original)

    def test_builtin_combat_power_bootstraps_missing_events_and_rolls_back_empty_target(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            self.make_target(target)
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            original = "[@PlayDie]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
            qfunction.write_bytes(original)
            repo = PackageRepository(platform_root() / "packages")
            repo.refresh()
            installer = Installer(repo, base / "backups")

            plan = installer.preflight(target, ["xy.combat.power"], {})

            self.assertEqual(qfunction.read_bytes(), original)
            planned = next(change.after for change in plan.changes if change.relative_path.endswith("QFunction-0.txt"))
            text = planned.decode("gb18030")
            for label in ("PlayLogin", "TakeOnEx", "TakeOffEx"):
                self.assertIn(f"[@{label}]", text)
                self.assertIn(f"XYDP-HOOK-BEGIN xy.combat.power {label}", text)
            receipt = installer.install(plan)
            installer.rollback(target, receipt.transaction_id)
            self.assertEqual(qfunction.read_bytes(), original)

    def test_first_pick_bootstrap_keeps_qfunction_in_explicit_gb18030(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            self.make_target(target)
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.unlink()
            repo = PackageRepository(platform_root() / "packages")
            repo.refresh()
            installer = Installer(repo, base / "backups")

            plan = installer.preflight(target, ["xy.ops.first-pick"], {})

            planned = next(change.after for change in plan.changes if change.relative_path.endswith("QFunction-0.txt"))
            text = planned.decode("gb18030")
            self.assertIn("#CALL [\\首爆脚本\\首爆处理.txt] @首爆拾取处理", text)
            self.assertEqual(planned, text.encode("gb18030"))
            with self.assertRaises(UnicodeDecodeError):
                planned.decode("utf-8")

    def test_preflight_rejects_missing_required_parameter(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            packages = base / "packages"
            self.make_target(target)
            self.make_package(packages)
            repo = PackageRepository(packages)
            repo.refresh()
            with self.assertRaisesRegex(InstallError, "npc_map"):
                Installer(repo, base / "backups").preflight(target, ["xy.demo"], {})

    def test_manifest_parameter_default_is_applied_and_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); target = base / "server"; packages = base / "packages"
            self.make_target(target); self.make_package(packages)
            manifest_path = packages / "verified/xy.demo/manifest.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["parameters"]["npc_map"] = {"type": "string", "required": True, "default": "default_map"}
            manifest_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            repo = PackageRepository(packages); repo.refresh(); installer = Installer(repo, base / "backups")
            default_plan = installer.preflight(target, ["xy.demo"], {})
            self.assertEqual(default_plan.parameters["npc_map"], "default_map")
            override_plan = installer.preflight(target, ["xy.demo"], {"npc_map": "other_map"})
            self.assertEqual(override_plan.parameters["npc_map"], "other_map")

    def test_preflight_rejects_duplicate_target_labels(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            packages = base / "packages"
            self.make_target(target)
            self.make_package(packages)
            qf = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qf.write_text("[@A]\n[@a]\n", encoding="gb18030")
            repo = PackageRepository(packages)
            repo.refresh()
            with self.assertRaisesRegex(InstallError, "重复标签"):
                Installer(repo, base / "backups").preflight(target, ["xy.demo"], {"npc_map": "map9"})

    def test_copy_operation_preserves_binary_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            packages = base / "packages"
            self.make_target(target)
            package = packages / "verified" / "xy.binary"
            (package / "payload").mkdir(parents=True)
            payload = bytes(range(256))
            (package / "payload" / "map.map").write_bytes(payload)
            data = {
                "schema_version": 1, "id": "xy.binary", "version": "1.0.0", "display_name": "二进制",
                "status": "verified", "engine": "LFM2", "bundle": None, "dependencies": [], "parameters": {},
                "claims": {"labels": [], "variables": [], "maps": ["xy_map"], "npcs": []},
                "operations": [{"type": "copy", "source": "payload/map.map", "target": "Mir200/Map/xy_map.map"}],
                "preflight_checks": [{"type": "file_missing", "path": "Mir200/Map/xy_map.map"}],
                "post_checks": [{"type": "file_exists", "path": "Mir200/Map/xy_map.map"}], "evidence": ["static:test"]
            }
            (package / "manifest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            repo = PackageRepository(packages); repo.refresh()
            installer = Installer(repo, base / "backups")
            plan = installer.preflight(target, ["xy.binary"], {})
            self.assertEqual(plan.changes[0].after, payload)

    def test_render_preserve_existing_creates_missing_but_keeps_user_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            packages = base / "packages"
            package = packages / "verified" / "xy.preserve"
            (package / "payload").mkdir(parents=True)
            (package / "payload" / "config.txt").write_text("[配置]\n默认值=1\n", encoding="utf-8")
            data = {
                "schema_version": 1,
                "id": "xy.preserve",
                "version": "1.0.0",
                "display_name": "保留现有配置",
                "status": "verified",
                "engine": "LFM2",
                "bundle": None,
                "dependencies": [],
                "parameters": {},
                "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
                "operations": [{
                    "type": "render",
                    "source": "payload/config.txt",
                    "target": "Mir200/Envir/QuestDiary/配置.txt",
                    "target_encoding": "gb18030",
                    "preserve_existing": True,
                }],
                "preflight_checks": [],
                "post_checks": [{"type": "file_exists", "path": "Mir200/Envir/QuestDiary/配置.txt"}],
                "evidence": ["static:test"],
            }
            (package / "manifest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            repo = PackageRepository(packages)
            repo.refresh()
            installer = Installer(repo, base / "backups")

            missing_target = base / "missing-server"
            self.make_target(missing_target)
            create_plan = installer.preflight(missing_target, ["xy.preserve"], {})
            self.assertEqual(len(create_plan.changes), 1)
            self.assertEqual(create_plan.changes[0].after.decode("gb18030"), "[配置]\r\n默认值=1\r\n")

            existing_target = base / "existing-server"
            self.make_target(existing_target)
            existing = existing_target / "Mir200/Envir/QuestDiary/配置.txt"
            existing.parent.mkdir(parents=True, exist_ok=True)
            user_bytes = "[配置]\r\n用户值=999\r\n".encode("gb18030")
            existing.write_bytes(user_bytes)
            preserve_plan = installer.preflight(existing_target, ["xy.preserve"], {})
            self.assertEqual(preserve_plan.changes, [])
            self.assertEqual(existing.read_bytes(), user_bytes)

    def test_copy_tree_expands_files_and_client_scope_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); target = base / "server"; client = base / "client"; packages = base / "packages"
            self.make_target(target); client.mkdir()
            package = packages / "verified/xy.mapdemo"; (package / "payload/maps/sub").mkdir(parents=True)
            (package / "payload/maps/a.map").write_bytes(b"map-a")
            (package / "payload/maps/sub/b.map").write_bytes(b"map-b")
            data = {
                "schema_version": 1, "id": "xy.mapdemo", "version": "1.0.0", "display_name": "地图目录",
                "status": "verified", "engine": "LFM2", "bundle": None, "dependencies": [], "parameters": {},
                "claims": {"labels": [], "variables": [], "maps": ["a", "b"], "npcs": []},
                "operations": [{"type": "copy_tree", "source": "payload/maps", "target": "Map", "scope": "client"}],
                "preflight_checks": [],
                "post_checks": [
                    {"type": "file_exists", "path": "Map/a.map", "scope": "client"},
                    {"type": "sha256", "path": "Map/sub/b.map", "scope": "client", "value": sha256(b"map-b")},
                ], "evidence": ["static:test"]
            }
            (package / "manifest.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            repo = PackageRepository(packages); repo.refresh(); installer = Installer(repo, base / "backups")
            plan = installer.preflight(target, ["xy.mapdemo"], {}, client_root=client)
            self.assertEqual({item.relative_path for item in plan.changes}, {"Map/a.map", "Map/sub/b.map"})
            self.assertTrue(all(item.scope == "client" for item in plan.changes))
            receipt = installer.install(plan)
            self.assertEqual((client / "Map/sub/b.map").read_bytes(), b"map-b")
            installer.rollback(target, receipt.transaction_id)
            self.assertFalse((client / "Map/a.map").exists())

    def test_client_operation_requires_client_root(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); target = base / "server"; packages = base / "packages"
            self.make_target(target)
            package = packages / "verified/xy.client"; (package / "payload").mkdir(parents=True)
            (package / "payload/a.bin").write_bytes(b"a")
            data = {
                "schema_version": 1, "id": "xy.client", "version": "1", "display_name": "客户端",
                "status": "verified", "engine": "LFM2", "bundle": None, "dependencies": [], "parameters": {},
                "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
                "operations": [{"type": "copy", "source": "payload/a.bin", "target": "Data/a.bin", "scope": "client"}],
                "preflight_checks": [], "post_checks": [], "evidence": []
            }
            (package / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
            repo = PackageRepository(packages); repo.refresh()
            with self.assertRaisesRegex(InstallError, "客户端根目录"):
                Installer(repo, base / "backups").preflight(target, ["xy.client"], {})

    def test_claim_conflict_blocks_install(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            packages = base / "packages"
            self.make_target(target)
            self.make_package(packages)
            qf = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qf.write_text("[@PlayLogin]\n#ACT\nMOV N$XY_Demo 99\nBREAK\n", encoding="gb18030")
            repo = PackageRepository(packages); repo.refresh()
            with self.assertRaisesRegex(InstallError, "变量占用冲突"):
                Installer(repo, base / "backups").preflight(target, ["xy.demo"], {"npc_map": "map9"})

    def test_legacy_managed_package_is_recognized_and_superseded(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            packages = base / "packages"
            self.make_target(target)
            self.make_package(packages)
            manifest_path = packages / "verified/xy.demo/manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            operation = next(item for item in manifest["operations"] if item["type"] == "managed_block")
            operation["legacy_package_ids"] = ["xy.demo.legacy"]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            qfunction = target / "Mir200/Envir/Market_Def/QFunction-0.txt"
            legacy = install_managed_block(
                qfunction.read_text(encoding="gb18030"),
                "xy.demo.legacy",
                "[@XY_DEMO]\r\n#IF\r\n#ACT\r\nMOV N$XY_Demo 1\r\nBREAK",
                "\r\n",
            )
            qfunction.write_text(legacy.text, encoding="gb18030", newline="")
            repo = PackageRepository(packages)
            repo.refresh()
            installer = Installer(repo, base / "backups")
            plan = installer.preflight(target, ["xy.demo"], {"npc_map": "map9"})
            self.assertEqual(plan.superseded_package_ids, ["xy.demo.legacy"])
            receipt = installer.install(plan)
            installed = qfunction.read_text(encoding="gb18030")
            self.assertIn("XYDP-BEGIN xy.demo", installed)
            self.assertNotIn("XYDP-BEGIN xy.demo.legacy", installed)
            state = json.loads((target / ".xydp/installed.json").read_text(encoding="utf-8"))
            self.assertNotIn("xy.demo.legacy", state["packages"])
            self.assertEqual(receipt.superseded_package_ids, ["xy.demo.legacy"])

    def test_rollback_rejects_files_changed_after_install(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            packages = base / "packages"
            self.make_target(target); self.make_package(packages)
            repo = PackageRepository(packages); repo.refresh()
            installer = Installer(repo, base / "backups")
            receipt = installer.install(installer.preflight(target, ["xy.demo"], {"npc_map": "map9"}))
            path = target / "Mir200/Envir/Market_Def/演示NPC-map9.txt"
            path.write_bytes(path.read_bytes() + b"changed")
            with self.assertRaisesRegex(InstallError, "安装后被修改"):
                installer.rollback(target, receipt.transaction_id)

    def test_second_preflight_is_a_noop(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); target = base / "server"; packages = base / "packages"
            self.make_target(target); self.make_package(packages)
            repo = PackageRepository(packages); repo.refresh()
            installer = Installer(repo, base / "backups")
            installer.install(installer.preflight(target, ["xy.demo"], {"npc_map": "map9"}))
            second = installer.preflight(target, ["xy.demo"], {"npc_map": "map9"})
            self.assertEqual(second.changes, [])
            with self.assertRaisesRegex(InstallError, "没有需要应用"):
                installer.install(second)

    def test_uninstall_latest_package_restores_original_bytes_and_state(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); target = base / "server"; packages = base / "packages"
            self.make_target(target); self.make_package(packages)
            before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            repo = PackageRepository(packages); repo.refresh()
            installer = Installer(repo, base / "backups")
            installer.install(installer.preflight(target, ["xy.demo"], {"npc_map": "map9"}))
            installer.uninstall(target, "xy.demo")
            after = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file() and ".xydp" not in p.parts}
            self.assertEqual(before, after)
            state = json.loads((target / ".xydp/installed.json").read_text(encoding="utf-8"))
            self.assertNotIn("xy.demo", state["packages"])


if __name__ == "__main__":
    unittest.main()
