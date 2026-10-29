import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class ProductionResumeTests(unittest.TestCase):
    def test_run_engine_allows_blocked_main_only_for_exact_resume_preflight(self):
        from wzl_blackbox import native_engine as e
        request = {
            'command': 'm2-client-build',
            'arguments': {
                'mode': e.PRODUCTION_MODE,
                'labRoot': r'D:\MirServer',
                'pid': 30860,
                'expectedWindowTitle': e.PRODUCTION_TITLE,
                'resumeExistingExport': True,
            },
        }
        root, ui = Path(r'D:\MirServer'), Mock()
        with patch.object(e, 'validate_operation'), \
                patch.object(e, 'validate_production_authorization', return_value=root), \
                patch.object(e, 'EngineUI', return_value=ui) as engine_ui, \
                patch.object(e, 'inspect_resume_monster_export_state', return_value=('post-confirm-monster-settings', Mock())) as inspect, \
                patch.object(e, 'client_build', return_value={'resumedExistingExport': True}) as build:
            result = e._run_engine(request)
        engine_ui.assert_called_once_with(
            root, 30860, 'Mir200/M2Server.exe',
            expected_title=e.PRODUCTION_TITLE, allow_blocked_main=True)
        inspect.assert_called_once_with(ui)
        build.assert_called_once_with(ui, request['arguments'], production=True, production_request=request)
        self.assertTrue(result['resumedExistingExport'])

    def test_blocked_main_requires_explicit_resume_title_check(self):
        from wzl_blackbox import native_engine as e
        main = Mock()
        main.window_text.return_value = e.PRODUCTION_TITLE
        main.is_visible.return_value = True
        main.is_enabled.return_value = False
        with self.assertRaises(ValueError):
            e.verify_production_main_title(main, e.PRODUCTION_TITLE)
        self.assertTrue(e.verify_production_main_title(main, e.PRODUCTION_TITLE, allow_disabled=True))

    def test_resume_preflight_accepts_only_exact_blocking_monster_form(self):
        from wzl_blackbox import native_engine as e
        form, main, ui = Mock(), Mock(), Mock()
        form.class_name.return_value, form.window_text.return_value = 'TfrmMonsterConfig', '怪物设置'
        form.is_visible.return_value = form.is_enabled.return_value = True
        main.is_enabled.return_value = False
        ui.main = main
        ui.dialogs.return_value = [form]
        self.assertEqual(e.inspect_resume_monster_export_state(ui), ('post-confirm-monster-settings', form))
        form.window_text.return_value = 'other'
        with self.assertRaises(RuntimeError):
            e.inspect_resume_monster_export_state(ui)

    def test_runtime_revalidation_does_not_reapply_new_output_precondition(self):
        from wzl_blackbox import native_engine as e
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'job'; target = output / 'input/native-custom-monsters.dat'
            target.parent.mkdir(parents=True); target.write_bytes(b'finished-dat')
            request = {'schemaVersion': 1, 'command': 'm2-client-build', 'arguments': {'outputRoot': str(output)}, 'policy': {}}
            with patch.object(e, 'validate_production_authorization', return_value=Path(r'D:\MirServer')) as validate, patch.object(e, 'sha256', return_value='A' * 64):
                result = e.validate_production_runtime(request, target)
        self.assertEqual(result['exportSha256'], 'A' * 64)
        validate.assert_called_once_with(request, verify_live=True, require_new_output=False)

    def test_resume_uses_existing_dat_and_never_reexports(self):
        from wzl_blackbox import native_control as c, native_engine as e
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'source', root / 'job'
            source.mkdir(); (source / 'MakeGameLogin.exe').write_bytes(b'verified-test-generator')
            (source / 'Config.ini').write_text('[Setup]\nSaveFilePath=\n', encoding='utf-8')
            bundle = output / 'input'; shutil.copytree(source, bundle)
            target = bundle / 'native-custom-monsters.dat'; target.write_bytes(b'completed-before-tool-failure')
            ui = Mock(root=Path(r'D:\MirServer'))
            request = {'schemaVersion': 1, 'command': 'm2-client-build', 'arguments': {'resumeExistingExport': True}}
            def build(build_request):
                staged = Path(build_request['arguments']['outputRoot']) / 'generator'
                staged.parent.mkdir(parents=True)
                shutil.copytree(Path(build_request['arguments']['sourceDirectory']), staged)
                return {'sourceFiles': {target.name: e.sha256(target)}, 'artifacts': [{'peVerified': True}]}
            with patch.object(c, 'LAUNCHER_SHA256', e.sha256(source / 'MakeGameLogin.exe')), patch.object(c, 'validate_request'), patch.object(e, 'production_client_build_paths', return_value=(source.resolve(), output.resolve())), patch.object(e, 'export_monsters') as export, patch.object(e, 'resume_monster_export', return_value={'path': str(target), 'sha256': e.sha256(target), 'size': target.stat().st_size, 'nativeCompletionVerified': True}) as resume_export, patch.object(c, 'run', side_effect=build):
                result = e.client_build(ui, {'sourceDirectory': str(source), 'outputRoot': str(output), 'resumeExistingExport': True}, production=True, production_request=request)
            export.assert_not_called()
            resume_export.assert_called_once_with(ui, target.resolve())
            self.assertTrue(result['resumedExistingExport'])
            self.assertEqual(result['wilUpdate'], {'requested': False, 'performed': False})

    def test_post_confirm_resume_closes_only_existing_monster_settings(self):
        from wzl_blackbox import native_engine as e
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'native-custom-monsters.dat'; target.write_bytes(b'finished-dat')
            form, main, ui = Mock(), Mock(), Mock()
            form.class_name.return_value, form.window_text.return_value = 'TfrmMonsterConfig', '怪物设置'
            form.is_visible.return_value = form.is_enabled.return_value = True
            main.is_enabled.side_effect = [False, True]
            ui.main = main; ui.dialogs.side_effect = [[form], []]
            ui.production_guard = Mock(return_value={'exportSha256': e.sha256(target), 'exportSize': target.stat().st_size})
            result = e.resume_monster_export(ui, target)
            form.post_message.assert_called_once_with(0x10)
            self.assertEqual(result['resumedAt'], 'post-confirm-monster-settings')
            self.assertTrue(result['nativeCompletionVerified'])

    def test_normal_production_still_requires_a_new_output(self):
        from wzl_blackbox import native_engine as e
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            request = {'arguments': {'outputRoot': str(output)}}
            with patch.object(e, '_validate_production_bindings', return_value=(Path(r'D:\MirServer'), Path(r'D:\MirServer\Mir200\M2Server.exe'), output, {})):
                with self.assertRaises(FileExistsError):
                    e.validate_production_authorization(request, verify_live=False, require_new_output=True)


if __name__ == '__main__':
    unittest.main()
