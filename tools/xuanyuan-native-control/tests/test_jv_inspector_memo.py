"""TJvInspectorMemo text-only support through the existing native edit dispatch."""
import ctypes
import json
from ctypes import wintypes

import pytest

from test_native_window import module
from test_rz_button_edit import MessageDesktop, path_action_request


MULTILINE_STYLE = 1411448900


class MemoDesktop(MessageDesktop):
    """Extend only the fake OS edit messages; controller and readback stay real."""

    def __init__(self, *, before='旧标题', multiline=True, replace_mode='apply', timeout_message=None, **options):
        super().__init__(**options)
        self.target['controls'][0].update({'class': 'TJvInspectorMemo', 'text': before,
                                          'style': MULTILINE_STYLE if multiline else MULTILINE_STYLE & ~4})
        self.os_text = before
        self.selection, self.payloads = None, []
        self.replace_mode, self.timeout_message = replace_mode, timeout_message

    def send_message_timeout(self, hwnd, message, wparam, lparam, flags, timeout, result):
        if message == self.timeout_message:
            self.messages.append((hwnd, message, wparam, flags, timeout))
            if message in (0xC, 0xC2):
                self.payloads.append(ctypes.wstring_at(lparam))
            return 0
        if message not in (0xB1, 0xC2):
            if message == 0xC:
                self.payloads.append(ctypes.wstring_at(lparam))
            return super().send_message_timeout(hwnd, message, wparam, lparam, flags, timeout, result)
        self.messages.append((hwnd, message, wparam, flags, timeout))
        assert hwnd == 10
        if message == 0xB1:
            self.selection = (wparam, lparam)
        else:
            payload = ctypes.wstring_at(lparam)
            self.payloads.append(payload)
            if self.replace_mode == 'apply':
                self.os_text = payload if self.selection == (0, -1) else self.os_text + payload
            elif self.replace_mode == 'different-newlines':
                self.os_text = '装\r\n备'  # Simulated OS mismatch must fail exact readback.
        result._obj.value = 0  # Existing EM dispatch relies on delivery ACK and final text, not this value.
        return 1


def memo_request(tmp_path, desktop, value):
    request = path_action_request(tmp_path, desktop)
    request['arguments']['action'].update(expectedClass='TJvInspectorMemo', expectedText=desktop.os_text, value=value)
    return request


def edit_messages(desktop):
    return [message for message in desktop.messages if message[1] in (0xC, 0xB1, 0xC2)]


def failure_data(tmp_path):
    return json.loads((tmp_path / 'action' / 'failure.json').read_text('utf-8'))


@pytest.mark.parametrize('multiline', [True, False], ids=['EM-replace', 'WM-set'])
@pytest.mark.parametrize('value', ['装\n备', '装\r\n备', '装备', ''], ids=['LF', 'CRLF', 'single-line', 'clear'])
def test_memo_exact_payload_uses_existing_style_branch_and_native_readback(tmp_path, multiline, value):
    desktop = MemoDesktop(multiline=multiline)
    result = module().run_window(memo_request(tmp_path, desktop, value), backend=desktop)
    expected = [(10, 0xB1, 0, 2, 60000), (10, 0xC2, 1, 2, 60000)] if multiline else [(10, 0xC, 0, 2, 60000)]
    assert edit_messages(desktop) == expected
    assert desktop.payloads == [value] and desktop.os_text == value
    if multiline:
        assert desktop.selection == (0, -1)
    assert len(desktop.events) == 1 and result['actionAttempted']
    assert result['dispatch']['handlerAcknowledged'] and result['readbackVerified']
    assert result['target']['controls'][0]['text'] == value
    last_write = max(index for index, message in enumerate(desktop.messages) if message[1] in (0xC, 0xC2))
    assert [message[1] for message in desktop.messages[last_write + 1:last_write + 3]] == [0xE, 0xD]
    assert not result['businessSaveVerified'] and 'guardEvidence' not in result


def test_memo_existing_length_limit_accepts_exactly_65535_characters(tmp_path):
    desktop = MemoDesktop()
    value = '装' * 65535
    result = module().run_window(memo_request(tmp_path, desktop, value), backend=desktop)
    assert desktop.payloads == [value] and result['target']['controls'][0]['text'] == value
    assert result['readbackVerified'] and len(desktop.events) == 1


@pytest.mark.parametrize('multiline,message,expected_count', [(True, 0xB1, 1), (True, 0xC2, 2), (False, 0xC, 1)])
def test_memo_timeout_at_each_original_message_is_not_retried(tmp_path, multiline, message, expected_count):
    desktop = MemoDesktop(multiline=multiline, timeout_message=message)
    with pytest.raises(OSError):
        module().run_window(memo_request(tmp_path, desktop, '装\n备'), backend=desktop)
    assert len(edit_messages(desktop)) == expected_count
    assert sum(item[1] == message for item in edit_messages(desktop)) == 1
    assert desktop.os_text == '旧标题' and len(desktop.events) == 1
    failure = failure_data(tmp_path)
    assert failure['actionAttempted'] and not failure.get('readbackVerified', False)


def test_memo_single_line_rejected_wm_settext_cannot_claim_success(tmp_path):
    desktop = MemoDesktop(multiline=False, reject_write=True)
    with pytest.raises(ValueError, match='WM_SETTEXT'):
        module().run_window(memo_request(tmp_path, desktop, '装备'), backend=desktop)
    assert edit_messages(desktop) == [(10, 0xC, 0, 2, 60000)]
    assert desktop.os_text == '旧标题' and failure_data(tmp_path)['actionAttempted']


@pytest.mark.parametrize('multiline,mode', [(True, 'ignore'), (False, 'ignore')])
def test_memo_delivery_ack_without_changed_text_cannot_claim_success(tmp_path, multiline, mode):
    desktop = MemoDesktop(multiline=multiline, replace_mode=mode, ignore_write=True)
    with pytest.raises(ValueError, match='readback'):
        module().run_window(memo_request(tmp_path, desktop, '装\n备'), backend=desktop)
    assert desktop.payloads == ['装\n备'] and desktop.os_text == '旧标题'
    assert len(desktop.events) == 1 and failure_data(tmp_path)['actionAttempted']


def test_memo_lf_readback_is_not_silently_equated_with_crlf(tmp_path):
    desktop = MemoDesktop(replace_mode='different-newlines')
    with pytest.raises(ValueError, match='readback'):
        module().run_window(memo_request(tmp_path, desktop, '装\n备'), backend=desktop)
    assert desktop.payloads == ['装\n备'] and desktop.os_text == '装\r\n备'
    assert failure_data(tmp_path)['actionAttempted']


@pytest.mark.parametrize('change', ['text', 'class', 'parent', 'owner', 'style', 'rect', 'hidden', 'disabled',
                                   'process-created', 'missing', 'expired', 'receipt-sha'])
def test_memo_original_value_identity_and_receipt_guards_reject_before_edit(tmp_path, change):
    desktop = MemoDesktop()
    request = memo_request(tmp_path, desktop, '装\n备')
    field = desktop.target['controls'][0]
    if change == 'text':
        desktop.os_text = '其他标题'
    elif change in ('hidden', 'disabled'):
        field['visible' if change == 'hidden' else 'enabled'] = False
    elif change == 'process-created':
        desktop.target['processCreated'] = '13370002'
    elif change == 'missing':
        desktop.target['controls'] = []
    elif change == 'expired':
        desktop.clock += 121
    elif change == 'receipt-sha':
        request['arguments']['observationSha256'] = '0' * 64
    else:
        field[change] = {'class': 'TMemo', 'parent': 777, 'owner': 888,
                         'style': MULTILINE_STYLE ^ 0x10000, 'rect': [31, 60, 101, 85]}[change]
    with pytest.raises(ValueError):
        module().run_window(request, backend=desktop)
    assert not edit_messages(desktop) and not desktop.events


def test_memo_truncated_observation_cannot_be_overwritten(tmp_path):
    desktop = MemoDesktop(before='装' * 65536)
    request = memo_request(tmp_path, desktop, '装备')
    request['arguments']['action']['expectedText'] = '装' * 65535
    with pytest.raises(ValueError, match='truncated'):
        module().run_window(request, backend=desktop)
    assert not edit_messages(desktop) and not desktop.events


def test_memo_foreign_process_control_fails_real_ancestor_check(tmp_path):
    desktop = MemoDesktop()
    request = memo_request(tmp_path, desktop, '装备')
    desktop.native.w = wintypes

    def window_process(hwnd, result):
        result._obj.value = 88 if hwnd == 10 else 12
        return 1

    desktop.native.user.GetWindowThreadProcessId = window_process
    desktop.native.user.GetAncestor = lambda hwnd, flag: 345 if hwnd == 10 else 0
    desktop.control_in_form = desktop.native.control_in_form
    with pytest.raises(ValueError, match='Control process/ancestor'):
        module().run_window(request, backend=desktop)
    assert not edit_messages(desktop) and not desktop.events


@pytest.mark.parametrize('loss', ['foreground', 'point'])
def test_memo_lost_foreground_or_point_ownership_blocks_edit(tmp_path, loss):
    desktop = MemoDesktop()
    request = memo_request(tmp_path, desktop, '装备')
    if loss == 'foreground':
        desktop.activate = lambda hwnd: None
    else:
        desktop.covered = True
    with pytest.raises(ValueError, match='Native focus or point ownership changed'):
        module().run_window(request, backend=desktop)
    assert not edit_messages(desktop) and not desktop.events


@pytest.mark.parametrize('value,error', [('装\x00备', 'exact text'), ('装' * 65536, 'too long')], ids=['NUL', 'over-limit'])
def test_memo_invalid_text_remains_rejected_before_input(tmp_path, value, error):
    desktop = MemoDesktop()
    request = memo_request(tmp_path, desktop, value)
    with pytest.raises(ValueError, match=error):
        module().run_window(request, backend=desktop)
    assert not edit_messages(desktop) and not desktop.events


@pytest.mark.parametrize('cls', ['tjvinspectormemo', 'TJvInspectorMemoEx', 'TJvMemo', 'TJvInspector'])
def test_memo_support_does_not_enable_similar_or_case_changed_classes(tmp_path, cls):
    desktop = MemoDesktop()
    request = memo_request(tmp_path, desktop, '装备')
    request['arguments']['action']['expectedClass'] = cls
    with pytest.raises(ValueError, match='Control class'):
        module().run_window(request, backend=desktop)
    assert not edit_messages(desktop) and not desktop.events
