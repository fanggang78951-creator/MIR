import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class NativeControlTests(unittest.TestCase):
    def setUp(self):
        from wzl_blackbox import native_control as module
        self.m = module
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'MakeGameLogin.exe').write_bytes(b'test-generator')
        (self.source / 'Config.ini').write_bytes('[Setup]\r\n快捷方式=测试登录器\r\nSaveFilePath=E:\\正式客户端\\\r\n客户端文件=Client.dat\r\n'.encode('gb18030'))
        (self.source / 'GUI_Config.ini').write_bytes(b'[Setup]\r\nImageLibrary=D:\\old\\\r\n')
        self.request = {'schemaVersion': 1, 'command': 'launcher-save', 'arguments': {'sourceDirectory': str(self.source), 'outputRoot': str(self.root / 'job')}, 'policy': {'allowedWriteRoots': [str(self.root)]}}
        self.fingerprint = patch.object(module, 'LAUNCHER_SHA256', hashlib.sha256(b'test-generator').hexdigest().upper())
        self.fingerprint.start()
        self.addCleanup(self.fingerprint.stop)

    def test_validate_is_read_only(self):
        plan = self.m.validate_request(self.request)
        self.assertEqual(plan['source'], self.source.resolve())
        self.assertFalse((self.root / 'job').exists())

    def test_stage_rebinds_output_and_preserves_source(self):
        before = self.m.fingerprints(self.source)
        plan = self.m.validate_request(self.request)
        staged = self.m.stage_launcher(plan)
        self.assertEqual(before, self.m.fingerprints(self.source))
        settings = self.m.read_ini(staged / 'Config.ini')[0]
        self.assertEqual(Path(settings['Setup']['SaveFilePath']).resolve(), (self.root / 'job' / 'artifacts').resolve())

    def test_existing_output_rejected(self):
        (self.root / 'job').mkdir()
        with self.assertRaises(FileExistsError): self.m.validate_request(self.request)

    def test_unknown_executable_rejected(self):
        (self.source / 'MakeGameLogin.exe').write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError, 'build'): self.m.validate_request(self.request)

    def test_production_output_rejected(self):
        self.request['arguments']['outputRoot'] = r'D:\MirServer\native-job'
        self.request['policy']['allowedWriteRoots'] = [r'D:\MirServer']
        with self.assertRaises(PermissionError): self.m.validate_request(self.request)

    def test_external_config_input_rejected(self):
        cfg = self.source / 'Config.ini'
        cfg.write_text('[Setup]\n客户端文件=E:\\external\\Client.dat\n', encoding='gb18030')
        with self.assertRaisesRegex(ValueError, 'external'): self.m.validate_request(self.request)

    def test_unsafe_engine_operation_rejected(self):
        self.request['command'] = 'engine-start'
        with self.assertRaisesRegex(ValueError, 'command'): self.m.validate_request(self.request)

    def test_inspect_requires_explicit_expected_path(self):
        with self.assertRaises(ValueError): self.m.validate_request({'schemaVersion': 1, 'command': 'inspect', 'arguments': {'pid': 1}})

    def test_source_inside_job_rejected(self):
        self.request['arguments']['outputRoot'] = str(self.root)
        with self.assertRaises((ValueError, FileExistsError)): self.m.validate_request(self.request)

    def test_links_in_source_rejected(self):
        with patch.object(self.m, 'is_reparse', return_value=True):
            with self.assertRaisesRegex(ValueError, 'reparse'): self.m.validate_request(self.request)

    def test_packer_progress_is_wait_not_confirmation(self):
        self.assertEqual(self.m.generation_dialog_kind('SoPY_Status', '', []), 'wait')
        self.assertEqual(self.m.generation_dialog_kind('#32770', '提示信息', ['登录器生成成功！']), 'unknown')
        self.assertEqual(self.m.generation_dialog_kind('#32770', '提示信息', ['是否覆盖？']), 'unknown')
        self.assertEqual(self.m.generation_dialog_kind('#32770', '浏览文件夹', []), 'folder')
        message = '配置成功 ！\r\n\r\n请把"gee.txt"上传到你的网站，并确保下面的地址可以正常下载\r\nhttp://example.invalid/gee.txt'
        self.assertEqual(self.m.generation_dialog_kind('#32770', '提示', [message]), 'success')

    def test_relative_original_output_cannot_bypass_protection(self):
        cfg = self.source / 'Config.ini'
        cfg.write_text('[Setup]\nSaveFilePath=..\\original-client\\\n', encoding='gb18030')
        with self.assertRaisesRegex(ValueError, 'fully qualified'):
            self.m.validate_request(self.request)

    def test_failure_or_question_text_is_not_a_success(self):
        for text in ('生成失败，未成功。', '生成尚未完成，是否覆盖已有文件？', '配置成功，是否覆盖文件？'):
            self.assertEqual(self.m.generation_dialog_kind('#32770', '提示', [text]), 'unknown')

    def test_truncated_pe_is_rejected(self):
        import struct
        path = self.root / 'broken.exe'
        data = bytearray(68)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 0x3c, 64)
        data[64:] = b'PE\0\0'
        path.write_bytes(data)
        with self.assertRaises(ValueError): self.m.validate_pe(path)

    def test_dialog_enumeration_returns_waitable_specifications(self):
        from types import SimpleNamespace
        observed = SimpleNamespace(handle=123, class_name=lambda: '#32770')
        main = SimpleNamespace(handle=124, class_name=lambda: 'TfrmMain')
        specification = object()
        app = SimpleNamespace(windows=lambda **kwargs: [main, observed], window=lambda **kwargs: specification)
        launcher = self.m.Launcher.__new__(self.m.Launcher)
        launcher.app = app
        self.assertEqual(launcher.visible_dialogs(), [specification])

    def test_folder_selection_checks_whole_path_not_leaf_only(self):
        chain = ['artifacts', 'job', 'tasks', '软件 (D:)', '此电脑', '桌面']
        self.assertTrue(self.m.folder_chain_matches(chain, r'D:\tasks\job\artifacts'))
        self.assertFalse(self.m.folder_chain_matches(chain, r'E:\tasks\job\artifacts'))
        self.assertFalse(self.m.folder_chain_matches(chain, r'D:\formal\job\artifacts'))

    def test_cli_pins_json_streams_to_utf8(self):
        import io
        class Pipe(io.StringIO):
            def reconfigure(self, **options):
                self.options = options
        streams = [Pipe(), Pipe(), Pipe()]
        with patch.object(sys, 'stdin', streams[0]), patch.object(sys, 'stdout', streams[1]), patch.object(sys, 'stderr', streams[2]):
            self.assertEqual(self.m.main(['capabilities']), 0)
        self.assertTrue(all(stream.options == {'encoding': 'utf-8'} for stream in streams))

    def test_hidden_main_form_is_still_inspectable_without_restoring(self):
        self.assertTrue(self.m.include_native_form('TFrmMain', False))
        self.assertTrue(self.m.include_native_form('TfrmMain', False))
        self.assertFalse(self.m.include_native_form('TFrmConfigClient', False))
        self.assertTrue(self.m.include_native_form('TFrmConfigClient', True))

    def test_visible_lowercase_delphi_settings_dialog_is_not_lost(self):
        self.assertTrue(self.m.include_native_form('TfrmGeneralConfig', True))
        self.assertFalse(self.m.include_native_form('TfrmGeneralConfig', False))

    def test_unknown_visible_top_level_dialog_cannot_be_hidden_by_class_filter(self):
        self.assertTrue(self.m.include_native_form('TCustomWarning', True, top_level=True))
        self.assertFalse(self.m.include_native_form('TApplication', True, top_level=True))
        self.assertFalse(self.m.include_native_form('TEdit', True))

    def test_save_acknowledgement_requires_exact_signature(self):
        self.assertTrue(self.m.is_save_success_dialog('#32770', '提示信息', ['', '配置信息保存成功！！！']))
        self.assertFalse(self.m.is_save_success_dialog('#32770', '提示信息', ['保存失败，未保存成功！！！']))
        self.assertFalse(self.m.is_save_success_dialog('#32770', '提示信息', ['配置信息保存成功！！！', '是否覆盖？']))

    def test_dialog_construction_is_waited_without_confirming(self):
        self.assertFalse(self.m.dialog_content_ready([], []))
        self.assertFalse(self.m.dialog_content_ready(['保存成功'], []))
        self.assertTrue(self.m.dialog_content_ready(['保存失败'], ['确定']))

    def test_confirmation_pins_native_button_id_per_dialog(self):
        from types import SimpleNamespace
        button = SimpleNamespace(is_visible=lambda: True, is_enabled=lambda: True, control_id=lambda: 2, window_text=lambda: '确定')
        calls = []
        dialog = SimpleNamespace(descendants=lambda **kw: [button], child_window=lambda **kw: kw)
        launcher = self.m.Launcher.__new__(self.m.Launcher)
        launcher.keys = lambda control, keys: calls.append(control)
        launcher.confirm_ok(dialog, 2)
        self.assertEqual(calls[0]['control_id'], 2)
        with self.assertRaises(RuntimeError): launcher.confirm_ok(dialog, 1)
        self.assertEqual(len(calls), 1)

    def test_success_handle_is_captured_before_dismissing_dialog(self):
        from types import SimpleNamespace
        message = '配置成功 ！\r\n\r\n请把"gee.txt"上传到你的网站，并确保下面的地址可以正常下载\r\nhttp://example.invalid/gee.txt'
        class Dialog:
            closed = False
            @property
            def handle(self):
                if self.closed: raise RuntimeError('Dialog was already destroyed')
                return 123
            def class_name(self): return '#32770'
            def window_text(self): return '提示'
            def descendants(self, class_name):
                return [SimpleNamespace(window_text=lambda: message if class_name == 'Static' else '确定')]
        dialog = Dialog()
        launcher = self.m.Launcher.__new__(self.m.Launcher)
        launcher.main = SimpleNamespace(is_enabled=lambda: True)
        launcher.success_urls = {'http://example.invalid/gee.txt'}
        launcher.click_named = lambda name: None
        launcher.confirm_ok = lambda target, expected_id: setattr(target, 'closed', True)
        launcher.visible_dialogs = lambda: [] if dialog.closed else [dialog]
        (self.root / 'generated.exe').write_bytes(b'placeholder')
        launcher.build(self.root)
        self.assertTrue(dialog.closed)


if __name__ == '__main__':
    unittest.main()
