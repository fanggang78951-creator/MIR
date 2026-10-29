"""Pinned LoginSrv window contracts at fake OS boundaries; no live UI or IDDB."""
import copy
import ctypes
import json
from ctypes import wintypes
from types import SimpleNamespace

import pytest

from test_native_window import Desktop, module


EXE = r'D:\MirServer\LoginSrv\LoginSrv.exe'
HASH = '1CC15D5A3848E2EB3DD2FB52947331527D8708C165F3266D5AC7DA80C8D9BC57'
HOST_EXE = r'D:\MirServer\GameCenter.exe'
HOST_HASH = '497C03D8C323258069EB4582F1C291BA5C67E190D8C31DDC5FAD5A79C2D72857'


class LoginDesktop(Desktop):
    """Keep snapshot, hosting, ancestry, dispatch and text readback real."""

    def __init__(self, *, hosted=False):
        super().__init__()
        self.root_hwnd = 700 if hosted else 345
        self.parents = {10: 345, 14: 345, 345: 600 if hosted else 0, 600: 700, 700: 0, 800: 700}
        self.pids = {10: 12, 14: 12, 345: 12, 600: 77, 700: 77, 800: 77}
        self.hit, self.focus = 10, 10
        self.minimized = set()
        self.identities = {12: {'executable': EXE, 'sha256': HASH, 'processCreated': '13370001'},
                           77: {'executable': HOST_EXE, 'sha256': HOST_HASH, 'processCreated': '1337999'}}
        self.nodes = {
            345: self.node(345, 'TFrmLoginSrv', '游戏登陆服务器', style=0x36CF0000),
            600: self.node(600, 'TPanel', '', style=0x50000000),
            700: self.node(700, 'TfrmMain', '翎风引擎控制台', style=0x16CB0000),
            800: self.node(800, 'TPanel', 'other page', style=0x50000000),
            10: self.node(10, 'TEdit', '12', style=0x50010080),
            14: self.node(14, 'TButton', '保存', style=0x50010000),
        }
        self.messages, self.button_count = [], 0
        self.native = object.__new__(module().Win32WindowBackend)
        self.native.w = wintypes
        self.native.enum_callback = lambda callback: callback
        self.native.user = SimpleNamespace(
            GetWindowThreadProcessId=self.window_process, GetAncestor=self.ancestor,
            GetParent=lambda hwnd: self.parents.get(hwnd, 0),
            GetClientRect=self.client_rect, IsIconic=lambda hwnd: hwnd in self.minimized,
            GetMenu=lambda hwnd: 0, EnumChildWindows=self.enum_children,
            SendMessageTimeoutW=self.send_message_timeout,
        )
        self.native.exists = self.exists
        self.native._basic = self.basic
        self.native._process = lambda pid: copy.deepcopy(self.identities[pid])
        self.native.native_forms = self.native_forms
        self.native.client_to_screen = self.client_to_screen

    @staticmethod
    def node(hwnd, cls, text, *, style):
        return {'hwnd': hwnd, 'class': cls, 'text': text, 'owner': 0, 'style': style,
                'rect': [10, 20, 810, 620], 'visible': True, 'enabled': True}

    def exists(self, hwnd):
        return hwnd == 999 or hwnd in self.nodes

    def window_process(self, hwnd, result):
        result._obj.value = self.pids.get(hwnd, 0)
        return 1

    def ancestor(self, hwnd, flag):
        if flag == 1:
            return self.parents.get(hwnd, 0)
        assert flag == 2
        return self.root_hwnd if hwnd in self.nodes else hwnd

    @staticmethod
    def client_rect(hwnd, result):
        result._obj.right, result._obj.bottom = 780, 560
        return True

    def basic(self, hwnd):
        item = copy.deepcopy(self.nodes[hwnd])
        item['parent'] = self.parents.get(hwnd, 0)
        item['text'], item['textTruncated'] = self.native._title(hwnd)
        return item

    def native_forms(self, pid):
        item = self.basic(345)
        item['title'] = item.pop('text')
        return [item]

    def enum_children(self, hwnd, callback, unused):
        for child in (10, 14):
            if not callback(child, 0):
                return False
        return True

    def send_message_timeout(self, hwnd, message, wparam, lparam, flags, timeout, result):
        if message == 0xE:
            result._obj.value = len(self.nodes[hwnd]['text'])
        elif message == 0xD:
            text = ctypes.create_unicode_buffer(self.nodes[hwnd]['text'][:wparam - 1])
            ctypes.memmove(lparam, text, ctypes.sizeof(text))
            result._obj.value = len(text.value)
        elif message == 0xC:
            self.messages.append((hwnd, message, flags, timeout))
            self.nodes[hwnd]['text'] = ctypes.wstring_at(lparam)
            result._obj.value = 1
        elif message == 0xF5:
            self.messages.append((hwnd, message, flags, timeout))
            self.button_count += 1
            result._obj.value = 1
        else:
            raise AssertionError(f'Unexpected native message {message:#x}')
        return 1

    def snapshot(self, pid, hwnd):
        return self.native.snapshot(pid, hwnd)

    def root(self, hwnd):
        return self.native.root(hwnd)

    def root_at(self, point):
        return self.root(self.hit)

    def observation_point_in_form(self, hwnd, point):
        return self.native._inside(self.hit, hwnd, same_process=False)

    def point_in_form(self, hwnd, point):
        return self.native._inside(self.hit, hwnd)

    def control_in_form(self, control, hwnd):
        return self.native.control_in_form(control, hwnd)

    def focus_in_form(self, hwnd):
        return self.native._inside(self.focus, hwnd)

    def dispatch(self, target, action):
        return self.native.dispatch(target, action)


def request(tmp_path, *, command='window-observe', name='observe'):
    return {'schemaVersion': 1, 'command': command,
            'arguments': {'pid': 12, 'hwnd': 345, 'expectedExecutable': EXE, 'expectedSha256': HASH,
                          'expectedClass': 'TFrmLoginSrv', 'expectedTitle': '游戏登陆服务器',
                          'outputRoot': str(tmp_path / name)},
            'policy': {'allowedWriteRoots': [str(tmp_path)]}}


def action_request(tmp_path, desktop, action):
    observed = module().run_window(request(tmp_path), backend=desktop)
    result = request(tmp_path, command='window-action', name='action')
    result['arguments'].update(observationReceipt=observed['observationReceipt'],
                               observationSha256=observed['observationSha256'], action=action)
    return result


@pytest.mark.parametrize('hosted', [False, True])
def test_pinned_loginsrv_observation_uses_real_snapshot_hosting_and_ancestry(tmp_path, hosted):
    desktop = LoginDesktop(hosted=hosted)
    result = module().run_window(request(tmp_path), backend=desktop)
    host = result['target']['hosting']
    if hosted:
        assert host['kind'] == 'GameCenterHostedLoginSrv'
        assert [(item['hwnd'], item['pid'], item['parent']) for item in host['ancestorChain']] == [
            (345, 12, 600), (600, 77, 700), (700, 77, 0)]
        assert host['executable'] == HOST_EXE and host['sha256'] == HOST_HASH
    else:
        assert host is None
    assert result['screenshot'] and not desktop.messages
    assert result['recovery'] == {'foregroundRestored': True, 'cursorRestored': True}


@pytest.mark.parametrize('hosted', [False, True])
@pytest.mark.parametrize('kind', ['set-text', 'button'])
def test_loginsrv_actions_use_native_messages_and_readback_without_business_claim(tmp_path, hosted, kind):
    desktop = LoginDesktop(hosted=hosted)
    action = ({'kind': 'set-text', 'controlHwnd': 10, 'expectedClass': 'TEdit', 'expectedText': '12', 'value': '13'}
              if kind == 'set-text' else
              {'kind': 'button', 'controlHwnd': 14, 'expectedClass': 'TButton', 'expectedText': '保存'})
    result = module().run_window(action_request(tmp_path, desktop, action), backend=desktop)
    assert desktop.messages == [(10 if kind == 'set-text' else 14, 0xC if kind == 'set-text' else 0xF5, 2, 60000)]
    assert result['actionAttempted'] and result['dispatch']['handlerAcknowledged']
    assert result['readbackVerified'] is (kind == 'set-text')
    assert desktop.nodes[10]['text'] == ('13' if kind == 'set-text' else '12')
    assert desktop.button_count == (1 if kind == 'button' else 0)
    assert not result['businessSaveVerified']


@pytest.mark.parametrize('field,value', [('expectedSha256', '0' * 64),
                                        ('expectedExecutable', r'D:\MirServer\DBServer\DBServer.exe'),
                                        ('expectedExecutable', r'D:\MirServer\Other.exe')])
def test_loginsrv_request_does_not_admit_unpinned_or_other_components(tmp_path, field, value):
    desktop = LoginDesktop(hosted=True)
    req = request(tmp_path)
    req['arguments'][field] = value
    with pytest.raises(PermissionError):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and desktop.front == 999


@pytest.mark.parametrize('field,value', [('executable', r'E:\other\LoginSrv\LoginSrv.exe'),
                                        ('sha256', '0' * 64)])
def test_loginsrv_live_process_image_must_match_request(tmp_path, field, value):
    desktop = LoginDesktop(hosted=True)
    desktop.identities[12][field] = value
    with pytest.raises(PermissionError):
        module().run_window(request(tmp_path), backend=desktop)
    assert not desktop.messages


@pytest.mark.parametrize('change', ['hash', 'cross-root', 'class', 'third-pid', 'broken-parent', 'cycle', 'hidden', 'disabled', 'minimized'])
def test_invalid_loginsrv_host_or_parent_chain_rejects_before_input(tmp_path, change):
    desktop = LoginDesktop(hosted=True)
    if change == 'hash':
        desktop.identities[77]['sha256'] = '0' * 64
    elif change == 'cross-root':
        desktop.identities[77]['executable'] = r'E:\other\GameCenter.exe'
    elif change == 'class':
        desktop.nodes[700]['class'] = 'OtherHost'
    elif change == 'third-pid':
        desktop.pids[600] = 88
    elif change == 'broken-parent':
        desktop.parents[600] = 0
    elif change == 'cycle':
        desktop.parents[600] = 600
    elif change == 'minimized':
        desktop.minimized.add(700)
    else:
        desktop.nodes[700]['visible' if change == 'hidden' else 'enabled'] = False
    with pytest.raises((ValueError, PermissionError)):
        module().run_window(request(tmp_path), backend=desktop)
    assert not desktop.messages


def test_loginsrv_cannot_claim_the_existing_m2_host_adapter():
    desktop = LoginDesktop(hosted=True)
    target = desktop.snapshot(12, 345)
    target['hosting']['kind'] = 'GameCenterHostedM2'
    with pytest.raises(PermissionError):
        module()._check_hosting(target)


def test_other_whitelisted_process_child_does_not_inherit_gamecenter_host_adapter(tmp_path):
    desktop = LoginDesktop(hosted=True)
    desktop.identities[12].update(executable=HOST_EXE, sha256=HOST_HASH)
    observed_request = request(tmp_path)
    observed_request['arguments'].update(expectedExecutable=HOST_EXE, expectedSha256=HOST_HASH)
    observed = module().run_window(observed_request, backend=desktop)
    assert observed['target']['hosting'] is None
    action = copy.deepcopy(observed_request)
    action['command'] = 'window-action'
    action['arguments'].update(outputRoot=str(tmp_path / 'action'),
                               observationReceipt=observed['observationReceipt'],
                               observationSha256=observed['observationSha256'],
                               action={'kind': 'set-text', 'controlHwnd': 10,
                                       'expectedClass': 'TEdit', 'expectedText': '12', 'value': '13'})
    with pytest.raises(ValueError, match='Child native form'):
        module().run_window(action, backend=desktop)
    assert not desktop.messages


@pytest.mark.parametrize('change', ['host-created', 'parent-class', 'parent-style', 'parent', 'host-hidden', 'host-disabled'])
def test_loginsrv_receipt_binds_host_and_complete_parent_identity(tmp_path, change):
    desktop = LoginDesktop(hosted=True)
    req = action_request(tmp_path, desktop, {'kind': 'set-text', 'controlHwnd': 10,
                                           'expectedClass': 'TEdit', 'expectedText': '12', 'value': '13'})
    if change == 'host-created':
        desktop.identities[77]['processCreated'] = '1338000'
    elif change == 'parent-class':
        desktop.nodes[600]['class'] = 'ChangedPanel'
    elif change == 'parent-style':
        desktop.nodes[600]['style'] ^= 0x10000
    elif change == 'parent':
        desktop.parents[345] = 700
    else:
        desktop.nodes[700]['visible' if change == 'host-hidden' else 'enabled'] = False
    with pytest.raises((ValueError, PermissionError)):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and desktop.nodes[10]['text'] == '12'


def test_hidden_loginsrv_show_cannot_select_gamecenter_host_page(tmp_path):
    desktop = LoginDesktop(hosted=True)
    desktop.nodes[345]['visible'] = False
    req = action_request(tmp_path, desktop, {'kind': 'show'})
    with pytest.raises(ValueError, match='host page'):
        module().run_window(req, backend=desktop)
    assert not desktop.messages
    failure = json.loads((tmp_path / 'action' / 'failure.json').read_text('utf-8'))
    assert not failure['actionAttempted']


@pytest.mark.parametrize('kind', ['key', 'visual-click', 'set-text'])
def test_loginsrv_host_or_foreign_controls_never_receive_selected_form_input(tmp_path, kind):
    desktop = LoginDesktop(hosted=True)
    action = ({'kind': 'key', 'key': 'HOME'} if kind == 'key' else
              {'kind': 'visual-click', 'x': 50, 'y': 60} if kind == 'visual-click' else
              {'kind': 'set-text', 'controlHwnd': 10, 'expectedClass': 'TEdit', 'expectedText': '12', 'value': '13'})
    req = action_request(tmp_path, desktop, action)
    if kind == 'key':
        desktop.focus = 600
    elif kind == 'visual-click':
        desktop.hit = 800
    else:
        desktop.pids[10] = 77
    with pytest.raises(ValueError):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and not desktop.events
