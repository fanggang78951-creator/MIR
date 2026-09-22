from __future__ import annotations

import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from xyequip.equipment_graphics import transaction as TRANSACTION


class GraphicsTransactionContractTests(unittest.TestCase):
    def _manifest(self, root: Path, database: Path, candidate: Path, target: Path) -> Path:
        manifest = root / "equipment-graphics.json"
        manifest.write_text(json.dumps({
            "outputRoot": str(root / "output"),
            "target": {"database": str(database)},
            "preparedFiles": [{
                "candidate": str(candidate), "target": str(target),
                "candidateSha256": self._sha(candidate),
                "targetSha256": self._sha(target) if target.exists() else None,
            }],
        }), encoding="utf-8")
        return manifest

    @staticmethod
    def _sha(path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_new_resource_target_is_allowed_when_preflight_declares_missing_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            database = root / "ApexM2.DB"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE StdItems (Idx INTEGER, Shape INTEGER)")
                connection.commit()
            candidate = root / "candidate.wil"
            candidate.write_bytes(b"candidate")
            target = root / "new" / "target.wil"
            target.parent.mkdir(parents=True)
            manifest = self._manifest(root, database, candidate, target)
            result = TRANSACTION.apply_prepared(manifest_path=manifest, preflight={"configHash": "fixture", "shapeUpdates": []})
            self.assertEqual("applied", result["status"])
            self.assertEqual(candidate.read_bytes(), target.read_bytes())

    def test_new_resource_rolls_back_to_absent_target_and_database_before(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); database = root / "ApexM2.DB"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Looks INTEGER, Shape INTEGER)")
                connection.execute("INSERT INTO StdItems VALUES (1, '测试', 5, 10, 10)")
                connection.commit()
            db_before = self._sha(database)
            candidate = root / "candidate.wil"; candidate.write_bytes(b"candidate")
            target = root / "new" / "target.wil"; target.parent.mkdir(parents=True)
            manifest = self._manifest(root, database, candidate, target)
            result = TRANSACTION.apply_prepared(manifest_path=manifest, preflight={"configHash": "fixture", "shapeUpdates": []})
            self.assertEqual("rolled-back", TRANSACTION.rollback_receipt(Path(result["receiptPath"]))["status"])
            self.assertFalse(target.exists())
            self.assertEqual(db_before, self._sha(database))

    def test_rollback_rejects_database_drift_after_apply(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            database = root / "ApexM2.DB"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Looks INTEGER, Shape INTEGER, Note TEXT)")
                connection.execute("INSERT INTO StdItems VALUES (1, '测试', 5, 10, 10, 'before')")
                connection.commit()
            candidate = root / "candidate.wil"; candidate.write_bytes(b"candidate")
            target = root / "target.wil"; target.write_bytes(b"before")
            manifest = self._manifest(root, database, candidate, target)
            receipt = TRANSACTION.apply_prepared(manifest_path=manifest, preflight={
                "configHash": "fixture", "shapeUpdates": [{"idx": 1, "oldShape": 10, "newShape": 100}],
            })
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("UPDATE StdItems SET Note='external-change' WHERE Idx=1")
                connection.commit()
            with self.assertRaises(TRANSACTION.TransactionError):
                TRANSACTION.rollback_receipt(Path(receipt["receiptPath"]))

    def test_failed_transaction_removes_new_target_during_restore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); database = root / "ApexM2.DB"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Looks INTEGER, Shape INTEGER)")
                connection.execute("INSERT INTO StdItems VALUES (1, '测试', 5, 10, 10)")
                connection.commit()
            candidate = root / "candidate.wil"; candidate.write_bytes(b"candidate")
            target = root / "new" / "target.wil"
            target.parent.mkdir(parents=True)
            manifest = self._manifest(root, database, candidate, target)
            with self.assertRaises(TRANSACTION.TransactionError):
                TRANSACTION.apply_prepared(manifest_path=manifest, preflight={
                    "configHash": "fixture", "shapeUpdates": [{"idx": 1, "oldShape": 99, "newShape": 100}],
                })
            self.assertFalse(target.exists())

    def test_empty_prepared_transaction_is_a_noop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); database = root / "ApexM2.DB"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE StdItems (Idx INTEGER, Shape INTEGER)")
                connection.commit()
            manifest = root / "equipment-graphics.json"
            manifest.write_text(json.dumps({
                "outputRoot": str(root / "output"), "target": {"database": str(database)}, "preparedFiles": [],
            }), encoding="utf-8")
            result = TRANSACTION.apply_prepared(manifest_path=manifest, preflight={"configHash": "fixture", "shapeUpdates": [], "expectedFiles": [{"target": "a.wil", "after": "a"}, {"target": "b.wix", "after": "b"}]})
            self.assertEqual("noop", result["status"])
            receipt = json.loads(Path(result["receiptPath"]).read_text(encoding="utf-8"))
            self.assertEqual(2, len(receipt["expectedFiles"]))
            self.assertEqual(receipt["database"]["before"], receipt["database"]["after"])
            self.assertFalse((Path(result["receiptPath"]).parent / "original").exists())

    def test_identical_files_and_unchanged_shape_return_noop_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); database = root / "ApexM2.DB"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Looks INTEGER, Shape INTEGER)")
                connection.execute("INSERT INTO StdItems VALUES (1, '测试', 5, 10, 10)")
                connection.commit()
            candidate = root / "candidate.wil"; candidate.write_bytes(b"same")
            target = root / "target.wil"; target.write_bytes(b"same")
            manifest = self._manifest(root, database, candidate, target)
            result = TRANSACTION.apply_prepared(manifest_path=manifest, preflight={
                "configHash": "fixture", "shapeUpdates": [{"idx": 1, "oldShape": 10, "newShape": 10}],
                "expectedFiles": [{"target": str(target), "after": self._sha(candidate), "role": "client"}] * 16,
            })
            self.assertEqual("noop", result["status"])
            receipt = json.loads(Path(result["receiptPath"]).read_text(encoding="utf-8"))
            self.assertEqual("noop", receipt["status"])
            self.assertEqual(16, len(receipt["expectedFiles"]))

    def test_noop_receipt_keeps_source_hashes_and_verifiable_expected_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); database = root / "ApexM2.DB"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE StdItems (Idx INTEGER, Shape INTEGER)")
                connection.commit()
            client = root / "client.wil"; patch = root / "patch.wil"
            client.write_bytes(b"same"); patch.write_bytes(b"same")
            source_hashes = {str(root / "source.png"): "source-fingerprint"}
            manifest = root / "equipment-graphics.json"
            manifest.write_text(json.dumps({
                "outputRoot": str(root / "output"), "target": {"database": str(database)}, "preparedFiles": [],
            }), encoding="utf-8")
            result = TRANSACTION.apply_prepared(manifest_path=manifest, preflight={
                "configHash": "fixture", "sourceHashes": source_hashes, "shapeUpdates": [],
                "expectedFiles": [
                    {"target": str(client), "after": self._sha(client), "role": "client-action"},
                    {"target": str(patch), "after": self._sha(patch), "role": "launcher-action"},
                ],
            })
            receipt = json.loads(Path(result["receiptPath"]).read_text(encoding="utf-8"))
            self.assertEqual(source_hashes, receipt["sourceHashes"])
            self.assertEqual(2, len(receipt["expectedFiles"]))
            self.assertEqual(["client-action", "launcher-action"], [item["role"] for item in receipt["expectedFiles"]])

    def test_nonempty_database_sidecar_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); database = root / "ApexM2.DB"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE StdItems (Idx INTEGER, Name TEXT, StdMode INTEGER, Looks INTEGER, Shape INTEGER)")
                connection.commit()
            (root / "ApexM2.DB-wal").write_bytes(b"pending")
            candidate = root / "candidate.wil"; candidate.write_bytes(b"candidate")
            target = root / "target.wil"; target.write_bytes(b"before")
            manifest = self._manifest(root, database, candidate, target)
            with self.assertRaises(TRANSACTION.TransactionError):
                TRANSACTION.apply_prepared(manifest_path=manifest, preflight={"configHash": "fixture", "shapeUpdates": []})


if __name__ == "__main__":
    unittest.main()
