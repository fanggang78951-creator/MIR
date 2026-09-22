import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xyequip.resources.action_resource_bundle import build_action_manifest, compile_action_sequences, compile_static_libraries, render_static_icons, write_candidate_resource_map


def write_sequence(folder: Path, *, visible_ids: tuple[int, ...] = (0, 7)) -> None:
    placements = folder / "Placements"
    placements.mkdir(parents=True)
    for index in range(1200):
        image = folder / f"{index:05d}.PNG"
        if index in visible_ids:
            Image.new("RGBA", (2, 3), (255, 0, 0, 255)).save(image)
        else:
            image.write_bytes(b"")
        if index in visible_ids:
            (placements / f"{index:05d}.txt").write_text("-2\n3\n", encoding="utf-8")


class ActionResourceBundleTests(unittest.TestCase):
    def test_manifest_assigns_source_folders_to_new_shapes_and_reserves_static_range(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_sequence(root / "武器-" / "外观" / "01")
            write_sequence(root / "衣服-" / "外观" / "02")
            write_sequence(root / "衣服-" / "外观" / "10-配三职业翅膀")

            manifest = build_action_manifest(root, static_start=7112)

            self.assertEqual([entry.source_name for entry in manifest.weapons], ["01"])
            self.assertEqual([entry.source_name for entry in manifest.clothes], ["02", "10-配三职业翅膀"])
            self.assertEqual([entry.shape for entry in manifest.weapons], [38])
            self.assertEqual([entry.shape for entry in manifest.clothes], [12, 13])
            self.assertEqual([entry.looks for entry in manifest.static_entries], [7112, 7113, 7114, 7115, 7116])
            self.assertEqual(manifest.static_entries[0].slot, "武器")
            self.assertEqual([entry.slot for entry in manifest.static_entries[1:]], ["男衣服", "女衣服", "男衣服", "女衣服"])
            self.assertEqual(manifest.weapons[0].frame_count, 1200)
            self.assertEqual(manifest.weapons[0].frames[0].x, -2)
            self.assertEqual(manifest.weapons[0].frames[0].y, 3)
            self.assertTrue(manifest.weapons[0].frames[1].empty)

    def test_compiler_appends_each_action_library_once_at_its_assigned_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_sequence(root / "武器-" / "外观" / "01")
            write_sequence(root / "衣服-" / "外观" / "02")
            write_sequence(root / "衣服-" / "外观" / "10-配三职业翅膀")
            manifest = build_action_manifest(root, weapon_shape_start=1, cloth_shape_start=1)
            weapon_wzl, weapon_wzx = write_empty_pair(root, "Weapon", 1200)
            hum_wzl, hum_wzx = write_empty_pair(root, "Hum", 1200)

            receipt = compile_action_sequences(
                manifest,
                weapon_wzl,
                weapon_wzx,
                hum_wzl,
                hum_wzx,
                backup_root=root / "backups",
            )

            self.assertEqual(receipt.weapon.count_before, 1200)
            self.assertEqual(receipt.weapon.count_after, 2400)
            self.assertEqual(receipt.hum.count_before, 1200)
            self.assertEqual(receipt.hum.count_after, 3600)
            self.assertEqual(receipt.weapon.shapes, (1,))
            self.assertEqual(receipt.hum.shapes, (1, 2))
            self.assertEqual(read_frame_type(weapon_wzl, weapon_wzx, 1200), 6)
            self.assertEqual(read_frame_type(hum_wzl, hum_wzx, 1200), 6)
            self.assertEqual(read_frame_type(hum_wzl, hum_wzx, 2400), 6)

    def test_static_icons_are_generated_from_the_matching_action_entry_for_all_three_libraries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_sequence(root / "武器-" / "外观" / "01")
            write_sequence(root / "衣服-" / "外观" / "02")
            manifest = build_action_manifest(root, static_start=7112)

            outputs = render_static_icons(manifest, root / "icons")

            self.assertEqual(len(outputs), 9)
            with Image.open(root / "icons" / "Items" / "07112.png") as item_icon:
                self.assertEqual(item_icon.size, (48, 48))
                self.assertGreater(item_icon.getchannel("A").getextrema()[1], 0)
            with Image.open(root / "icons" / "StateItem" / "07113.png") as state_icon:
                self.assertEqual(state_icon.size, (64, 64))
            with Image.open(root / "icons" / "DnItems" / "07114.png") as ground_icon:
                self.assertEqual(ground_icon.size, (32, 32))

    def test_static_compiler_keeps_reserved_missing_item_slots_empty_before_new_icons(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_sequence(root / "武器-" / "外观" / "01")
            write_sequence(root / "衣服-" / "外观" / "02")
            manifest = build_action_manifest(root, static_start=7112)
            icon_root = root / "icons"
            render_static_icons(manifest, icon_root)
            data_dir = root / "data"
            data_dir.mkdir()
            for library in ("Items", "StateItem", "DnItems"):
                write_empty_pair(data_dir, library, 7098)

            receipt = compile_static_libraries(manifest, icon_root, data_dir, backup_root=root / "backups")

            self.assertEqual(receipt.count_before, 7098)
            self.assertEqual(receipt.count_after, 7115)
            for library in ("Items", "StateItem", "DnItems"):
                self.assertTrue(is_empty(data_dir / f"{library}.wzx", 7098))
                self.assertTrue(is_empty(data_dir / f"{library}.wzx", 7111))
                self.assertEqual(read_frame_type(data_dir / f"{library}.wzl", data_dir / f"{library}.wzx", 7112), 6)

    def test_candidate_mapping_retires_only_old_weapon_and_clothing_rows_and_adds_new_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_sequence(root / "武器-" / "外观" / "01")
            write_sequence(root / "衣服-" / "外观" / "02")
            manifest = build_action_manifest(root, static_start=7112)
            source_csv = root / "map.csv"
            source_csv.write_text(
                "资源编号,部位,StdMode,Looks,Shape,Items,DnItems,StateItem,Weapon,Hum,状态,备注\n"
                "6398,武器,5,6398,14,6398,6398,6398,Weapon.wzl,,已导入静态资源_待装备定义验收,玄渊二十套全装备700件；旧武器\n"
                "6399,男衣服,10,6399,1,6399,6399,6399,,Hum.wzl,已导入静态资源_待装备定义验收,玄渊二十套全装备700件；旧男衣服\n"
                "6400,戒指,22,6400,0,6400,6400,6400,,,已导入静态资源_待装备定义验收,保留\n",
                encoding="utf-8-sig",
            )

            result = write_candidate_resource_map(source_csv, root / "candidate.csv", manifest)

            self.assertEqual(result.retired_count, 2)
            rows = read_csv(root / "candidate.csv")
            self.assertEqual(next(row for row in rows if row["资源编号"] == "6398")["状态"], "已退役_不可选")
            self.assertEqual(next(row for row in rows if row["资源编号"] == "6399")["状态"], "已退役_不可选")
            self.assertEqual(next(row for row in rows if row["资源编号"] == "6400")["状态"], "已导入静态资源_待装备定义验收")
            self.assertEqual(len([row for row in rows if row["资源编号"] == "7112"]), 1)
            self.assertEqual(next(row for row in rows if row["资源编号"] == "7112")["Weapon"], "Weapon.wzl")


def write_empty_pair(root: Path, name: str, count: int) -> tuple[Path, Path]:
    import struct

    wzl = bytearray(48)
    wzx = bytearray(48)
    struct.pack_into("<I", wzl, 44, count)
    struct.pack_into("<I", wzx, 44, count)
    wzx.extend(b"\0\0\0\0" * count)
    wzl_path, wzx_path = root / f"{name}.wzl", root / f"{name}.wzx"
    wzl_path.write_bytes(wzl)
    wzx_path.write_bytes(wzx)
    return wzl_path, wzx_path


def read_frame_type(wzl_path: Path, wzx_path: Path, index: int) -> int:
    import struct

    offset = struct.unpack_from("<I", wzx_path.read_bytes(), 48 + index * 4)[0]
    return struct.unpack_from("<H", wzl_path.read_bytes(), offset)[0]


def is_empty(wzx_path: Path, index: int) -> bool:
    import struct

    return struct.unpack_from("<I", wzx_path.read_bytes(), 48 + index * 4)[0] == 0


def read_csv(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


if __name__ == "__main__":
    unittest.main()
