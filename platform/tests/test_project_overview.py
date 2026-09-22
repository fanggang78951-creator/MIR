import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from xydp.project_overview import ProjectOverview


class ProjectOverviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.write('所需材料表格汇总/00_填写文档注册表.json', {'documents': [
            {'id': 'equipment_wash_import', 'file': '洗练属性.txt', 'consumer': 'equipment-wash-import'}]})
        self.write('所需材料表格汇总/洗练属性.txt', '洗练说明')
        self.manifest = 'packages/verified/test.wash/manifest.json'
        self.write(self.manifest, {'id': 'test.wash', 'display_name': '测试洗练', 'version': '1', 'status': 'verified', 'dependencies': [], 'operations': [{'type': 'unique_line', 'target': 'sample.txt', 'line': 'ok'}]})
        self.write('src/xydp/equipment_wash.py', '# baseline')
        self.write('run_cli.py', '# platform CLI entry')
        self.service = ProjectOverview(self.root)

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else data, encoding='utf-8')
        return path

    def test_manifest_verified_does_not_inherit_game_acceptance(self):
        card = self.service.get('package:test.wash')
        self.assertFalse(card['dispatch_ready'])
        self.assertEqual(card['package_status'], 'verified')
        self.assertIn('验收', ' '.join(card['limitations']))

    def test_source_change_invalidates_version_bound_acceptance(self):
        paths = [self.manifest, 'src/xydp/equipment_wash.py']
        marks = {p: hashlib.sha256((self.root/p).read_bytes()).hexdigest() for p in paths}
        evidence = self.write('evidence/game.json', {'passed': True})
        self.write('catalog/feature_annotations.json', {'schema_version': 1, 'features': {'package:test.wash': {
            'game_verified': True, 'verified_fingerprints': marks,
            'evidence': [{'path': str(evidence), 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}]}}})
        self.assertTrue(self.service.get('package:test.wash')['dispatch_ready'])
        self.write('src/xydp/equipment_wash.py', '# changed')
        self.assertFalse(self.service.get('package:test.wash')['dispatch_ready'])

    def test_config_card_has_real_route_and_input_hash(self):
        card = self.service.get('document:equipment_wash_import')
        self.assertEqual(card['entry']['tab'], '脚本配置同步')
        self.assertEqual(card['inputs'][0]['path'], str(self.root/'所需材料表格汇总/洗练属性.txt'))
        self.assertEqual(len(card['inputs'][0]['sha256']), 64)

    def test_release_change_invalidates_acceptance_even_when_sources_are_identical(self):
        release = 'catalog/current-release.json'
        self.write(release, {'release_id':'r1','cli':{'sha256':'a'*64}})
        card = self.service.get('package:test.wash')
        self.assertIn(release, card['required_fingerprints'])
        marks = {p:hashlib.sha256((self.root/p).read_bytes()).hexdigest() for p in card['required_fingerprints']}
        evidence = self.write('evidence/game.json', {'passed':True})
        self.write('catalog/feature_annotations.json', {'features':{'package:test.wash':{
            'game_verified':True,'verified_fingerprints':marks,
            'evidence':[{'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}]}}})
        self.assertTrue(self.service.get('package:test.wash')['capability_verified'])
        self.write(release, {'release_id':'r1','cli':{'sha256':'b'*64}})
        self.assertFalse(self.service.get('package:test.wash')['capability_verified'])
        self.assertFalse(self.service.get('package:test.wash')['dispatch_ready'])

    def test_acceptance_missing_existing_release_fingerprint_is_rejected(self):
        self.write('catalog/current-release.json', {'release_id':'r1'})
        marks = {p:hashlib.sha256((self.root/p).read_bytes()).hexdigest()
                 for p in [self.manifest,'src/xydp/equipment_wash.py']}
        evidence = self.write('evidence/game.json', {'passed':True})
        self.write('catalog/feature_annotations.json', {'features':{'package:test.wash':{
            'game_verified':True,'verified_fingerprints':marks,
            'evidence':[{'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}]}}})
        self.assertFalse(self.service.get('package:test.wash')['capability_verified'])

    def test_registry_path_escape_is_blocked(self):
        self.write('所需材料表格汇总/00_填写文档注册表.json', {'documents': [{'id':'bad','file':'../secret.txt','consumer':'equipment'}]})
        with self.assertRaises(ValueError): self.service.cards()

    def test_missing_input_disables_ready_and_preserves_card(self):
        (self.root/'所需材料表格汇总/洗练属性.txt').unlink()
        card = self.service.get('document:equipment_wash_import')
        self.assertFalse(card['dispatch_ready'])
        self.assertFalse(card['inputs'][0]['exists'])

    def test_read_only_catalog_does_not_write(self):
        before = sorted(str(x.relative_to(self.root)) for x in self.root.rglob('*'))
        self.service.cards()
        self.assertEqual(before, sorted(str(x.relative_to(self.root)) for x in self.root.rglob('*')))

    def test_validation_order_binds_inputs_and_never_has_install_command(self):
        order = self.service.task_order('document:equipment_wash_import', self.root/'target', validation=True)
        self.assertEqual(order['mode'], 'validation')
        self.assertIn('config-sync-preflight', order['preflight_argv'])
        self.assertNotIn('--yes', order['preflight_argv'])
        self.assertFalse(order['target_write_authorized'])
        self.assertEqual(order['handoff_owner'], '总控')

    def test_unverified_production_order_is_blocked(self):
        with self.assertRaises(ValueError):
            self.service.task_order('document:equipment_wash_import', self.root/'target')

    def test_unknown_consumer_is_not_routed_to_generic_installer(self):
        self.write('所需材料表格汇总/00_填写文档注册表.json', {'documents': [{'id':'new','file':'洗练属性.txt','consumer':'unknown-new'}]})
        card = self.service.get('document:new')
        self.assertFalse(card['entry']['supported'])

    def test_arbitrary_annotation_cannot_certify_unbound_registry(self):
        evidence = self.write('evidence/game.json', {'passed': True})
        source = 'src/xydp/equipment_wash.py'
        self.write('catalog/feature_annotations.json', {'features': {'document:equipment_wash_import': {
            'game_verified': True, 'verified_fingerprints': {source: hashlib.sha256((self.root/source).read_bytes()).hexdigest()},
            'evidence': [{'path': str(evidence), 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}]}}})
        self.assertFalse(self.service.get('document:equipment_wash_import')['capability_verified'])

    def test_input_change_requires_new_preflight_without_erasing_capability(self):
        evidence = self.write('evidence/game.json', {'passed': True})
        paths = ['src/xydp/equipment_wash.py', '所需材料表格汇总/00_填写文档注册表.json']
        self.write('catalog/feature_annotations.json', {'features': {'document:equipment_wash_import': {
            'game_verified': True, 'verified_fingerprints': {p:hashlib.sha256((self.root/p).read_bytes()).hexdigest() for p in paths},
            'accepted_input_hashes': {'洗练属性.txt': hashlib.sha256((self.root/'所需材料表格汇总/洗练属性.txt').read_bytes()).hexdigest()},
            'evidence': [{'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}]}}})
        self.assertTrue(self.service.get('document:equipment_wash_import')['dispatch_ready'])
        self.write('所需材料表格汇总/洗练属性.txt', '合法数值变化，由平台预检判定')
        card = self.service.get('document:equipment_wash_import')
        self.assertTrue(card['capability_verified'])
        self.assertFalse(card['dispatch_ready'])
        self.assertTrue(card['configuration_changed'])

    def test_specialist_package_uses_registered_configuration_entry(self):
        manifest = json.loads((self.root/self.manifest).read_text(encoding='utf-8'))
        manifest['install_route'] = 'equipment-wash-import'
        self.write(self.manifest, manifest)
        card = self.service.get('package:test.wash')
        self.assertEqual(card['entry']['tab'], '脚本配置同步')
        order = self.service.task_order(card['id'], self.root/'target', validation=True)
        self.assertIn('config-sync-preflight', order['preflight_argv'])
        self.assertNotIn('--package', order['preflight_argv'])

    def test_missing_platform_entry_cannot_create_executable_task_order(self):
        (self.root/'run_cli.py').unlink()
        with self.assertRaisesRegex(ValueError, '入口'):
            self.service.task_order('document:equipment_wash_import', self.root/'target', validation=True)

    def test_results_show_only_selected_route_and_target(self):
        self.write('backups/equipment-wash-import/one/receipt.json', {'operation':'equipment-wash-import', 'server':str(self.root/'target'), 'transaction_id':'one', 'status':'installed-pending-game-verification'})
        self.write('backups/equipment-wash-import/two/receipt.json', {'server':str(self.root/'other'), 'transaction_id':'two', 'status':'installed'})
        self.write('backups/unrelated/three/receipt.json', {'server':str(self.root/'target'), 'transaction_id':'three'})
        results = self.service.results('document:equipment_wash_import', self.root/'target')
        self.assertEqual([r['transaction_id'] for r in results], ['one'])

    def test_results_reject_wrong_operation_and_show_rollback(self):
        data = {'operation':'equipment-wash-import', 'server':str(self.root/'target'), 'transaction_id':'one', 'status':'installed-pending-game-verification'}
        self.write('backups/equipment-wash-import/one/receipt.json', data)
        self.write('backups/equipment-wash-import/one/rollback.json', {'operation':'equipment-wash-import-rollback','transaction_id':'one','status':'rolled-back'})
        self.write('backups/equipment-wash-import/two/receipt.json', dict(data,operation='weapon-enchant',transaction_id='two'))
        results = self.service.results('document:equipment_wash_import', self.root/'target')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'rolled-back')
        self.assertTrue(results[0]['rollback_sha256'])

    def test_optional_wash_parameters_are_bound_but_not_passed_as_registered_document(self):
        card = self.service.get('document:equipment_wash_import')
        self.assertFalse(card['auxiliary_inputs'][0]['exists'])
        self.write('所需材料表格汇总/洗练目标参数.json', {'NPC名称':'洗练测试'})
        order = self.service.task_order(card['id'], self.root/'target', validation=True)
        self.assertTrue(order['auxiliary_inputs'][0]['sha256'])
        self.assertNotIn(order['auxiliary_inputs'][0]['path'], order['preflight_argv'])


if __name__ == '__main__': unittest.main()
