"""Observed, single-action control of version-pinned native engine/editor forms.

This adapter shares the established Win32 desktop boundary, not the game
request contract. UI receipts prove delivery and UI readback, not business saves.
"""
from __future__ import annotations

import ctypes
import json
import re
from contextlib import nullcontext
from pathlib import Path, PureWindowsPath

from .native_game import Win32GameBackend, _digest, _independent, _integer, _same_path, _write_json
from .policy import DEFAULT_PROTECTED_ROOTS, WritePolicy

COMMANDS = ('window-observe', 'window-action')
KEYS = {'HOME': 0x24, 'END': 0x23, 'UP': 0x26, 'DOWN': 0x28, 'LEFT': 0x25,
        'RIGHT': 0x27, 'PAGEUP': 0x21, 'PAGEDOWN': 0x22, 'ENTER': 0x0D,
        'ESC': 0x1B, 'TAB': 0x09, **{f'F{i}': 0x6F+i for i in range(1, 13)}}
IDENTITY_FIELDS = ('pid', 'hwnd', 'class', 'title', 'executable', 'sha256', 'processCreated',
                   'parent', 'owner', 'style', 'hosting', 'rect', 'clientSize', 'clientOrigin', 'visible', 'enabled', 'minimized')
EDIT_CLASSES = {'Edit', 'TEdit', 'TRzEdit', 'TRzMaskEdit', 'TRzButtonEdit', 'TJvInspectorEdit', 'TJvInspectorMemo', 'TSpinEditEx', 'TSpinEdit', 'TMemo', 'TMaskEdit', 'TRichEdit', 'RichEdit20W'}
COMBO_CLASSES = {'ComboBox', 'TComboBox'}
TAB_CLASSES = {'SysTabControl32', 'TPageControl', 'TTabControl'}
BUTTON_CLASSES = {'Button', 'TButton', 'TBitBtn', 'TCheckBox', 'TRadioButton'}
GAMECENTER_HOST_KINDS = {
    'm2server.exe': 'GameCenterHostedM2',
    'loginsrv.exe': 'GameCenterHostedLoginSrv',
    'dbserver.exe': 'GameCenterHostedDBServer',
    'rungate.exe': 'GameCenterHostedRunGate',
    'selgate.exe': 'GameCenterHostedSelGate',
}


def verified_binaries():
    from .native_engine import BINARIES, STACK_BINARIES
    from .native_control import LAUNCHER_SHA256
    from .native_editor import EDITOR_SHA256
    return {'m2server.exe': BINARIES['Mir200/M2Server.exe'],
            'gamecenter.exe': BINARIES['GameCenter.exe'],
            'loginsrv.exe': STACK_BINARIES['LoginSrv/LoginSrv.exe'],
            'dbserver.exe': STACK_BINARIES['DBServer/DBServer.exe'],
            'rungate.exe': STACK_BINARIES['RunGate/RunGate.exe'],
            'selgate.exe': STACK_BINARIES['SelGate/SelGate.exe'],
            'updateserver_x64.exe': '2FE71E3C8ED9FD113A392EBC50D603396412DEBD6DEC6CBCEEFC785646055DE2',
            'mirupdategate.exe': '2F12AB71F0D35D4259F96C2CCBA77F5DC8239BF0B3705654457F59D27CFB26B5',
            'makegamelogin.exe': LAUNCHER_SHA256, 'wzl编辑器.exe': EDITOR_SHA256}


def _text(value, label, *, empty=False):
    if not isinstance(value, str) or ('\x00' in value) or (not empty and not value):
        raise ValueError(label + ' must be exact text')
    return value


def _action(action):
    if not isinstance(action, dict):
        raise ValueError('action must be one object')
    kind = action.get('kind')
    fields = {'show': set(), 'minimize': set(), 'close': {'synchronous'}, 'menu': {'path', 'synchronous'},
              'set-text': {'controlHwnd', 'expectedClass', 'expectedText', 'value'},
              'select-combo': {'controlHwnd', 'expectedClass', 'expectedIndex', 'expectedOptions', 'index'},
              'select-tab': {'controlHwnd', 'expectedClass', 'expectedSelection', 'text'},
              'button': {'controlHwnd', 'expectedClass', 'expectedText', 'expectedCheck', 'synchronous'},
              'visual-click': {'x', 'y', 'button', 'holdMs'}, 'key': {'key', 'holdMs'}}
    if kind not in fields or set(action) - (fields[kind] | {'kind', 'settleMs'}):
        raise ValueError('Unsupported single native action or unexpected action fields')
    result = dict(action)
    result['settleMs'] = _integer(action.get('settleMs', 400), 'settleMs', 0, 3000)
    if kind in ('set-text', 'select-combo', 'select-tab', 'button'):
        _integer(action.get('controlHwnd'), 'controlHwnd', 1, (1 << 64)-1)
        cls = _text(action.get('expectedClass'), 'expectedClass')
        allowed = {'set-text': EDIT_CLASSES, 'select-combo': COMBO_CLASSES,
                   'select-tab': TAB_CLASSES, 'button': BUTTON_CLASSES}[kind]
        if cls not in allowed:
            raise ValueError('Control class does not support the requested native action')
    if kind in ('set-text', 'button'):
        _text(action.get('expectedText'), 'expectedText', empty=True)
    if kind == 'set-text':
        _text(action.get('value'), 'value', empty=True)
        if len(action['value']) > 65535:
            raise ValueError('Edit value is too long')
    if kind == 'select-combo':
        _integer(action.get('index'), 'index', 0, 65535)
        _integer(action.get('expectedIndex'), 'expectedIndex', -1, 65535)
        options = action.get('expectedOptions')
        if not isinstance(options, list) or not options or any(not isinstance(x, str) for x in options):
            raise ValueError('expectedOptions must be exact nonempty option list')
        if action['index'] >= len(options):
            raise ValueError('index exceeds expectedOptions')
    if kind == 'select-tab':
        _text(action.get('expectedSelection'), 'expectedSelection', empty=True)
        _text(action.get('text'), 'text')
    if kind == 'button' and 'expectedCheck' in action:
        _integer(action['expectedCheck'], 'expectedCheck', 0, 2)
    if kind == 'menu':
        path = action.get('path')
        if not isinstance(path, list) or not path or len(path) > 16 or any(not isinstance(x, str) or not x for x in path):
            raise ValueError('Menu path must be the complete caption array')
    if kind in ('menu', 'button', 'close'):
        result['synchronous'] = action.get('synchronous', kind == 'button')
        if not isinstance(result['synchronous'], bool):
            raise ValueError('synchronous must be boolean')
    if kind in ('key', 'visual-click'):
        result['holdMs'] = _integer(action.get('holdMs', 60), 'holdMs', 0, 1000)
    if kind == 'key' and action.get('key') not in KEYS:
        raise ValueError('Unsupported single native key')
    if kind == 'visual-click':
        _integer(action.get('x'), 'x', 0, 65535)
        _integer(action.get('y'), 'y', 0, 65535)
        result['button'] = action.get('button', 'left')
        if result['button'] not in ('left', 'right'):
            raise ValueError('Only left/right visual clicks are supported')
    return result


def validate_request(request):
    if not isinstance(request, dict) or request.get('schemaVersion') != 1 or request.get('command') not in COMMANDS:
        raise ValueError('Unknown native window command or schemaVersion')
    args = request.get('arguments')
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    _integer(args.get('pid'), 'pid', 1, 0xFFFFFFFF)
    _integer(args.get('hwnd'), 'hwnd', 1, (1 << 64)-1)
    executable = _text(args.get('expectedExecutable'), 'expectedExecutable')
    if not PureWindowsPath(executable).is_absolute():
        raise ValueError('expectedExecutable must be absolute')
    digest = verified_binaries().get(PureWindowsPath(executable).name.casefold())
    if digest is None or str(args.get('expectedSha256', '')).upper() != digest:
        raise PermissionError('Only version-pinned original M2/LoginSrv/DBServer/RunGate/SelGate/GameCenter/UpdateServer_x64/MirUpdateGate/launcher/editor binaries are supported')
    _text(args.get('expectedClass'), 'expectedClass')
    _text(args.get('expectedTitle'), 'expectedTitle', empty=True)
    if not args.get('outputRoot'):
        raise ValueError('outputRoot is required')
    output = _independent(args['outputRoot'])
    policy = WritePolicy(request.get('policy', {}).get('allowedWriteRoots', []),
                         protected_roots=(*DEFAULT_PROTECTED_ROOTS, Path(executable).parent))
    policy.assert_writable(output)
    if output.exists():
        raise FileExistsError('outputRoot must be a new independent directory')
    plan = {'command': request['command'], 'arguments': dict(args), 'output': output}
    if request['command'] == 'window-action':
        if not args.get('observationReceipt'):
            raise ValueError('observationReceipt is required')
        receipt = _independent(args['observationReceipt'])
        if not receipt.is_file() or receipt.stat().st_size > 16*1024*1024:
            raise ValueError('observationReceipt must be an existing bounded JSON file')
        policy.assert_writable(receipt)
        if not re.fullmatch('[0-9a-fA-F]{64}', str(args.get('observationSha256', ''))):
            raise ValueError('observationSha256 is required')
        plan.update(receipt=receipt, action=_action(args.get('action')))
    return plan


def _check_target(target, args):
    if not isinstance(target, dict) or any(key not in target for key in IDENTITY_FIELDS):
        raise ValueError('Incomplete live native window identity')
    expected = {'pid': args['pid'], 'hwnd': args['hwnd'], 'class': args['expectedClass'], 'title': args['expectedTitle']}
    if any(target[k] != v for k, v in expected.items()):
        raise ValueError('Native process/window identity changed')
    if not _same_path(target['executable'], args['expectedExecutable']) or target['sha256'].upper() != args['expectedSha256'].upper():
        raise PermissionError('Native executable fingerprint changed')
    if not isinstance(target['processCreated'], str) or not target['processCreated'].isdigit():
        raise ValueError('Process creation identity is missing')
    for key, size in (('rect', 4), ('clientSize', 2), ('clientOrigin', 2)):
        value = target[key]
        if not isinstance(value, list) or len(value) != size or any(isinstance(x, bool) or not isinstance(x, int) for x in value):
            raise ValueError('Native window geometry is invalid')
    if target['visible'] and not target['minimized'] and (target['rect'][2] <= target['rect'][0] or target['rect'][3] <= target['rect'][1] or min(target['clientSize']) <= 0):
        raise ValueError('Visible native window geometry is invalid')
    _check_hosting(target)
    return target



def _hidden_after_action(previous, observed):
    """Validate metadata for this request's previously verified, now hidden form.

    This never changes ordinary form eligibility and never returns input authority.
    A matching HWND has no independently queryable window-creation generation.
    """
    if (not previous.get('visible') or previous.get('hosting') is not None or previous.get('textTruncated') or
            previous.get('style', 0) & 0x40000000 or
            observed.get('visible') is not False or observed.get('style', 0) & 0x40000000 or
            observed.get('rootHwnd') != previous['hwnd'] or observed.get('textTruncated')):
        raise ValueError('Post-action hidden form lifecycle is not verified')
    fields = ('pid', 'hwnd', 'class', 'title', 'parent', 'owner', 'processCreated')
    if any(observed.get(key) != previous.get(key) for key in fields):
        raise ValueError('Post-action form identity or ancestry changed')
    if (not _same_path(observed.get('executable', ''), previous['executable']) or
            str(observed.get('sha256', '')).upper() != previous['sha256'].upper() or
            (observed['style'] & ~0x10000000) != (previous['style'] & ~0x10000000)):
        raise PermissionError('Post-action process fingerprint or form style changed')
    return {'state': 'hidden', 'hwnd': previous['hwnd'], 'exists': True, 'visible': False,
            'postActionOnly': True, 'identity': observed,
            'claim': 'Matching identity fields at both samples; HWND exists and is hidden.'}


def _check_hosting(target):
    host = target.get('hosting')
    if host is None:
        return
    binaries = verified_binaries()
    name = PureWindowsPath(target['executable']).name.casefold()
    kind = GAMECENTER_HOST_KINDS.get(name)
    expected_host = PureWindowsPath(target['executable']).parent.parent / 'GameCenter.exe'
    if (kind is None or not isinstance(host, dict) or host.get('kind') != kind or
            host.get('class') not in ('TfrmMain', 'TFrmMain') or not _same_path(host.get('executable', ''), expected_host) or
            str(host.get('sha256', '')).upper() != binaries['gamecenter.exe']):
        raise PermissionError('Embedded native component requires the verified GameCenter from the same engine root')
    if not isinstance(host.get('processCreated'), str) or not host['processCreated'].isdigit():
        raise ValueError('GameCenter host process creation identity is missing')
    chain = host.get('ancestorChain')
    if (not isinstance(chain, list) or not 2 <= len(chain) <= 64 or
            chain[0].get('hwnd') != target['hwnd'] or chain[-1].get('hwnd') != host.get('rootHwnd') or
            chain[-1].get('pid') != host.get('pid') or chain[0].get('pid') != target['pid'] or
            any(item.get('pid') not in (target['pid'], host['pid']) for item in chain) or
            any(item.get('parent') != chain[index+1].get('hwnd') for index,item in enumerate(chain[:-1]))):
        raise ValueError('GameCenter host ancestor chain is incomplete or changed')
    if chain[0].get('style') != target['style'] or chain[0].get('class') != target['class']:
        raise ValueError('GameCenter host leaf identity changed')


def _usable(target):
    if not target['visible'] or not target['enabled'] or target['minimized']:
        raise ValueError('Native target must be visible, enabled and restored')
    if target.get('blockingWindows'):
        raise ValueError('An owned native modal blocks this target; observe the modal itself')
    host = target.get('hosting')
    if host and (not host.get('visible') or not host.get('enabled') or host.get('minimized')):
        raise ValueError('Verified GameCenter host must be visible, enabled and restored')


def _control_style_identity(control):
    style = control.get('style')
    if (control.get('class') in ('Button', 'TButton', 'TBitBtn') and
            isinstance(style, int) and not isinstance(style, bool) and style & 0xF in (0, 1)):
        # Native dialog focus changes BS_PUSHBUTTON <-> BS_DEFPUSHBUTTON.
        # Only this default marker is transient; every other type/WS bit stays bound.
        return style & ~1
    return style


def _receipt(plan, target, now):
    if _digest(plan['receipt']) != plan['arguments']['observationSha256'].upper():
        raise ValueError('Observation receipt SHA256 changed')
    data = json.loads(plan['receipt'].read_text('utf-8'))
    recovery = data.get('recovery', {})
    if data.get('command') not in COMMANDS or recovery.get('error') or recovery.get('errors') or not all(recovery.get(k) for k in ('foregroundRestored', 'cursorRestored')):
        raise ValueError('A recovered native observation is required')
    before = data.get('target')
    if not isinstance(before, dict) or any(before.get(k) != target[k] for k in IDENTITY_FIELDS):
        raise ValueError('Native process/window/geometry/visibility changed since observation')
    action = plan['action']
    _precondition(before, action)
    if 'controlHwnd' in action:
        old = [x for x in before.get('controls', []) if x['hwnd'] == action['controlHwnd']]
        new = [x for x in target.get('controls', []) if x['hwnd'] == action['controlHwnd']]
        fields = ('hwnd', 'class', 'parent', 'owner', 'rect', 'visible', 'enabled')
        if (len(old) != 1 or len(new) != 1 or any(old[0].get(k) != new[0].get(k) for k in fields) or
                _control_style_identity(old[0]) != _control_style_identity(new[0])):
            raise ValueError('Control identity, parent, owner, geometry or availability changed since observation')
    when = data.get('observedAtUnix')
    if isinstance(when, bool) or not isinstance(when, (float, int)) or not 0 <= now-when <= 120:
        raise ValueError('Observation must be no older than 120 seconds and not from the future')
    shot = data.get('screenshot')
    if shot is None:
        if plan['action']['kind'] != 'show':
            raise ValueError('Only show may consume a hidden native observation')
    else:
        image = _independent(shot.get('path', ''))
        if not image.is_relative_to(plan['receipt'].parent) or not image.is_file() or _digest(image) != shot.get('sha256'):
            raise ValueError('Observation screenshot changed or is missing')
    return data


def _precondition(target, action):
    kind = action['kind']
    if kind == 'minimize':
        style = target.get('style')
        required = 0x80000 | 0xC00000 | 0x20000  # WS_SYSMENU, full WS_CAPTION, WS_MINIMIZEBOX.
        if type(style) is not int or style & required != required:
            raise ValueError('Native form does not expose the required minimize window styles')
    if kind == 'menu':
        matches = [x for x in target.get('menus', []) if x['path'] == action['path']]
        if len(matches) != 1 or not matches[0].get('enabled') or not matches[0].get('id'):
            raise ValueError('Full native menu path is unavailable, disabled or ambiguous')
    if 'controlHwnd' not in action:
        return
    matches = [x for x in target.get('controls', []) if x['hwnd'] == action['controlHwnd']]
    if len(matches) != 1:
        raise ValueError('Control is not a unique descendant of the selected native form')
    control = matches[0]
    if control['class'] != action['expectedClass'] or not control['visible'] or not control['enabled']:
        raise ValueError('Control class, visibility or enabled state changed')
    if 'expectedText' in action and control['text'] != action['expectedText']:
        raise ValueError('Control text changed')
    if kind == 'set-text' and control.get('textTruncated'):
        raise ValueError('Cannot overwrite an edit field whose observation is truncated')
    if kind == 'select-combo' and (control.get('options') != action['expectedOptions'] or control.get('selectedIndex') != action['expectedIndex']):
        raise ValueError('Combo options or selection changed')
    if kind == 'select-tab' and (control.get('selectedText') != action['expectedSelection'] or control.get('tabs', []).count(action['text']) != 1):
        raise ValueError('Tab selection changed or target caption is ambiguous')
    if kind == 'select-tab' and control.get('style', 0) & 0x100:
        raise ValueError('Native button-style tab requires an observed visual click')
    if 'expectedCheck' in action and control.get('check') != action['expectedCheck']:
        raise ValueError('Checkbox state changed')


def _guard(backend, target, point, *, require_membership=False, evidence=None, stage=None):
    if evidence is not None:
        evidence.update(stage=stage, pointScreen=list(point), targetHwnd=target['hwnd'], targetRootHwnd=None,
                        clientOrigin=list(target['clientOrigin']), clientSize=list(target['clientSize']),
                        requireMembership=require_membership, firstFailedCheck=None,
                        foregroundBefore=None, pointRoot=None, foregroundAfter=None)
    root = backend.root(target['hwnd'])
    if evidence is not None:
        evidence['targetRootHwnd'] = root
    foreground_before = backend.foreground()
    if evidence is not None:
        evidence['foregroundBefore'] = foreground_before
    if foreground_before != root:
        if evidence is not None:
            evidence['firstFailedCheck'] = 'foregroundBefore'
        raise ValueError('Native focus or point ownership changed')
    point_root = backend.root_at(point)
    if evidence is not None:
        evidence['pointRoot'] = point_root
    if point_root != root:
        if evidence is not None:
            evidence['firstFailedCheck'] = 'pointRoot'
        raise ValueError('Native focus or point ownership changed')
    foreground_after = backend.foreground()
    if evidence is not None:
        evidence['foregroundAfter'] = foreground_after
    if foreground_after != root:
        if evidence is not None:
            evidence['firstFailedCheck'] = 'foregroundAfter'
        raise ValueError('Native focus or point ownership changed')
    if not backend.observation_point_in_form(target['hwnd'], point):
        if evidence is not None:
            evidence['firstFailedCheck'] = 'observationMembership'
        raise ValueError('Point ancestor chain does not reach the selected native form')
    if require_membership and not backend.point_in_form(target['hwnd'], point):
        if evidence is not None:
            evidence['firstFailedCheck'] = 'inputMembership'
        raise ValueError('Point belongs to the host or another native form, not the selected form')


def _readback(target, action):
    if action['kind'] not in ('set-text', 'select-combo', 'select-tab'):
        return False
    controls = [] if target is None else [x for x in target.get('controls', []) if x['hwnd'] == action['controlHwnd']]
    if len(controls) != 1 or controls[0]['class'] != action['expectedClass']:
        raise ValueError('Desired control readback unavailable; action state is unknown')
    control = controls[0]
    key, desired = {'set-text': ('text', action.get('value')),
                    'select-combo': ('selectedIndex', action.get('index')),
                    'select-tab': ('selectedText', action.get('text'))}[action['kind']]
    if control.get(key) != desired or (key == 'text' and control.get('textTruncated')):
        raise ValueError('Desired control readback does not match the requested value')
    return True


def _verify_minimized(previous, current):
    """Verify this exact form minimized while its verified host stayed intact."""
    if (not isinstance(current, dict) or current.get('minimized') is not True or
            not current.get('style', 0) & 0x20000000 or current.get('blockingWindows')):
        raise ValueError('Native minimize readback is unavailable or did not remain minimized')
    fields = ('pid', 'hwnd', 'class', 'title', 'processCreated', 'parent', 'owner', 'visible', 'enabled')
    if any(previous.get(key) != current.get(key) for key in fields):
        raise ValueError('Native form identity changed during minimize')
    if (not _same_path(previous['executable'], current.get('executable', '')) or
            previous['sha256'].upper() != str(current.get('sha256', '')).upper() or
            (previous['style'] ^ current['style']) & ~0x20000000):
        raise PermissionError('Native process fingerprint or unrelated form style changed during minimize')
    before_host, after_host = previous.get('hosting'), current.get('hosting')
    if before_host is None:
        if after_host is not None:
            raise ValueError('Native form acquired a host during minimize')
        return True
    if (not isinstance(after_host, dict) or after_host.get('minimized') is not False or
            not after_host.get('visible') or not after_host.get('enabled') or
            {k:v for k,v in before_host.items() if k != 'ancestorChain'} !=
            {k:v for k,v in after_host.items() if k != 'ancestorChain'}):
        raise ValueError('Verified native host changed or minimized with its component')
    before_chain, after_chain = before_host['ancestorChain'], after_host.get('ancestorChain')
    if (not isinstance(after_chain, list) or len(before_chain) != len(after_chain) or
            before_chain[1:] != after_chain[1:] or
            {k:v for k,v in before_chain[0].items() if k not in ('style', 'rect')} !=
            {k:v for k,v in after_chain[0].items() if k not in ('style', 'rect')} or
            (before_chain[0]['style'] ^ after_chain[0]['style']) & ~0x20000000):
        raise ValueError('Native component ancestor identity changed during minimize')
    return True


def _tab_item_type(bits):
    if bits not in (32, 64):
        raise ValueError('Unsupported native target pointer width')
    pointer = ctypes.c_uint32 if bits == 32 else ctypes.c_uint64
    signed_pointer = ctypes.c_int32 if bits == 32 else ctypes.c_int64
    class TabItem(ctypes.Structure):
        _fields_ = [('mask', ctypes.c_uint32), ('dwState', ctypes.c_uint32), ('dwStateMask', ctypes.c_uint32),
                    ('pszText', pointer), ('cchTextMax', ctypes.c_int32), ('iImage', ctypes.c_int32), ('lParam', signed_pointer)]
    return TabItem


def run_window(request, backend=None):
    plan = validate_request(request)
    real = backend is None
    backend = Win32WindowBackend() if real else backend
    if real:
        from .native_engine import serial_engine_operation
        lock, dpi = serial_engine_operation(), backend.dpi_context()
    else:
        lock, dpi = nullcontext(), nullcontext()
    with dpi, lock:
        return _run(plan, backend)


def _run(plan, backend):
    args, output = plan['arguments'], plan['output']
    output.mkdir(parents=True, exist_ok=False)
    front, pointer = backend.foreground(), backend.cursor()
    data, error, attempted, dispatch = None, None, False, None
    lifecycle = None
    recovery = {'foregroundRestored': False, 'cursorRestored': False}
    guard_evidence = {'stage': None, 'firstFailedCheck': None, 'pointScreen': None,
                      'targetHwnd': None, 'targetRootHwnd': None, 'clientOrigin': None, 'clientSize': None,
                      'requireMembership': None, 'foregroundBefore': None, 'pointRoot': None, 'foregroundAfter': None,
                      'requestedClientPoint': ([plan['action']['x'], plan['action']['y']]
                                               if plan.get('action', {}).get('kind') == 'visual-click' else None),
                      'pointerMoveAttempted': False, 'pointerMoveVerified': False}
    try:
        target = _check_target(backend.snapshot(args['pid'], args['hwnd']), args)
        action = plan.get('action')
        if action:
            _receipt(plan, target, backend.now())
            if backend.root(target['hwnd']) != target['hwnd'] and not target.get('hosting'):
                raise ValueError('Child native form input needs a proven form-specific focus adapter; root ancestry is insufficient')
            if action['kind'] == 'show' and target.get('hosting') and not target['visible']:
                raise ValueError('Select the target host page in verified GameCenter before controlling the embedded native component')
            if action['kind'] != 'show':
                _usable(target)
            _precondition(target, action)
            if action['kind'] == 'minimize' and front == target['hwnd']:
                raise ValueError('Cannot minimize the original foreground target while preserving foreground recovery')
        if target['visible'] and target['enabled'] and not target['minimized'] and not target.get('blockingWindows'):
            backend.assert_input_idle()
            backend.activate(backend.root(target['hwnd']))
            point = backend.client_to_screen(target['hwnd'], target['clientSize'][0]//2, target['clientSize'][1]//2)
            _guard(backend, target, point, evidence=guard_evidence, stage='initial-center')
        if action:
            fresh = _check_target(backend.snapshot(args['pid'], args['hwnd']), args)
            _receipt(plan, fresh, backend.now())
            _precondition(fresh, action)
            if action['kind'] != 'show':
                _usable(fresh)
                _guard(backend, fresh, point, evidence=guard_evidence, stage='fresh-center')
            elif not fresh['enabled'] or fresh.get('blockingWindows'):
                raise ValueError('Cannot show a disabled native window blocked by a modal')
            backend.assert_input_idle()
            if action['kind'] in ('key', 'visual-click'):
                if action['kind'] == 'key' and not backend.focus_in_form(target['hwnd']):
                    raise ValueError('Keyboard focus belongs to the host or another form')
                if action['kind'] == 'visual-click':
                    if action['x'] >= target['clientSize'][0] or action['y'] >= target['clientSize'][1]:
                        raise ValueError('Visual action is outside the native client area')
                    point = backend.client_to_screen(target['hwnd'], action['x'], action['y'])
                    _guard(backend, target, point, require_membership=True, evidence=guard_evidence, stage='pre-move')
                    guard_evidence['pointerMoveAttempted'] = True
                    backend.move(point)
                    guard_evidence['pointerMoveVerified'] = True
                _guard(backend, target, point, require_membership=action['kind'] == 'visual-click',
                       evidence=guard_evidence, stage='post-move' if action['kind'] == 'visual-click' else 'pre-input')
                backend.assert_input_idle()
                kind, value = ('key', action['key']) if action['kind'] == 'key' else ('mouse', action['button'])
                attempted = True
                try:
                    backend.down(kind, value)
                    backend.sleep(action['holdMs']/1000)
                finally:
                    # SendInput release is independent of a dialog that Enter may close.
                    backend.up(kind, value)
                dispatch = {'mode': 'SendInput', 'accepted': True, 'handlerAcknowledged': False}
            else:
                if 'controlHwnd' in action and not backend.control_in_form(action['controlHwnd'], fresh['hwnd']):
                    raise ValueError('Control process/ancestor no longer belongs to the selected native form')
                attempted = True
                dispatch = backend.dispatch(fresh, action)
            backend.sleep(action['settleMs']/1000)
        forms = backend.native_forms(args['pid'])
        target_closed = not backend.exists(args['hwnd'])
        if target_closed:
            target = None
            lifecycle = {'state': 'destroyed', 'hwnd': args['hwnd'], 'exists': False, 'visible': False}
        elif action and attempted and not any(form['hwnd'] == args['hwnd'] for form in forms):
            lifecycle = backend.post_action_lifecycle(fresh)
            target = None  # Hidden outcome metadata must not authorize another input.
        else:
            target = _check_target(backend.snapshot(args['pid'], args['hwnd']), args)
            lifecycle = {'state': 'visible' if target['visible'] else 'hidden', 'hwnd': args['hwnd'],
                         'exists': True, 'visible': target['visible'], 'postActionOnly': False}
        if action and action['kind'] == 'minimize':
            _verify_minimized(fresh, target)
            lifecycle = {'state': 'minimized', 'hwnd': args['hwnd'], 'exists': True,
                         'visible': target['visible'], 'postActionOnly': False}
            readback_verified = True
        else:
            readback_verified = _readback(target, action) if action else False
        screenshot = None
        # Unknown/new dialogs are captured in forms and never automatically confirmed.
        capture = target
        if target is None or not target['visible'] or not target['enabled'] or target.get('blockingWindows'):
            candidates = [x for x in forms if x.get('visible') and x.get('enabled')]
            current = next((x for x in candidates if backend.root(x['hwnd']) == backend.foreground()), None)
            if current and current['hwnd'] != args['hwnd']:
                capture = backend.snapshot(args['pid'], current['hwnd'])
            else:
                capture = None
        if capture and capture.get('visible') and not capture.get('minimized'):
            _usable(capture)
            capture_point = backend.client_to_screen(capture['hwnd'], capture['clientSize'][0]//2, capture['clientSize'][1]//2)
            _guard(backend, capture, capture_point, evidence=guard_evidence, stage='capture-before')
            image = output/'window.png'
            captured_at = backend.now()
            backend.screenshot(image, capture['rect'])
            after_capture = backend.snapshot(args['pid'], capture['hwnd'])
            if any(after_capture.get(k) != capture.get(k) for k in IDENTITY_FIELDS):
                raise ValueError('Native window identity or geometry changed during capture')
            _guard(backend, after_capture, capture_point, evidence=guard_evidence, stage='capture-after')
            screenshot = {'path': str(image), 'sha256': _digest(image), 'capturedAtUnix': captured_at, 'hwnd': capture['hwnd']}
        data = {'command': plan['command'], 'outputRoot': str(output), 'target': target, 'targetClosed': target_closed,
                'forms': forms, 'screenshot': screenshot, 'observedAtUnix': screenshot['capturedAtUnix'] if screenshot else backend.now(),
                'actionAttempted': attempted, 'dispatch': dispatch, 'readbackVerified': readback_verified,
                'businessSaveVerified': False, 'targetLifecycle': lifecycle,
                'continuation': {'requiresFreshObservation': target is None,
                    'candidateForms': [dict(pid=args['pid'], **{key: form[key] for key in ('hwnd', 'class', 'title', 'visible', 'enabled')})
                                       for form in forms if form.get('enabled') and (form.get('visible') or form.get('class', '').casefold() == 'tfrmmain')] if target is None else []}}
    except BaseException as exc:
        error = exc
        data = {'command': plan['command'], 'outputRoot': str(output), 'actionAttempted': attempted,
                'error': str(exc), 'dispatch': dispatch, 'targetLifecycle': lifecycle or {'state': 'unknown'}}
        if getattr(exc, 'retainedRemoteBuffer', None):
            data['retainedRemoteBuffer'] = exc.retainedRemoteBuffer
        try:
            data['forms'] = backend.native_forms(args['pid'])
            selected = next((x for x in data['forms'] if x.get('visible') and x.get('enabled') and backend.root(x['hwnd']) == backend.foreground()), None)
            if selected and selected.get('rect'):
                # A failed observation must not repeat the failing control
                # query merely to capture diagnostic desktop pixels.
                image = output/'failure-window.png'; backend.screenshot(image, selected['rect'])
                data['screenshot'] = {'path': str(image), 'sha256': _digest(image), 'capturedAtUnix': backend.now(), 'hwnd': selected['hwnd'], 'diagnosticOnly': True}
        except BaseException as capture_error:
            data['captureError'] = str(capture_error)
    finally:
        try:
            recovery = backend.restore(front, pointer)
            if not backend.exists(front):
                recovery['foregroundRestored'] = False
        except BaseException as restore_error:
            recovery['error'] = str(restore_error)
        if error is None and plan.get('action', {}).get('kind') == 'minimize':
            try:
                restored_target = _check_target(backend.snapshot(args['pid'], args['hwnd']), args)
                _verify_minimized(fresh, restored_target)
            except BaseException as minimize_error:
                error = minimize_error
                data['error'] = str(minimize_error)
                data['readbackVerified'] = False
        data['recovery'] = recovery
    if (recovery.get('error') or recovery.get('errors') or not all(recovery.get(k) for k in ('foregroundRestored', 'cursorRestored'))) and error is None:
        error = RuntimeError('Could not restore original foreground and cursor')
        data['error'] = str(error)
    if error is not None:
        data['guardEvidence'] = guard_evidence
        _write_json(output/'failure.json', data)
        raise error
    receipt = output/'observation.json'
    _write_json(receipt, data)
    return dict(data, observationReceipt=str(receipt), observationSha256=_digest(receipt))


class Win32WindowBackend(Win32GameBackend):
    """Native forms, controls and menu messages layered on the shared Win32 boundary."""
    def __init__(self):
        super().__init__()
        w = self.w
        declarations = {
            'EnumChildWindows': ([w.HWND, self.enum_callback, w.LPARAM], w.BOOL),
            'GetParent': ([w.HWND], w.HWND), 'GetWindow': ([w.HWND, w.UINT], w.HWND),
            'GetDlgCtrlID': ([w.HWND], ctypes.c_int),
            'GetMenu': ([w.HWND], w.HMENU), 'GetMenuItemCount': ([w.HMENU], ctypes.c_int),
            'GetSubMenu': ([w.HMENU, ctypes.c_int], w.HMENU),
            'GetMenuItemID': ([w.HMENU, ctypes.c_int], w.UINT),
            'GetMenuStringW': ([w.HMENU, w.UINT, w.LPWSTR, ctypes.c_int, w.UINT], ctypes.c_int),
            'GetMenuState': ([w.HMENU, w.UINT, w.UINT], w.UINT),
            'PostMessageW': ([w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
            'SendMessageTimeoutW': ([w.HWND, w.UINT, w.WPARAM, w.LPARAM, w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)], ctypes.c_ssize_t),
            'ShowWindow': ([w.HWND, ctypes.c_int], w.BOOL),
            'IsWindowUnicode': ([w.HWND], w.BOOL),
            'PeekMessageW': ([ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT], w.BOOL),
        }
        for name, (args, result) in declarations.items():
            fn = getattr(self.user, name); fn.argtypes, fn.restype = args, result

    def exists(self, hwnd): return bool(self.user.IsWindow(hwnd))

    def activate(self, hwnd):
        # AttachThreadInput requires the calling thread to own a message queue.
        # An empty PM_NOREMOVE PeekMessage creates it without consuming messages.
        message = self.w.MSG()
        self.user.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        return super().activate(hwnd)

    def root(self, hwnd):
        return int(self.user.GetAncestor(hwnd, 2) or 0)

    def root_at(self, point):
        return self.root(self.user.WindowFromPoint(self.w.POINT(*point)))

    def _inside(self, child, target, *, same_process=True):
        target_pid = self.w.DWORD()
        self.user.GetWindowThreadProcessId(target, ctypes.byref(target_pid))
        handle, seen = int(child or 0), set()
        while handle and handle not in seen:
            current_pid = self.w.DWORD()
            self.user.GetWindowThreadProcessId(handle, ctypes.byref(current_pid))
            if same_process and (not target_pid.value or current_pid.value != target_pid.value):
                return False
            if handle == target:
                return True
            seen.add(handle)
            # GA_PARENT follows actual SetParent links; GetParent follows an
            # owner for some non-WS_CHILD Delphi embedded windows instead.
            handle = int(self.user.GetAncestor(handle, 1) or 0)
        return False

    def point_in_form(self, hwnd, point):
        return self._inside(self.user.WindowFromPoint(self.w.POINT(*point)), hwnd)

    def observation_point_in_form(self, hwnd, point):
        return self._inside(self.user.WindowFromPoint(self.w.POINT(*point)), hwnd, same_process=False)

    def control_in_form(self, control, hwnd):
        return self._inside(control, hwnd)

    def focus_in_form(self, hwnd):
        w = self.w
        class GuiThreadInfo(ctypes.Structure):
            _fields_ = [('cbSize', w.DWORD), ('flags', w.DWORD), ('hwndActive', w.HWND),
                        ('hwndFocus', w.HWND), ('hwndCapture', w.HWND), ('hwndMenuOwner', w.HWND),
                        ('hwndMoveSize', w.HWND), ('hwndCaret', w.HWND), ('rcCaret', w.RECT)]
        get_info = self.user.GetGUIThreadInfo
        get_info.argtypes, get_info.restype = [w.DWORD, ctypes.POINTER(GuiThreadInfo)], w.BOOL
        info = GuiThreadInfo(); info.cbSize = ctypes.sizeof(info)
        # thread=0 asks for the real foreground thread, including an embedded
        # M2 thread attached to GameCenter's input queue.
        if not get_info(0, ctypes.byref(info)):
            raise OSError('Cannot verify foreground keyboard focus')
        return self._inside(info.hwndFocus, hwnd)

    def _message(self, hwnd, message, wparam=0, lparam=0, timeout=2000):
        result = ctypes.c_size_t()
        ctypes.set_last_error(0)
        if not self.user.SendMessageTimeoutW(hwnd, message, wparam, lparam, 2, timeout, ctypes.byref(result)):
            raise TimeoutError('Native message has no handler ACK; action state is unknown; do not retry automatically')
        return ctypes.c_ssize_t(result.value).value

    def _title(self, hwnd):
        # WM_GETTEXT reads cross-process Edit values; GetWindowText only reads captions.
        count = self._message(hwnd, 0xE)
        if count < 0:
            raise ValueError('Cannot read native control text length')
        text = ctypes.create_unicode_buffer(min(count, 65535)+1)
        self._message(hwnd, 0xD, len(text), ctypes.addressof(text))
        return text.value, count > 65535

    def _basic(self, hwnd):
        rect = self.w.RECT()
        if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise OSError('Cannot read native window rectangle')
        text, truncated = self._title(hwnd)
        return {'hwnd': int(hwnd), 'parent': int(self.user.GetParent(hwnd) or 0),
                'owner': int(self.user.GetWindow(hwnd, 4) or 0), 'class': self._class(hwnd),
                'style': int(self.window_long(hwnd, -16)),
                'text': text, 'textTruncated': truncated, 'rect': [rect.left, rect.top, rect.right, rect.bottom],
                'visible': bool(self.user.IsWindowVisible(hwnd)), 'enabled': bool(self.user.IsWindowEnabled(hwnd))}

    def native_forms(self, pid):
        from .native_control import native_forms
        result = []
        for form in native_forms(pid):
            if not self.exists(form.handle):
                continue
            item = self._basic(form.handle); item['title'] = item.pop('text')
            result.append(item)
        return result

    def _controls(self, hwnd):
        result, failures = [], []
        process = self.w.DWORD(); self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
        @self.enum_callback
        def collect(handle, unused):
            try:
                control_process = self.w.DWORD()
                self.user.GetWindowThreadProcessId(handle, ctypes.byref(control_process))
                if control_process.value != process.value:
                    return True
                if len(result) >= 4096:
                    raise ValueError('Native control tree exceeds bounded observation size')
                item = self._basic(handle); cls = item['class']
                if cls in COMBO_CLASSES and item['visible']:
                    count = self._message(handle, 0x146)
                    if not 0 <= count <= 65536:
                        raise ValueError('Native combo option count exceeds observation bounds')
                    item['options'] = []
                    for index in range(count):
                        length = self._message(handle, 0x149, index)
                        if not 0 <= length <= 65535:
                            raise ValueError('Native combo option is invalid')
                        text = ctypes.create_unicode_buffer(length+1)
                        self._message(handle, 0x148, index, ctypes.addressof(text))
                        item['options'].append(text.value)
                    item['selectedIndex'] = self._message(handle, 0x147)
                if cls in TAB_CLASSES and item['visible']:
                    item['tabs'] = self._read_tabs(handle)
                    item['selectedIndex'] = self._message(handle, 0x130B)
                    index = item['selectedIndex']
                    item['selectedText'] = item['tabs'][index] if 0 <= index < len(item['tabs']) else ''
                if cls in ('TCheckBox', 'TRzCheckBox', 'TRadioButton', 'Button') and item['visible']:
                    item['check'] = self._message(handle, 0xF0)
                result.append(item)
                return True
            except BaseException as exc:
                failures.append(exc); return False
        self.user.EnumChildWindows(hwnd, collect, 0)
        if failures:
            raise failures[0]
        return result

    def _pointer_bits(self, pid):
        if ctypes.sizeof(ctypes.c_void_p) == 4:
            raise ValueError('Use the published 64-bit tool for cross-bitness native controls')
        process = self.kernel.OpenProcess(0x1000, False, pid)
        if not process:
            raise OSError('Cannot query native target pointer width')
        try:
            wow64 = self.w.BOOL()
            query = self.kernel.IsWow64Process
            query.argtypes, query.restype = [self.w.HANDLE, ctypes.POINTER(self.w.BOOL)], self.w.BOOL
            if not query(process, ctypes.byref(wow64)):
                raise OSError('Cannot determine native target pointer width')
            return 32 if wow64.value else 64
        finally:
            self.kernel.CloseHandle(process)

    def _read_tabs(self, hwnd):
        # Common-control messages above WM_USER carry remote pointers. Build
        # TCITEM for the target, rather than the Python process's pointer width.
        from types import SimpleNamespace
        from pywinauto.remote_memory_block import RemoteMemoryBlock
        pid = self.w.DWORD(); self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        bits = self._pointer_bits(pid.value)
        unicode_window = bool(self.user.IsWindowUnicode(hwnd))
        count = self._message(hwnd, 0x1304)
        if not 0 <= count <= 4096:
            raise ValueError('Native tab count exceeds bounded observation size')
        item_type = _tab_item_type(bits)
        capacity = 1024
        remote = RemoteMemoryBlock(SimpleNamespace(handle=int(hwnd)), size=4096)
        retain_remote = False
        try:
            address = remote.Address()+ctypes.sizeof(item_type)
            if address+(capacity*2) >= 1 << bits:
                raise ValueError('Tab remote text pointer exceeds target address width')
            result = []
            for index in range(count):
                item = item_type(); item.mask = 1; item.pszText = address; item.cchTextMax = capacity
                remote.Write(item)
                buffer = ctypes.create_unicode_buffer(capacity) if unicode_window else ctypes.create_string_buffer(capacity)
                remote.Write(buffer, address)
                try:
                    accepted = self._message(hwnd, 0x133C if unicode_window else 0x1305, index, remote.Address())
                except BaseException as exc:
                    # A timed-out handler may still dereference this pointer.
                    # Keep this one small block until the target exits rather
                    # than freeing memory that the UI thread may still use.
                    retain_remote = True
                    exc.retainedRemoteBuffer = {'pid': pid.value, 'address': remote.Address(), 'bytes': 4096,
                                                'reason': 'handler ACK missing'}
                    remote.mem_address = 0
                    remote._CloseHandle()
                    raise
                if not accepted:
                    raise ValueError('Native tab rejected bounded text retrieval')
                remote.Read(buffer, address)
                text = buffer.value if unicode_window else buffer.value.decode('mbcs', errors='strict')
                if len(text) >= capacity-1:
                    raise ValueError('Native tab caption exceeds bounded observation size')
                result.append(text)
            return result
        finally:
            if not retain_remote:
                remote.CleanUp()

    def _menus(self, hwnd):
        result = []
        def walk(menu, path, parents_enabled=True):
            if len(path) > 16:
                raise ValueError('Native menu exceeds depth bounds')
            count = self.user.GetMenuItemCount(menu)
            if count < 0:
                raise OSError('Cannot inspect native menu')
            for index in range(count):
                buffer = ctypes.create_unicode_buffer(4096)
                self.user.GetMenuStringW(menu, index, buffer, len(buffer), 0x400)
                state = self.user.GetMenuState(menu, index, 0x400)
                if state == 0xFFFFFFFF:
                    raise OSError('Cannot inspect native menu state')
                submenu = self.user.GetSubMenu(menu, index)
                # For a submenu GetMenuState packs its child count in the
                # high byte; eight children therefore look like MF_SEPARATOR.
                if not submenu and state & 0x800:
                    continue
                enabled = parents_enabled and not bool(state & 3)
                current = [*path, buffer.value]
                result.append({'path': current, 'id': int(self.user.GetMenuItemID(menu, index)) if not submenu else None,
                               'enabled': enabled, 'submenu': bool(submenu)})
                if submenu: walk(submenu, current, enabled)
        menu = self.user.GetMenu(hwnd)
        if menu: walk(menu, [])
        return result

    def post_action_lifecycle(self, previous):
        """Metadata only for a same-request form no longer eligible for snapshot."""
        pid, hwnd = previous['pid'], previous['hwnd']
        def sample():
            if not self.exists(hwnd):
                raise ValueError('Post-action form disappeared during lifecycle sampling')
            owner = self.w.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid:
                raise ValueError('Post-action HWND belongs to another process')
            process = self._process(pid)
            if (process.get('processCreated') != previous['processCreated'] or
                    not _same_path(process.get('executable', ''), previous['executable']) or
                    str(process.get('sha256', '')).upper() != previous['sha256'].upper()):
                raise PermissionError('Post-action process identity changed')
            if self._class(hwnd) != previous['class']:
                raise ValueError('Post-action native form class changed')
            item = self._basic(hwnd); item['title'] = item.pop('text')
            item.update(pid=pid, rootHwnd=self.root(hwnd), **process)
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or not self.exists(hwnd):
                raise ValueError('Post-action native form ownership changed')
            _hidden_after_action(previous, item)
            return item
        first, second = sample(), sample()
        if first != second:
            raise ValueError('Post-action hidden form changed between lifecycle samples')
        return _hidden_after_action(previous, second)

    def snapshot(self, pid, hwnd):
        if not self.exists(hwnd):
            raise ValueError('Native HWND no longer exists')
        owner = self.w.DWORD(); self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            raise ValueError('Native HWND belongs to another process')
        forms = self.native_forms(pid)
        if not any(x['hwnd'] == hwnd for x in forms):
            raise ValueError('Select an observed native form, not an arbitrary child control')
        item = self._basic(hwnd); item['title'] = item.pop('text')
        client = self.w.RECT()
        if not self.user.GetClientRect(hwnd, ctypes.byref(client)):
            raise OSError('Cannot inspect native client geometry')
        def below(candidate):
            handle, seen = candidate['parent'], set()
            while handle and handle not in seen:
                if handle == hwnd:
                    return True
                seen.add(handle)
                handle = int(self.user.GetParent(handle) or 0)
            return False
        # WS_CHILD dialogs are controls inside their parent form, including the
        # common file dialog's hook/template child. Keep them observable, but do
        # not mistake them for independent owned modals, regardless of geometry.
        blocking = [x for x in forms if x['hwnd'] != hwnd and x['visible'] and x['enabled'] and
                    not (x['style'] & 0x40000000) and
                    (x.get('owner') == hwnd or below(x)) and
                    not (x['class'] == 'tooltips_class32' and x['style'] & 0x80000000)]
        process = self._process(pid)
        hosting = self._hosting(pid, hwnd, process)
        return dict(item, pid=pid, **process, hosting=hosting, clientSize=[client.right-client.left, client.bottom-client.top],
                    clientOrigin=self.client_to_screen(hwnd, 0, 0), minimized=bool(self.user.IsIconic(hwnd)),
                    blockingWindows=blocking, controls=self._controls(hwnd), menus=self._menus(hwnd))

    def _hosting(self, pid, hwnd, process):
        root = self.root(hwnd)
        name = PureWindowsPath(process['executable']).name.casefold()
        kind = GAMECENTER_HOST_KINDS.get(name)
        if root == hwnd or kind is None:
            return None
        host_pid = self.w.DWORD(); self.user.GetWindowThreadProcessId(root, ctypes.byref(host_pid))
        host = self._basic(root); host['title'] = host.pop('text')
        host.update(self._process(host_pid.value), kind=kind, rootHwnd=root,
                    pid=host_pid.value, minimized=bool(self.user.IsIconic(root)))
        chain, handle, seen = [], hwnd, set()
        while handle and handle not in seen and len(chain) < 64:
            seen.add(handle)
            item = self._basic(handle)
            parent = int(self.user.GetAncestor(handle, 1) or 0)
            item['parent'] = parent
            owner_pid = self.w.DWORD(); self.user.GetWindowThreadProcessId(handle, ctypes.byref(owner_pid))
            item['pid'] = owner_pid.value
            chain.append(item)
            if handle == root:
                break
            handle = parent
        host['ancestorChain'] = chain
        return host

    def assert_input_idle(self):
        super().assert_input_idle()
        if any(self.user.GetAsyncKeyState(vk) & 0x8000 for vk in KEYS.values()):
            raise ValueError('Release physical native navigation keys first')

    def _send(self, kind, value, release):
        if kind != 'key':
            return super()._send(kind, value, release)
        event = self.Input(); event.type = 1; event.ki.wVk = KEYS[value]
        event.ki.dwFlags = 2 if release else 0
        if value in ('HOME', 'END', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'PAGEUP', 'PAGEDOWN'):
            event.ki.dwFlags |= 1
        if self.user.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise OSError('Native SendInput did not accept the event')

    def dispatch(self, target, action):
        hwnd, kind = target['hwnd'], action['kind']
        if kind == 'show':
            self.user.ShowWindow(hwnd, 9)
            self.activate(self.root(hwnd))
            return {'mode': 'ShowWindow', 'handlerAcknowledged': False, 'visible': bool(self.user.IsWindowVisible(hwnd))}
        if kind == 'minimize':
            result = self._message(hwnd, 0x112, 0xF020, 0, timeout=60000)
            return {'mode': 'synchronous', 'handlerAcknowledged': True, 'acknowledged': True, 'messageResult': result}
        if kind == 'menu':
            item = next(x for x in target['menus'] if x['path'] == action['path'])
            message_hwnd, message, wparam, lparam = hwnd, 0x111, item['id'], 0
        elif kind == 'button':
            message_hwnd, message, wparam, lparam = action['controlHwnd'], 0xF5, 0, 0
        elif kind == 'close':
            message_hwnd, message, wparam, lparam = hwnd, 0x10, 0, 0
        else:
            control = next(x for x in target['controls'] if x['hwnd'] == action['controlHwnd'])
            if kind == 'set-text':
                text = ctypes.create_unicode_buffer(action['value'])
                if control.get('style', 0) & 4 or control['class'] in ('TMemo', 'TRichEdit', 'RichEdit20W'):
                    # EM_REPLACESEL emits the edit notifications that multiline
                    # WM_SETTEXT omits. This is the original EditWrapper sequence.
                    self._message(control['hwnd'], 0xB1, 0, -1, timeout=60000)
                    self._message(control['hwnd'], 0xC2, 1, ctypes.addressof(text), timeout=60000)
                else:
                    accepted = self._message(control['hwnd'], 0xC, 0, ctypes.addressof(text), timeout=60000)
                    if not accepted: raise ValueError('Native edit rejected WM_SETTEXT')
            elif kind == 'select-combo':
                index = self._message(control['hwnd'], 0x14E, action['index'], timeout=60000)
                if index != action['index']: raise ValueError('Native combo rejected selection')
                control_id = self.user.GetDlgCtrlID(control['hwnd'])
                self._message(control['parent'], 0x111, (1 << 16) | (control_id & 0xFFFF), control['hwnd'], timeout=60000)
            elif kind == 'select-tab':
                self._message(control['hwnd'], 0x1330, control['tabs'].index(action['text']), timeout=60000)
            else:
                raise ValueError('Unsupported native message action')
            return {'mode': 'synchronous', 'handlerAcknowledged': True, 'acknowledged': True}
        if action.get('synchronous', True):
            result = self._message(message_hwnd, message, wparam, lparam, timeout=60000)
            return {'mode': 'synchronous', 'handlerAcknowledged': True, 'acknowledged': True, 'messageResult': result}
        if not self.user.PostMessageW(message_hwnd, message, wparam, lparam):
            raise OSError('Native PostMessage was not accepted')
        return {'mode': 'posted', 'handlerAcknowledged': False, 'acknowledged': False}
