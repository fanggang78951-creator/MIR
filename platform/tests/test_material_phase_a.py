from __future__ import annotations

import json
import sqlite3
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class MaterialPhaseATests(unittest.TestCase):
    def test_icon_manifest_is_items_only_and_exact_range(self):
        from xydp.material_phase_a import validate_icon_manifest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            materials = []
            for idx in range(907, 972):
                icon = root / f"{idx}.png"
                icon.write_bytes(f"png-{idx}".encode("ascii"))
                materials.append({"idx": idx, "name": f"材料{idx}", "icon": icon.name, "library": "Items"})
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"materials": materials}, ensure_ascii=False), encoding="utf-8")
            rows = validate_icon_manifest(manifest)
            self.assertEqual([row["idx"] for row in rows], list(range(907, 972)))
            self.assertEqual({row["library"] for row in rows}, {"Items"})

    def test_database_plan_protects_existing_and_reserved_rows(self):
        from xydp.material_phase_a import preflight_database

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "ApexM2.DB"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Shape INTEGER, Looks INTEGER, DuraMax INTEGER, Color INTEGER, OverLap INTEGER)")
            for idx in (793, 794, 802):
                connection.execute("INSERT INTO StdItems VALUES (?, ?, 46, 1, ?, 99999, 251, 2)", (idx, f"保护{idx}", 6000 + idx))
            connection.commit()
            connection.close()
            materials = [{"idx": idx, "name": f"材料{idx}", "looks": 6398 + idx - 907, "colorValue": 251, "templateIdx": 793} for idx in range(907, 972)]
            report = preflight_database(database, materials)
            self.assertEqual(report["pendingCount"], 65)
            self.assertEqual(report["protectedIdx"], [793, 794, 802])
            self.assertEqual(report["reservedRange"], [972, 983])

    def test_wzl_readback_compares_client_visible_black_key_pixels(self):
        from PIL import Image
        from xydp.material_phase_a import _pixel_bytes

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            readback = root / "readback.png"
            Image.new("RGBA", (1, 1), (0, 85, 85, 3)).save(source)
            Image.new("RGBA", (1, 1), (0, 1, 1, 255)).save(readback)
            self.assertEqual(_pixel_bytes(source), _pixel_bytes(readback))

    def test_database_transaction_rolls_back_byte_identically(self):
        from xydp.material_phase_a import apply_database_transaction, rollback

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "ApexM2.DB"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Shape INTEGER, Weight INTEGER, "
                "Anicount INTEGER, Source INTEGER, Reserved INTEGER, Looks INTEGER, DuraMax INTEGER, Need INTEGER, "
                "NeedLevel INTEGER, Price INTEGER, Stock INTEGER, Color INTEGER, OverLap INTEGER)"
            )
            for idx in (793, 794, 802):
                connection.execute("INSERT INTO StdItems VALUES (?,?,46,1,0,0,0,0,?,99999,0,0,0,5,251,2)", (idx, f"保护{idx}", 6000 + idx))
            connection.commit()
            connection.close()
            before = hashlib.sha256(database.read_bytes()).hexdigest().upper()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"materials": [
                {"idx": idx, "name": f"材料{idx}", "looks": 6398 + idx - 907, "colorValue": 251, "templateIdx": 793}
                for idx in range(907, 972)
            ]}, ensure_ascii=False), encoding="utf-8")
            receipt = apply_database_transaction(manifest, database)
            try:
                self.assertNotEqual(hashlib.sha256(database.read_bytes()).hexdigest().upper(), before)
                result = rollback(Path(receipt["receiptPath"]))
                self.assertEqual(result["status"], "rolled_back_verified")
                self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest().upper(), before)
            finally:
                Path(receipt["receiptPath"]).unlink(missing_ok=True)
                shutil.rmtree(Path(receipt["backup"]).parents[1], ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
