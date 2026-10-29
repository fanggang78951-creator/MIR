"""Minimize is one guarded UI message, never process lifecycle or host input."""
import copy
import json
from pathlib import Path

import pytest

from test_native_window import module
from test_stack_component_window import ComponentDesktop, COMPONENTS, action_request


DB = COMPONENTS[0]


class MinimizeDesktop(ComponentDesktop):
    def __init__(self, *, hosted=False):
        super().__init__(DB, hosted=hosted)
        self.nodes[345]['style'] = 0x16CF0000
        self.minimize_messages = []
        self.message_timeout = False
        self.ignore_minimize = False
        self.undo_on_restore = False

    def send_message_timeout(self, hwnd, message, wparam, lparam, flags, timeout, result):
        if message == 0x112:
            self.messages.append((hwnd, message, flags, timeout))
            self.minimize_messages.append((hwnd, wparam, lparam))
            if self.message_timeout:
                return 0
            if not self.ignore_minimize:
                self.minimized.add(hwnd)
                self.nodes[hwnd]['style'] |= 0x20000000
                self.nodes[hwnd]['rect'] = [10, 20, 170, 50]
            result._obj.value = 0
            return 1
        return super().send_message_timeout(hwnd, message, wparam, lparam, flags, timeout, result)

    def restore(self, front, pointer):
        result = super().restore(front, pointer)
        if self.undo_on_restore:
            self.minimized.discard(345)
            self.nodes[345]['style'] &= ~0x20000000
        return result


@pytest.mark.parametrize('hosted', [False, True])
def test_minimize_targets_only_verified_form_and_keeps_host_restored(tmp_path, hosted):
    desktop = MinimizeDesktop(hosted=hosted)
    if hosted:
        desktop.front = 700
    req = action_request(tmp_path, desktop, DB, {'kind': 'minimize'})
    result = module().run_window(req, backend=desktop)
    assert desktop.minimize_messages == [(345, 0xF020, 0)]
    assert desktop.messages == [(345, 0x112, 2, 60000)]
    assert desktop.minimized == {345}
    assert result['actionAttempted'] and result['dispatch']['handlerAcknowledged']
    assert result['readbackVerified'] and result['target']['minimized']
    assert not result['targetClosed'] and result['targetLifecycle']['state'] == 'minimized'
    assert result['screenshot'] is None
    assert not (Path(result['outputRoot']) / 'window.png').exists()
    assert not result['businessSaveVerified']
    assert result['recovery'] == {'foregroundRestored': True, 'cursorRestored': True}
    assert desktop.front == (700 if hosted else 999)
    assert not desktop.nodes[700]['style'] & 0x20000000


@pytest.mark.parametrize('extra', [{'synchronous': False}, {'hwnd': 700}, {'force': True}, {'retry': 2}])
def test_minimize_has_no_extra_control_or_retry_arguments(extra):
    with pytest.raises(ValueError):
        module()._action(dict(kind='minimize', **extra))


@pytest.mark.parametrize('missing', [0x80000, 0x20000, 0x400000, 0x800000])
def test_minimize_requires_sysmenu_minimizebox_and_full_caption(tmp_path, missing):
    desktop = MinimizeDesktop(hosted=True)
    desktop.nodes[345]['style'] &= ~missing
    req = action_request(tmp_path, desktop, DB, {'kind': 'minimize'})
    with pytest.raises(ValueError, match='minimiz'):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and not desktop.minimized


def test_minimize_original_foreground_target_is_rejected_before_dispatch(tmp_path):
    desktop = MinimizeDesktop()
    desktop.front = 345
    req = action_request(tmp_path, desktop, DB, {'kind': 'minimize'})
    with pytest.raises(ValueError, match='foreground'):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and not desktop.minimized


@pytest.mark.parametrize('mode', ['ignored', 'timeout', 'undo-on-restore'])
def test_minimize_ack_timeout_and_restore_are_never_false_success_or_retried(tmp_path, mode):
    desktop = MinimizeDesktop(hosted=True)
    req = action_request(tmp_path, desktop, DB, {'kind': 'minimize'})
    desktop.ignore_minimize = mode == 'ignored'
    desktop.message_timeout = mode == 'timeout'
    desktop.undo_on_restore = mode == 'undo-on-restore'
    with pytest.raises((ValueError, OSError, RuntimeError)):
        module().run_window(req, backend=desktop)
    assert desktop.minimize_messages == [(345, 0xF020, 0)]
    assert (Path(req['arguments']['outputRoot']) / 'failure.json').is_file()
    assert not (Path(req['arguments']['outputRoot']) / 'observation.json').exists()
    assert 700 not in desktop.minimized
    if mode == 'undo-on-restore':
        failure = json.loads((Path(req['arguments']['outputRoot']) / 'failure.json').read_text('utf-8'))
        assert failure['readbackVerified'] is False


@pytest.mark.parametrize('change', ['creation', 'owner', 'parent', 'title', 'class', 'style',
                                   'host-creation', 'host-root', 'host-rect', 'chain-class', 'chain-pid'])
def test_minimize_postcondition_rejects_identity_host_or_ancestry_drift(change):
    desktop = MinimizeDesktop(hosted=True)
    before = desktop.snapshot(12, 345)
    desktop.minimized.add(345)
    desktop.nodes[345]['style'] |= 0x20000000
    desktop.nodes[345]['rect'] = [10, 20, 170, 50]
    after = desktop.snapshot(12, 345)
    if change in ('creation', 'owner', 'parent', 'title', 'class', 'style'):
        key, value = {'creation': ('processCreated', '13370002'), 'owner': ('owner', 123),
                      'parent': ('parent', 123), 'title': ('title', 'different'),
                      'class': ('class', 'DifferentForm'), 'style': ('style', after['style'] ^ 0x10000)}[change]
        after[key] = value
    elif change == 'host-creation':
        after['hosting']['processCreated'] = '1338000'
    elif change == 'host-root':
        after['hosting']['rootHwnd'] = 701
    elif change == 'host-rect':
        after['hosting']['rect'][0] += 1
    elif change == 'chain-class':
        after['hosting']['ancestorChain'][1]['class'] = 'DifferentPanel'
    else:
        after['hosting']['ancestorChain'][1]['pid'] = 88
    verify = getattr(module(), '_verify_minimized', None)
    assert callable(verify), 'minimize must verify identity and host after the UI message'
    with pytest.raises((ValueError, PermissionError)):
        verify(before, after)


def test_minimize_postcondition_allows_only_expected_geometry_and_minimize_bit():
    desktop = MinimizeDesktop(hosted=True)
    before = desktop.snapshot(12, 345)
    desktop.minimized.add(345)
    desktop.nodes[345]['style'] |= 0x20000000
    desktop.nodes[345]['rect'] = [10, 20, 170, 50]
    after = desktop.snapshot(12, 345)
    verify = getattr(module(), '_verify_minimized', None)
    assert callable(verify), 'minimize readback must be a validated postcondition'
    verify(before, after)
    assert before['hosting']['ancestorChain'][0]['style'] != after['hosting']['ancestorChain'][0]['style']
    assert before['hosting']['ancestorChain'][1:] == after['hosting']['ancestorChain'][1:]
