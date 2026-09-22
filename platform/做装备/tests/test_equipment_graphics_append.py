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


def write_library(root: Path, stem: str, count: int, marker: int) -> None:
    header = bytearray(48)
    struct.pack_into("<I", header, 44, count)
    wzl = bytearray(header)
    offsets = []
    for index in range(count):
        offsets.append(len(wzl))
        wzl.extend(struct.pack("<HHHHhhhh", 6, 0, 1, 1, 0, 0, 0, 0))
        wzl.extend(bytes(((marker + index) % 255, 1, 2)))
    wzx = bytes(header) + b"".join(struct.pack("<I", offset) for offset in offsets)
    (root / f"{stem}.wzl").write_bytes(bytes(wzl))
    (root / f"{stem}.wzx").write_bytes(wzx)


def count_slots(path: Path) -> int:
    return struct.unpack_from("<I", path.read_bytes(), 44)[0]


class EquipmentGraphicsAppendTests(unittest.TestCase):
    def fixture(self, *, resource_count: int = 42) -> tuple[Path, Path, list[tuple[Path, Path]]]:
        root = Path(tempfile.mkdtemp())
        output = root / "output"
        client = root / "targets" / "client"
        patch = root / "targets" / "patch"
        for directory, marker in ((client, 5), (patch, 173)):
            directory.mkdir(parents=True)
            for library, library_marker in (("Items", marker), ("DnItems", marker + 20), ("StateItem", marker + 40)):
                write_library(directory, library, 8900, library_marker)
            graphics = directory / "Graphics" / "Weapon"
            graphics.mkdir(parents=True)
            # Existing number must be skipped in every relevant action root.
            (graphics / "1400.wil").write_bytes(b"old-wil")
            (graphics / "1400.wix").write_bytes(b"old-wix")
        resources = []
        assets = root / "assets"
        for index in range(resource_count):
            item = assets / f"r{index:02d}"
            (item / "Placements").mkdir(parents=True)
            Image.new("RGBA", (2, 2), (index % 255, 30, 90, 255)).save(item / "static.png")
            Image.new("RGBA", (2, 2), (index % 255, 90, 30, 255)).save(item / "0.png")
            (item / "Placements" / "0.txt").write_text("-1\n2\n", encoding="utf-8")
            resources.append({
                "name": f"JJ-{index + 1:02d}",
                "sources": {"bagImage": str(item / "static.png"), "innerImage": str(item / "static.png"), "actionFrames": str(item)},
                "static": {"bagPlacement": [0, 0], "innerPlacement": [0, 0]},
                "action": {
                    "kind": "weapon", "library": "Weapon",
                    "frameCount": 1, "sourceFrameDigits": 1, "treatOneByOneAsEmpty": False,
                },
            })
        config_dir = root / "config"; config_dir.mkdir()
        # Targets intentionally sit outside the config directory: production
        # deployment paths are authorized by the task, not by a candidate-path
        # whitelist.
        config = config_dir / "append.json"
        config.write_text(json.dumps({
            "schemaVersion": 1, "operation": "equipment-graphics-append", "outputRoot": str(output),
            "startLooks": 8900, "expectedResourceCount": 42, "shapeStart": 1400,
            "encoding": {"alphaCutoff": 128, "staticType": "type6-bgr24-bottom-up"},
            "resources": resources,
            "target": {"serverRoot": str(root / "server-label"),
                "staticTargets": [
                    *[{"role": "client-static", "name": f"client {library}", "library": library, "wzl": str(client / f"{library}.wzl"), "wzx": str(client / f"{library}.wzx"), "expectedCount": 8900} for library in ("Items", "DnItems", "StateItem")],
                    *[{"role": "launcher-patch", "name": f"patch {library}", "library": library, "wzl": str(patch / f"{library}.wzl"), "wzx": str(patch / f"{library}.wzx"), "expectedCount": 8900} for library in ("Items", "DnItems", "StateItem")],
                ],
                "clientActionRoots": {"Weapon": [str(client / "Graphics" / "Weapon")]},
                "actionMirrorRoots": {"Weapon": [str(patch / "Graphics" / "Weapon")]},
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        pairs = [(directory / f"{library}.wzl", directory / f"{library}.wzx") for directory in (client, patch) for library in ("Items", "DnItems", "StateItem")]
        return root, config, pairs

    def test_append_42_resources_keeps_distinct_baselines_and_rolls_back(self):
        from xyequip.equipment_graphics import apply, preflight, rollback, verify_launcher

        root, config, pairs = self.fixture()
        original = [(wzl.read_bytes(), wzx.read_bytes()) for wzl, wzx in pairs]
        plan = preflight(config)
        self.assertFalse(plan["blockers"])
        self.assertEqual(list(range(8900, 8942)), [entry["looks"] for entry in plan["resourceMap"]])
        self.assertEqual(list(range(1401, 1443)), [entry["actionAssetId"] for entry in plan["resourceMap"]])
        self.assertEqual([], plan["databaseAccess"])

        applied = apply(config)
        self.assertEqual("applied", applied["status"])
        receipt = Path(applied["receiptPath"])
        self.assertEqual("verified", verify_launcher(receipt)["status"])
        for (wzl, wzx), (before_wzl, before_wzx) in zip(pairs, original):
            self.assertEqual(8942, count_slots(wzx))
            self.assertEqual(8942, struct.unpack_from("<I", wzl.read_bytes(), 44)[0])
            self.assertEqual(before_wzl[:44], wzl.read_bytes()[:44])
            self.assertEqual(before_wzl[48:], wzl.read_bytes()[48:len(before_wzl)])
            self.assertEqual(before_wzx[48:], wzx.read_bytes()[48:len(before_wzx)])
        # Candidate action assets are created for every resource in both roots.
        self.assertTrue((root / "targets" / "client" / "Graphics" / "Weapon" / "1442.wil").is_file())
        self.assertTrue((root / "targets" / "patch" / "Graphics" / "Weapon" / "1442.wix").is_file())

        snapshots = [(wzl.read_bytes(), wzx.read_bytes()) for wzl, wzx in pairs]
        repeated = apply(config)
        self.assertEqual("noop", repeated["status"])
        self.assertEqual(snapshots, [(wzl.read_bytes(), wzx.read_bytes()) for wzl, wzx in pairs])

        rolled = rollback(receipt)
        self.assertEqual("rolled-back", rolled["status"])
        self.assertEqual(original, [(wzl.read_bytes(), wzx.read_bytes()) for wzl, wzx in pairs])
        self.assertFalse((root / "targets" / "client" / "Graphics" / "Weapon" / "1442.wil").exists())

    def test_preflight_rejects_resource_count_that_differs_from_configured_expected_count(self):
        from xyequip.equipment_graphics.append import append_preflight

        _, config, _ = self.fixture(resource_count=41)
        result = append_preflight(config)
        self.assertTrue(any("expectedResourceCount" in blocker for blocker in result["blockers"]))

    def test_write_failure_restores_every_static_target_and_removes_new_action_files(self):
        from xyequip.equipment_graphics.append import append_apply
        from xyequip.equipment_graphics import transaction

        root, config, pairs = self.fixture()
        original = [(wzl.read_bytes(), wzx.read_bytes()) for wzl, wzx in pairs]
        calls = 0
        real_copy = transaction._atomic_copy

        def fail_after_two_writes(candidate: Path, target: Path) -> None:
            nonlocal calls
            calls += 1
            # Six static pairs consume 12 writes.  Fail while writing the
            # first action pair, after its WIL exists but before its WIX.
            if calls == 14:
                raise OSError("injected write failure")
            real_copy(candidate, target)

        with patch.object(transaction, "_atomic_copy", side_effect=fail_after_two_writes):
            with self.assertRaises(OSError):
                append_apply(config)
        self.assertEqual(original, [(wzl.read_bytes(), wzx.read_bytes()) for wzl, wzx in pairs])
        self.assertFalse((root / "targets" / "client" / "Graphics" / "Weapon" / "1401.wil").exists())

    def test_preflight_rejects_unknown_schema_version(self):
        from xyequip.equipment_graphics import preflight

        _, config, _ = self.fixture()
        body = json.loads(config.read_text(encoding="utf-8"))
        body["schemaVersion"] = 2
        config.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        result = preflight(config)
        self.assertTrue(any("schemaVersion" in blocker for blocker in result["blockers"]))

    def test_apply_rejects_action_target_created_after_preflight_without_overwriting_it(self):
        from xyequip.equipment_graphics import apply
        from xyequip.equipment_graphics import append as append_module
        from xyequip.equipment_graphics.append import EquipmentGraphicsAppendError

        root, config, pairs = self.fixture()
        static_before = [(wzl.read_bytes(), wzx.read_bytes()) for wzl, wzx in pairs]
        intruder = root / "targets" / "client" / "Graphics" / "Weapon" / "1401.wil"
        real_builder = append_module.build_action_wil_wix
        injected = False

        def create_intruder_then_build(**kwargs):
            nonlocal injected
            if not injected:
                intruder.write_bytes(b"external-after-preflight")
                injected = True
            return real_builder(**kwargs)

        with patch.object(append_module, "build_action_wil_wix", side_effect=create_intruder_then_build):
            with self.assertRaises(EquipmentGraphicsAppendError):
                apply(config)
        self.assertEqual(b"external-after-preflight", intruder.read_bytes())
        self.assertEqual(static_before, [(wzl.read_bytes(), wzx.read_bytes()) for wzl, wzx in pairs])


if __name__ == "__main__":
    unittest.main()
