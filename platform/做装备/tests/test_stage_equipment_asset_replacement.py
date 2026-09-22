from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xyequip.resources.stage_equipment_asset_replacement import deploy_staged_replacement


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_pair(directory: Path, name: str, count: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    wzl = bytearray(48)
    wzx = bytearray(48)
    struct.pack_into("<I", wzl, 44, count)
    struct.pack_into("<I", wzx, 44, count)
    wzx.extend(b"\x00" * (count * 4))
    (directory / f"{name}.wzl").write_bytes(wzl)
    (directory / f"{name}.wzx").write_bytes(wzx)


class StagedEquipmentAssetReplacementTests(unittest.TestCase):
    def test_deploy_rechecks_sources_and_replaces_client_launcher_database_and_map_as_one_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            client, launcher = root / "client", root / "launcher"
            run = root / "run"
            staging = run / "client_static_staging"
            for library in ("Items", "StateItem", "DnItems"):
                write_pair(client, library, 1)
                write_pair(launcher, library, 1)
                write_pair(staging, library, 2)
            database = root / "ApexM2.DB"
            con = sqlite3.connect(database)
            con.execute("CREATE TABLE StdItems (Idx INTEGER, Looks INTEGER, Shape INTEGER)")
            con.execute("INSERT INTO StdItems VALUES (1,7106,1)")
            con.commit()
            con.close()
            staged_db = run / database.name
            con = sqlite3.connect(staged_db)
            con.execute("CREATE TABLE StdItems (Idx INTEGER, Looks INTEGER, Shape INTEGER)")
            con.execute("INSERT INTO StdItems VALUES (1,7106,38)")
            con.commit()
            con.close()
            resource_map = root / "map.csv"
            resource_map.write_bytes(b"old-map")
            candidate = run / "装备资源映射表_稳定编号候选.csv"
            candidate.write_bytes(b"new-map")
            source_hashes = {
                str(path): sha(path)
                for path in [
                    *(client / f"{library}{ext}" for library in ("Items", "StateItem", "DnItems") for ext in (".wzl", ".wzx")),
                    database,
                    resource_map,
                ]
            }
            (run / "staging_receipt.json").write_text(json.dumps({
                "source_hashes": source_hashes,
                "static_count_after": 2,
                "shape_updates_detail": [{"idx": 1, "looks": 7106, "old_shape": 1, "new_shape": 38}],
            }), encoding="utf-8")

            result = deploy_staged_replacement(
                run_root=run,
                client_data=client,
                launcher_patch_data=launcher,
                database=database,
                resource_map=resource_map,
                backup_root=root / "backups",
            )

            self.assertEqual(2, result["client_counts"]["Items"])
            self.assertEqual(2, result["launcher_counts"]["DnItems"])
            self.assertEqual(b"new-map", resource_map.read_bytes())
            con = sqlite3.connect(database)
            try:
                self.assertEqual((7106, 38), con.execute("SELECT Looks, Shape FROM StdItems WHERE Idx=1").fetchone())
            finally:
                con.close()
            self.assertTrue((run / "deployment_receipt.json").is_file())

