"""TRzButtonEdit contract checks with fake Win32 messages, never a live GUI."""
import copy
import ctypes
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_native_window import Desktop, module, request


BEFORE = r'D:\candidate\old\Resources'
AFTER = r'D:\candidate\新素材\Resources'


class MessageDesktop(Desktop):
    """Keep dispatch, SendMessageTimeout handling and WM_GETTEXT readback real."""

    def __init__(self, *, reject_write=False, ignore_write=False):
        super().__init__()
        from wzl_blackbox.native_control import LAUNCHER_SHA256

        self.target.update(executable=r'D:\candidate\MakeGameLogin.exe',
                           sha256=LAUNCHER_SHA256, **{'class': 'TfrmGUI', 'title': '界面设置'})
        self.target['controls'][0].update({'class': 'TRzButtonEdit', 'text': BEFORE})
        self.forms[0].update({'class': 'TfrmGUI', 'title': '界面设置'})
        self.os_text = BEFORE
        self.messages = []
        self.reject_write, self.ignore_write = reject_write, ignore_write
        self.native = object.__new__(module().Win32WindowBackend)
        self.native.user = SimpleNamespace(SendMessageTimeoutW=self.send_message_timeout)

    def send_message_timeout(self, hwnd, message, wparam, lparam, flags, timeout, result):
        self.messages.append((hwnd, message, wparam, flags, timeout))
        assert hwnd == 10
        if message == 0xC:  # WM_SETTEXT: the only state-changing OS boundary.
            if not self.reject_write and not self.ignore_write:
                self.os_text = ctypes.wstring_at(lparam)
            result._obj.value = 0 if self.reject_write else 1
        elif message == 0xE:  # WM_GETTEXTLENGTH
            result._obj.value = len(self.os_text)
        elif message == 0xD:  # WM_GETTEXT
            text = self.os_text[:wparam - 1]
            buffer = ctypes.create_unicode_buffer(text)
            ctypes.memmove(lparam, buffer, ctypes.sizeof(buffer))
            result._obj.value = len(text)
        else:
            raise AssertionError(f'Unexpected native message {message:#x}')
        return 1

    def snapshot(self, pid, hwnd):
        target = super().snapshot(pid, hwnd)
        field = next((item for item in target['controls'] if item['hwnd'] == 10), None)
        if field is not None:
            field['text'], field['textTruncated'] = self.native._title(10)
        return target

    def dispatch(self, target, action):
        self.events.append(('dispatch', copy.deepcopy(action)))
        return self.native.dispatch(target, action)


def path_action_request(tmp_path, desktop):
    observe = request(tmp_path)
    for field, source in (('expectedExecutable', 'executable'), ('expectedSha256', 'sha256'),
                          ('expectedClass', 'class'), ('expectedTitle', 'title')):
        observe['arguments'][field] = desktop.target[source]
    data = module().run_window(observe, backend=desktop)
    receipt = Path(data['observationReceipt'])
    action = copy.deepcopy(observe)
    action['command'] = 'window-action'
    action['arguments'].update(outputRoot=str(tmp_path / 'action'),
                               observationReceipt=str(receipt),
                               observationSha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
                               action={'kind': 'set-text', 'controlHwnd': 10,
                                       'expectedClass': 'TRzButtonEdit',
                                       'expectedText': BEFORE, 'value': AFTER})
    return action


def writes(desktop):
    return [item for item in desktop.messages if item[1] == 0xC]


def test_rz_path_validation_and_single_sync_message_use_native_text_readback(tmp_path):
    desktop = MessageDesktop()
    req = path_action_request(tmp_path, desktop)
    plan = module().validate_request(req)
    assert plan['action']['expectedClass'] == 'TRzButtonEdit'

    data = module().run_window(req, backend=desktop)

    assert len(desktop.events) == 1
    assert writes(desktop) == [(10, 0xC, 0, 2, 60000)]
    assert data['dispatch']['mode'] == 'synchronous'
    assert data['dispatch']['handlerAcknowledged'] and data['readbackVerified']
    assert data['target']['controls'][0]['text'] == AFTER
    assert desktop.target['controls'][0]['text'] == BEFORE  # Not fixture-set readback.
    assert desktop.os_text == AFTER
    last_write = next(i for i, item in enumerate(desktop.messages) if item[1] == 0xC)
    assert [item[1] for item in desktop.messages[last_write + 1:last_write + 3]] == [0xE, 0xD]
    assert not data['businessSaveVerified']


@pytest.mark.parametrize('change', ['text', 'class', 'parent', 'owner', 'rect', 'style',
                                   'disabled', 'hidden', 'process-identity', 'missing'])
def test_rz_stale_value_identity_or_availability_rejects_before_write(tmp_path, change):
    desktop = MessageDesktop()
    req = path_action_request(tmp_path, desktop)
    field = desktop.target['controls'][0]
    if change == 'text':
        desktop.os_text = r'D:\changed\Resources'
    elif change == 'disabled':
        field['enabled'] = False
    elif change == 'hidden':
        field['visible'] = False
    elif change == 'process-identity':
        desktop.target['processCreated'] = '13370002'
    elif change == 'missing':
        desktop.target['controls'] = []
    else:
        field[change] = {'class': 'TButton', 'parent': 777, 'owner': 888,
                         'rect': [31, 60, 101, 85], 'style': 0x800}[change]
    with pytest.raises(ValueError):
        module().run_window(req, backend=desktop)
    assert not desktop.events and not writes(desktop)
    assert desktop.os_text != AFTER


@pytest.mark.parametrize('behavior,error', [('reject_write', 'WM_SETTEXT'),
                                           ('ignore_write', 'readback')])
def test_rz_rejected_write_or_ack_without_text_change_cannot_claim_success(tmp_path, behavior, error):
    desktop = MessageDesktop(**{behavior: True})
    req = path_action_request(tmp_path, desktop)
    with pytest.raises(ValueError, match=error):
        module().run_window(req, backend=desktop)
    assert len(desktop.events) == 1 and len(writes(desktop)) == 1
    assert desktop.os_text == BEFORE
    failure = json.loads((tmp_path / 'action' / 'failure.json').read_text('utf-8'))
    assert failure['actionAttempted'] and not failure.get('readbackVerified', False)


@pytest.mark.parametrize('cls', ['TButton', 'TRzUnknownEdit', 'trzbuttonedit'])
def test_rz_support_does_not_allow_other_control_classes(tmp_path, cls):
    desktop = MessageDesktop()
    req = path_action_request(tmp_path, desktop)
    req['arguments']['action']['expectedClass'] = cls
    with pytest.raises(ValueError, match='Control class'):
        module().run_window(req, backend=desktop)
    assert not desktop.events and not writes(desktop)
