import copy
import ctypes
import hashlib
import importlib.util
import json
import sys
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
SPEC = importlib.util.find_spec('wzl_blackbox.native_game')


def module():
    assert SPEC is not None, 'game adapter is not implemented'
    from wzl_blackbox import native_game
    return native_game


EXE = r'D:\Mirserver100\LabClient\LFM2-100-LAB.exe'
DIGEST = 'C47FF89016182E8E48E5CB85F4FF60571AC60AB5E16437F6B37C706C95477503'


class Desktop:
    def __init__(self):
        self.target = {'pid': 12, 'hwnd': 345, 'class': 'TfrmMain', 'title': '01区 - 测试',
                       'executable': EXE, 'sha256': DIGEST, 'processCreated': '13370000111222333',
                       'rect': [10, 20, 810, 620], 'clientSize': [780, 560], 'clientOrigin': [20, 50],
                       'visible': True, 'enabled': True, 'modalWindows': []}
        self.front, self.pointer = 999, [3, 4]
        self.held = set()
        self.events = []
        self.restore_ok = True
        self.fail_on_down = False
        self.covered = False
        self.lose_focus = False
        self.clock = time.time()

    def now(self):
        return self.clock

    def enumerate_targets(self):
        return [copy.deepcopy(self.target)]

    def snapshot(self, pid, hwnd):
        assert (pid, hwnd) == (12, 345)
        return copy.deepcopy(self.target)

    def foreground(self):
        return self.front

    def cursor(self):
        return list(self.pointer)

    def activate(self, hwnd):
        self.front = hwnd

    def restore(self, front, pointer):
        if self.restore_ok:
            self.front, self.pointer = front, list(pointer)
        return {'cursorRestored': self.pointer == list(pointer), 'foregroundRestored': self.front == front}

    def client_to_screen(self, hwnd, x, y):
        return [20 + x, 50 + y]

    def root_at(self, point):
        if self.lose_focus:
            self.front = 888
        return 888 if self.covered else 345

    def move(self, point):
        self.pointer = list(point)

    def assert_input_idle(self):
        if self.held:
            raise ValueError('input already held')

    def down(self, kind, value):
        self.held.add((kind, value))
        self.events.append(('down', kind, value))
        if self.fail_on_down:
            raise RuntimeError('input failure')

    def up(self, kind, value):
        self.held.discard((kind, value))
        self.events.append(('up', kind, value))

    def sleep(self, seconds):
        pass

    def screenshot(self, path, rect):
        Path(path).write_bytes(b'pixel capture fixture')


def request(tmp_path, command='game-observe', name='observe'):
    return {'schemaVersion': 1, 'command': command,
            'arguments': {'pid': 12, 'hwnd': 345, 'expectedTitle': '01区 - 测试',
                          'expectedClass': 'TfrmMain', 'expectedExecutable': EXE,
                          'expectedSha256': DIGEST, 'outputRoot': str(tmp_path / name)},
            'policy': {'allowedWriteRoots': [str(tmp_path)]}}


def input_request(tmp_path, desktop, action=None):
    m = module()
    data = m.run_game(request(tmp_path), backend=desktop)
    receipt = Path(data['outputRoot']) / 'observation.json'
    req = request(tmp_path, 'game-input', 'input')
    req['arguments'].update(observationReceipt=str(receipt),
                            observationSha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
                            action=action or {'kind': 'click', 'x': 60, 'y': 80, 'button': 'left', 'holdMs': 5, 'settleMs': 0})
    return req


def test_inspect_is_read_only_and_needs_no_pid(tmp_path):
    m = module()
    d = Desktop()
    result = m.run_game({'schemaVersion': 1, 'command': 'game-inspect'}, backend=d)
    assert result['targets'][0]['hwnd'] == 345
    assert d.front == 999 and d.pointer == [3, 4] and d.events == []
    assert list(tmp_path.iterdir()) == []


def test_observe_writes_fingerprinted_receipt_and_restores(tmp_path):
    m, d = module(), Desktop()
    data = m.run_game(request(tmp_path), backend=d)
    assert data['target']['processCreated'] == '13370000111222333'
    assert data['recovery'] == {'cursorRestored': True, 'foregroundRestored': True}
    shot = Path(data['screenshot']['path'])
    assert data['screenshot']['sha256'] == hashlib.sha256(shot.read_bytes()).hexdigest().upper()
    assert json.loads((Path(data['outputRoot']) / 'observation.json').read_text(encoding='utf-8')) == data
    assert d.events == []


@pytest.mark.parametrize('field,value', [('expectedExecutable', r'E:\client.exe'), ('expectedSha256', '0' * 64), ('pid', True), ('hwnd', 0), ('expectedClass', '#32770')])
def test_invalid_identity_is_rejected_before_desktop_input(tmp_path, field, value):
    m, d = module(), Desktop()
    req = request(tmp_path)
    req['arguments'][field] = value
    with pytest.raises((ValueError, PermissionError)):
        m.run_game(req, backend=d)
    assert d.events == [] and d.front == 999


@pytest.mark.parametrize('field,value', [('visible', False), ('enabled', False), ('title', 'another'), ('class', '#32770'), ('executable', r'E:\other.exe'), ('sha256', '0' * 64), ('modalWindows', [{'hwnd': 444}])])
def test_observe_rejects_live_identity_or_modal_change(tmp_path, field, value):
    m, d = module(), Desktop()
    d.target[field] = value
    with pytest.raises((ValueError, PermissionError)):
        m.run_game(request(tmp_path), backend=d)
    assert d.events == [] and d.front == 999


def test_one_click_has_no_business_success_claim(tmp_path):
    m, d = module(), Desktop()
    req = input_request(tmp_path, d)
    data = m.run_game(req, backend=d)
    assert data['inputSent'] is True and data['visualVerificationRequired'] is True
    assert 'businessSuccess' not in data
    assert d.events == [('down', 'mouse', 'left'), ('up', 'mouse', 'left')]
    assert d.held == set() and d.front == 999 and d.pointer == [3, 4]


@pytest.mark.parametrize('mutation', ['old', 'future', 'created', 'rect', 'size', 'receipt_hash', 'pixels'])
def test_input_rejects_stale_or_changed_observation(tmp_path, mutation):
    m, d = module(), Desktop()
    req = input_request(tmp_path, d)
    receipt = Path(req['arguments']['observationReceipt'])
    if mutation == 'old':
        d.clock += 121
    elif mutation == 'future':
        d.clock -= 10
    elif mutation == 'created':
        d.target['processCreated'] = '13370000999999999'
    elif mutation == 'rect':
        d.target['rect'][0] = 11
    elif mutation == 'size':
        d.target['clientSize'][0] = 779
    elif mutation == 'receipt_hash':
        receipt.write_bytes(receipt.read_bytes() + b' ')
    elif mutation == 'pixels':
        data = json.loads(receipt.read_text(encoding='utf-8'))
        Path(data['screenshot']['path']).write_bytes(b'changed')
    with pytest.raises((ValueError, PermissionError)):
        m.run_game(req, backend=d)
    assert d.events == [] and d.front == 999


@pytest.mark.parametrize('action', [
    {'kind': 'click', 'x': -1, 'y': 2}, {'kind': 'click', 'x': 780, 'y': 2},
    {'kind': 'click', 'x': 1, 'y': 560}, {'kind': 'key', 'key': 'ENTER'},
    {'kind': 'key', 'key': 'B', 'holdMs': 1001}, {'kind': 'key', 'key': 'B', 'settleMs': 3001},
    {'kind': 'text', 'text': '/command'}, {'kind': 'key', 'key': 'B', 'x': 2},
    {'kind': 'hover', 'x': True, 'y': 2}, {'kind': 'click', 'x': 1, 'y': 2, 'button': 'middle'},
])
def test_invalid_or_outside_action_never_sends_input(tmp_path, action):
    m, d = module(), Desktop()
    req = input_request(tmp_path, d, action)
    with pytest.raises((ValueError, PermissionError)):
        m.run_game(req, backend=d)
    assert d.events == []


@pytest.mark.parametrize('failure', ['covered', 'lose_focus'])
def test_input_rejects_covering_window_or_lost_focus(tmp_path, failure):
    m, d = module(), Desktop()
    req = input_request(tmp_path, d)
    setattr(d, failure, True)
    with pytest.raises((ValueError, PermissionError)):
        m.run_game(req, backend=d)
    assert d.events == [] and d.held == set() and d.front == 999


def test_input_exception_releases_and_records_recovery(tmp_path):
    m, d = module(), Desktop()
    req = input_request(tmp_path, d, {'kind': 'key', 'key': 'B', 'settleMs': 0})
    d.fail_on_down = True
    with pytest.raises(RuntimeError, match='input failure'):
        m.run_game(req, backend=d)
    assert d.held == set()
    assert d.events == [('down', 'key', 'B'), ('up', 'key', 'B')]
    failure = json.loads((tmp_path / 'input' / 'failure.json').read_text(encoding='utf-8'))
    assert failure['recovery'] == {'cursorRestored': True, 'foregroundRestored': True}
    assert failure['inputAttempted'] is True and failure['inputSent'] is False


def test_failed_recovery_is_not_reported_as_success(tmp_path):
    m, d = module(), Desktop()
    d.restore_ok = False
    with pytest.raises(ValueError, match='restore'):
        m.run_game(request(tmp_path), backend=d)
    failure = json.loads((tmp_path / 'observe' / 'failure.json').read_text(encoding='utf-8'))
    assert failure['recovery']['foregroundRestored'] is False
    assert not (tmp_path / 'observe' / 'observation.json').exists()


def test_output_must_be_new_and_policy_allowed(tmp_path):
    m = module()
    req = request(tmp_path)
    req['policy']['allowedWriteRoots'] = []
    with pytest.raises(PermissionError):
        m.run_game(req, backend=Desktop())
    req['policy']['allowedWriteRoots'] = [str(tmp_path)]
    Path(req['arguments']['outputRoot']).mkdir()
    with pytest.raises(FileExistsError):
        m.run_game(req, backend=Desktop())


def test_receipt_can_chain_from_previous_input(tmp_path):
    m, d = module(), Desktop()
    first = m.run_game(input_request(tmp_path, d, {'kind': 'key', 'key': 'F9', 'settleMs': 0}), backend=d)
    receipt = Path(first['outputRoot']) / 'observation.json'
    req = request(tmp_path, 'game-input', 'second-input')
    req['arguments'].update(observationReceipt=str(receipt), observationSha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
                            action={'kind': 'key', 'key': 'F9', 'settleMs': 0})
    second = m.run_game(req, backend=d)
    assert second['inputSent'] and len(d.events) == 4


def test_observation_expiring_during_activation_blocks_input(tmp_path):
    m, d = module(), Desktop()
    req = input_request(tmp_path, d)
    def activate(hwnd):
        d.front = hwnd
        d.clock += 121
    d.activate = activate
    with pytest.raises(ValueError, match='120 seconds'):
        m.run_game(req, backend=d)
    assert d.events == []


def test_restore_detach_error_blocks_success_even_if_positions_match(tmp_path):
    m, d = module(), Desktop()
    original_restore = d.restore
    def restore(front, pointer):
        state = original_restore(front, pointer)
        state['errors'] = ['input queue detach failed']
        return state
    d.restore = restore
    with pytest.raises(ValueError, match='restore'):
        m.run_game(request(tmp_path), backend=d)
    assert not (tmp_path / 'observe' / 'observation.json').exists()


@pytest.mark.parametrize('held', [0x78, 0x42, 0x49, 0x1B])
def test_physical_supported_key_down_blocks_synthetic_release(held):
    m = module()
    backend = object.__new__(m.Win32GameBackend)
    backend.user = SimpleNamespace(GetAsyncKeyState=lambda key: -32768 if key == held else 0)
    with pytest.raises(ValueError, match='Release physical'):
        backend.assert_input_idle()


@pytest.mark.parametrize('kind,value,release,want', [
    ('key', 'F9', False, (1, 0x78, 0)), ('key', 'F9', True, (1, 0x78, 2)),
    ('mouse', 'right', False, (0, 0, 8)), ('mouse', 'right', True, (0, 0, 16)),
])
def test_native_input_uses_correct_union_and_flags(kind, value, release, want):
    m = module()
    backend = m.Win32GameBackend()  # Bind signatures only; no desktop operation.
    captured = []
    def send(count, pointer, size):
        event = ctypes.cast(pointer, ctypes.POINTER(backend.Input)).contents
        assert count == 1 and size == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        captured.append((event.type, event.ki.wVk if event.type else 0,
                         event.ki.dwFlags if event.type else event.mi.dwFlags))
        return 1
    backend.user = SimpleNamespace(SendInput=send)
    backend._send(kind, value, release)
    assert captured == [want]


def test_short_native_send_is_failure():
    m = module()
    backend = m.Win32GameBackend()
    backend.user = SimpleNamespace(SendInput=lambda *args: 0)
    with pytest.raises(OSError, match='complete event'):
        backend.down('key', 'F9')


def test_client_origin_change_invalidates_previous_input_coordinates(tmp_path):
    m, d = module(), Desktop()
    req = input_request(tmp_path, d)
    d.target['clientOrigin'][0] = 30
    with pytest.raises(ValueError, match='geometry changed'):
        m.run_game(req, backend=d)
    assert d.events == []


def test_observe_rejects_pressed_input_before_changing_foreground(tmp_path):
    m, d = module(), Desktop()
    d.held.add(('mouse', 'left'))
    called = []
    def activate(hwnd):
        called.append(hwnd)
        d.front = hwnd
    d.activate = activate
    with pytest.raises(ValueError, match='already held'):
        m.run_game(request(tmp_path), backend=d)
    assert called == [] and d.front == 999


def test_dpi_context_restores_previous_context_even_on_error():
    m = module()
    backend = object.__new__(m.Win32GameBackend)
    contexts = []
    def set_context(value):
        contexts.append(value)
        return 111
    backend.user = SimpleNamespace(SetThreadDpiAwarenessContext=set_context)
    with pytest.raises(RuntimeError, match='test error'):
        with backend.dpi_context():
            raise RuntimeError('test error')
    assert contexts == [-4, 111]


def test_dpi_context_failure_refuses_to_continue():
    m = module()
    backend = object.__new__(m.Win32GameBackend)
    backend.user = SimpleNamespace(SetThreadDpiAwarenessContext=lambda value: None)
    with pytest.raises(OSError):
        with backend.dpi_context():
            pytest.fail('must not enter without consistent DPI coordinates')


def test_unverified_window_class_is_rejected_at_request_boundary(tmp_path):
    m = module()
    req = request(tmp_path)
    req['arguments']['expectedClass'] = '#32770'
    with pytest.raises(PermissionError):
        m.validate_request(req)


@pytest.mark.parametrize('changes,nonblocking', [
    ({}, True),
    ({'class': '#32770'}, False),
    ({'class': 'TApplication'}, False),
    ({'class': 'sopy_status'}, False),
    ({'enabled': True}, False),
    ({'exstyle': 0x800088}, False),
    ({'rect': [1384, 859, 1565, 1033]}, False),
    ({'rect': [1384, 860, 1565, 1033]}, True),
    ({'rect': [1879, 300, 1900, 350]}, True),
    ({'rect': [1878, 300, 1900, 350]}, False),
    ({'rect': [900, 300, 974, 350]}, False),
    ({'rect': [900, 300, 973, 350]}, True),
    ({'rect': [1000, 200, 1100, 231]}, True),
    ({'rect': [1000, 200, 1100, 232]}, False),
    ({'rect': [1384, 1001, 1384, 1033]}, False),
    ({'rect': None}, False),
])
def test_only_proven_noninteractive_status_outside_game_is_nonblocking(changes, nonblocking):
    m = module()
    assert hasattr(m, 'classify_auxiliary_windows'), 'auxiliary-window classifier is not implemented'
    window = {'hwnd': 726564, 'class': 'SoPY_Status', 'enabled': False,
              'rect': [1384, 1001, 1565, 1033], 'exstyle': 0x08080088}
    window.update(changes)
    result = m.classify_auxiliary_windows([window], [973, 231, 1879, 860])
    assert result['nonBlockingWindows'] == ([window] if nonblocking else [])
    assert result['modalWindows'] == ([] if nonblocking else [window])


def test_nonblocking_window_does_not_hide_other_modal_windows():
    m = module()
    assert hasattr(m, 'classify_auxiliary_windows'), 'auxiliary-window classifier is not implemented'
    status = {'hwnd': 726564, 'class': 'SoPY_Status', 'enabled': False,
              'rect': [1384, 1001, 1565, 1033], 'exstyle': 0x08080088}
    dialog = {'hwnd': 900, 'class': '#32770', 'enabled': False,
              'rect': [1384, 1001, 1565, 1033], 'exstyle': 0x08080088}
    result = m.classify_auxiliary_windows([status, dialog], [973, 231, 1879, 860])
    assert result['nonBlockingWindows'] == [status]
    assert result['modalWindows'] == [dialog]


@pytest.mark.parametrize('window,nonblocking', [
    ({'hwnd': 11732106, 'class': 'TApplication', 'enabled': True,
      'rect': [960, 540, 960, 540], 'exstyle': 256}, True),
    ({'class': 'TApplication', 'rect': [960, 540, 961, 541]}, False),
    ({'class': 'TApplication', 'rect': [960, 540, 960, 541]}, False),
    ({'class': 'TApplication', 'rect': [960, 540, 961, 540]}, False),
    ({'class': 'TApplication', 'rect': [960, 540, 959, 539]}, False),
    ({'class': 'tapplication', 'rect': [960, 540, 960, 540]}, False),
    ({'class': '#32770', 'rect': [960, 540, 960, 540]}, False),
])
def test_only_zero_width_and_height_tapplication_is_nonblocking(window, nonblocking):
    m = module()
    result = m.classify_auxiliary_windows([window], [973, 231, 1879, 860])
    assert result['nonBlockingWindows'] == ([window] if nonblocking else [])
    assert result['modalWindows'] == ([] if nonblocking else [window])


def test_failure_receipt_keeps_last_rejected_target_snapshot(tmp_path):
    m, d = module(), Desktop()
    dialog = {'hwnd': 888, 'class': '#32770', 'enabled': True,
              'rect': [100, 100, 300, 300], 'exstyle': 256}
    d.target['modalWindows'] = [dialog]
    with pytest.raises(ValueError, match='modal'):
        m.run_game(request(tmp_path), backend=d)
    failure = json.loads((tmp_path / 'observe' / 'failure.json').read_text(encoding='utf-8'))
    assert failure['target']['modalWindows'] == [dialog]
    assert failure['target']['hwnd'] == 345
