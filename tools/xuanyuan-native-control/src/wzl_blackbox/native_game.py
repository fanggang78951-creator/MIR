"""Bounded foreground input for the verified disposable Mir client.

No process injection, game-state API, or unattended gameplay is provided. Every
input requires a fresh pixel observation and returns pixels for human/agent review.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path, PureWindowsPath

from .policy import DEFAULT_PROTECTED_ROOTS, WritePolicy

COMMANDS = ('game-inspect', 'game-observe', 'game-input')
EXECUTABLE = r'D:\Mirserver100\LabClient\LFM2-100-LAB.exe'
EXECUTABLE_SHA256 = 'C47FF89016182E8E48E5CB85F4FF60571AC60AB5E16437F6B37C706C95477503'
KEYS = {'ESC': 0x1B, 'TAB': 0x09, 'B': 0x42, 'I': 0x49,
        **{f'F{i}': 0x6F + i for i in range(1, 13)}}
IDENTITY_FIELDS = ('pid', 'hwnd', 'class', 'title', 'executable', 'sha256',
                   'processCreated', 'rect', 'clientSize', 'clientOrigin')


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest().upper()


def _same_path(a, b):
    return str(PureWindowsPath(str(a))).casefold() == str(PureWindowsPath(str(b))).casefold()


def _integer(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(label + ' is outside its integer range')
    return value


def _independent(path):
    original = Path(path).absolute()
    for item in (original, *original.parents):
        try:
            if getattr(item.lstat(), 'st_file_attributes', 0) & 0x400 or item.is_symlink():
                raise ValueError('Game evidence paths must not contain reparse points')
        except FileNotFoundError:
            pass
    return original.resolve(strict=False)


def validate_request(request):
    if not isinstance(request, dict) or request.get('schemaVersion') != 1 or request.get('command') not in COMMANDS:
        raise ValueError('Unknown game command or schemaVersion')
    command = request['command']
    args = request.get('arguments', {})
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    if command == 'game-inspect':
        if args:
            raise ValueError('game-inspect has no arguments')
        return {'command': command}
    _integer(args.get('pid'), 'pid', 1, 0xFFFFFFFF)
    _integer(args.get('hwnd'), 'hwnd', 1, (1 << 64) - 1)
    if not _same_path(args.get('expectedExecutable', ''), EXECUTABLE):
        raise PermissionError('Only the verified disposable LabClient executable is supported')
    if str(args.get('expectedSha256', '')).upper() != EXECUTABLE_SHA256:
        raise PermissionError('Expected executable SHA256 does not match the verified LabClient')
    for key in ('expectedTitle', 'expectedClass'):
        if not isinstance(args.get(key), str) or not args[key].strip():
            raise ValueError(key + ' must be exact nonempty text')
    if args['expectedClass'] != 'TfrmMain':
        raise PermissionError('Only the verified TfrmMain game window class is supported')
    if not args.get('outputRoot'):
        raise ValueError('outputRoot is required')
    output = _independent(args['outputRoot'])
    policy = WritePolicy(request.get('policy', {}).get('allowedWriteRoots', []),
                         protected_roots=(*DEFAULT_PROTECTED_ROOTS, Path(EXECUTABLE).parent))
    policy.assert_writable(output)
    if output.exists():
        raise FileExistsError('outputRoot must be a new job directory')
    plan = {'command': command, 'arguments': dict(args), 'output': output}
    if command == 'game-input':
        receipt = _independent(args.get('observationReceipt', ''))
        if not receipt.is_file() or receipt.stat().st_size > 1024 * 1024:
            raise ValueError('observationReceipt must be an existing bounded JSON file')
        if not re.fullmatch(r'[0-9a-fA-F]{64}', str(args.get('observationSha256', ''))):
            raise ValueError('observationSha256 is required')
        policy.assert_writable(receipt)
        action = args.get('action')
        if not isinstance(action, dict) or action.get('kind') not in ('click', 'hover', 'key'):
            raise ValueError('Only one click, hover or key action is supported')
        kind = action['kind']
        allowed = {'kind', 'settleMs'} | ({'key', 'holdMs'} if kind == 'key' else {'x', 'y'} | ({'button', 'holdMs'} if kind == 'click' else set()))
        if set(action) - allowed:
            raise ValueError('Unexpected action fields')
        normalized = dict(action)
        normalized['settleMs'] = _integer(action.get('settleMs', 400), 'settleMs', 0, 3000)
        if kind != 'hover':
            normalized['holdMs'] = _integer(action.get('holdMs', 60), 'holdMs', 0, 1000)
        if kind == 'key':
            if action.get('key') not in KEYS:
                raise ValueError('Unsupported single key')
        else:
            _integer(action.get('x'), 'x', 0, 65535)
            _integer(action.get('y'), 'y', 0, 65535)
            if kind == 'click':
                normalized['button'] = action.get('button', 'left')
                if normalized['button'] not in ('left', 'right'):
                    raise ValueError('Only left and right buttons are supported')
        plan.update(receipt=receipt, action=normalized)
    return plan


def _check_target(target, args):
    if not isinstance(target, dict) or any(key not in target for key in IDENTITY_FIELDS):
        raise ValueError('Incomplete live game identity')
    expected = {'pid': args['pid'], 'hwnd': args['hwnd'], 'class': args['expectedClass'],
                'title': args['expectedTitle']}
    if any(target[key] != value for key, value in expected.items()):
        raise ValueError('Live game window identity changed')
    if not _same_path(target['executable'], EXECUTABLE) or target['sha256'].upper() != EXECUTABLE_SHA256:
        raise PermissionError('Live game executable fingerprint changed')
    if not target.get('visible') or not target.get('enabled') or target.get('minimized'):
        raise ValueError('Game window must be visible, enabled and not minimized')
    if target.get('modalWindows'):
        raise ValueError('Another visible game modal/top-level window blocks operation')
    if not isinstance(target['processCreated'], str) or not target['processCreated'].isdigit():
        raise ValueError('Process creation identity is missing')
    if (not isinstance(target['rect'], list) or len(target['rect']) != 4 or
            not isinstance(target['clientSize'], list) or len(target['clientSize']) != 2 or
            not isinstance(target['clientOrigin'], list) or len(target['clientOrigin']) != 2 or
            target['rect'][2] <= target['rect'][0] or target['rect'][3] <= target['rect'][1] or
            min(target['clientSize']) <= 0):
        raise ValueError('Invalid game window geometry')
    return target


def _compare_target(before, after):
    if not isinstance(before, dict) or any(key not in before or before[key] != after[key] for key in IDENTITY_FIELDS):
        raise ValueError('Game process/window/geometry changed since observation')


def _read_observation(plan, target, now):
    receipt = plan['receipt']
    if _digest(receipt) != plan['arguments']['observationSha256'].upper():
        raise ValueError('Observation receipt SHA256 changed')
    data = json.loads(receipt.read_text(encoding='utf-8'))
    if data.get('command') not in ('game-observe', 'game-input') or not data.get('recovery', {}).get('foregroundRestored') or not data.get('recovery', {}).get('cursorRestored'):
        raise ValueError('A recovered game observation is required')
    _compare_target(data.get('target', {}), target)
    shot = data.get('screenshot', {})
    captured = shot.get('capturedAtUnix')
    if isinstance(captured, bool) or not isinstance(captured, (int, float)) or not 0 <= now - captured <= 120:
        raise ValueError('Observation must be no older than 120 seconds and cannot be from the future')
    image = _independent(shot.get('path', ''))
    if not image.is_relative_to(receipt.parent) or not image.is_file() or _digest(image) != shot.get('sha256'):
        raise ValueError('Observation screenshot is missing, relocated or changed')
    return data


def _foreground_guard(backend, hwnd, point):
    if backend.foreground() != hwnd or backend.root_at(point) != hwnd or backend.foreground() != hwnd:
        raise ValueError('Foreground focus or point ownership does not match the game window')


def classify_auxiliary_windows(windows, game_rect):
    """Classify same-process visible top-level windows using the proven signature.

    RECT uses Win32 half-open coordinates: touching an outside edge does not
    cover a pixel. Any unknown or malformed window remains blocking.
    """
    def valid_rect(rect):
        return (isinstance(rect, list) and len(rect) == 4 and
                all(isinstance(value, int) and not isinstance(value, bool) for value in rect) and
                rect[0] < rect[2] and rect[1] < rect[3])
    if not valid_rect(game_rect):
        raise ValueError('Cannot classify auxiliary windows without valid game geometry')
    result = {'modalWindows': [], 'nonBlockingWindows': []}
    for window in windows:
        rect, exstyle = window.get('rect'), window.get('exstyle')
        outside = (valid_rect(rect) and
                   (rect[2] <= game_rect[0] or rect[0] >= game_rect[2] or
                    rect[3] <= game_rect[1] or rect[1] >= game_rect[3]))
        proven_status = (window.get('class') == 'SoPY_Status' and window.get('enabled') is False and
                         isinstance(exstyle, int) and not isinstance(exstyle, bool) and
                         bool(exstyle & 0x08000000) and outside)
        zero_application = (window.get('class') == 'TApplication' and isinstance(rect, list) and
                            len(rect) == 4 and all(isinstance(value, int) and not isinstance(value, bool) for value in rect) and
                            rect[0] == rect[2] and rect[1] == rect[3])
        result['nonBlockingWindows' if proven_status or zero_application else 'modalWindows'].append(window)
    return result


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run_game(request, backend=None):
    plan = validate_request(request)
    real = backend is None
    backend = Win32GameBackend() if real else backend
    dpi_scope = backend.dpi_context() if real else nullcontext()
    with dpi_scope:
        if plan['command'] == 'game-inspect':
            return {'command': 'game-inspect', 'targets': backend.enumerate_targets(), 'readOnly': True}
        if real:
            from .native_engine import serial_engine_operation
            mutex = serial_engine_operation()
        else:
            mutex = nullcontext()
        with mutex:
            return _run_with_backend(plan, backend)


def _run_with_backend(plan, backend):
    output, args = plan['output'], plan['arguments']
    output.mkdir(parents=True, exist_ok=False)
    front, pointer = None, None
    recovery = {'cursorRestored': False, 'foregroundRestored': False}
    error, data = None, None
    input_attempted, input_sent = False, False
    last_target = None
    def live_target():
        nonlocal last_target
        last_target = backend.snapshot(args['pid'], args['hwnd'])
        return _check_target(last_target, args)
    try:
        front, pointer = backend.foreground(), backend.cursor()
        target = live_target()
        if plan['command'] == 'game-input':
            _read_observation(plan, target, backend.now())
            action = plan['action']
            if action['kind'] != 'key' and not (action['x'] < target['clientSize'][0] and action['y'] < target['clientSize'][1]):
                raise ValueError('Action coordinates are outside the game client area')
            backend.assert_input_idle()
        backend.assert_input_idle()
        backend.activate(target['hwnd'])
        _compare_target(target, live_target())
        center = backend.client_to_screen(target['hwnd'], target['clientSize'][0] // 2, target['clientSize'][1] // 2)
        _foreground_guard(backend, target['hwnd'], center)
        if plan['command'] == 'game-input':
            # Foreground activation and live hashing can take time; consume the
            # observation only when it is still fresh immediately before input.
            _read_observation(plan, target, backend.now())
            action = plan['action']
            point = center if action['kind'] == 'key' else backend.client_to_screen(target['hwnd'], action['x'], action['y'])
            _foreground_guard(backend, target['hwnd'], point)
            if action['kind'] != 'key':
                input_attempted = True
                backend.move(point)
            _foreground_guard(backend, target['hwnd'], point)
            backend.assert_input_idle()
            if action['kind'] == 'hover':
                input_sent = True
            else:
                kind, value = ('key', action['key']) if action['kind'] == 'key' else ('mouse', action['button'])
                try:
                    input_attempted = True
                    backend.down(kind, value)
                    input_sent = True
                    backend.sleep(action['holdMs'] / 1000)
                finally:
                    backend.up(kind, value)
            backend.sleep(action['settleMs'] / 1000)
        _foreground_guard(backend, target['hwnd'], center)
        _compare_target(target, live_target())
        image = output / 'capture.png'
        backend.screenshot(image, target['rect'])
        captured = backend.now()
        _foreground_guard(backend, target['hwnd'], center)
        _compare_target(target, live_target())
        data = {'command': plan['command'], 'outputRoot': str(output), 'target': target,
                'screenshot': {'path': str(image), 'sha256': _digest(image), 'capturedAtUnix': captured},
                'inputAttempted': input_attempted, 'inputSent': input_sent, 'visualVerificationRequired': True}
        if plan['command'] == 'game-input':
            data['action'] = dict(plan['action'])
    except BaseException as exc:
        error = exc
    finally:
        if front is not None and pointer is not None:
            try:
                recovery = backend.restore(front, pointer)
            except BaseException as restore_error:
                recovery['error'] = str(restore_error)
        if (not all(recovery.get(key) is True for key in ('cursorRestored', 'foregroundRestored')) or recovery.get('error') or recovery.get('errors')) and error is None:
            error = ValueError('Could not restore foreground window and cursor')
    if error is not None:
        _write_json(output / 'failure.json', {'command': plan['command'], 'errorType': type(error).__name__,
                    'error': str(error), 'recovery': recovery, 'inputAttempted': input_attempted,
                    'inputSent': input_sent, 'target': last_target, 'visualVerificationRequired': True})
        raise error
    data['recovery'] = recovery
    _write_json(output / 'observation.json', data)
    return data


class Win32GameBackend:
    """Explicitly typed Win32 boundary. Constructing it performs no input."""
    def __init__(self):
        from ctypes import wintypes as w
        self.w = w
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.enum_callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        declarations = {
            'EnumWindows': ([self.enum_callback, w.LPARAM], w.BOOL),
            'GetWindowThreadProcessId': ([w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            'GetClassNameW': ([w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetWindowTextLengthW': ([w.HWND], ctypes.c_int),
            'GetWindowTextW': ([w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
            'IsWindow': ([w.HWND], w.BOOL), 'IsWindowVisible': ([w.HWND], w.BOOL),
            'IsWindowEnabled': ([w.HWND], w.BOOL), 'IsIconic': ([w.HWND], w.BOOL),
            'GetWindowRect': ([w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            'GetClientRect': ([w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            'ClientToScreen': ([w.HWND, ctypes.POINTER(w.POINT)], w.BOOL),
            'GetCursorPos': ([ctypes.POINTER(w.POINT)], w.BOOL),
            'SetCursorPos': ([ctypes.c_int, ctypes.c_int], w.BOOL),
            'GetForegroundWindow': ([], w.HWND), 'SetForegroundWindow': ([w.HWND], w.BOOL),
            'BringWindowToTop': ([w.HWND], w.BOOL),
            'AttachThreadInput': ([w.DWORD, w.DWORD, w.BOOL], w.BOOL),
            'WindowFromPoint': ([w.POINT], w.HWND), 'GetAncestor': ([w.HWND, w.UINT], w.HWND),
            'GetAsyncKeyState': ([ctypes.c_int], ctypes.c_short),
            'SetThreadDpiAwarenessContext': ([ctypes.c_void_p], ctypes.c_void_p),
        }
        for name, (args, result) in declarations.items():
            fn = getattr(self.user, name)
            fn.argtypes, fn.restype = args, result
        self.window_long = getattr(self.user, 'GetWindowLongPtrW' if ctypes.sizeof(ctypes.c_void_p) == 8 else 'GetWindowLongW')
        self.window_long.argtypes = [w.HWND, ctypes.c_int]
        self.window_long.restype = ctypes.c_ssize_t
        declarations = {
            'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'CloseHandle': ([w.HANDLE], w.BOOL),
            'QueryFullProcessImageNameW': ([w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            'GetProcessTimes': ([w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)], w.BOOL),
            'GetExitCodeProcess': ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            'GetCurrentThreadId': ([], w.DWORD),
        }
        for name, (args, result) in declarations.items():
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result
        class Mouse(ctypes.Structure):
            _fields_ = [('dx', w.LONG), ('dy', w.LONG), ('mouseData', w.DWORD),
                        ('dwFlags', w.DWORD), ('time', w.DWORD), ('dwExtraInfo', ctypes.c_size_t)]
        class Keyboard(ctypes.Structure):
            _fields_ = [('wVk', w.WORD), ('wScan', w.WORD), ('dwFlags', w.DWORD),
                        ('time', w.DWORD), ('dwExtraInfo', ctypes.c_size_t)]
        class Hardware(ctypes.Structure):
            _fields_ = [('uMsg', w.DWORD), ('wParamL', w.WORD), ('wParamH', w.WORD)]
        class Payload(ctypes.Union):
            _fields_ = [('mi', Mouse), ('ki', Keyboard), ('hi', Hardware)]
        class Input(ctypes.Structure):
            _anonymous_ = ('payload',)
            _fields_ = [('type', w.DWORD), ('payload', Payload)]
        self.Input = Input
        self.user.SendInput.argtypes = [w.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user.SendInput.restype = w.UINT

    def now(self):
        return time.time()

    @contextmanager
    def dpi_context(self):
        previous = self.user.SetThreadDpiAwarenessContext(-4)
        if not previous:
            raise OSError(ctypes.get_last_error(), 'Cannot establish per-monitor physical-pixel coordinates')
        try:
            yield
        finally:
            if not self.user.SetThreadDpiAwarenessContext(previous):
                raise OSError(ctypes.get_last_error(), 'Cannot restore previous thread DPI context')

    def sleep(self, seconds):
        time.sleep(seconds)

    def _process(self, pid, fingerprint=True):
        w = self.w
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise OSError(ctypes.get_last_error(), 'Cannot query game process')
        try:
            name, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
                raise OSError(ctypes.get_last_error(), 'Cannot query game image')
            times = [w.FILETIME() for _ in range(4)]
            if not self.kernel.GetProcessTimes(handle, *(ctypes.byref(x) for x in times)):
                raise OSError(ctypes.get_last_error(), 'Cannot query game process creation')
            status = w.DWORD()
            if not self.kernel.GetExitCodeProcess(handle, ctypes.byref(status)) or status.value != 259:
                raise ValueError('Game process is no longer running')
            result = {'executable': name.value, 'processCreated': str(times[0].dwLowDateTime | times[0].dwHighDateTime << 32)}
            if fingerprint:
                result['sha256'] = _digest(name.value)
            return result
        finally:
            self.kernel.CloseHandle(handle)

    def _windows(self):
        result = []
        @self.enum_callback
        def collect(hwnd, unused):
            pid = self.w.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            result.append((int(hwnd), pid.value))
            return True
        if not self.user.EnumWindows(collect, 0):
            raise OSError(ctypes.get_last_error(), 'Cannot enumerate windows')
        return result

    def _class(self, hwnd):
        text = ctypes.create_unicode_buffer(256)
        if not self.user.GetClassNameW(hwnd, text, 256):
            raise OSError(ctypes.get_last_error(), 'Cannot query window class')
        return text.value

    def snapshot(self, pid, hwnd):
        w = self.w
        if not self.user.IsWindow(hwnd):
            raise ValueError('Game HWND no longer exists')
        owner = w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or self.user.GetAncestor(hwnd, 2) != hwnd:
            raise ValueError('Game HWND does not belong to the requested top-level process')
        process = self._process(pid)
        title = ctypes.create_unicode_buffer(self.user.GetWindowTextLengthW(hwnd) + 1)
        self.user.GetWindowTextW(hwnd, title, len(title))
        rect, client = w.RECT(), w.RECT()
        if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)) or not self.user.GetClientRect(hwnd, ctypes.byref(client)):
            raise OSError(ctypes.get_last_error(), 'Cannot query game geometry')
        game_rect = [rect.left, rect.top, rect.right, rect.bottom]
        auxiliary = []
        for handle, process_id in self._windows():
            if process_id != pid or handle == hwnd or not self.user.IsWindowVisible(handle):
                continue
            window_class = self._class(handle)
            other_rect = w.RECT()
            if not self.user.GetWindowRect(handle, ctypes.byref(other_rect)):
                raise OSError(ctypes.get_last_error(), 'Cannot query auxiliary game window geometry')
            ctypes.set_last_error(0)
            exstyle = self.window_long(handle, -20)
            error = ctypes.get_last_error()
            if not exstyle and error:
                raise OSError(error, 'Cannot query auxiliary game window extended style')
            auxiliary.append({'hwnd': handle, 'class': window_class,
                              'enabled': bool(self.user.IsWindowEnabled(handle)),
                              'rect': [other_rect.left, other_rect.top, other_rect.right, other_rect.bottom],
                              'exstyle': int(exstyle)})
        classified = classify_auxiliary_windows(auxiliary, game_rect)
        return {'pid': pid, 'hwnd': hwnd, 'class': self._class(hwnd), 'title': title.value,
                'rect': game_rect,
                'clientSize': [client.right - client.left, client.bottom - client.top],
                'clientOrigin': self.client_to_screen(hwnd, 0, 0),
                'visible': bool(self.user.IsWindowVisible(hwnd)), 'enabled': bool(self.user.IsWindowEnabled(hwnd)),
                'minimized': bool(self.user.IsIconic(hwnd)), **classified, **process}

    def enumerate_targets(self):
        processes, targets = {}, []
        for hwnd, pid in self._windows():
            if pid not in processes:
                try:
                    processes[pid] = self._process(pid, fingerprint=False)
                except (OSError, ValueError):
                    processes[pid] = None
            process = processes[pid]
            if process and _same_path(process['executable'], EXECUTABLE) and self._class(hwnd) == 'TfrmMain':
                targets.append(self.snapshot(pid, hwnd))
        return targets

    def foreground(self):
        return int(self.user.GetForegroundWindow() or 0)

    def cursor(self):
        point = self.w.POINT()
        if not self.user.GetCursorPos(ctypes.byref(point)):
            raise OSError(ctypes.get_last_error(), 'Cannot read cursor position')
        return [point.x, point.y]

    def activate(self, hwnd):
        if not self.user.IsWindow(hwnd):
            raise ValueError('Cannot activate a missing window')
        self.user.SetForegroundWindow(hwnd)
        if self.foreground() == hwnd:
            return
        current = self.kernel.GetCurrentThreadId()
        foreground = self.foreground()
        targets = {self.user.GetWindowThreadProcessId(hwnd, None)}
        if foreground:
            targets.add(self.user.GetWindowThreadProcessId(foreground, None))
        attached = []
        try:
            self.assert_input_idle()
            for thread in sorted(targets - {0, current}):
                if not self.user.AttachThreadInput(current, thread, True):
                    raise OSError(ctypes.get_last_error(), 'Cannot attach foreground input queues')
                attached.append(thread)
            self.user.BringWindowToTop(hwnd)
            self.user.SetForegroundWindow(hwnd)
        finally:
            detach_failed = False
            for thread in reversed(attached):
                if not self.user.AttachThreadInput(current, thread, False):
                    detach_failed = True
            if detach_failed:
                raise OSError('Could not detach foreground input queues')
        if self.foreground() != hwnd:
            raise ValueError('Could not activate the exact game window')

    def restore(self, front, pointer):
        errors = []
        try:
            self.activate(front)
        except Exception as exc:
            errors.append(str(exc))
        try:
            self.move(pointer)
        except Exception as exc:
            errors.append(str(exc))
        result = {'foregroundRestored': self.foreground() == front, 'cursorRestored': self.cursor() == list(pointer)}
        if errors:
            result['errors'] = errors
        return result

    def client_to_screen(self, hwnd, x, y):
        point = self.w.POINT(x, y)
        if not self.user.ClientToScreen(hwnd, ctypes.byref(point)):
            raise OSError(ctypes.get_last_error(), 'Cannot map game client coordinates')
        return [point.x, point.y]

    def root_at(self, point):
        hwnd = self.user.WindowFromPoint(self.w.POINT(*point))
        return int(self.user.GetAncestor(hwnd, 2) or 0) if hwnd else 0

    def move(self, point):
        if not self.user.SetCursorPos(*point):
            raise OSError(ctypes.get_last_error(), 'Cannot position cursor')
        if self.cursor() != list(point):
            raise ValueError('Cursor did not reach the requested location')

    def assert_input_idle(self):
        # Existing modifiers/buttons can convert one harmless action into another.
        if any(self.user.GetAsyncKeyState(vk) & 0x8000 for vk in (1, 2, 4, 5, 6, 0x10, 0x11, 0x12, 0x5B, 0x5C, *KEYS.values())):
            raise ValueError('Release physical mouse buttons and keyboard modifiers first')

    def _send(self, kind, value, release):
        event = self.Input()
        if kind == 'key':
            event.type = 1
            event.ki.wVk = KEYS[value]
            event.ki.dwFlags = 2 if release else 0
        else:
            event.type = 0
            event.mi.dwFlags = {('left', False): 2, ('left', True): 4, ('right', False): 8, ('right', True): 16}[(value, release)]
        if self.user.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise OSError(ctypes.get_last_error(), 'SendInput did not accept the complete event')

    def down(self, kind, value):
        self._send(kind, value, False)

    def up(self, kind, value):
        self._send(kind, value, True)

    def screenshot(self, path, rect):
        from PIL import ImageGrab
        image = ImageGrab.grab(bbox=tuple(rect), all_screens=True)
        if image.size != (rect[2] - rect[0], rect[3] - rect[1]):
            raise ValueError('Desktop screenshot dimensions do not match the game window')
        image.save(path, format='PNG')
