from __future__ import annotations

from pathlib import Path
import csv
import sqlite3
import struct
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xyequip.resources.equipment_asset_replacement import (
    build_replacement_plan,
    apply_shape_updates_to_database_copy,
    compile_static_replacements,
    render_replacement_icons,
    write_replacement_resource_map,
)


class EquipmentAssetReplacementPlanTests(unittest.TestCase):
    def test_preserves_existing_looks_and_assigns_only_remaining_assets_after_db_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "ApexM2.DB"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Shape INTEGER, Looks INTEGER)")
            con.executemany(
                "INSERT INTO StdItems VALUES (?,?,?,?,?)",
                [
                    (1, "weapon-a", 5, 1, 7106),
                    (2, "weapon-special", 68, 0, 7106),
                    (3, "clothes-a", 10, 1, 7098),
                    (4, "fashion-clothes", 66, 0, 7098),
                    (5, "occupied-other", 22, 0, 7313),
                ],
            )
            con.commit()
            con.close()
            source = root / "source"
            for family, amount in (("武器-", 3), ("衣服-", 3)):
                folder = source / family / "外观"
                folder.mkdir(parents=True)
                for index in range(1, amount + 1):
                    (folder / f"{index:02d}").mkdir()

            plan = build_replacement_plan(db, source)

            self.assertEqual((7106,), tuple(item.looks for item in plan.weapon_replacements))
            self.assertEqual((7098,), tuple(item.looks for item in plan.clothing_replacements))
            self.assertEqual((38,), tuple(item.action_shape for item in plan.weapon_replacements))
            self.assertEqual((12,), tuple(item.action_shape for item in plan.clothing_replacements))
            self.assertEqual((7314, 7315, 7316, 7317), tuple(item.looks for item in plan.tail_additions))
            self.assertEqual((1, 3), tuple(item.idx for item in plan.shape_updates))
            apply_shape_updates_to_database_copy(db, plan)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(
                    [(1, 38), (2, 0), (3, 12), (4, 0)],
                    list(con.execute("SELECT Idx, Shape FROM StdItems WHERE Idx <= 4 ORDER BY Idx")),
                )
            finally:
                con.close()

    def test_static_compiler_fills_preserved_looks_and_only_appends_remaining_sources_at_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "ApexM2.DB"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Shape INTEGER, Looks INTEGER)")
            con.executemany(
                "INSERT INTO StdItems VALUES (?,?,?,?,?)",
                [(1, "weapon", 5, 1, 7106), (2, "clothing", 10, 1, 7098), (3, "other", 22, 0, 7313)],
            )
            con.commit()
            con.close()
            source = root / "source"
            for family in ("武器-", "衣服-"):
                for index in range(1, 4):
                    folder = source / family / "外观" / f"{index:02d}"
                    folder.mkdir(parents=True)
                    Image.new("RGBA", (12, 9), (index * 30, 40, 80, 255)).save(folder / "00000.PNG")
            plan = build_replacement_plan(db, source)
            icons = render_replacement_icons(plan, root / "icons")
            self.assertEqual(18, len(icons))
            data = root / "data"
            data.mkdir()
            for library in ("Items", "StateItem", "DnItems"):
                write_empty_pair(data, library, 7098)

            receipt = compile_static_replacements(plan, root / "icons", data, backup_root=root / "backups")

            self.assertEqual((7098, 7318), (receipt.count_before, receipt.count_after))
            for library in ("Items", "StateItem", "DnItems"):
                self.assertEqual(6, read_frame_type(data / f"{library}.wzl", data / f"{library}.wzx", 7098))
                self.assertEqual(6, read_frame_type(data / f"{library}.wzl", data / f"{library}.wzx", 7106))
                self.assertTrue(is_empty(data / f"{library}.wzx", 7099))
                self.assertEqual(6, read_frame_type(data / f"{library}.wzl", data / f"{library}.wzx", 7314))
                self.assertEqual(7318, wzx_count(data / f"{library}.wzx"))

    def test_resource_map_removes_only_the_failed_candidate_entries_and_records_stable_looks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "ApexM2.DB"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Shape INTEGER, Looks INTEGER)")
            con.executemany(
                "INSERT INTO StdItems VALUES (?,?,?,?,?)",
                [(1, "weapon", 5, 1, 7112), (2, "clothing", 10, 1, 7098), (3, "other", 22, 0, 7313)],
            )
            con.commit()
            con.close()
            source = root / "source"
            for family in ("武器-", "衣服-"):
                folder = source / family / "外观"
                for index in range(1, 3):
                    (folder / f"{index:02d}").mkdir(parents=True)
            plan = build_replacement_plan(db, source)
            fields = ["资源编号", "部位", "StdMode", "Looks", "Shape", "Items", "DnItems", "StateItem", "Weapon", "Hum", "状态", "备注"]
            original = root / "mapping.csv"
            with original.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows([
                    dict(zip(fields, ["7112", "武器", "5", "7112", "38", "7112", "7112", "7112", "Weapon.wzl", "", "candidate_待客户端游戏验收", "20260910完整动作素材；错误候选"])),
                    dict(zip(fields, ["7000", "戒指", "22", "7000", "0", "7000", "7000", "7000", "", "", "已验证", "保留"])),
                ])

            receipt = write_replacement_resource_map(original, root / "candidate.csv", plan)

            self.assertEqual((1, 4), (receipt.removed_failed_candidates, receipt.added_entries))
            with (root / "candidate.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(1, len([row for row in rows if row["资源编号"] == "7000"]))
            replacement = next(row for row in rows if row["资源编号"] == "7112")
            self.assertEqual(("武器", "5", "38"), (replacement["部位"], replacement["StdMode"], replacement["Shape"]))
            self.assertEqual(1, len([row for row in rows if row["资源编号"] == "7098"]))


def write_empty_pair(root: Path, name: str, count: int) -> None:
    wzl = bytearray(48)
    wzx = bytearray(48)
    struct.pack_into("<I", wzl, 44, count)
    struct.pack_into("<I", wzx, 44, count)
    wzx.extend(b"\x00" * (count * 4))
    (root / f"{name}.wzl").write_bytes(wzl)
    (root / f"{name}.wzx").write_bytes(wzx)


def wzx_count(path: Path) -> int:
    return struct.unpack_from("<I", path.read_bytes(), 44)[0]


def is_empty(path: Path, index: int) -> bool:
    return struct.unpack_from("<I", path.read_bytes(), 48 + index * 4)[0] == 0


def read_frame_type(wzl_path: Path, wzx_path: Path, index: int) -> int:
    offset = struct.unpack_from("<I", wzx_path.read_bytes(), 48 + index * 4)[0]
    return struct.unpack_from("<H", wzl_path.read_bytes(), offset)[0]
