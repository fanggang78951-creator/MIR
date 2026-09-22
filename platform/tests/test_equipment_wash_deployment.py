import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_equipment_wash_import import SOURCE
from xydp.equipment_wash import (
    ATTACK_SPEED_CORE_RELATIVE, DIRECT_SPECS, EFFECT_CORE_RELATIVE, EquipmentWashImportService,
    MAIN_RELATIVE, PACKAGE_ID, QFUNCTION_RELATIVE, RANDOM_CORE_RELATIVE, STATE_RELATIVE,
    TEXTVAR_RELATIVE, WASH_DIRECTORY, check_external_calls, render_direct_script,
)
from xydp.mingge_dual import _script_bytes, _script_text
from xydp.config_sync import ConfigSyncService
from xydp.installer import Installer
from xydp.repository import PackageRepository

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'packages/verified' / PACKAGE_ID


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.name.endswith('.lock')}


def fixture(base, current=False, params=None):
    platform = base / 'platform'
    shutil.copytree(PACKAGE, platform / 'packages/verified' / PACKAGE_ID)
    docs = platform / '所需材料表格汇总'
    docs.mkdir()
    source = docs / '洗练属性.txt'
    source.write_text(SOURCE, encoding='utf-8')
    (docs / '00_填写文档注册表.json').write_text(json.dumps({'documents': [{'id': 'equipment_wash_import', 'file': source.name, 'consumer': 'equipment-wash-import'}]}), encoding='utf-8')
    if params:
        (docs / '洗练目标参数.json').write_text(json.dumps(params, ensure_ascii=False), encoding='utf-8')
    server = base / 'server'
    if current:
        shutil.copytree(ROOT / 'tests/fixtures/equipment_wash_current', server)
    else:
        for rel, text in {
            QFUNCTION_RELATIVE: '[@PlayLogin]\n#IF\n#ACT\nBREAK\n[@TakeOnEx]\n#IF\n#ACT\nBREAK\n[@TakeOffEx]\n#IF\n#ACT\nBREAK\n[@Combat]\n#IF\n#ACT\nMOV N$XY_RT_DamageCoeff 100\nMOV N$XY_最大爆率 100\nMOV N$XY_SUS_LifeStealHeal 0\n; XY_EXECUTION_LAB_TOUGHNESS_ANCHOR\nMOV N$XY_MDA_Final 0\nBREAK',
            ATTACK_SPEED_CORE_RELATIVE: '[@Speed]\n{\n#IF\n#ACT\nMOV N$XY_AS_RAW <$HITSPD>\nGetAllCustomItemValueByTextLine 60 -1 40 N$TMP N$BREAKTHROUGH N$TMP\nBREAK\n}',
            TEXTVAR_RELATIVE: '\n'.join(['']*39 + ['{攻速突破∶|251}+$$2']),
            Path('Mir200/Envir/MapInfo.txt'): '[XY_NMGF_MAIN|宁姆格福]\n[NEW_MAP|新地图]',
            Path('Mir200/Envir/EffectImageList.txt'): 'OtherResource.wz',
            Path('Mir200/Envir/MerChant.txt'): '',
        }.items():
            dest = server / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_script_bytes(text))
    client = base / 'client'
    shutil.copytree(PACKAGE / 'payload/client', client / 'data')
    return platform, server, client, source


class WashDeploymentTests(unittest.TestCase):
    def test_fresh_install_uses_generated_quality_scripts_and_rolls_back_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            platform, server, client, source = fixture(Path(td))
            service = EquipmentWashImportService(platform)
            before = snapshot(server)
            client_before = snapshot(client)
            plan = service.preflight(server, source, client=client)
            self.assertFalse(plan.blockers, plan.blockers)
            self.assertEqual(len(plan.external_calls), 46)
            receipt = service.install(plan)
            main = _script_text((server / MAIN_RELATIVE).read_bytes())
            self.assertIn('OPENMERCHANTBIGDLG 1 ', main)
            self.assertIn('<ITEMBOX:27:1:', main)
            self.assertIn('GAMEGOLD - 100', main.upper())
            self.assertEqual(main.count('洗练词条随机核心.txt'), 8)
            self.assertFalse(service.preflight(server, source, client=client).changes)
            service.rollback(server, receipt.transaction_id)
            self.assertEqual(snapshot(server), before)
            self.assertEqual(snapshot(client), client_before)

    def test_stateless_legacy_runtime_is_upgraded_then_idempotent_and_reversible(self):
        with tempfile.TemporaryDirectory() as td:
            platform, server, client, source = fixture(Path(td), current=True)
            service = EquipmentWashImportService(platform)
            plan = service.preflight(server, source, client=client)
            self.assertFalse(plan.blockers, plan.blockers)
            self.assertEqual({c.relative_path for c in plan.changes}, {MAIN_RELATIVE.as_posix(), RANDOM_CORE_RELATIVE.as_posix(), STATE_RELATIVE.as_posix(), *[(WASH_DIRECTORY / s[0]).as_posix() for s in DIRECT_SPECS]})
            before = snapshot(server)
            receipt = service.install(plan)
            main = _script_text((server / MAIN_RELATIVE).read_bytes())
            self.assertIn('EQUAL N$XY_WASH_BUSY_V2 1', main)
            self.assertNotIn('N$XYEW_W_洗练CD', main)
            core = _script_text((server / RANDOM_CORE_RELATIVE).read_bytes())
            self.assertIn('[@XY_WASH_PICK_NORMAL_27_CATEGORY_14]', core)
            again = service.preflight(server, source, client=client)
            self.assertFalse(again.blockers, again.blockers)
            self.assertFalse(again.changes)
            service.rollback(server, receipt.transaction_id)
            self.assertEqual(snapshot(server), before)

    def test_input_edit_rebuilds_random_values_and_reversible_state(self):
        with tempfile.TemporaryDirectory() as td:
            platform, server, client, source = fixture(Path(td))
            service = EquipmentWashImportService(platform)
            service.install(service.preflight(server, source, client=client))
            before = snapshot(server)
            source.write_text(SOURCE.replace('韧性+20', '韧性+25'), encoding='utf-8')
            plan = service.preflight(server, source, client=client)
            self.assertFalse(plan.blockers, plan.blockers)
            self.assertEqual({c.relative_path for c in plan.changes}, {RANDOM_CORE_RELATIVE.as_posix(), STATE_RELATIVE.as_posix()})
            receipt = service.install(plan)
            self.assertIn('MOV N$XY_WASH_PICK_VALUE 25', _script_text((server / RANDOM_CORE_RELATIVE).read_bytes()))
            self.assertFalse(service.preflight(server, source, client=client).changes)
            service.rollback(server, receipt.transaction_id)
            self.assertEqual(snapshot(server), before)

    def test_new_target_chinese_parameters_and_config_sync_use_same_core(self):
        with tempfile.TemporaryDirectory() as td:
            params = {'洗练NPC脚本': '新服/重铸', '洗练NPC名称': '新服洗练师', '洗练地图': 'NEW_MAP', '洗练坐标X': 10, '洗练坐标Y': 20,
                      '开光NPC脚本': '新服/开光', '开光地图': 'NEW_MAP', '洗练核心目录': '新服/洗练核心'}
            platform, server, client, source = fixture(Path(td), params=params)
            sync = ConfigSyncService(platform)
            outer = sync.preflight(server, [source], client)
            direct = EquipmentWashImportService(platform).preflight(server, source, client=client)
            self.assertFalse(outer.blockers, outer.blockers)
            self.assertEqual(outer.inner_plan.plan_id, direct.plan_id)
            self.assertEqual([(c.relative_path,c.after) for c in outer.changes], [(c.relative_path,c.after) for c in direct.changes])
            sync.install(outer)
            main = (server / 'Mir200/Envir/Market_Def/新服/重铸-NEW_MAP.txt').read_text(encoding='gb18030')
            self.assertIn('新服洗练师', main)
            self.assertIn('\\新服\\洗练核心\\洗练词条随机核心.txt', main)
            self.assertFalse((server / MAIN_RELATIVE).exists())
            self.assertFalse(sync.preflight(server, [source], client).changes)

    def test_ordinary_package_entry_is_blocked_even_if_old_manifest_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            platform, server, client, source = fixture(Path(td))
            repo = PackageRepository(platform / 'packages'); repo.refresh()
            installer = Installer(repo, platform / 'backups')
            with self.assertRaisesRegex(Exception, 'equipment-wash-import'):
                installer.preflight(server, [PACKAGE_ID], {}, client_root=client)

    def test_dependencies_and_shared_blocks_block_without_partial_changes(self):
        for corruption in ('missing_speed', 'missing_toughness', 'textvar', 'unknown_marker', 'client', 'duplicate_resource', 'duplicate_map'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as td:
                platform, server, client, source = fixture(Path(td))
                service = EquipmentWashImportService(platform)
                if corruption == 'missing_speed': (server / ATTACK_SPEED_CORE_RELATIVE).unlink()
                elif corruption == 'missing_toughness':
                    path = server / QFUNCTION_RELATIVE
                    path.write_bytes(path.read_bytes().replace(b'; XY_EXECUTION_LAB_TOUGHNESS_ANCHOR', b'; missing'))
                elif corruption == 'textvar':
                    path = server / TEXTVAR_RELATIVE
                    path.write_bytes(path.read_bytes() + b'\r\n\r\noccupied\r\n')
                elif corruption == 'unknown_marker':
                    service.install(service.preflight(server, source, client=client))
                    path = server / QFUNCTION_RELATIVE
                    path.write_bytes(path.read_bytes().replace(b'DELAYGOTO 1500', b'DELAYGOTO 2500'))
                elif corruption == 'client': (client / 'data/XY_EquipmentWorkbench.wzx').write_bytes(b'wrong')
                elif corruption == 'duplicate_resource': (server / 'Mir200/Envir/EffectImageList.txt').write_bytes(b'XY_EquipmentWorkbench.wz\r\nXY_EquipmentWorkbench.wz\r\n')
                elif corruption == 'duplicate_map':
                    path = server / 'Mir200/Envir/MapInfo.txt'; path.write_bytes(path.read_bytes() + b'[XY_NMGF_MAIN]\r\n')
                before = snapshot(server)
                plan = service.preflight(server, source, client=client)
                self.assertTrue(plan.blockers, corruption)
                self.assertFalse(plan.changes)
                self.assertEqual(snapshot(server), before)

    def test_all_read_inputs_rechecked_including_noop_dependencies(self):
        for rel in (Path('Mir200/Envir/MapInfo.txt'), RANDOM_CORE_RELATIVE):
            with self.subTest(rel=rel), tempfile.TemporaryDirectory() as td:
                platform, server, client, source = fixture(Path(td))
                service = EquipmentWashImportService(platform)
                service.install(service.preflight(server, source, client=client))
                source.write_text(SOURCE.replace('韧性+20', '韧性+25'), encoding='utf-8')
                plan = service.preflight(server, source, client=client)
                (server / rel).write_bytes((server / rel).read_bytes() + b'; drift\r\n')
                before = snapshot(server)
                with self.assertRaisesRegex(Exception, '变化'): service.install(plan)
                self.assertEqual(snapshot(server), before)

    def test_actual_call_graph_checks_all_four_quality_entries_and_ignores_internal_goto(self):
        core = WASH_DIRECTORY / '被调用.txt'
        def missing(rel): raise AssertionError(rel)
        scripts = {MAIN_RELATIVE: '#CALL [\\玄渊实验室\\装备洗练\\被调用.txt] @PUBLIC\n',
                   core: '[@PUBLIC]\n{\n#IF\n#ACT\nGOTO @PRIVATE\nBREAK\n}\n[@PRIVATE]\n#IF\n#ACT\nBREAK\n'}
        self.assertEqual(len(check_external_calls(scripts, missing)), 1)
        scripts[core] = scripts[core].replace('[@PUBLIC]\n{', '[@PUBLIC]')
        with self.assertRaisesRegex(ValueError, '脚本块'): check_external_calls(scripts, missing)

    def test_every_actual_quality_call_is_checked_for_a_complete_block(self):
        from xydp.equipment_wash import parse_wash_affix_text, render_random_core
        random = {RANDOM_CORE_RELATIVE: render_random_core(parse_wash_affix_text(SOURCE))}
        for filename, *args in DIRECT_SPECS:
            with self.subTest(filename=filename):
                label = args[0]
                rel = WASH_DIRECTORY / filename
                callers = {MAIN_RELATIVE: f'#CALL [\\玄渊实验室\\装备洗练\\{filename}] @{label}\n'}
                output = render_direct_script(*args)
                scripts = {**callers, **random, rel: output}
                self.assertEqual(len(check_external_calls(scripts, lambda p: self.fail(str(p)))), 36)
                scripts[rel] = output.rsplit('}', 1)[0]
                with self.assertRaisesRegex(ValueError, '脚本块不完整'): check_external_calls(scripts, lambda p: self.fail(str(p)))

    def test_historical_unwrapped_quality_outputs_are_repaired_and_then_stable(self):
        with tempfile.TemporaryDirectory() as td:
            platform, server, client, source = fixture(Path(td), current=True)
            for filename, *args in DIRECT_SPECS:
                # Freeze the actual historical input, not this version's new renderer.
                output = _script_text((ROOT / 'tests/fixtures/equipment_wash_current' / WASH_DIRECTORY / filename).read_bytes()).replace('\n{\n', '\n').replace('\n}\n', '\n')
                (server / WASH_DIRECTORY / filename).write_bytes(_script_bytes(output))
            service = EquipmentWashImportService(platform)
            plan = service.preflight(server, source, client=client)
            self.assertFalse(plan.blockers, plan.blockers)
            self.assertEqual(len(plan.changes), 7)
            before = snapshot(server)
            receipt = service.install(plan)
            self.assertFalse(service.preflight(server, source, client=client).changes)
            service.rollback(server, receipt.transaction_id)
            self.assertEqual(snapshot(server), before)
