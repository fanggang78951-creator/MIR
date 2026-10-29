import site
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

class ClientBuildTests(unittest.TestCase):
    def test_sandbox_launcher_button_posts_to_exact_active_native_main(self):
        from wzl_blackbox import native_control as c, native_engine as e
        ui = c.Launcher.__new__(c.Launcher)
        ui.copy_executable = Path(r'C:\NativeDirectoryLab\job\MakeGameLogin.exe')
        ui.process = Mock(pid=1234)
        ui.main = Mock(handle=100)
        control = Mock(handle=200)
        control.class_name.return_value = 'TButton'
        control.window_text.return_value = '保存配置(&G)'
        control.is_visible.return_value = control.is_enabled.return_value = True
        with patch.object(e, 'sandbox_environment'), patch.object(e, 'process_image', return_value=ui.copy_executable), patch.object(c, 'sha256', return_value=c.LAUNCHER_SHA256), patch('win32process.GetWindowThreadProcessId', return_value=(99, 1234)), patch('win32gui.GetAncestor', return_value=100), patch.object(e, 'active_thread_window', return_value=100):
            ui.keys(control, '{SPACE}')
        control.post_message.assert_called_once_with(0xF5, 0, 0)
        control.set_focus.assert_not_called()
        control.type_keys.assert_not_called()

    def test_sandbox_launcher_button_rejects_wrong_identity_activity_or_network(self):
        from wzl_blackbox import native_control as c, native_engine as e
        for reason in ('identity', 'active', 'pid', 'network', 'key'):
            with self.subTest(reason=reason):
                ui = c.Launcher.__new__(c.Launcher)
                ui.copy_executable = Path(r'C:\NativeDirectoryLab\job\MakeGameLogin.exe')
                ui.process, ui.main = Mock(pid=1234), Mock(handle=100)
                control = Mock(handle=200)
                control.class_name.return_value, control.window_text.return_value = 'TButton', '保存配置(&G)'
                control.is_visible.return_value = control.is_enabled.return_value = True
                with patch.object(e, 'sandbox_environment', side_effect=PermissionError('network') if reason == 'network' else None), patch.object(e, 'process_image', return_value=Path('C:/wrong.exe') if reason == 'identity' else ui.copy_executable), patch.object(c, 'sha256', return_value=c.LAUNCHER_SHA256), patch('win32process.GetWindowThreadProcessId', return_value=(99, 9999 if reason == 'pid' else 1234)), patch('win32gui.GetAncestor', return_value=100), patch.object(e, 'active_thread_window', return_value=300 if reason == 'active' else 100):
                    with self.assertRaises((ValueError, PermissionError, RuntimeError)):
                        ui.keys(control, '{ENTER}' if reason == 'key' else '{SPACE}')
                control.post_message.assert_not_called()
                control.type_keys.assert_not_called()

    def test_host_launcher_keeps_existing_input_contract(self):
        from wzl_blackbox import native_control as c
        ui = c.Launcher.__new__(c.Launcher)
        ui.copy_executable = Path(r'D:\job\MakeGameLogin.exe')
        control = Mock()
        with patch.object(c.NativeEditor, 'keys', return_value='host') as original:
            self.assertEqual(ui.keys(control, '{SPACE}'), 'host')
        original.assert_called_once_with(control, '{SPACE}')

    def test_sandbox_launcher_standard_confirmation_uses_bound_uia_invoke(self):
        from wzl_blackbox import native_control as c, native_engine as e
        ui = c.Launcher.__new__(c.Launcher)
        ui.copy_executable = Path(r'C:\NativeDirectoryLab\job\MakeGameLogin.exe')
        ui.process = Mock(pid=1234)
        control, parent, button = Mock(handle=200), Mock(), Mock(handle=200)
        control.class_name.return_value, control.window_text.return_value = 'Button', '确定'
        control.control_id.return_value = 2
        control.is_visible.return_value = control.is_enabled.return_value = True
        parent.class_name.return_value, parent.window_text.return_value = '#32770', '提示信息'
        button.element_info.process_id, button.element_info.control_type = 1234, 'Button'
        win, uia = Mock(), Mock()
        win.connect.return_value.window.return_value = parent
        uia.connect.return_value.window.return_value.wrapper_object.return_value = button
        with patch.object(e, 'sandbox_environment'), patch.object(e, 'process_image', return_value=ui.copy_executable), patch.object(c, 'sha256', return_value=c.LAUNCHER_SHA256), patch('win32process.GetWindowThreadProcessId', return_value=(99, 1234)), patch('win32gui.GetAncestor', return_value=300), patch('pywinauto.Application', side_effect=lambda backend: win if backend == 'win32' else uia):
            ui.keys(control, '{SPACE}')
        button.invoke.assert_called_once()
        control.type_keys.assert_not_called()

    def test_destroyed_form_during_wrapping_is_skipped(self):
        from wzl_blackbox import native_control as c
        from pywinauto.controls.hwndwrapper import InvalidWindowHandle
        survivor = Mock(handle=20)
        with patch('pywinauto.controls.hwndwrapper.HwndWrapper', side_effect=[InvalidWindowHandle(10), survivor]), patch('win32gui.IsWindow', return_value=False), patch('win32process.GetWindowThreadProcessId', return_value=(99, 1234)):
            self.assertEqual(c.wrap_native_forms([10, 20], 1234), [survivor])

    def test_still_valid_wrapper_failure_is_not_hidden(self):
        from wzl_blackbox import native_control as c
        from pywinauto.controls.hwndwrapper import InvalidWindowHandle
        with patch('pywinauto.controls.hwndwrapper.HwndWrapper', side_effect=InvalidWindowHandle(10)), patch('win32gui.IsWindow', return_value=True):
            with self.assertRaises(InvalidWindowHandle):
                c.wrap_native_forms([10], 1234)

    def test_reused_window_from_another_pid_is_excluded(self):
        from wzl_blackbox import native_control as c
        with patch('pywinauto.controls.hwndwrapper.HwndWrapper', return_value=Mock(handle=10)), patch('win32process.GetWindowThreadProcessId', return_value=(99, 9876)):
            self.assertEqual(c.wrap_native_forms([10], 1234), [])

    def test_opt_in_diagnostic_reports_actual_failure_stack(self):
        from wzl_blackbox import native_control as c
        import io
        import json
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request.json'
            path.write_text('{"schemaVersion":1,"command":"inspect"}', encoding='utf-8')
            with patch('sys.stdout', output), patch.dict('os.environ', {'XY_NATIVE_DIAGNOSTICS': '1'}), patch.object(c, 'run', side_effect=RuntimeError('diagnostic-test')):
                self.assertEqual(c.main(['run', '--request', str(path)]), 1)
        self.assertIn('diagnostic-test', json.loads(output.getvalue())['error']['traceback'])

    def test_pipeline_receipt_and_export_input_hash_binding(self):
        from wzl_blackbox import native_engine as e, native_control as c
        import shutil
        for mismatch in (False, True):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, output = root / 'source', root / 'job'
                source.mkdir()
                (source / 'MakeGameLogin.exe').write_bytes(b'verified-test-generator')
                (source / 'Config.ini').write_text('[Setup]\nSaveFilePath=\n', encoding='utf-8')
                ui = Mock(root=root)
                original = c.fingerprints(source)
                def export(_ui, target):
                    target.write_bytes(b'generated-native-dat')
                    return {'path': str(target), 'sha256': e.sha256(target), 'size': target.stat().st_size}
                def build(request):
                    bundle = Path(request['arguments']['sourceDirectory'])
                    cfg, _ = c.read_ini(bundle / 'Config.ini')
                    self.assertEqual(cfg['Setup']['集成怪物配置'], '1')
                    self.assertEqual(cfg['Setup']['怪物配置文件'], 'native-custom-monsters.dat')
                    staged = Path(request['arguments']['outputRoot']) / 'generator'
                    staged.parent.mkdir()
                    shutil.copytree(bundle, staged)
                    digest = '0' * 64 if mismatch else e.sha256(bundle / 'native-custom-monsters.dat')
                    return {'sourceFiles': {'native-custom-monsters.dat': digest}}
                with patch.object(c, 'LAUNCHER_SHA256', e.sha256(source / 'MakeGameLogin.exe')), patch.object(c, 'validate_request'), patch.object(e, 'update_wil_resources', return_value={'nativeButtonDispatchAcknowledged': True}), patch.object(e, 'export_monsters', side_effect=export), patch.object(c, 'run', side_effect=build):
                    if mismatch:
                        with self.assertRaisesRegex(RuntimeError, 'binding'):
                            e.client_build(ui, {'sourceDirectory': str(source), 'outputRoot': str(output)})
                    else:
                        result = e.client_build(ui, {'sourceDirectory': str(source), 'outputRoot': str(output)})
                        self.assertEqual(result['outputRoot'], str(output.resolve()))
                        self.assertTrue(result['exportInputBindingVerified'])
                self.assertEqual(c.fingerprints(source), original)

    def test_taskdialog_ack_uses_exact_uia_invoke_without_foreground_input(self):
        from wzl_blackbox import native_engine as e
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'monsters.dat'
            target.write_bytes(b'native-export')
            ui = Mock()
            ui.pid = 1234
            dialog, native_ok, text, uia_ok, wrapper = Mock(), Mock(handle=12), Mock(), Mock(handle=12), Mock()
            ui.wait_dialog.return_value = dialog
            native_ok.is_visible.return_value = native_ok.is_enabled.return_value = True
            native_ok.window_text.return_value = 'OK'
            dialog.descendants.return_value = [native_ok]
            text.element_info.control_type = 'Text'
            text.element_info.automation_id = 'ContentText'
            text.window_text.return_value = '已经生成自定义怪物登录器配置文件'
            uia_ok.element_info.control_type = 'Button'
            uia_ok.element_info.automation_id = 'CommandButton_1'
            uia_ok.window_text.return_value = 'OK'
            wrapper.descendants.return_value = [text, uia_ok]
            form = Mock()
            form.class_name.return_value = 'TfrmMonsterConfig'
            form.is_enabled.return_value = True
            ui.dialogs.side_effect = [[form], []]
            ui.main.is_enabled.return_value = True
            ui.prepare_form.side_effect = RuntimeError('disabled main is active')
            with patch('pywinauto.Application') as app, patch.object(e, 'sandbox_environment'):
                app.return_value.connect.return_value.window.return_value = wrapper
                self.assertTrue(e.confirm_monster_export(ui, target)['nativeCompletionVerified'])
            uia_ok.invoke.assert_called_once()
            native_ok.post_message.assert_not_called()
            ui.prepare_form.assert_not_called()

    def test_taskdialog_rejects_mismatched_or_unauthorized_invoke(self):
        from wzl_blackbox import native_engine as e
        for reason in ('handle', 'duplicate', 'network', 'identity'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'native.dat'
                target.write_bytes(b'valid-native-export')
                ui, dialog, native_ok, wrapper = Mock(), Mock(handle=10), Mock(handle=12), Mock()
                ui.pid = 1234
                ui.wait_dialog.return_value = dialog
                native_ok.is_visible.return_value = native_ok.is_enabled.return_value = True
                native_ok.window_text.return_value = 'OK'
                dialog.descendants.return_value = [native_ok]
                text, invoke = Mock(), Mock(handle=13 if reason == 'handle' else 12)
                text.element_info.control_type, text.element_info.automation_id = 'Text', 'ContentText'
                text.window_text.return_value = '已经生成自定义怪物登录器配置文件'
                invoke.element_info.control_type, invoke.element_info.automation_id = 'Button', 'CommandButton_1'
                invoke.window_text.return_value = 'OK'
                wrapper.descendants.return_value = [text, invoke] + ([invoke] if reason == 'duplicate' else [])
                if reason == 'identity':
                    ui.verify.side_effect = ValueError('identity changed')
                with patch('pywinauto.Application') as app, patch.object(e, 'sandbox_environment', side_effect=PermissionError('network enabled') if reason == 'network' else None):
                    app.return_value.connect.return_value.window.return_value = wrapper
                    with self.assertRaises((RuntimeError, PermissionError, ValueError)):
                        e.confirm_monster_export(ui, target)
                invoke.invoke.assert_not_called()

    def test_dialog_transition_allows_only_the_exact_previous_form(self):
        from wzl_blackbox import native_engine as e
        ui = e.EngineUI.__new__(e.EngineUI)
        previous = Mock(handle=10)
        previous.class_name.return_value = '#32770'
        previous.window_text.return_value = '生成登录器配置文件'
        completed = Mock(handle=20)
        completed.class_name.return_value = '#32770'
        completed.window_text.return_value = 'M2server'
        ui.dialogs = Mock(side_effect=[[previous], [completed]])
        with patch.object(e.time, 'sleep'):
            self.assertIs(ui.wait_dialog('#32770', 'M2server', transition_from=(10, '#32770', '生成登录器配置文件')), completed)
        unknown = Mock(handle=30)
        unknown.class_name.return_value = '#32770'
        unknown.window_text.return_value = 'unexpected'
        ui.dialogs = Mock(return_value=[unknown])
        with self.assertRaises(RuntimeError):
            ui.wait_dialog('#32770', 'M2server', transition_from=(10, '#32770', '生成登录器配置文件'))

    def test_release_capabilities_do_not_open_unverified_whole_stack(self):
        from wzl_blackbox import native_control as c
        import io
        import json
        stream = io.StringIO()
        with patch('sys.stdout', stream):
            c.main(['capabilities'])
        data = json.loads(stream.getvalue())
        self.assertFalse(data['wholeEngineStartStop'])
        self.assertIn('m2-client-build', data['commands'])
        self.assertNotIn('engine-start', data['commands'])

    def test_public_engine_dispatch_returns_the_locked_operation_result(self):
        from wzl_blackbox import native_engine as e
        from contextlib import nullcontext
        request = {'command': 'm2-client-build'}
        with patch.object(e, 'serial_engine_operation', return_value=nullcontext()), patch.object(e, '_run_engine', return_value={'ok': True}) as operation:
            self.assertEqual(e.run_engine(request), {'ok': True})
            operation.assert_called_once_with(request)

    def test_wil_button_dispatch_is_single_synchronous_bm_click(self):
        from wzl_blackbox import native_engine as e
        import ctypes
        api = Mock()
        api.SendMessageTimeoutW.return_value = 1
        with patch.object(ctypes, 'WinDLL', return_value=api):
            e.synchronous_button_click(123)
        self.assertEqual(api.SendMessageTimeoutW.call_args.args[:5], (123, 0xF5, 0, 0, 2))
        api.SendMessageTimeoutW.assert_called_once()

    def test_unknown_export_kind_is_rejected(self):
        from wzl_blackbox import native_engine as e
        with self.assertRaisesRegex(ValueError, 'exportKind'):
            e.validate_operation('m2-client-build', {'exportKind': 'all'})

    def test_client_build_is_fixed_guest_only(self):
        from wzl_blackbox import native_engine as e
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(e, 'validate_lab_root', return_value=Path(directory)):
                with self.assertRaises(PermissionError):
                    e.validate_operation('m2-client-build', {'exportKind': 'custom-monsters', 'labRoot': directory})

    def test_success_message_must_be_exact(self):
        from wzl_blackbox.native_engine import monster_export_message_verified
        self.assertTrue(monster_export_message_verified(['已经生成自定义怪物登录器配置文件']))
        for texts in ([], ['失败'], ['已经生成自定义怪物登录器配置文件', '失败']):
            self.assertFalse(monster_export_message_verified(texts))

    def test_client_bundle_cannot_escape_or_overlap_source(self):
        from wzl_blackbox.native_engine import client_build_paths
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'generator'
            source.mkdir()
            for output in (root.parent / 'outside', source / 'job', root):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    client_build_paths(root, source, output)
            got = client_build_paths(root, source, root / 'job')
            self.assertEqual(got, (source.resolve(), (root / 'job').resolve()))

if __name__ == '__main__':
    unittest.main()
