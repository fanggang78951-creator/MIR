from __future__ import annotations

import sys
import tempfile
import unittest
import argparse
import struct
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path


EQUIPMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EQUIPMENT_ROOT / "src"))


class EquipmentResourceTests(unittest.TestCase):
    def write_library(self, client_data: Path, lib: str, count: int, declared: int | None = None) -> list[bytes]:
        frames: list[bytes] = []
        wzl = bytearray(64)
        offsets: list[int] = []
        for index in range(count):
            offsets.append(len(wzl))
            payload = bytes(((index + 1) % 256, len(lib)))
            frame = struct.pack("<HHHHhhhh", 6, 0, 1, 1, index, -index, len(payload), 0) + payload
            frames.append(frame)
            wzl.extend(frame)
        struct.pack_into("<I", wzl, 44, declared if declared is not None else count)
        wzx = bytearray(48)
        struct.pack_into("<I", wzx, 44, declared if declared is not None else count)
        for offset in offsets:
            wzx.extend(struct.pack("<I", offset))
        (client_data / f"{lib}.wzl").write_bytes(wzl)
        (client_data / f"{lib}.wzx").write_bytes(wzx)
        return frames

    def test_resource_tools_have_no_old_machine_defaults(self):
        resources = EQUIPMENT_ROOT / "src/xyequip/resources"
        for name in ("static_icon_from_wzl.py", "clone_wzl_frame_raw.py"):
            text = (resources / name).read_text(encoding="utf-8")
            self.assertNotIn(r"D:\11周年", text)
            self.assertNotIn(r"D:\MirServer\AI_Handoff", text)
            self.assertNotIn("MirServer旧", text)

    def test_legacy_bridge_passes_explicit_target_resource_paths(self):
        from xyequip.legacy import xy_equip_maker
        from xyequip.paths import EquipmentPaths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = EquipmentPaths.for_target(EQUIPMENT_ROOT.parent, root / "Server", root / "Client/data")
            xy_equip_maker.configure_paths(paths)
            spec = xy_equip_maker.EquipmentSpec(name="资源头盔", slot="头盔")
            spec.icon_source = {"source_id": "4460"}
            args = xy_equip_maker.build_raw_clone_args(spec)
            self.assertEqual(args.client_data, paths.client_data)
            self.assertEqual(args.resource_map, paths.resource_map)
            self.assertEqual(args.backup_root, paths.backup_root)

    def test_static_icon_import_does_not_launch_frozen_gui_executable(self):
        from xyequip.legacy import xy_equip_maker
        from xyequip.paths import EquipmentPaths
        from xyequip.resources import clone_wzl_frame_raw as clone

        old_paths = xy_equip_maker._PATHS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            platform = root / "Platform"
            client = root / "Client" / "data"
            client.mkdir(parents=True)
            for lib, count in (("Items", 3), ("StateItem", 2), ("DnItems", 2)):
                self.write_library(client, lib, count)

            paths = EquipmentPaths.for_target(platform, root / "Server", client)
            paths.raw_clone_importer.parent.mkdir(parents=True, exist_ok=True)
            paths.raw_clone_importer.write_text("# packaged resource marker\n", encoding="utf-8")
            xy_equip_maker.configure_paths(paths)
            spec = xy_equip_maker.EquipmentSpec(
                name="冻结版进程内导入测试",
                slot="头盔",
                fields={"StdMode": 15},
                icon_source={"source_id": "1"},
            )
            launched = False

            def fake_frozen_gui_launch(_command, **_kwargs):
                nonlocal launched
                launched = True
                result = clone.run(argparse.Namespace(
                    client_data=client,
                    source_id=1,
                    output_dir=paths.output_root,
                    backup_root=paths.backup_root,
                    dry_run=False,
                    register_resource=True,
                    resource_map=paths.resource_map,
                    slot="头盔",
                    stdmode="15",
                    shape="",
                    name=spec.name,
                ))
                stdout = (
                    f"LOOKS={result['target_id']}\n"
                    f"OUTPUT_DIR={result['output_dir']}\n"
                    f"BACKUP_DIR={result['backup_dir']}\n"
                )
                return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

            try:
                with patch("subprocess.run", side_effect=fake_frozen_gui_launch):
                    message = xy_equip_maker.apply_static_icon_source(spec)
            finally:
                xy_equip_maker.configure_paths(old_paths)

            self.assertFalse(launched, "冻结版不应把当前 GUI EXE 当作 Python 启动器")
            self.assertEqual(spec.fields["Looks"], 3)
            self.assertIn("Looks=3", message)

    def test_source_offset_is_valid_when_header_count_differs_from_physical_slots(self):
        from xyequip.legacy import xy_equip_maker

        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            self.write_library(data, "Items", 4, declared=3)
            offset = xy_equip_maker.read_wzx_count_and_offset(data / "Items.wzx", 1)
            self.assertGreater(offset, 0)

    def test_equipment_still_requires_stateitem_source_frame(self):
        from xyequip.legacy import xy_equip_maker
        from xyequip.paths import EquipmentPaths

        old_paths = xy_equip_maker._PATHS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / "data"
            client.mkdir()
            for lib in ("Items", "StateItem", "DnItems"):
                self.write_library(client, lib, 1)
            wzx = bytearray((client / "StateItem.wzx").read_bytes())
            struct.pack_into("<I", wzx, 48, 0)
            (client / "StateItem.wzx").write_bytes(wzx)
            xy_equip_maker.configure_paths(EquipmentPaths.for_target(root / "Platform", root / "Server", client))
            spec = xy_equip_maker.EquipmentSpec(name="仍需穿戴图装备", slot="戒指", icon_source={"source_id": "0"})

            try:
                with self.assertRaisesRegex(xy_equip_maker.EquipMakerError, "StateItem.wzx"):
                    xy_equip_maker.preflight_icon_source(spec)
                xy_equip_maker.preflight_icon_source(spec, xy_equip_maker.MATERIAL_ICON_LIBRARIES)
            finally:
                xy_equip_maker.configure_paths(old_paths)

    def test_new_equipment_reuses_existing_source_id_without_changing_libraries(self):
        from xyequip.legacy import xy_equip_maker
        from xyequip.paths import EquipmentPaths

        old_paths = xy_equip_maker._PATHS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / "data"
            client.mkdir()
            for lib in ("Items", "StateItem", "DnItems"):
                self.write_library(client, lib, 3)
            before = {path.name: path.read_bytes() for path in client.iterdir()}
            xy_equip_maker.configure_paths(EquipmentPaths.for_target(root / "Platform", root / "Server", client))
            spec = xy_equip_maker.EquipmentSpec(
                name="直接复用来源装备",
                slot="头盔",
                fields={"StdMode": 15},
                icon_source={"source_id": "1"},
            )

            try:
                message = xy_equip_maker.reuse_static_icon_source(spec)
            finally:
                xy_equip_maker.configure_paths(old_paths)

            self.assertEqual(spec.fields["Looks"], 1)
            self.assertEqual(spec.icon_import_log["action"], "reuse_source_id")
            self.assertFalse(spec.icon_import_log["client_files_changed"])
            self.assertIn("未修改 WZL/WZX", message)
            self.assertEqual({path.name: path.read_bytes() for path in client.iterdir()}, before)

    def test_8942_frame_library_accepts_looks_8941_and_rejects_8942(self):
        from xyequip.legacy import xy_equip_maker
        from xyequip.paths import EquipmentPaths

        old_paths = xy_equip_maker._PATHS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / "data"
            client.mkdir()
            for lib in ("Items", "StateItem", "DnItems"):
                self.write_library(client, lib, 8942)
            before = {path.name: path.read_bytes() for path in client.iterdir()}
            xy_equip_maker.configure_paths(EquipmentPaths.for_target(root / "Platform", root / "Server", client))

            try:
                last_valid = xy_equip_maker.EquipmentSpec(
                    name="8942张图库末张",
                    slot="头盔",
                    fields={"StdMode": 15},
                    icon_source={"source_id": "8941"},
                )
                xy_equip_maker.reuse_static_icon_source(last_valid)
                self.assertEqual(last_valid.fields["Looks"], 8941)

                beyond_count = xy_equip_maker.EquipmentSpec(
                    name="8942张图库越界",
                    slot="头盔",
                    fields={"StdMode": 15},
                    icon_source={"source_id": "8942"},
                )
                with self.assertRaisesRegex(xy_equip_maker.EquipMakerError, "超出范围 0-8941"):
                    xy_equip_maker.reuse_static_icon_source(beyond_count)
            finally:
                xy_equip_maker.configure_paths(old_paths)

            self.assertEqual({path.name: path.read_bytes() for path in client.iterdir()}, before)

    def test_raw_clone_aligns_unequal_library_counts_to_one_new_looks(self):
        from xyequip.resources import clone_wzl_frame_raw as clone

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / "data"
            client.mkdir()
            original_frames = {
                "Items": self.write_library(client, "Items", 4, declared=3),
                "StateItem": self.write_library(client, "StateItem", 2),
                "DnItems": self.write_library(client, "DnItems", 3),
            }
            args = argparse.Namespace(
                client_data=client,
                source_id=1,
                output_dir=root / "output",
                backup_root=root / "backup",
                dry_run=False,
                register_resource=False,
                resource_map=root / "map.csv",
                slot="武器",
                stdmode="5",
                shape="1",
                name="不等长图库测试",
            )
            result = clone.run(args)
            self.assertEqual(result["target_id"], 4)
            self.assertEqual(result["counts_before"], {"Items": 4, "StateItem": 2, "DnItems": 3})
            for lib in clone.LIBS:
                offsets = clone.read_offsets(client / f"{lib}.wzx")
                self.assertEqual(len(offsets), 5)
                self.assertGreater(offsets[4], 0)
                info, frame = clone.inspect_library(client, lib, 4)
                self.assertEqual(frame, original_frames[lib][1])
                self.assertEqual(info["wzx_declared_count"], 5)
                self.assertEqual(info["wzl_header_count"], 5)
            self.assertEqual(clone.read_offsets(client / "StateItem.wzx")[2:4], [0, 0])
            self.assertEqual(clone.read_offsets(client / "DnItems.wzx")[3], 0)
            self.assertTrue(Path(result["backup_dir"]).is_dir())

    def test_material_raw_clone_writes_items_only(self):
        from xyequip.resources import clone_wzl_frame_raw as clone

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / "data"
            client.mkdir()
            original_frames = {"Items": self.write_library(client, "Items", 4)}
            self.write_library(client, "DnItems", 3)
            self.write_library(client, "StateItem", 2)
            unused_before = {
                f"{lib}.{ext}": (client / f"{lib}.{ext}").read_bytes()
                for lib in ("DnItems", "StateItem")
                for ext in ("wzl", "wzx")
            }
            args = argparse.Namespace(
                client_data=client, source_id=1, output_dir=root / "output", backup_root=root / "backup",
                dry_run=False, register_resource=False, resource_map=root / "map.csv",
                slot="材料", stdmode="46", shape="1", name="材料图库范围测试",
                libraries=("Items",),
            )

            result = clone.run(args)

            self.assertEqual(result["libraries"], ["Items"])
            self.assertEqual(result["counts_before"], {"Items": 4})
            self.assertEqual(result["target_id"], 4)
            _info, frame = clone.inspect_library(client, "Items", 4)
            self.assertEqual(frame, original_frames["Items"][1])
            for name, data in unused_before.items():
                self.assertEqual((client / name).read_bytes(), data)

    def test_raw_clone_failure_restores_all_six_client_files(self):
        from xyequip.resources import clone_wzl_frame_raw as clone

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / "data"
            client.mkdir()
            for lib, count in (("Items", 4), ("StateItem", 2), ("DnItems", 3)):
                self.write_library(client, lib, count)
            before = {path.name: path.read_bytes() for path in client.iterdir()}
            args = argparse.Namespace(
                client_data=client, source_id=1, output_dir=root / "output", backup_root=root / "backup",
                dry_run=False, register_resource=False, resource_map=root / "map.csv",
                slot="武器", stdmode="5", shape="1", name="失败恢复测试",
            )
            original_append = clone.append_raw_frame
            calls = 0

            def fail_on_second(client_data, lib, target_id, frame):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise clone.RawCloneError("injected second-library failure")
                return original_append(client_data, lib, target_id, frame)

            with patch.object(clone, "append_raw_frame", side_effect=fail_on_second):
                with self.assertRaisesRegex(clone.RawCloneError, "injected"):
                    clone.run(args)
            after = {path.name: path.read_bytes() for path in client.iterdir()}
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
