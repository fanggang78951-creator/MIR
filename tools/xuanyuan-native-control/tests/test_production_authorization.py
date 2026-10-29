import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class ProductionAuthorizationTests(unittest.TestCase):
    def setUp(self):
        # Original tests depended on live historical roots. Keep all bindings real
        # but put their filesystem fixtures in this test's independent temp tree.
        import tempfile
        from wzl_blackbox import native_engine as e
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.server = base / 'server'
        self.exe = self.server / 'Mir200' / 'M2Server.exe'
        self.source = self.server / 'launcher'
        self.client = base / 'client'
        self.output_base = base / 'output'
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b'production-authorization-test-fixture')
        for directory in (self.source, self.client, self.output_base): directory.mkdir()
        for name, value in [('PRODUCTION_ROOT', self.server), ('PRODUCTION_EXECUTABLE', self.exe),
                            ('PRODUCTION_SOURCE', self.source), ('PRODUCTION_CLIENT', self.client),
                            ('PRODUCTION_OUTPUT_BASE', self.output_base)]:
            binding = patch.object(e, name, value)
            binding.start()
            self.addCleanup(binding.stop)

    def request(self):
        return {
            'schemaVersion': 1,
            'command': 'm2-client-build',
            'arguments': {
                'mode': 'production-authorized',
                'labRoot': str(self.server),
                'pid': 30860,
                'expectedExecutable': str(self.exe),
                'expectedWindowTitle': '01区 [无限版]',
                'exportKind': 'custom-monsters',
                'sourceDirectory': str(self.source),
                'outputRoot': str(self.output_base / 'job-new'),
                'clientRoot': str(self.client),
            },
            'policy': {
                'productionAuthorization': 'AUTHORIZED_M2_CUSTOM_MONSTER_EXPORT_AND_LAUNCHER_BUILD',
                'authorizedServerRoot': str(self.server),
                'authorizedClientRoot': str(self.client),
                'allowedOperations': ['custom-monster-export', 'launcher-build'],
                'allowedWriteRoots': [str(self.output_base)],
            },
        }

    def test_exact_production_authorization_is_accepted(self):
        from wzl_blackbox import native_engine as e
        request = self.request()
        with patch.object(e, 'process_image', return_value=Path(request['arguments']['expectedExecutable']).resolve()), patch.object(e, 'sha256', return_value=e.BINARIES['Mir200/M2Server.exe']):
            root = e.validate_production_authorization(request, verify_live=True)
        self.assertEqual(root, self.server.resolve())

    def test_production_is_opt_in_and_exactly_bounded(self):
        from wzl_blackbox import native_engine as e
        mutations = [
            ('mode', 'lab'),
            ('labRoot', r'D:\Mirserver100'),
            ('expectedExecutable', r'D:\Mirserver100\Mir200\M2Server.exe'),
            ('expectedWindowTitle', 'other'),
            ('exportKind', 'all'),
            ('sourceDirectory', r'D:\Mirserver100\登录器'),
            ('clientRoot', r'E:\客户端\other'),
            ('outputRoot', r'D:\outside\job'),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                request = self.request()
                request['arguments'][key] = value
                with self.assertRaises((ValueError, PermissionError, FileNotFoundError)):
                    e.validate_production_authorization(request, verify_live=False)
        for key, value in [
            ('productionAuthorization', 'wrong'),
            ('authorizedServerRoot', r'D:\Mirserver100'),
            ('authorizedClientRoot', r'E:\客户端\other'),
            ('allowedOperations', ['custom-monster-export', 'launcher-build', 'm2-stop']),
            ('allowedWriteRoots', ['D:\\']),
        ]:
            with self.subTest(policy_key=key):
                request = self.request()
                request['policy'][key] = value
                with self.assertRaises((ValueError, PermissionError)):
                    e.validate_production_authorization(request, verify_live=False)

    def test_live_pid_path_and_hash_are_revalidated(self):
        from wzl_blackbox import native_engine as e
        request = self.request()
        for actual, digest in [(Path(r'D:\Mirserver100\Mir200\M2Server.exe').resolve(), e.BINARIES['Mir200/M2Server.exe']), (Path(request['arguments']['expectedExecutable']).resolve(), '0' * 64)]:
            with self.subTest(actual=actual, digest=digest), patch.object(e, 'process_image', return_value=actual), patch.object(e, 'sha256', return_value=digest):
                with self.assertRaises(ValueError):
                    e.validate_production_authorization(request, verify_live=True)

    def test_only_m2_client_build_can_use_production_mode(self):
        from wzl_blackbox import native_engine as e
        for command in ('m2-stop', 'm2-start', 'm2-reload', 'engine-parameter', 'engine-controller-stop'):
            request = self.request()
            request['command'] = command
            with self.subTest(command=command), self.assertRaises(PermissionError):
                e.validate_production_authorization(request, verify_live=False)

    def test_production_pipeline_skips_wil_update(self):
        from wzl_blackbox import native_control as c, native_engine as e
        import tempfile
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'source', root / 'job'
            source.mkdir()
            (source / 'MakeGameLogin.exe').write_bytes(b'verified-test-generator')
            (source / 'Config.ini').write_text('[Setup]\nSaveFilePath=\n', encoding='utf-8')
            ui = Mock(root=Path(r'D:\MirServer'))
            original = c.fingerprints(source)
            def export(_ui, target):
                target.write_bytes(b'generated-native-dat')
                return {'path': str(target), 'sha256': e.sha256(target), 'size': target.stat().st_size, 'nativeCompletionVerified': True}
            def build(request):
                bundle = Path(request['arguments']['sourceDirectory'])
                staged = Path(request['arguments']['outputRoot']) / 'generator'
                staged.parent.mkdir(parents=True)
                shutil.copytree(bundle, staged)
                return {'sourceFiles': {'native-custom-monsters.dat': e.sha256(bundle / 'native-custom-monsters.dat')}, 'artifacts': [{'peVerified': True}]}
            with patch.object(c, 'LAUNCHER_SHA256', e.sha256(source / 'MakeGameLogin.exe')), patch.object(c, 'validate_request'), patch.object(e, 'production_client_build_paths', return_value=(source.resolve(), output.resolve())), patch.object(e, 'update_wil_resources') as wil, patch.object(e, 'export_monsters', side_effect=export), patch.object(c, 'run', side_effect=build):
                result = e.client_build(ui, {'sourceDirectory': str(source), 'outputRoot': str(output)}, production=True)
            wil.assert_not_called()
            self.assertEqual(result['wilUpdate'], {'requested': False, 'performed': False})
            self.assertTrue(result['exportInputBindingVerified'])
            self.assertEqual(c.fingerprints(source), original)

    def test_production_confirmation_uses_guard_without_sandbox(self):
        from wzl_blackbox import native_engine as e
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'native.dat'
            target.write_bytes(b'valid-native-export')
            ui = Mock(pid=30860)
            ui.production_guard = Mock()
            dialog, native_ok, text, invoke, wrapper = Mock(handle=10), Mock(handle=12), Mock(), Mock(handle=12), Mock()
            ui.wait_dialog.return_value = dialog
            native_ok.is_visible.return_value = native_ok.is_enabled.return_value = True
            native_ok.window_text.return_value = 'OK'
            dialog.descendants.return_value = [native_ok]
            text.element_info.control_type, text.element_info.automation_id = 'Text', 'ContentText'
            text.window_text.return_value = '已经生成自定义怪物登录器配置文件'
            invoke.element_info.control_type, invoke.element_info.automation_id = 'Button', 'CommandButton_1'
            invoke.window_text.return_value = 'OK'
            wrapper.descendants.return_value = [text, invoke]
            form = Mock()
            form.class_name.return_value, form.is_enabled.return_value = 'TfrmMonsterConfig', True
            ui.dialogs.side_effect = [[form], []]
            ui.main.is_enabled.return_value = True
            with patch('pywinauto.Application') as app, patch.object(e, 'sandbox_environment') as sandbox:
                app.return_value.connect.return_value.window.return_value = wrapper
                self.assertTrue(e.confirm_monster_export(ui, target)['nativeCompletionVerified'])
            ui.production_guard.assert_called_once_with()
            sandbox.assert_not_called()
            invoke.invoke.assert_called_once()

    def test_production_main_title_must_match_exactly(self):
        from wzl_blackbox import native_engine as e
        main = Mock()
        main.window_text.return_value = '01区 [无限版]'
        e.verify_production_main_title(main, '01区 [无限版]')
        main.window_text.return_value = '01区 [无限版] - altered'
        with self.assertRaises(ValueError):
            e.verify_production_main_title(main, '01区 [无限版]')

    def test_capabilities_keep_default_read_only_and_name_narrow_mode(self):
        from wzl_blackbox import native_control as c
        stream = io.StringIO()
        with patch('sys.stdout', stream):
            c.main(['capabilities'])
        data = json.loads(stream.getvalue())
        self.assertFalse(data['productionEngineWritesDefault'])
        self.assertEqual(data['productionAuthorizedOperation'], 'custom-monster-export-plus-launcher-build')
        self.assertFalse(data['wholeEngineStartStop'])


if __name__ == '__main__':
    unittest.main()
