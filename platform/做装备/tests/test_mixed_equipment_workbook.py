import csv
from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / '做装备/src'), str(ROOT / 'src')]
from test_equipment_preflight import make_target, tree_hash
from test_shared_equipment_workbook_contract import make_client
from xydp.equipment_bridge import EquipmentBridge
from xyequip.batch import BatchSourceError
from xyequip.installer import EquipmentInstallError


class MixedEquipmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.server = self.root / 'server'
        self.client = self.root / 'client'
        make_target(self.server)
        make_client(self.client)
        self.bridge = EquipmentBridge(ROOT)
        self.bridge.installer.backup_root = self.root / 'backups'
        self.file = self.root / 'mixed.csv'

    def plan(self, rows):
        with self.file.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['名称', '部位', '来源编号', '防御'])
            writer.writeheader()
            writer.writerows(rows)
        return self.bridge.preflight(self.file, self.server, self.client)

    def rows(self, update_source=''):
        return [{'名称':'青铜头盔', '防御':'3-8', '来源编号':update_source},
                {'名称':'混合新头盔', '部位':'头盔', '来源编号':'2', '防御':'5-9'}]

    def test_mixed_create_update_and_exact_rollback(self):
        before, client_before = tree_hash(self.server), tree_hash(self.client)
        plan = self.plan(self.rows())
        self.assertEqual(plan.blockers, [])
        self.assertEqual(tree_hash(self.server), before)
        receipt = self.bridge.install(plan)
        with closing(sqlite3.connect(self.server / 'Mud2/DB/ApexM2.DB')) as c:
            self.assertEqual(c.execute('SELECT Name,Ac,Ac2,Looks FROM StdItems ORDER BY Idx').fetchall(),
                             [('青铜头盔',3,8,1),('混合新头盔',5,9,2)])
        self.assertEqual(tree_hash(self.client), client_before)
        data = json.loads(Path(receipt.receipt_path).read_text(encoding='utf-8'))
        self.assertEqual(data['row_operations'], {'青铜头盔':'update','混合新头盔':'create'})
        repeat = self.bridge.preflight(self.file, self.server, self.client)
        self.assertEqual(repeat.blockers, [])
        self.assertEqual([r.operation for r in repeat.compiled.rows], ['update','update'])
        self.bridge.rollback(self.server, receipt.transaction_id)
        restored = tree_hash(self.server)
        restored.pop('.xydp/equipment-installed.json', None)
        self.assertEqual(restored, before)
        self.assertEqual(tree_hash(self.client), client_before)

    def test_update_source_reuse_in_same_transaction(self):
        before = tree_hash(self.client)
        plan = self.plan(self.rows('2'))
        self.assertEqual(plan.blockers, [])
        self.assertEqual(sum(c.scope == 'client' for c in plan.changes), 0)
        receipt = self.bridge.install(plan)
        with closing(sqlite3.connect(self.server / 'Mud2/DB/ApexM2.DB')) as c:
            self.assertEqual(c.execute("SELECT Looks FROM StdItems WHERE Name='青铜头盔'").fetchone()[0], 2)
            self.assertEqual(c.execute("SELECT Looks FROM StdItems WHERE Name='混合新头盔'").fetchone()[0], 2)
        self.bridge.rollback(self.server, receipt.transaction_id)
        self.assertEqual(tree_hash(self.client), before)

    def test_missing_source_only_blocks_new_row(self):
        rows = self.rows(); rows[1]['来源编号']=''
        plan = self.plan(rows)
        self.assertTrue(any('混合新头盔' in b and '来源编号' in b for b in plan.blockers))
        self.assertFalse(any('青铜头盔' in b for b in plan.blockers))

    def test_duplicate_sheet_names_rejected(self):
        with self.assertRaises(BatchSourceError):
            self.plan([self.rows()[0],self.rows()[0]])

    def test_later_failure_preserves_target_and_client(self):
        plan = self.plan(self.rows('2'))
        before, client_before = tree_hash(self.server), tree_hash(self.client)
        with patch('xyequip.legacy.xy_equip_maker.make_equipment', side_effect=RuntimeError('injected')):
            with self.assertRaises(EquipmentInstallError):
                self.bridge.install(plan)
        self.assertEqual(tree_hash(self.server), before)
        self.assertEqual(tree_hash(self.client), client_before)

    def test_changed_database_after_plan_cannot_overwrite(self):
        plan = self.plan(self.rows())
        with closing(sqlite3.connect(self.server / 'Mud2/DB/ApexM2.DB')) as c:
            c.execute("UPDATE StdItems SET Ac=77 WHERE Name='青铜头盔'")
            c.commit()
        before = tree_hash(self.server)
        with self.assertRaises(EquipmentInstallError):
            self.bridge.install(plan)
        self.assertEqual(tree_hash(self.server), before)
