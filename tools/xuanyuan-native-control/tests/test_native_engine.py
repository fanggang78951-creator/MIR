import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class EngineIsolationTests(unittest.TestCase):
    def test_controller_stop_uses_guest_active_dialog_confirmation(self):
        ui, dialog, button = Mock(), Mock(), Mock()
        button.window_text.return_value = '启动游戏服务器(&S)'
        ui.main.descendants.return_value = [button]
        ui.dialogs.return_value = [dialog]
        ui.prepare_form.return_value = True
        with patch.object(self.e, 'EngineUI', return_value=ui), patch.object(self.e, 'matching_processes', return_value=[]), patch.object(self.e, 'confirm_native_yes') as confirm, patch.object(self.e, 'wait_stopped'):
            self.e._run_engine({'command': 'engine-controller-stop', 'arguments': {'labRoot': str(self.root), 'pid': 123}, 'policy': {'allowedWriteRoots': [str(self.root)]}})
            ui.prepare_form.assert_called_once_with(dialog)
            confirm.assert_called_once_with(dialog, '是否确认关闭控制台 ?', require_foreground=False)

    def test_native_network_assembly_rejects_nonloopback_and_both_default_routes(self):
        import ctypes
        import socket
        for address, route in (('127.0.0.1', None), ('::1', None), ('192.0.2.1', None), ('fe80::1', None), ('2001:db8::1', None), ('127.0.0.1', '0.0.0.0'), ('::1', '::')):
            with self.subTest(address=address, route=route):
                ip = self.e._UnicastRow()
                family = socket.AF_INET6 if ':' in address else socket.AF_INET
                ip.address.family = family
                target = ip.address.v6.address if family == socket.AF_INET6 else ip.address.v4.address
                target[:] = socket.inet_pton(family, address)
                routes = []
                if route is not None:
                    row = self.e._RouteRow()
                    row.destination.address.family = socket.AF_INET6 if ':' in route else socket.AF_INET
                    routes.append(row)
                api, user = Mock(), Mock()
                def username(buffer, size):
                    buffer.value = 'WDAGUtilityAccount'
                    return 1
                user.GetUserNameW.side_effect = username
                with patch.object(ctypes, 'WinDLL', side_effect=[api, user]), patch.object(self.e, '_read_ip_table', side_effect=[[ip], routes]):
                    if address in ('127.0.0.1', '::1') and route is None:
                        self.assertEqual(self.e.sandbox_environment()['defaultRoutes'], [])
                    else:
                        with self.assertRaises(PermissionError):
                            self.e.sandbox_environment()

    def test_native_username_failure_fails_closed(self):
        import ctypes
        api, user = Mock(), Mock()
        user.GetUserNameW.return_value = 0
        with patch.object(ctypes, 'WinDLL', side_effect=[api, user]), patch.object(self.e, '_read_ip_table', side_effect=[[], []]):
            with self.assertRaises(OSError):
                self.e.sandbox_environment()

    def test_native_network_key_field_offsets_match_windows_headers(self):
        self.assertEqual(self.e._UnicastRow.luid.offset, 32)
        self.assertEqual(self.e._UnicastRow.created.offset, 72)
        self.assertEqual(self.e._RouteRow.destination.offset, 12)
        self.assertEqual(self.e._RouteRow.nextHop.offset, 44)
        self.assertEqual(self.e._RouteRow.origin.offset, 100)

    def test_native_table_success_with_null_pointer_is_rejected(self):
        api = Mock()
        api.GetIpForwardTable2.return_value = 0
        with self.assertRaises(OSError):
            self.e._read_ip_table(api, 'GetIpForwardTable2', self.e._RouteRow)
        api.FreeMibTable.assert_not_called()

    def test_native_table_releases_once_on_oversized_count_or_copy_failure(self):
        import ctypes
        class Table(ctypes.Structure):
            _fields_ = [('count', ctypes.c_uint32), ('rows', self.e._RouteRow * 1)]
        for count in (65537, 1):
            with self.subTest(count=count):
                table = Table()
                table.count = count
                def query(family, pointer):
                    ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(table)
                    return 0
                api = Mock()
                api.GetIpForwardTable2.side_effect = query
                with patch.object(ctypes, 'string_at', side_effect=RuntimeError('copy failed')):
                    with self.assertRaises((ValueError, RuntimeError)):
                        self.e._read_ip_table(api, 'GetIpForwardTable2', self.e._RouteRow)
                api.FreeMibTable.assert_called_once()

    def test_native_network_abi_and_ipv4_ipv6_decoding(self):
        import ctypes
        import socket
        self.assertEqual(ctypes.sizeof(self.e._SockaddrInet), 28)
        self.assertEqual(ctypes.sizeof(self.e._UnicastRow), 80)
        self.assertEqual(ctypes.sizeof(self.e._RouteRow), 104)
        for family, address in ((socket.AF_INET, '127.0.0.1'), (socket.AF_INET6, '::1')):
            native = self.e._SockaddrInet()
            native.family = family
            target = native.v4.address if family == socket.AF_INET else native.v6.address
            target[:] = socket.inet_pton(family, address)
            self.assertEqual(self.e._ip_text(native), address)
        with self.assertRaises(ValueError):
            self.e._ip_text(self.e._SockaddrInet())

    def test_native_table_respects_alignment_and_copies_before_free(self):
        import ctypes
        class Table(ctypes.Structure):
            _fields_ = [('count', ctypes.c_uint32), ('rows', self.e._RouteRow * 2)]
        table = Table()
        table.count = 2
        table.rows[0].metric, table.rows[1].metric = 7, 19
        def query(family, pointer):
            ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(table)
            return 0
        api = Mock()
        api.GetIpForwardTable2.side_effect = query
        api.FreeMibTable.side_effect = lambda _: ctypes.memset(ctypes.addressof(table), 0, ctypes.sizeof(table))
        rows = self.e._read_ip_table(api, 'GetIpForwardTable2', self.e._RouteRow)
        self.assertEqual([r.metric for r in rows], [7, 19])
        api.FreeMibTable.assert_called_once()

    def test_native_table_api_failure_fails_closed(self):
        api = Mock()
        api.GetIpForwardTable2.return_value = 5
        with self.assertRaises(OSError):
            self.e._read_ip_table(api, 'GetIpForwardTable2', self.e._RouteRow)
        api.FreeMibTable.assert_not_called()

    def test_sandbox_network_check_is_live_without_powershell(self):
        safe = {'username': 'WDAGUtilityAccount', 'nonLoopbackAddresses': [], 'defaultRoutes': []}
        changed = {**safe, 'defaultRoutes': ['::/0']}
        with patch.object(self.e, 'native_network_observation', side_effect=[safe, changed], create=True) as native, patch.object(self.e.subprocess, 'run', side_effect=AssertionError('No PowerShell per action')):
            self.assertEqual(self.e.sandbox_environment(), safe)
            with self.assertRaises(PermissionError):
                self.e.sandbox_environment()
            self.assertEqual(native.call_count, 2)

    def test_sandbox_network_query_failure_is_not_accepted(self):
        with patch.object(self.e, 'native_network_observation', side_effect=OSError('native API failed'), create=True), patch.object(self.e.subprocess, 'run', side_effect=AssertionError('No fallback that hides failure')):
            with self.assertRaises(OSError):
                self.e.sandbox_environment()

    def setUp(self):
        from wzl_blackbox import native_engine as engine
        self.e = engine
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'lab'
        self.root.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(engine, 'LAB_BASE', self.base).start()
        for relative in engine.BINARIES:
            p = self.root / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(relative.encode())
        patch.object(engine, 'BINARIES', {p: hashlib.sha256(p.encode()).hexdigest().upper() for p in engine.BINARIES}).start()
        files = {
            'Config.ini': '[GameConf]\nGameDirectory={r}\\\nGetAutoStartServer=0\nUseSqliteDB=1\nSqliteDBName={r}\\Mud2\\DB\\ApexM2.DB\nSqliteDBFile={r}\\Mud2\\DB\\ApexM2.DB\n[DataSaveDB]\nDataSaveDBType=0\n',
            'Mir200/!Setup.txt': '[Server]\nDBAddr=127.0.0.1\nDBPort=26000\nIDSAddr=127.0.0.1\nIDSPort=25600\nGateAddr=127.0.0.1\nGatePort=25000\nMsgSrvAddr=127.0.0.1\nMsgSrvPort=24900\nLogServerAddr=127.0.0.1\nLogServerPort=30000\nUseSqliteDB=1\nSqliteDBName={r}\\Mud2\\DB\\ApexM2.DB\nSqliteDBFile={r}\\Mud2\\DB\\ApexM2.DB\n[Share]\nEnvirDir={r}\\Mir200\\Envir\\\n[DataSaveDB]\nDataSaveDBType=0\n',
            'DBServer/dbsrc.ini': '[Setup]\nServerAddr=127.0.0.1\nServerPort=26000\nGateAddr=127.0.0.1\nGatePort=25100\nUseSqliteDB=1\nSqliteDBName={r}\\Mud2\\DB\\ApexM2.DB\nSqliteDBFile={r}\\Mud2\\DB\\ApexM2.DB\n[Server]\nIDSAddr=127.0.0.1\nIDSPort=25600\n[DB]\nDir={r}\\DBServer\\FDB\\\n[DataSaveDB]\nDataSaveDBType=0\n',
            'LoginSrv/Logsrv.ini': '[Server]\nGateAddr=127.0.0.1\nGatePort=25500\nServerAddr=127.0.0.1\nServerPort=25600\nMonAddr=127.0.0.1\nMonPort=23000\n[DB]\nIdDir={r}\\LoginSrv\\IDDB\\\n[DataSaveDB]\nDataSaveDBType=0\n',
            'LogServer/LogData.ini': '[Setup]\nPort=30000\nBaseDir={r}\\LogServer\\BaseDir\\\n',
            'Mir200/系统插件.ini': '[setup]\nIP插件=0\n脚本解密=0\n远程脚本=0\n封包记录=0\n',
            'Mir200/PlugList.txt': '',
            'Mir200/Envir/MapQuest_def/QManage.txt': '[@main]\n#ACT\nBREAK\n',
            'Mir200/Envir/Market_Def/QFunction-0.txt': '[@main]\n#ACT\nBREAK\n',
            'Mir200/Envir/MapInfo.txt': '[0 NativeControlLab 0] SAFE\n',
        }
        for relative, text in files.items():
            p = self.root / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text.format(r=self.root).replace('\n', '\r\n').encode('gb18030'))
        from wzl_blackbox.native_control import read_ini
        cfg, _ = read_ini(self.root / 'Mir200/!Setup.txt')
        for key, folder in {'BaseDir': 'Share', 'GuildDir': 'GuildBase/Guilds', 'VentureDir': 'ShareV', 'ConLogDir': 'ConLog', 'LogDir': 'Log', 'PlugDir': '', 'BoxsDir': 'Envir/Boxs', 'CastleDir': 'Castle', 'MapDir': 'Map', 'NoticeDir': 'Notice', 'SortDir': 'Sort', 'ChatDir': 'ChatLog'}.items():
            cfg['Share'][key] = str(self.root / 'Mir200' / folder) + '\\'
        import io
        stream = io.StringIO()
        cfg.write(stream, space_around_delimiters=False)
        (self.root / 'Mir200/!Setup.txt').write_bytes(stream.getvalue().replace('\n', '\r\n').encode('gb18030'))
        db = self.root / 'Mud2/DB/ApexM2.DB'
        db.parent.mkdir(parents=True)
        import sqlite3
        with sqlite3.connect(db) as conn:
            conn.execute('create table fixture(id integer)')
        conn.close()

    def mutate(self, relative, old, new):
        p = self.root / relative
        p.write_bytes(p.read_bytes().replace(old.encode('gb18030'), new.encode('gb18030')))

    def test_engine_ui_accepts_main_form_class_case_variants(self):
        for class_name in ('TFrmMain', 'TfrmMain'):
            with self.subTest(class_name=class_name):
                main = Mock()
                main.class_name.return_value = class_name
                with patch.object(self.e.EngineUI, 'verify'), patch('pywinauto.Application'), patch('wzl_blackbox.native_control.native_forms', return_value=[main]):
                    ui = self.e.EngineUI(self.root, 12345, 'GameCenter.exe')
                    self.assertEqual(ui.dialogs(), [])
                self.assertIs(ui.main, main)

    def test_engine_ui_rejects_duplicate_main_forms_with_different_case(self):
        first, second = Mock(), Mock()
        first.class_name.return_value = 'TFrmMain'
        second.class_name.return_value = 'TfrmMain'
        with patch.object(self.e.EngineUI, 'verify'), patch('pywinauto.Application'), patch('wzl_blackbox.native_control.native_forms', return_value=[first, second]):
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                self.e.EngineUI(self.root, 12345, 'GameCenter.exe')

    def test_valid_lab_preflight_is_read_only(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.e.preflight(self.root)
        self.assertEqual(result['root'], str(self.root.resolve()))
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_native_mixed_bom_gb18030_is_read_without_modifying_bytes(self):
        from wzl_blackbox.native_control import read_ini
        path = self.root / 'Config.ini'
        raw = b'\xef\xbb\xbf' + '[GameConf]\r\nServerName=翎风测试\r\n'.encode('gb18030')
        path.write_bytes(raw)
        cfg, _ = read_ini(path)
        self.assertEqual(cfg['GameConf']['ServerName'], '翎风测试')
        self.assertEqual(self.e.ini_bytes(raw)[('GameConf', 'ServerName')], '翎风测试')
        self.assertEqual(path.read_bytes(), raw)

    def full_profile(self):
        patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root, create=True).start()
        patch.object(self.e, 'sandbox_environment', return_value={}).start()
        patch.object(self.e, 'STACK_BINARIES', self.e.BINARIES).start()
        (self.root / 'LoginSrv/IDDB').mkdir(exist_ok=True)

    def test_complete_guest_profile_preserves_real_business_scripts(self):
        self.full_profile()
        script = self.root / 'Mir200/Envir/Market_Def/QFunction-0.txt'
        script.write_bytes(b'[@main]\r\n#ACT\r\nSENDMSG 6 test\r\nBREAK\r\n')
        before = script.read_bytes()
        result = self.e.preflight(self.root)
        self.assertTrue(result['wholeEngineStartStop'])
        self.assertEqual(result['mode'], 'network-disabled-WDAG-complete')
        self.assertEqual(script.read_bytes(), before)

    def test_complete_guest_profile_uses_native_ports_and_isolated_wildcard_bindings(self):
        self.full_profile()
        self.mutate('Mir200/!Setup.txt', 'DBPort=26000', 'DBPort=6000')
        self.mutate('DBServer/dbsrc.ini', 'GateAddr=127.0.0.1', 'GateAddr=0.0.0.0')
        self.mutate('Mir200/!Setup.txt', 'MsgSrvAddr=127.0.0.1', 'MsgSrvAddr=0.0.0.0')
        self.assertTrue(self.e.preflight(self.root)['wholeEngineStartStop'])
        self.mutate('Mir200/!Setup.txt', 'DBAddr=127.0.0.1', 'DBAddr=10.0.0.1')
        with self.assertRaisesRegex(ValueError, 'address|loopback'):
            self.e.preflight(self.root)

    def test_complete_guest_profile_still_rejects_plugins_and_external_database(self):
        self.full_profile()
        (self.root / 'Mir200/PlugList.txt').write_bytes(b'IPLocal.dll')
        with self.assertRaisesRegex(ValueError, 'plugin'):
            self.e.preflight(self.root)
        (self.root / 'Mir200/PlugList.txt').write_bytes(b'')
        self.mutate('Config.ini', 'SqliteDBFile=' + str(self.root), 'SqliteDBFile=D:\\MirServer')
        with self.assertRaisesRegex(ValueError, 'path|database'):
            self.e.preflight(self.root)

    def test_complete_guest_profile_never_permits_arbitrary_external_paths(self):
        self.full_profile()
        self.mutate('Mir200/!Setup.txt', 'MapDir=' + str(self.root) + '\\Mir200\\Map\\', 'MapDir=D:\\MirServer\\Mir200\\Map\\')
        with self.assertRaisesRegex(ValueError, 'path|binding'):
            self.e.preflight(self.root)

    def test_complete_guest_root_always_requires_actual_network_isolation(self):
        with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root, create=True), patch.object(self.e, 'sandbox_environment', side_effect=PermissionError('network enabled')):
            with self.assertRaisesRegex(PermissionError, 'network'):
                self.e.validate_lab_root(self.root)

    def test_stack_waits_for_native_start_button_after_components_have_exited(self):
        ui = Mock()
        ui.main.is_enabled.return_value = True
        ui.dialogs.return_value = []
        button = object()
        with patch.object(self.e, 'stack_button', side_effect=[ValueError('not restored yet'), button]), patch.object(self.e.time, 'sleep'):
            self.assertIs(self.e.wait_stack_button(ui, '启动游戏服务器(&S)', timeout=1), button)

    def test_stack_start_waits_for_controller_finalization_after_components_are_ready(self):
        ui = Mock()
        ui.dialogs.return_value = []
        page = Mock()
        page.parent.return_value.handle = ui.main.handle
        checks = []
        for caption in self.e.STACK_CHECKS:
            control = Mock()
            control.window_text.return_value = caption
            checks.append(control)
        ui.main.descendants.side_effect = lambda class_name: [page] if class_name == 'TPageControl' else checks
        stopped = {name: [] for name in self.e.STACK_COMPONENTS}
        running = {name: [i + 100] for i, name in enumerate(self.e.STACK_COMPONENTS)}
        def button(_ui, caption):
            if caption == '停止游戏服务器(&T)':
                raise ValueError('native controller finalization not complete yet')
            return Mock()
        with patch.object(self.e, 'matching_processes', return_value=[]), patch.object(self.e, 'stack_running', side_effect=[stopped, running]), patch.object(self.e, 'start_program', return_value={'pid': 123}), patch.object(self.e, 'EngineUI', return_value=ui), patch.object(self.e, 'verify_controller_target'), patch('pywinauto.controls.common_controls.TabControlWrapper'), patch('pywinauto.controls.win32_controls.ButtonWrapper') as wrapper, patch.object(self.e, 'stack_button', side_effect=button), patch.object(self.e, 'stack_confirm'), patch.object(self.e, 'stack_m2_ready', return_value=True), patch.object(self.e, 'wait_stack_button') as wait_button, patch.object(self.e, 'tcp_listeners', return_value=[]), patch.object(self.e, 'sandbox_environment', return_value={}):
            wrapper.return_value.get_check_state.return_value = 1
            self.assertTrue(self.e.start_stack(self.root)['allSevenComponentsRunning'])
            wait_button.assert_called_once_with(ui, '停止游戏服务器(&T)')

    def test_stack_readiness_uses_the_current_native_peer_ports(self):
        ui = Mock()
        ui.main.descendants.return_value = [Mock()]
        ui.main.descendants.return_value[0].window_text.return_value = '游戏处理引擎初始化成功...登录服务器(127.0.0.1:5600)连接成功...数据库服务器(127.0.0.1:6000)连接成功...'
        self.mutate('Mir200/!Setup.txt', 'DBPort=26000', 'DBPort=6000')
        self.mutate('Mir200/!Setup.txt', 'IDSPort=25600', 'IDSPort=5600')
        with patch.object(self.e, 'EngineUI', return_value=ui), patch.object(self.e, 'tcp_listeners', return_value=[{'address': '127.0.0.1', 'port': 25000}]):
            self.assertTrue(self.e.stack_m2_ready(self.root, {'Mir200/M2Server.exe': [123]}))

    def test_complete_m2_listener_contract_uses_native_values_not_minimal_sample_ports(self):
        self.full_profile()
        self.mutate('Mir200/!Setup.txt', 'GateAddr=127.0.0.1', 'GateAddr=0.0.0.0')
        self.mutate('Mir200/!Setup.txt', 'GatePort=25000', 'GatePort=5000')
        self.assertEqual(self.e.expected_m2_listeners(self.root), [{'address': '0.0.0.0', 'port': 5000}])

    def test_complete_retains_only_unselected_access_database_paths(self):
        self.full_profile()
        self.mutate('Config.ini', '[GameConf]', '[GameConf]\r\nAccessFileName=D:\\unused-access.mdb')
        report = self.e.preflight(self.root)
        self.assertEqual(report['retainedLegacyPaths']['Config.ini/GameConf/AccessFileName'], r'D:\unused-access.mdb')
        self.mutate('Config.ini', 'UseSqliteDB=1', 'UseSqliteDB=0')
        with self.assertRaisesRegex(ValueError, 'path|database'):
            self.e.preflight(self.root)

    def test_waiting_controller_state_rejects_new_modal_dialog(self):
        ui = Mock()
        ui.main.is_enabled.return_value = False
        ui.dialogs.return_value = [object()]
        with self.assertRaisesRegex(RuntimeError, 'blocked'):
            self.e.wait_stack_button(ui, '启动游戏服务器(&S)', timeout=1)

    def test_complete_start_returns_the_current_preflight_legacy_path_warnings(self):
        self.full_profile()
        warning = {'Mir200/!Setup.txt/Share/SortDir': 'G:\\old\\Sort\\'}
        for command, target in (('engine-start', 'start_stack'), ('m2-start', 'start_program'), ('engine-controller-start', 'start_program')):
            with self.subTest(command=command), patch.object(self.e, 'preflight', return_value={'retainedLegacyPaths': warning}), patch.object(self.e, target, return_value={'pid': 123}):
                result = self.e._run_engine({'command': command, 'arguments': {'labRoot': str(self.root)}, 'policy': {'allowedWriteRoots': [str(self.base)]}})
                self.assertEqual(result['retainedLegacyPaths'], warning)

    def test_stack_m2_log_success_without_a_real_listener_is_not_ready(self):
        ui = Mock()
        ui.main.descendants.return_value = [Mock()]
        ui.main.descendants.return_value[0].window_text.return_value = '游戏处理引擎初始化成功...登录服务器(127.0.0.1:25600)连接成功...数据库服务器(127.0.0.1:26000)连接成功...'
        with patch.object(self.e, 'EngineUI', return_value=ui), patch.object(self.e, 'tcp_listeners', return_value=[]):
            self.assertFalse(self.e.stack_m2_ready(self.root, {'Mir200/M2Server.exe': [123]}))

    def test_stack_m2_listener_mismatch_is_an_error_not_native_readiness(self):
        ui = Mock()
        ui.main.descendants.return_value = [Mock()]
        ui.main.descendants.return_value[0].window_text.return_value = '游戏处理引擎初始化成功...登录服务器(127.0.0.1:25600)连接成功...数据库服务器(127.0.0.1:26000)连接成功...'
        with patch.object(self.e, 'EngineUI', return_value=ui), patch.object(self.e, 'tcp_listeners', return_value=[{'address': '0.0.0.0', 'port': 25000}]):
            with self.assertRaisesRegex(ValueError, 'listener'):
                self.e.stack_m2_ready(self.root, {'Mir200/M2Server.exe': [123]})

    def test_rejects_formal_root_even_if_caller_allows_it(self):
        with self.assertRaises(PermissionError): self.e.validate_lab_root(Path(r'D:\MirServer'))

    def test_rejects_external_target_despite_copied_executable(self):
        self.mutate('Config.ini', str(self.root) + '\\', 'D:\\MirServer\\')
        with self.assertRaisesRegex(ValueError, 'directory|path'): self.e.preflight(self.root)

    def test_rejects_external_db_in_one_of_the_two_keys(self):
        self.mutate('Mir200/!Setup.txt', 'SqliteDBFile=' + str(self.root), 'SqliteDBFile=D:\\MirServer')
        with self.assertRaisesRegex(ValueError, 'path|database'): self.e.preflight(self.root)

    def test_rejects_wide_bind_and_formal_peer_port(self):
        self.mutate('Mir200/!Setup.txt', 'GateAddr=127.0.0.1', 'GateAddr=0.0.0.0')
        with self.assertRaisesRegex(ValueError, 'loopback'): self.e.preflight(self.root)
        self.mutate('Mir200/!Setup.txt', 'GateAddr=0.0.0.0', 'GateAddr=127.0.0.1')
        self.mutate('Mir200/!Setup.txt', 'DBPort=26000', 'DBPort=6000')
        with self.assertRaisesRegex(ValueError, 'port'): self.e.preflight(self.root)

    def test_rejects_plugins_autostart_and_extra_scripts(self):
        self.mutate('Mir200/PlugList.txt', '', 'IPLocal.dll\r\n')
        with self.assertRaisesRegex(ValueError, 'plugin'): self.e.preflight(self.root)
        (self.root / 'Mir200/PlugList.txt').write_bytes(b'')
        self.mutate('Config.ini', 'GetAutoStartServer=0', 'GetAutoStartServer=1')
        with self.assertRaisesRegex(ValueError, 'auto'): self.e.preflight(self.root)
        self.mutate('Config.ini', 'GetAutoStartServer=1', 'GetAutoStartServer=0')
        (self.root / 'Mir200/Envir/Robot.txt').write_bytes(b'EXEC dangerous')
        with self.assertRaisesRegex(ValueError, 'script'): self.e.preflight(self.root)

    def test_rejects_missing_db_or_unknown_executable(self):
        (self.root / 'Mud2/DB/ApexM2.DB').unlink()
        with self.assertRaisesRegex(ValueError, 'database'): self.e.preflight(self.root)

    def test_rejects_unverified_binary_hash(self):
        (self.root / 'Mir200/M2Server.exe').write_bytes(b'unknown native build')
        with self.assertRaisesRegex(ValueError, 'binary'): self.e.preflight(self.root)

    def test_relative_escape_and_internal_script_rebinding_are_denied(self):
        self.mutate('Mir200/!Setup.txt', 'EnvirDir=' + str(self.root) + '\\Mir200\\Envir\\', 'EnvirDir=..\\..\\outside\\')
        with self.assertRaisesRegex(ValueError, 'path|directory'): self.e.preflight(self.root)
        self.mutate('Mir200/!Setup.txt', 'EnvirDir=..\\..\\outside\\', 'EnvirDir=' + str(self.root) + '\\other-scripts\\')
        with self.assertRaisesRegex(ValueError, 'path|directory'): self.e.preflight(self.root)

    def test_hardlinked_private_database_is_rejected(self):
        import os
        db = self.root / 'Mud2/DB/ApexM2.DB'
        os.link(db, self.base / 'outside-original.db')
        with self.assertRaisesRegex(ValueError, 'hard'): self.e.preflight(self.root)

    def test_native_created_data_list_is_not_treated_as_a_script(self):
        (self.root / 'Mir200/Envir/ClientEatItemNameList.txt').write_bytes(b'HPStone\r\n')
        (self.root / 'Mir200/Envir/Market_Def/QBatter-0.txt').write_bytes(b';native comment only\r\n')
        self.assertTrue(self.e.preflight(self.root)['isolated'])

    def test_rejects_unknown_reload_and_arbitrary_parameter(self):
        for command, args in [('m2-reload', {'target': 'delete-users'}), ('engine-parameter', {'parameter': 'RunShell', 'value': 'cmd.exe'})]:
            with self.assertRaises(ValueError):
                self.e.validate_operation(command, args)

    def test_parameter_rejects_bool_overflow_and_precondition_omission(self):
        for value in (True, -1, 1000000):
            with self.assertRaises(ValueError):
                self.e.validate_operation('engine-parameter', {'parameter': 'console-user-count-interval', 'value': value, 'expectedValue': 100})
        with self.assertRaises(ValueError):
            self.e.validate_operation('engine-parameter', {'parameter': 'console-user-count-interval', 'value': 101})

    def test_entire_engine_start_is_not_opened_with_unverified_database_bindings(self):
        with self.assertRaises(ValueError): self.e.validate_operation('engine-start', {})

    def test_full_stack_commands_deny_host_labs_even_when_writable(self):
        for command in ('engine-start', 'engine-stop'):
            with self.assertRaises(PermissionError):
                self.e.validate_operation(command, {'labRoot': str(self.root)})

    def test_sandbox_network_observation_requires_every_isolation_fact(self):
        state = {'username': 'WDAGUtilityAccount', 'nonLoopbackAddresses': [], 'defaultRoutes': []}
        self.assertEqual(self.e.validate_sandbox_observation(state), state)
        for key, value in (('username', 'Administrator'), ('nonLoopbackAddresses', ['10.0.0.1']),
                           ('defaultRoutes', ['0.0.0.0/0']), ('defaultRoutes', None)):
            with self.subTest(key=key, value=value), self.assertRaises(PermissionError):
                self.e.validate_sandbox_observation({**state, key: value})

    def test_sandbox_root_requires_live_isolation_check(self):
        with patch.object(self.e, 'SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment', side_effect=PermissionError('network enabled')):
            with self.assertRaisesRegex(PermissionError, 'network'):
                self.e.validate_lab_root(self.root)

    def test_sandbox_preflight_uses_current_component_profile(self):
        current = {**self.e.BINARIES, 'DBServer/DBServer.exe': hashlib.sha256(b'current DB').hexdigest().upper()}
        (self.root / 'DBServer/DBServer.exe').write_bytes(b'current DB')
        (self.root / 'LoginSrv/IDDB').mkdir()
        with patch.object(self.e, 'SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment', return_value={}), patch.object(self.e, 'STACK_BINARIES', current):
            result = self.e.preflight(self.root)
            self.assertTrue(result['wholeEngineStartStop'])
            self.assertEqual(result['binaries'], current)

    def test_sandbox_preflight_does_not_accept_old_database_profile(self):
        current = {**self.e.BINARIES, 'DBServer/DBServer.exe': hashlib.sha256(b'current DB').hexdigest().upper()}
        with patch.object(self.e, 'SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment', return_value={}), patch.object(self.e, 'STACK_BINARIES', current):
            with self.assertRaisesRegex(ValueError, 'binary'):
                self.e.preflight(self.root)

    def test_stack_preflight_requires_account_database_directory(self):
        with patch.object(self.e, 'SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment', return_value={}), patch.object(self.e, 'STACK_BINARIES', self.e.BINARIES):
            with self.assertRaisesRegex(ValueError, 'IDDB'):
                self.e.preflight(self.root)

    def native_question(self):
        dialog = Mock()
        dialog.class_name.return_value = '#32770'
        dialog.window_text.return_value = '确认信息'
        dialog.handle = 456
        yes, no, text = Mock(), Mock(), Mock()
        yes.control_id.return_value, no.control_id.return_value = 6, 7
        yes.window_text.return_value, no.window_text.return_value = '是(&Y)', '否(&N)'
        text.window_text.return_value = '是否确认停止游戏服务器?'
        dialog.descendants.side_effect = lambda class_name: [yes, no] if class_name == 'Button' else [text]
        return dialog, yes

    def test_native_active_dialog_dispatch_needs_no_global_keyboard_focus(self):
        dialog, yes = self.native_question()
        with patch.object(self.e, 'active_thread_window', return_value=456):
            self.e.confirm_native_yes(dialog, '是否确认停止游戏服务器?', require_foreground=False)
        dialog.set_focus.assert_not_called()
        yes.post_message.assert_called_once_with(0xF5, 0, 0)

    def test_native_inactive_dialog_cannot_be_confirmed(self):
        dialog, yes = self.native_question()
        with patch.object(self.e, 'active_thread_window', return_value=789):
            with self.assertRaises(RuntimeError):
                self.e.confirm_native_yes(dialog, '是否确认停止游戏服务器?', require_foreground=False)
        yes.post_message.assert_not_called()

    def test_stack_button_selection_refuses_ambiguous_or_disabled_controls(self):
        ui = Mock()
        control = Mock()
        control.window_text.return_value = '启动游戏服务器(&S)'
        control.is_visible.return_value = control.is_enabled.return_value = True
        ui.main.descendants.return_value = [control, control]
        with self.assertRaises(ValueError):
            self.e.stack_button(ui, '启动游戏服务器(&S)')
        ui.main.descendants.return_value = [control]
        control.is_enabled.return_value = False
        with self.assertRaises(ValueError):
            self.e.stack_button(ui, '启动游戏服务器(&S)')

    def test_stack_readiness_requires_exactly_one_of_every_component_and_m2_ready(self):
        running = {name: [index + 100] for index, name in enumerate(('DBServer/DBServer.exe', 'Mir200/M2Server.exe', 'LoginGate/LoginGate.exe', 'LoginSrv/LoginSrv.exe', 'LogServer/LogDataServer.exe', 'RunGate/RunGate.exe', 'SelGate/SelGate.exe'))}
        self.assertTrue(self.e.stack_ready(running, True))
        self.assertFalse(self.e.stack_ready(running, False))
        self.assertFalse(self.e.stack_ready({k: v for k, v in running.items() if 'RunGate' not in k}, True))
        self.assertFalse(self.e.stack_ready({**running, 'DBServer/DBServer.exe': [1, 2]}, True))

    def test_fixed_sandbox_root_cannot_be_a_directory_link(self):
        import os
        alias = self.base / 'fixed-sandbox'
        os.symlink(self.root, alias, target_is_directory=True)
        with patch.object(self.e, 'SANDBOX_ROOT', alias), patch.object(self.e, 'sandbox_environment', return_value={}):
            with self.assertRaisesRegex(ValueError, 'reparse'):
                self.e.validate_lab_root(alias)

    def test_controller_target_check_accepts_only_current_config_and_runtime_title(self):
        ui = Mock(root=self.root)
        ui.main.window_text.return_value = 'Native console [' + str(self.root) + '\\]'
        self.e.verify_controller_target(ui)
        ui.main.window_text.return_value = 'Native console [' + str(self.base / 'other') + '\\]'
        with self.assertRaises(PermissionError):
            self.e.verify_controller_target(ui)

    def test_controller_target_check_also_rejects_changed_config(self):
        ui = Mock(root=self.root)
        ui.main.window_text.return_value = 'Native console [' + str(self.root) + '\\]'
        self.mutate('Config.ini', str(self.root) + '\\', str(self.base / 'other') + '\\')
        with self.assertRaises(PermissionError):
            self.e.verify_controller_target(ui)

    def test_guest_form_activation_checks_actual_network_and_thread_not_global_focus(self):
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.root, ui.verify = self.root.resolve(), Mock()
        form = Mock(handle=123)
        with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment') as network, patch.object(self.e, 'active_thread_window', return_value=123):
            self.assertTrue(ui.prepare_form(form))
            network.assert_called_once_with()
        form.set_focus.assert_not_called()

    def test_guest_form_activation_rejects_inactive_target_or_network_change(self):
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.root, ui.verify = self.root.resolve(), Mock()
        form = Mock(handle=123)
        with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment'), patch.object(self.e, 'active_thread_window', return_value=456):
            with self.assertRaisesRegex(RuntimeError, 'active'):
                ui.prepare_form(form)
        with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment', side_effect=PermissionError('network changed')):
            with self.assertRaises(PermissionError):
                ui.prepare_form(form)
        form.set_focus.assert_not_called()

    def test_guest_hidden_native_form_is_restored_before_active_thread_check(self):
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.root, ui.verify = self.root.resolve(), Mock()
        form = Mock(handle=123)
        form.is_visible.return_value = False
        state = {'restored': False}
        form.restore.side_effect = lambda: state.update(restored=True)
        with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment'), patch.object(self.e, 'active_thread_window', side_effect=lambda handle: 123 if state['restored'] else 0):
            self.assertTrue(ui.prepare_form(form))
        form.restore.assert_called_once_with()
        form.set_focus.assert_not_called()

    def test_host_form_activation_keeps_original_foreground_contract(self):
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.root, ui.verify = self.root, Mock()
        form = Mock()
        self.assertFalse(ui.prepare_form(form))
        form.set_focus.assert_called_once_with()

    def test_guest_visible_form_without_active_window_is_focused_and_rechecked(self):
        for initial in (0, None):
            with self.subTest(initial=initial):
                ui = self.e.EngineUI.__new__(self.e.EngineUI)
                ui.root, ui.verify = self.root.resolve(), Mock()
                form = Mock(handle=123)
                form.is_visible.return_value = True
                state = {'active': initial}
                form.set_focus.side_effect = lambda: state.update(active=123)
                with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment'), patch.object(self.e, 'active_thread_window', side_effect=lambda handle: state['active']):
                    self.assertTrue(ui.prepare_form(form))
                form.restore.assert_not_called()
                form.set_focus.assert_called_once_with()

    def test_guest_visible_form_does_not_activate_over_another_active_window(self):
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.root, ui.verify = self.root.resolve(), Mock()
        form = Mock(handle=123)
        form.is_visible.return_value = True
        with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment'), patch.object(self.e, 'active_thread_window', return_value=456):
            with self.assertRaisesRegex(RuntimeError, 'active'):
                ui.prepare_form(form)
        form.restore.assert_not_called()
        form.set_focus.assert_not_called()

    def test_guest_activation_must_establish_exact_active_window(self):
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.root, ui.verify = self.root.resolve(), Mock()
        form = Mock(handle=123)
        form.is_visible.return_value = True
        with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment'), patch.object(self.e, 'active_thread_window', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'active'):
                ui.prepare_form(form)
        form.set_focus.assert_called_once_with()

    def test_guest_direct_menu_does_not_require_foreground_activation(self):
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.root, ui.verify, ui.dialogs = self.root.resolve(), Mock(), Mock(return_value=[])
        form = Mock(handle=123)
        form.is_visible.return_value = form.is_enabled.return_value = True
        ui.main = form
        with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment'), patch.object(self.e, 'active_thread_window', return_value=None):
            self.assertTrue(ui.prepare_form(form, direct_menu=True))
        form.set_focus.assert_not_called()

    def test_guest_direct_menu_still_rejects_other_active_window(self):
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.root, ui.verify, ui.dialogs = self.root.resolve(), Mock(), Mock(return_value=[])
        form = Mock(handle=123)
        form.is_visible.return_value = form.is_enabled.return_value = True
        ui.main = form
        with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment'), patch.object(self.e, 'active_thread_window', return_value=456):
            with self.assertRaisesRegex(RuntimeError, 'active'):
                ui.prepare_form(form, direct_menu=True)
        form.set_focus.assert_not_called()

    def test_guest_menu_accepts_only_observed_hidden_client_form(self):
        for visible, cls, title, handle, expected in (
                (False, 'TFrmConfigClient', '客户端控制', 456, True),
                (True, 'TFrmConfigClient', '客户端控制', 456, False),
                (False, 'TUnknown', '客户端控制', 456, False),
                (False, 'TFrmConfigClient', 'other', 456, False),
                (False, 'TFrmConfigClient', '客户端控制', 789, False)):
            with self.subTest(visible=visible, cls=cls, title=title, handle=handle):
                ui = self.e.EngineUI.__new__(self.e.EngineUI)
                ui.root, ui.pid, ui.verify = self.root.resolve(), 1234, Mock()
                ui.dialogs = Mock(return_value=[])
                form = Mock(handle=123)
                form.is_visible.return_value = form.is_enabled.return_value = True
                ui.main = form
                hidden = Mock(handle=handle)
                hidden.is_visible.return_value = visible
                hidden.class_name.return_value = cls
                hidden.window_text.return_value = title
                with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment'), patch.object(self.e, 'active_thread_window', return_value=456), patch.object(self.e, 'hidden_client_form', return_value=expected):
                    if expected:
                        self.assertTrue(ui.prepare_form(form, direct_menu=True))
                    else:
                        with self.assertRaises(RuntimeError):
                            ui.prepare_form(form, direct_menu=True)
                form.set_focus.assert_not_called()

    def test_hidden_client_form_native_lookup_rejects_wrong_identity(self):
        for owner, visible, cls, title, expected in (
                (1234, False, 'TFrmConfigClient', '客户端控制', True),
                (1235, False, 'TFrmConfigClient', '客户端控制', False),
                (1234, True, 'TFrmConfigClient', '客户端控制', False),
                (1234, False, 'TUnknown', '客户端控制', False),
                (1234, False, 'TFrmConfigClient', 'other', False)):
            with self.subTest(owner=owner, visible=visible, cls=cls, title=title):
                with patch('win32gui.IsWindow', return_value=True), patch('win32process.GetWindowThreadProcessId', return_value=(99, owner)), patch('win32gui.IsWindowVisible', return_value=visible), patch('win32gui.GetClassName', return_value=cls), patch('win32gui.GetWindowText', return_value=title):
                    self.assertEqual(self.e.hidden_client_form(456, 1234), expected)

    def test_hidden_client_form_query_failure_is_rejected(self):
        with patch('win32gui.IsWindow', side_effect=OSError('query failed')):
            self.assertFalse(self.e.hidden_client_form(456, 1234))
        self.assertFalse(self.e.hidden_client_form(456, None))
        self.assertFalse(self.e.hidden_client_form(456, True))

    def test_guest_direct_menu_is_only_for_unblocked_main(self):
        for invalid in ('different-form', 'modal', 'disabled'):
            with self.subTest(invalid=invalid):
                ui = self.e.EngineUI.__new__(self.e.EngineUI)
                ui.root, ui.verify = self.root.resolve(), Mock()
                form = Mock(handle=123)
                form.is_visible.return_value = True
                form.is_enabled.return_value = invalid != 'disabled'
                ui.main = Mock(handle=456) if invalid == 'different-form' else form
                ui.dialogs = Mock(return_value=[Mock()] if invalid == 'modal' else [])
                with patch.object(self.e, 'COMPLETE_SANDBOX_ROOT', self.root), patch.object(self.e, 'sandbox_environment'):
                    with self.assertRaises(ValueError):
                        ui.prepare_form(form, direct_menu=True)
                form.set_focus.assert_not_called()

    def test_host_direct_menu_keeps_foreground_contract(self):
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.root, ui.verify = self.root, Mock()
        form = Mock()
        self.assertFalse(ui.prepare_form(form, direct_menu=True))
        form.set_focus.assert_called_once_with()

    def test_strict_process_query_cannot_treat_permission_error_as_exit(self):
        with patch.object(self.e, 'named_processes', return_value=[123]), patch.object(self.e, 'process_image', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.e.matching_processes(self.root / 'Mir200/M2Server.exe', strict=True)

    def test_strict_process_query_tolerates_only_confirmed_exit(self):
        with patch.object(self.e, 'named_processes', return_value=[123]), patch.object(self.e, 'process_image', side_effect=ProcessLookupError('exited')):
            self.assertEqual(self.e.matching_processes(self.root / 'Mir200/M2Server.exe', strict=True), [])

    def test_process_snapshot_identifies_the_current_native_process(self):
        import os
        self.assertIn(os.getpid(), self.e.named_processes(Path(sys.executable).name))

    def test_stack_m2_main_form_creation_is_waitable(self):
        ui = Mock()
        ui.main.descendants.return_value = [Mock()]
        ui.main.descendants.return_value[0].window_text.return_value = '游戏处理引擎初始化成功...登录服务器(127.0.0.1:25600)连接成功...数据库服务器(127.0.0.1:26000)连接成功...'
        running = {'Mir200/M2Server.exe': [123]}
        with patch.object(self.e, 'EngineUI', side_effect=[LookupError('not constructed'), ui]), patch.object(self.e, 'tcp_listeners', return_value=[{'address': '127.0.0.1', 'port': 25000}]):
            self.assertFalse(self.e.stack_m2_ready(self.root, running))
            self.assertTrue(self.e.stack_m2_ready(self.root, running))

    def test_stack_m2_wrong_identity_is_not_a_waitable_window(self):
        with patch.object(self.e, 'EngineUI', side_effect=ValueError('wrong PID')):
            with self.assertRaises(ValueError):
                self.e.stack_m2_ready(self.root, {'Mir200/M2Server.exe': [123]})

    def test_menu_selection_rejects_disabled_or_duplicate_items(self):
        menu = {'menu_items': [{'text': '控制(&C)', 'state': 0, 'menu_items': {'menu_items': [{'text': '重新加载(&R)', 'state': 0, 'menu_items': {'menu_items': [{'text': 'QFunction 功能脚本(&Q)', 'state': 0, 'item_id': 16}]}}]}}]}
        path = ['控制(&C)', '重新加载(&R)', 'QFunction 功能脚本(&Q)']
        self.assertEqual(self.e.menu_command_id(menu, path), 16)
        menu['menu_items'][0]['state'] = 3
        with self.assertRaises(ValueError): self.e.menu_command_id(menu, path)
        menu['menu_items'][0]['state'] = 0
        menu['menu_items'].append(menu['menu_items'][0].copy())
        with self.assertRaises(ValueError): self.e.menu_command_id(menu, path)

    def test_tcp_rows_report_actual_bind_not_only_configured_address(self):
        import os
        import socket
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            port = server.getsockname()[1]
            rows = self.e.tcp_listeners(os.getpid())
            self.assertIn({'address': '127.0.0.1', 'port': port}, rows)

    def test_disabled_input_method_status_is_not_an_actionable_dialog(self):
        from types import SimpleNamespace
        from wzl_blackbox import native_control
        overlay = SimpleNamespace(class_name=lambda: 'SoPY_Status', is_visible=lambda: True, is_enabled=lambda: False)
        ui = self.e.EngineUI.__new__(self.e.EngineUI)
        ui.pid = 123
        with patch.object(native_control, 'native_forms', return_value=[overlay]):
            self.assertEqual(ui.dialogs(), [])

    def test_reload_ack_requires_native_completion_not_startup_or_lua_alone(self):
        self.assertTrue(self.e.reload_acknowledged('items', '2026-10-15 重新加载物品数据库完成...'))
        self.assertFalse(self.e.reload_acknowledged('items', '物品数据库加载成功(1530)...'))
        self.assertFalse(self.e.reload_acknowledged('parameters', '[Lua] scripts reloaded'))
        self.assertFalse(self.e.reload_acknowledged('npcs', '交易NPC重新加载完成...'))
        self.assertTrue(self.e.reload_acknowledged('npcs', '交易NPC重新加载完成...管理NPC重新加载完成...'))

    def test_busy_native_operation_is_rejected_across_threads(self):
        from concurrent.futures import ThreadPoolExecutor
        def attempt():
            with self.e.serial_engine_operation():
                return 'wrongly entered'
        with self.e.serial_engine_operation():
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaisesRegex(ValueError, 'running'):
                    pool.submit(attempt).result(timeout=5)

    def test_failed_native_start_cleans_only_its_new_child(self):
        from types import SimpleNamespace
        child = SimpleNamespace(pid=4321, terminated=False, poll=lambda: None, wait=lambda **kw: 0)
        child.terminate = lambda: setattr(child, 'terminated', True)
        with patch.object(self.e, 'matching_processes', return_value=[]), patch.object(self.e.subprocess, 'Popen', return_value=child), patch.object(self.e, 'EngineUI', side_effect=ValueError('unsafe copied UI')):
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                self.e.start_program(self.root, 'GameCenter.exe')
        self.assertTrue(child.terminated)

    def test_controller_start_restores_native_regenerated_component_configs(self):
        from types import SimpleNamespace
        path = self.root / 'Mir200/!Setup.txt'
        before = path.read_bytes()
        child = SimpleNamespace(pid=4321, poll=lambda: None)
        def connect(*args):
            path.write_bytes(before.replace(b'GateAddr=127.0.0.1', b'GateAddr=0.0.0.0'))
            return SimpleNamespace(main=SimpleNamespace(window_text=lambda: str(self.root), is_enabled=lambda: True), dialogs=lambda: [])
        with patch.object(self.e, 'matching_processes', return_value=[]), patch.object(self.e.subprocess, 'Popen', return_value=child), patch.object(self.e, 'EngineUI', side_effect=connect):
            result = self.e.start_program(self.root, 'GameCenter.exe')
        self.assertEqual(path.read_bytes(), before)
        self.assertIn('Mir200/!Setup.txt', result['nativeRegeneratedConfigsRestored'])

    def test_controller_start_waits_for_observed_uninitialized_title(self):
        child = Mock(pid=4321)
        child.poll.return_value = None
        initial, initialized = Mock(), Mock()
        initial.main.window_text.return_value = '翎风引擎控制台'
        initialized.main.window_text.return_value = 'Native console [' + str(self.root) + '\\]'
        initialized.main.is_enabled.return_value = True
        initialized.dialogs.return_value = []
        with patch.object(self.e, 'matching_processes', return_value=[]), patch.object(self.e.subprocess, 'Popen', return_value=child), patch.object(self.e, 'EngineUI', side_effect=[initial, initialized]), patch.object(self.e.time, 'sleep'):
            self.assertEqual(self.e.start_program(self.root, 'GameCenter.exe')['pid'], child.pid)
        child.terminate.assert_not_called()

    def test_equal_value_save_cannot_hide_other_key_changes(self):
        before = b'[Setup]\r\nConsoleShowUserCountTime=600000\r\nOther=2\r\n'
        with self.assertRaises(ValueError):
            self.e.verify_saved_parameter(before, before.replace(b'Other=2', b'Other=3'), 600, 600)

    def test_truncated_log_cannot_reuse_historical_completion(self):
        before = 'old prefix\n2026-10-15 QFunction 脚本加载完成...'
        with self.assertRaises(ValueError): self.e.new_log_text(before, before.removeprefix('old prefix\n'))
        self.assertEqual(self.e.new_log_text(before, before + '\nnew line'), '\nnew line')

    def test_yes_confirmation_rejects_an_unrelated_native_question(self):
        from types import SimpleNamespace
        clicked = []
        yes = SimpleNamespace(is_visible=lambda: True, is_enabled=lambda: True, control_id=lambda: 6, window_text=lambda: '是(&Y)', click_input=lambda: clicked.append(6))
        no = SimpleNamespace(is_visible=lambda: True, is_enabled=lambda: True, control_id=lambda: 7, window_text=lambda: '否(&N)')
        dialog = SimpleNamespace(class_name=lambda: '#32770', window_text=lambda: '确认信息', descendants=lambda class_name: [yes, no] if class_name == 'Button' else [SimpleNamespace(window_text=lambda: '是否删除所有角色？')])
        with self.assertRaises(RuntimeError): self.e.confirm_native_yes(dialog, '是否确认关闭控制台 ?')
        self.assertEqual(clicked, [])

    def test_controller_cannot_regenerate_configs_while_lab_components_run(self):
        def processes(path):
            return [4321] if path.name == 'M2Server.exe' else []
        with patch.object(self.e, 'matching_processes', side_effect=processes):
            with self.assertRaisesRegex(ValueError, 'components'):
                self.e.start_program(self.root, 'GameCenter.exe')

    def test_not_yet_created_main_form_is_waitable_not_a_validation_failure(self):
        with self.assertRaises(LookupError): self.e.unique_main_form([])
        with self.assertRaises(ValueError): self.e.unique_main_form([1, 2])
        self.assertEqual(self.e.unique_main_form([123]), 123)

    def test_database_relative_paths_are_denied_even_when_cwd_is_lab(self):
        import os
        old = Path.cwd()
        try:
            os.chdir(self.root)
            for filename, section in [('Config.ini', 'GameConf'), ('Mir200/!Setup.txt', 'Server'), ('DBServer/dbsrc.ini', 'Setup')]:
                self.mutate(filename, str(self.root) + '\\Mud2\\DB\\ApexM2.DB', 'Mud2\\DB\\ApexM2.DB')
            with self.assertRaisesRegex(ValueError, 'database'): self.e.preflight(self.root)
        finally:
            os.chdir(old)

    def test_access_denied_is_not_exit_evidence(self):
        with self.assertRaises(PermissionError): self.e.raise_process_error(5)
        with self.assertRaises(ProcessLookupError): self.e.raise_process_error(87)
        with patch.object(self.e, 'process_image', side_effect=PermissionError('query denied')):
            with self.assertRaises(PermissionError): self.e.wait_stopped(123, self.root / 'Mir200/M2Server.exe', timeout=1)

    def test_query_image_failure_with_active_or_unknown_exit_status_is_not_stopped(self):
        for exit_status in (259, None):
            with self.assertRaises(OSError) as observed:
                self.e.query_image_failed(87, exit_status)
            self.assertNotIsInstance(observed.exception, ProcessLookupError)
        with self.assertRaises(ProcessLookupError): self.e.query_image_failed(87, 0)

    def test_failed_child_cleanup_cannot_skip_configuration_restore(self):
        from types import SimpleNamespace
        path = self.root / 'Mir200/!Setup.txt'
        before = path.read_bytes()
        def connect(*args):
            path.write_bytes(before.replace(b'GateAddr=127.0.0.1', b'GateAddr=0.0.0.0'))
            raise ValueError('initial failure')
        def wait(**kwargs):
            raise TimeoutError('cleanup timed out')
        child = SimpleNamespace(pid=4321, poll=lambda: None, terminate=lambda: None, wait=wait)
        with patch.object(self.e, 'matching_processes', return_value=[]), patch.object(self.e.subprocess, 'Popen', return_value=child), patch.object(self.e, 'EngineUI', side_effect=connect):
            with self.assertRaises(Exception): self.e.start_program(self.root, 'GameCenter.exe')
        self.assertEqual(path.read_bytes(), before)

    def test_synchronous_menu_dispatch_rejects_invalid_window(self):
        with self.assertRaises(OSError): self.e.synchronous_menu_command(0, 12)

    def test_synchronous_parameter_dispatch_is_single_bounded_and_clears_stale_error(self):
        import ctypes
        user = Mock()
        user.SendMessageTimeoutW.return_value = 1
        with patch.object(ctypes, 'WinDLL', return_value=user):
            ctypes.set_last_error(1460)
            self.e.synchronous_menu_command(123, 12)
        args = user.SendMessageTimeoutW.call_args.args
        self.assertEqual(args[:6], (123, 0x111, 12, 0, 2, 60000))
        user.SendMessageTimeoutW.assert_called_once()
        self.assertEqual(ctypes.get_last_error(), 0)

    def test_parameter_change_must_be_single_expected_key(self):
        before = b'[Setup]\r\nMaxUser=100\r\nOther=2\r\n'
        self.assertEqual(self.e.single_ini_change(before, before.replace(b'100', b'101'), ('Setup', 'MaxUser')), ('100', '101'))
        with self.assertRaises(ValueError):
            self.e.single_ini_change(before, before.replace(b'Other=2', b'Other=3'), ('Setup', 'MaxUser'))


if __name__ == '__main__':
    unittest.main()
