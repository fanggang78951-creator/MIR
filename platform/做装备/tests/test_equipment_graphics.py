from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image

MIRROR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MIRROR_ROOT / "src"))


def write_library(root: Path, name: str, count: int = 4) -> None:
    header = bytearray(48)
    struct.pack_into("<I", header, 44, count)
    wzl = bytearray(header)
    offsets = []
    for marker in range(count):
        offsets.append(len(wzl))
        wzl.extend(struct.pack("<HHHHhhhh", 6, 0, 1, 1, 0, 0, 0, 0))
        wzl.extend(bytes((marker, marker, marker)))
    wzx = bytes(header) + b"".join(struct.pack("<I", offset) for offset in offsets)
    (root / f"{name}.wzl").write_bytes(bytes(wzl))
    (root / f"{name}.wzx").write_bytes(wzx)


class EquipmentGraphicsPreflightTests(unittest.TestCase):
    def fixture(self, *, missing_frame=False, missing_placement=False, patch_drift=False, missing_graphics_root=False):
        root = Path(tempfile.mkdtemp())
        source = root / "source"; source.mkdir()
        placements = source / "Placements"; placements.mkdir()
        for index in range(2):
            if not (missing_frame and index == 1):
                Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(source / f"{index:02d}.png")
            if not (missing_placement and index == 1):
                (placements / f"{index:02d}.txt").write_text("0\n0\n", encoding="utf-8")
        bag = root / "bag.png"; inner = root / "inner.png"
        Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(bag)
        Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(inner)
        client = root / "client"; client.mkdir()
        patch = root / "patch"; patch.mkdir()
        for directory in (client, patch):
            for library in ("Items", "DnItems", "StateItem"):
                write_library(directory, library)
        if patch_drift:
            (patch / "Items.wzl").write_bytes((patch / "Items.wzl").read_bytes() + b"drift")
        graphics_weapon = root / "graphics" / "Weapon"
        if not missing_graphics_root:
            graphics_weapon.mkdir(parents=True)
        database = root / "ApexM2.DB"
        import sqlite3
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Looks INTEGER, Shape INTEGER)")
            connection.execute("INSERT INTO StdItems VALUES (1, '剑甲一', 5, 1, 1)")
            connection.execute("INSERT INTO StdItems VALUES (2, '剑甲二', 5, 2, 1)")
            connection.commit()
        items = []
        for name, bag_name in (("剑甲一", "bag.png"), ("剑甲二", "bag.png")):
            items.append({"name": name, "kind": "weapon", "autoShape": True, "sources": {"actionFrames": str(source), "bagImage": str(root / bag_name), "innerImage": str(inner)}, "static": {"libraries": ["Items", "DnItems", "StateItem"], "bagPlacement": [0, 0], "innerPlacement": [-1, -2]}, "action": {"library": "Weapon", "sourceFrameDigits": 2, "treatOneByOneAsEmpty": False}})
        manifest = root / "config.json"
        manifest.write_text(json.dumps({"schemaVersion": 1, "operation": "equipment-graphics-import", "outputRoot": str(root / "out"), "target": {"database": str(database), "clientData": str(client), "launcherPatchData": str(patch), "graphicsRoots": {"Weapon": str(graphics_weapon)}}, "encoding": {"actionFrameCount": 2, "actionVisibleFrames": 2, "actionEmptyFrames": 0, "alphaCutoff": 128, "staticType": "type6-bgr24-bottom-up"}, "items": items}, ensure_ascii=False), encoding="utf-8")
        return root, manifest, source

    def test_valid_is_read_only_and_hashes_placements(self):
        from xyequip.equipment_graphics import preflight
        root, manifest, source = self.fixture()
        before = manifest.parent / "ApexM2.DB"
        old = before.read_bytes()
        result = preflight(manifest)
        self.assertFalse(result["blockers"])
        self.assertFalse((root / "out").exists())
        self.assertEqual(old, before.read_bytes())
        self.assertIn(str((source / "Placements" / "00.txt").resolve()), result["sourceHashes"])

    def test_missing_frame_blocks(self):
        from xyequip.equipment_graphics import preflight
        _, manifest, _ = self.fixture(missing_frame=True)
        result = preflight(manifest)
        self.assertTrue(any("缺失" in blocker or "不存在" in blocker for blocker in result["blockers"]))

    def test_missing_placement_blocks(self):
        from xyequip.equipment_graphics import preflight
        _, manifest, _ = self.fixture(missing_placement=True)
        result = preflight(manifest)
        self.assertTrue(any("Placement" in blocker for blocker in result["blockers"]))

    def test_same_batch_reserves_distinct_shapes(self):
        from xyequip.equipment_graphics import preflight
        _, manifest, _ = self.fixture()
        result = preflight(manifest)
        shapes = [item["newShape"] for item in result["shapeUpdates"]]
        self.assertEqual(len(shapes), 2)
        self.assertEqual(len(set(shapes)), 2)

    def test_client_patch_drift_blocks(self):
        from xyequip.equipment_graphics import preflight
        _, manifest, _ = self.fixture(patch_drift=True)
        result = preflight(manifest)
        self.assertTrue(any("补丁源不一致" in blocker for blocker in result["blockers"]))

    def test_valid_missing_graphics_root_is_created_by_apply(self):
        from xyequip.equipment_graphics import apply, preflight

        root, manifest, _ = self.fixture(missing_graphics_root=True)
        plan = preflight(manifest)
        self.assertFalse(plan["blockers"])
        result = apply(manifest)
        self.assertEqual("applied", result["status"])
        self.assertTrue((root / "graphics" / "Weapon" / "1000.wil").is_file())

    def test_each_apply_receipt_keeps_its_own_manifest_snapshot(self):
        from xyequip.equipment_graphics import apply

        _, manifest, _ = self.fixture()
        first = apply(manifest)
        second = apply(manifest)
        first_receipt = json.loads(Path(first["receiptPath"]).read_text(encoding="utf-8"))
        second_receipt = json.loads(Path(second["receiptPath"]).read_text(encoding="utf-8"))
        self.assertNotEqual(first_receipt["manifest"], second_receipt["manifest"])
        self.assertTrue(Path(first_receipt["manifest"]).is_file())
        self.assertTrue(Path(second_receipt["manifest"]).is_file())

    def test_apply_rejects_config_changed_during_candidate_build(self):
        from xyequip.equipment_graphics import EquipmentGraphicsError, apply
        from xyequip.equipment_graphics import builder

        _, manifest, _ = self.fixture()

        def mutate_manifest_during_build(_manifest, _preflight):
            manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            return []

        with patch.object(builder, "build_prepared_files", side_effect=mutate_manifest_during_build):
            with self.assertRaisesRegex(EquipmentGraphicsError, "配置在构建后发生漂移"):
                apply(manifest)


class ActionWixHeaderTests(unittest.TestCase):
    def test_human_action_uses_the_human_wix_profile(self):
        from xyequip.equipment_graphics.action_wil import build_action_wil_wix

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "Placements").mkdir(parents=True)
            Image.new("RGBA", (1, 1), (10, 20, 30, 255)).save(source / "00.png")
            (source / "Placements" / "00.txt").write_text("0\n0\n", encoding="utf-8")
            output_wil = root / "Human_1.wil"
            output_wix = root / "Human_1.wix"

            build_action_wil_wix(
                kind="human", source_root=source, output_wil=output_wil, output_wix=output_wix,
                frame_count=1, source_filename_digits=2, alpha_cutoff=128,
                treat_one_by_one_as_empty=True,
            )

            wix = output_wix.read_bytes()
            self.assertEqual(bytes.fromhex("c0fa9a0ac0fa9a0a"), wix[32:40])


if __name__ == "__main__":
    unittest.main()
