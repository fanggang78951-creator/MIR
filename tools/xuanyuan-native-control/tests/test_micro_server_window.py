"""Pinned micro-server windows through existing OS boundaries, never live services."""
import copy
import json

import pytest

from test_native_window import module
from test_stack_component_window import ComponentDesktop, action_request, request


COMPONENTS = [
    (r'E:\客户端\热血传奇16周年客户端\UpdateServer_x64.exe',
     '2FE71E3C8ED9FD113A392EBC50D603396412DEBD6DEC6CBCEEFC785646055DE2', None),
    (r'D:\Mirserver\微端服务器\微端网关\MirUpdateGate.exe',
     '2F12AB71F0D35D4259F96C2CCBA77F5DC8239BF0B3705654457F59D27CFB26B5', None),
]


@pytest.fixture(params=COMPONENTS, ids=['UpdateServer', 'MirUpdateGate'])
def component(request):
    return request.param


class MicroDesktop(ComponentDesktop):
    """Real snapshot/edit/check paths; no fabricated Rz common-control behavior."""

    def __init__(self, component, monkeypatch, *, hosted=False):
        super().__init__(component, hosted=hosted)
        self.extra_forms, self.checks = [], {13: 0}
        self.check_reads = []
        self.native._pointer_bits = lambda pid: 64
        self.native.user.IsWindowUnicode = lambda hwnd: True

    def enum_children(self, hwnd, callback, unused):
        for child in (10, 12, 13, 14):
            if child in self.nodes and not callback(child, 0):
                return False
        return True

    def native_forms(self, pid):
        return [*super().native_forms(pid), *copy.deepcopy(self.extra_forms)]

    def send_message_timeout(self, hwnd, message, wparam, lparam, flags, timeout, result):
        if message == 0xF0:
            self.check_reads.append(hwnd)
            result._obj.value = self.checks[hwnd]
        elif message == 0xF5 and hwnd == 13:
            self.messages.append((hwnd, message, flags, timeout))
            self.button_count += 1
            # The native probe acknowledged BM_CLICK without changing this state.
            result._obj.value = 1
        else:
            return super().send_message_timeout(hwnd, message, wparam, lparam, flags, timeout, result)
        return 1

    def raize_action(self, cls):
        if cls in ('TRzEdit', 'TRzMaskEdit'):
            self.nodes[10]['class'] = cls
            return {'kind': 'set-text', 'controlHwnd': 10, 'expectedClass': cls,
                    'expectedText': '12', 'value': '13'}
        if cls == 'TRzBitBtn':
            self.nodes[14]['class'] = cls
            return {'kind': 'button', 'controlHwnd': 14, 'expectedClass': cls, 'expectedText': '保存'}
        control = 13 if cls == 'TRzCheckBox' else 12
        self.nodes[control] = self.node(control, cls, '启用' if control == 13 else '', style=0x50010003)
        self.parents[control], self.pids[control] = 345, 12
        if control == 13:
            return {'kind': 'button', 'controlHwnd': 13, 'expectedClass': cls,
                    'expectedText': '启用', 'expectedCheck': 0}
        return {'kind': 'select-tab', 'controlHwnd': 12, 'expectedClass': cls,
                'expectedSelection': '', 'text': '配置'}


@pytest.fixture
def desktop(component, monkeypatch):
    return MicroDesktop(component, monkeypatch)


def test_pinned_micro_binary_observes_without_inheriting_gamecenter_host(tmp_path, component, desktop):
    result = module().run_window(request(tmp_path, component), backend=desktop)
    assert result['target']['executable'] == component[0]
    assert result['target']['sha256'] == component[1] and result['target']['hosting'] is None
    assert result['screenshot'] and result['target']['controls']
    assert not result['actionAttempted'] and not desktop.messages


def test_pinned_micro_binary_reuses_exact_native_text_dispatch(tmp_path, component, desktop):
    action = {'kind': 'set-text', 'controlHwnd': 10, 'expectedClass': 'TEdit',
              'expectedText': '12', 'value': '13'}
    result = module().run_window(action_request(tmp_path, desktop, component, action), backend=desktop)
    assert desktop.messages == [(10, 0xC, 2, 60000)] and desktop.nodes[10]['text'] == '13'
    assert result['readbackVerified'] and not result['businessSaveVerified']


@pytest.mark.parametrize('change', ['wrong-hash', 'renamed', 'unknown-binary'])
def test_micro_binary_request_still_requires_exact_pinned_name_and_hash(tmp_path, component, desktop, change):
    req = request(tmp_path, component)
    if change == 'wrong-hash':
        req['arguments']['expectedSha256'] = '0' * 64
    else:
        req['arguments']['expectedExecutable'] = r'D:\copy\UpdateServer_copy.exe' if change == 'renamed' else r'D:\copy\UnknownService.exe'
    with pytest.raises(PermissionError):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and not desktop.events and desktop.front == 999


def test_micro_binary_live_fingerprint_cannot_change_after_request(tmp_path, component, desktop):
    desktop.identities[12]['sha256'] = '0' * 64
    with pytest.raises(PermissionError, match='fingerprint'):
        module().run_window(request(tmp_path, component), backend=desktop)
    assert not desktop.messages and not desktop.events


def test_micro_binary_does_not_gain_unknown_cross_process_host_input(tmp_path, component, monkeypatch):
    desktop = MicroDesktop(component, monkeypatch, hosted=True)
    action = {'kind': 'set-text', 'controlHwnd': 10, 'expectedClass': 'TEdit', 'expectedText': '12', 'value': '13'}
    req = action_request(tmp_path, desktop, component, action)
    with pytest.raises(ValueError, match='Child native form'):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and not desktop.events


@pytest.mark.parametrize('guard', ['stale', 'modal', 'foreign-control', 'point', 'focus'])
def test_micro_binary_admission_does_not_relax_existing_input_guards(tmp_path, monkeypatch, guard):
    component = COMPONENTS[0]
    desktop = MicroDesktop(component, monkeypatch)
    action = ({'kind': 'key', 'key': 'HOME'} if guard == 'focus' else
              {'kind': 'visual-click', 'x': 50, 'y': 60} if guard == 'point' else
              {'kind': 'set-text', 'controlHwnd': 10, 'expectedClass': 'TEdit', 'expectedText': '12', 'value': '13'})
    req = action_request(tmp_path, desktop, component, action)
    if guard == 'stale':
        desktop.clock += 121
    elif guard == 'modal':
        desktop.extra_forms.append({'hwnd': 401, 'parent': 345, 'owner': 345, 'class': '#32770',
                                    'style': 0x90C800C4, 'title': '确认', 'visible': True, 'enabled': True})
    elif guard == 'foreign-control':
        desktop.pids[10] = 77
    elif guard == 'point':
        desktop.hit = 800
    else:
        desktop.focus = 800
    with pytest.raises(ValueError):
        module().run_window(req, backend=desktop)
    failure = json.loads((tmp_path / 'action' / 'failure.json').read_text('utf-8'))
    assert not failure['actionAttempted'] and not desktop.messages and not desktop.events


RAIZE_CLASSES = ['TRzEdit', 'TRzMaskEdit', 'TRzBitBtn', 'TRzCheckBox', 'TRzPageControl']


@pytest.mark.parametrize('cls', RAIZE_CLASSES)
def test_raize_message_admission_is_limited_to_verified_edit_classes(monkeypatch, cls):
    desktop = MicroDesktop(COMPONENTS[1], monkeypatch)
    action = desktop.raize_action(cls)
    if cls in ('TRzEdit', 'TRzMaskEdit'):
        assert module()._action(action)['kind'] == 'set-text'
    else:
        with pytest.raises(ValueError, match='Control class'):
            module()._action(action)
    assert not desktop.messages and not desktop.events


@pytest.mark.parametrize('cls', RAIZE_CLASSES)
def test_raize_edits_dispatch_but_self_drawn_message_actions_remain_rejected(tmp_path, monkeypatch, cls):
    component = COMPONENTS[1]
    desktop = MicroDesktop(component, monkeypatch)
    action = desktop.raize_action(cls)
    req = action_request(tmp_path, desktop, component, action)
    if cls not in ('TRzEdit', 'TRzMaskEdit'):
        with pytest.raises(ValueError, match='Control class'):
            module().run_window(req, backend=desktop)
        assert not desktop.messages and not desktop.events
        return
    result = module().run_window(req, backend=desktop)
    control = next(item for item in result['target']['controls'] if item['hwnd'] == action['controlHwnd'])
    assert desktop.messages == [(10, 0xC, 2, 60000)] and control['text'] == '13'
    assert result['dispatch']['handlerAcknowledged'] and result['readbackVerified']
    assert not result['businessSaveVerified']


@pytest.mark.parametrize('state', [0, 1, 2])
def test_raize_checkbox_observes_native_state_without_message_write_access(tmp_path, monkeypatch, state):
    component = COMPONENTS[1]
    desktop = MicroDesktop(component, monkeypatch)
    action = desktop.raize_action('TRzCheckBox')
    desktop.checks[13] = state
    observed = module().run_window(request(tmp_path, component), backend=desktop)
    control = next(item for item in observed['target']['controls'] if item['hwnd'] == 13)
    assert control['check'] == state
    req = request(tmp_path, component, command='window-action', name='action')
    action['expectedCheck'] = state
    req['arguments'].update(observationReceipt=observed['observationReceipt'], observationSha256=observed['observationSha256'], action=action)
    with pytest.raises(ValueError, match='Control class'):
        module().run_window(req, backend=desktop)
    assert desktop.check_reads and not desktop.messages and not desktop.events


@pytest.mark.parametrize('cls', ['TRzEditExtra', 'TRzMaskEditExtra', 'TRzBitBtnExtra', 'TRzCheckbox', 'TRzPageControlExtra', 'TRzMemo'])
def test_similar_raize_classes_and_readonly_memo_do_not_gain_write_access(monkeypatch, cls):
    desktop = MicroDesktop(COMPONENTS[1], monkeypatch)
    original = 'TRzPageControl' if 'PageControl' in cls else 'TRzCheckBox' if 'Checkbox' in cls else 'TRzBitBtn' if 'BitBtn' in cls else 'TRzEdit'
    action = desktop.raize_action(original)
    action['expectedClass'] = cls
    with pytest.raises(ValueError, match='Control class'):
        module()._action(action)


def test_capabilities_include_micro_programs_without_adding_commands(capsys):
    from wzl_blackbox import native_control
    assert native_control.main(['capabilities']) == 0
    result = json.loads(capsys.readouterr().out)
    assert 'UpdateServer_x64' in result['nativeWindowScope'] and 'MirUpdateGate' in result['nativeWindowScope']
    assert result['nativeWindowCommands'] == ['window-observe', 'window-action']
    assert not result['wholeEngineStartStop'] and not result['gameAcceptancePerformed']
