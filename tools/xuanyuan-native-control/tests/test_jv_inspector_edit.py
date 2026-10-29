"""TJvInspectorEdit text-only contracts, reusing the existing native message fixture."""
import json
from ctypes import wintypes

import pytest

from test_native_window import module
from test_rz_button_edit import MessageDesktop, path_action_request, writes


def inspector_desktop(**options):
    desktop = MessageDesktop(**options)
    desktop.target['controls'][0].update({'class': 'TJvInspectorEdit', 'text': '503'})
    desktop.os_text = '503'
    return desktop


def inspector_action_request(tmp_path, desktop):
    request = path_action_request(tmp_path, desktop)
    request['arguments']['action'].update(expectedClass='TJvInspectorEdit', expectedText='503', value='504')
    return request


def test_inspector_set_text_uses_one_sync_message_and_native_text_readback(tmp_path):
    desktop = inspector_desktop()
    request = inspector_action_request(tmp_path, desktop)
    result = module().run_window(request, backend=desktop)
    assert writes(desktop) == [(10, 0xC, 0, 2, 60000)]
    assert len(desktop.events) == 1
    assert result['dispatch']['mode'] == 'synchronous'
    assert result['dispatch']['handlerAcknowledged'] and result['readbackVerified']
    assert result['target']['controls'][0]['text'] == '504'
    assert desktop.os_text == '504' and desktop.target['controls'][0]['text'] == '503'
    write_index = next(i for i, message in enumerate(desktop.messages) if message[1] == 0xC)
    assert [message[1] for message in desktop.messages[write_index + 1:write_index + 3]] == [0xE, 0xD]
    assert not result['businessSaveVerified']


@pytest.mark.parametrize('behavior,error', [('reject_write', 'WM_SETTEXT'), ('ignore_write', 'readback')])
def test_inspector_rejected_set_or_ack_without_text_change_cannot_succeed(tmp_path, behavior, error):
    desktop = inspector_desktop(**{behavior: True})
    request = inspector_action_request(tmp_path, desktop)
    with pytest.raises(ValueError, match=error):
        module().run_window(request, backend=desktop)
    assert len(writes(desktop)) == 1 and len(desktop.events) == 1
    assert desktop.os_text == '503'
    failure = json.loads((tmp_path / 'action' / 'failure.json').read_text('utf-8'))
    assert failure['actionAttempted'] and not failure.get('readbackVerified', False)


def test_inspector_set_timeout_is_not_retried_or_claimed_as_readback(tmp_path):
    desktop = inspector_desktop()
    request = inspector_action_request(tmp_path, desktop)
    original = desktop.send_message_timeout

    def timeout(hwnd, message, wparam, lparam, flags, budget, result):
        if message == 0xC:
            desktop.messages.append((hwnd, message, wparam, flags, budget))
            return 0
        return original(hwnd, message, wparam, lparam, flags, budget, result)

    desktop.native.user.SendMessageTimeoutW = timeout
    with pytest.raises(OSError):
        module().run_window(request, backend=desktop)
    assert writes(desktop) == [(10, 0xC, 0, 2, 60000)] and desktop.os_text == '503'
    failure = json.loads((tmp_path / 'action' / 'failure.json').read_text('utf-8'))
    assert failure['actionAttempted'] and not failure.get('readbackVerified', False)


@pytest.mark.parametrize('change', ['text', 'class', 'parent', 'owner', 'style', 'rect', 'hidden',
                                   'disabled', 'process-created', 'missing', 'expired'])
def test_inspector_stale_value_or_control_identity_rejects_before_write(tmp_path, change):
    desktop = inspector_desktop()
    request = inspector_action_request(tmp_path, desktop)
    field = desktop.target['controls'][0]
    if change == 'text':
        desktop.os_text = '505'
    elif change == 'hidden':
        field['visible'] = False
    elif change == 'disabled':
        field['enabled'] = False
    elif change == 'process-created':
        desktop.target['processCreated'] = '13370002'
    elif change == 'missing':
        desktop.target['controls'] = []
    elif change == 'expired':
        desktop.clock += 121
    else:
        field[change] = {'class': 'TEdit', 'parent': 777, 'owner': 888, 'style': 0x800,
                         'rect': [31, 60, 101, 85]}[change]
    with pytest.raises(ValueError):
        module().run_window(request, backend=desktop)
    assert not writes(desktop) and not desktop.events and desktop.os_text != '504'


def test_inspector_truncated_native_text_cannot_be_overwritten(tmp_path):
    desktop = inspector_desktop()
    desktop.os_text = '5' * 65536
    request = inspector_action_request(tmp_path, desktop)
    request['arguments']['action']['expectedText'] = '5' * 65535
    with pytest.raises(ValueError, match='truncated'):
        module().run_window(request, backend=desktop)
    assert not writes(desktop) and not desktop.events


def test_inspector_control_in_foreign_process_is_rejected_by_real_ancestry_check(tmp_path):
    desktop = inspector_desktop()
    request = inspector_action_request(tmp_path, desktop)
    desktop.native.w = wintypes

    def window_process(hwnd, result):
        result._obj.value = 88 if hwnd == 10 else 12
        return 1

    desktop.native.user.GetWindowThreadProcessId = window_process
    desktop.native.user.GetAncestor = lambda hwnd, flag: 345 if hwnd == 10 else 0
    desktop.control_in_form = desktop.native.control_in_form
    with pytest.raises(ValueError, match='Control process/ancestor'):
        module().run_window(request, backend=desktop)
    assert not writes(desktop) and not desktop.events


def test_inspector_lost_foreground_or_point_ownership_rejects_before_write(tmp_path):
    desktop = inspector_desktop()
    request = inspector_action_request(tmp_path, desktop)
    desktop.covered = True
    with pytest.raises(ValueError, match='ownership'):
        module().run_window(request, backend=desktop)
    assert not writes(desktop) and not desktop.events


@pytest.mark.parametrize('cls', ['tjvinspectoredit', 'TJvInspectorEditEx', 'TJvInspector', 'TRzUnknownEdit'])
def test_inspector_support_does_not_enable_similar_or_case_changed_classes(tmp_path, cls):
    desktop = inspector_desktop()
    request = inspector_action_request(tmp_path, desktop)
    request['arguments']['action']['expectedClass'] = cls
    with pytest.raises(ValueError, match='Control class'):
        module().run_window(request, backend=desktop)
    assert not writes(desktop) and not desktop.events
