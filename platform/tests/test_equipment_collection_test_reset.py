from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_equipment_collection import FIXTURE, _client, _hash, _platform, _server
from xydp.encoding import read_text_document
from xydp.equipment_collection import EquipmentCollectionService
from xydp.equipment_collection_test_reset import EquipmentCollectionTestResetService


class EquipmentCollectionTestResetTests(unittest.TestCase):
    def test_reset_requires_collection_core(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = EquipmentCollectionTestResetService(root / "platform").preflight(_server(root))
            self.assertTrue(any("@XY_COLLECTION_REFRESH" in item for item in plan.blockers))
            self.assertEqual(plan.changes, [])

    def test_install_is_idempotent_and_rollback_restores_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            platform = _platform(root)
            server = _server(root)
            client = _client(root)
            collection = EquipmentCollectionService(platform)
            collection.install(collection.preflight(FIXTURE, server, client))

            qfunction = server / "Mir200" / "Envir" / "Market_Def" / "QFunction-0.txt"
            usercmd = server / "Mir200" / "Envir" / "UserCmd.txt"
            before = {path: _hash(path) for path in (qfunction, usercmd)}

            service = EquipmentCollectionTestResetService(platform)
            plan = service.preflight(server)
            self.assertEqual(plan.blockers, [])
            receipt = service.install(plan)
            generated = qfunction.read_text(encoding="gb18030")
            self.assertIn("[@XY_COLLECTION_TEST_RESET]", generated)
            for flag in (400, 401, 402, 600):
                self.assertIn(f"SET [{flag}] 0", generated)
            self.assertIn("清空收集测试\t93", read_text_document(usercmd).text)

            second = service.preflight(server)
            self.assertEqual(second.blockers, [])
            self.assertEqual(second.changes, [])

            collection_second = collection.preflight(FIXTURE, server, client)
            self.assertEqual(collection_second.blockers, [])
            self.assertEqual(collection_second.changes, [])

            service.rollback(server, receipt.transaction_id)
            self.assertEqual({path: _hash(path) for path in (qfunction, usercmd)}, before)


if __name__ == "__main__":
    unittest.main()
