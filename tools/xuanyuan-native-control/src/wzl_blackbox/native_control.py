"""Version-pinned launcher, engine, game and observed native-window operations."""
from __future__ import annotations

import argparse
import configparser
import ctypes
import io
import json
import os
import re
import shutil
import struct
import sys
import time
import warnings
import traceback
from pathlib import Path, PureWindowsPath

from .native_editor import NativeEditor, sha256
from .policy import DEFAULT_PROTECTED_ROOTS, WritePolicy

VERSION = '1.1.24'
LAUNCHER_SHA256 = '340C5D6B7436DC0F50D27C7844BE29A381C230B65C1112683D2059F2DCE9AD35'
COMMANDS = ('inspect', 'launcher-save', 'launcher-build', 'engine-preflight', 'engine-controller-start', 'engine-controller-stop', 'm2-start', 'm2-stop', 'm2-reload', 'engine-parameter', 'm2-client-build', 'game-inspect', 'game-observe', 'game-input', 'window-observe', 'window-action', 'm2-event-evidence')
INPUT_KEYS = ('客户端文件', '客户端数据文件', '补丁文件', '背景图片', '游戏光标', '镶嵌光标', '拆卸光标', '快捷方式图标', '游戏图标', '怪物配置文件', '外挂检测列表文件')


def parse_ini_bytes(raw, *, strict=False):
    payload = raw.removeprefix(b'\xef\xbb\xbf')
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            text = payload.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError('INI encoding is not supported')
    parser = configparser.ConfigParser(interpolation=None, strict=strict)
    parser.optionxform = str
    parser.read_string(text)
    return parser, encoding


def read_ini(path):
    return parse_ini_bytes(Path(path).read_bytes())


def is_reparse(path):
    return bool(path.lstat().st_file_attributes & 0x400)


def fingerprints(directory):
    return {p.relative_to(directory).as_posix(): sha256(p) for p in sorted(Path(directory).rglob('*')) if p.is_file()}


def validate_request(request):
    if not isinstance(request, dict) or request.get('schemaVersion') != 1 or request.get('command') not in COMMANDS:
        raise ValueError('Unknown command or schemaVersion')
    args = request.get('arguments', {})
    if request['command'] == 'm2-event-evidence':
        from .native_events import validate_request as validate_event_request
        validate_event_request(request)
        return {'command': request['command'], 'eventRequest': request}
    if request['command'].startswith('window-'):
        from .native_window import validate_request as validate_window_request
        validate_window_request(request)
        return {'command': request['command'], 'windowRequest': request}
    if request['command'].startswith('game-'):
        from .native_game import validate_request as validate_game_request
        validate_game_request(request)
        return {'command': request['command'], 'gameRequest': request}
    if request['command'] not in ('inspect', 'launcher-save', 'launcher-build'):
        from .native_engine import validate_operation, validate_lab_root, validate_production_authorization, PRODUCTION_MODE
        if request['command'] == 'm2-client-build' and args.get('mode') == PRODUCTION_MODE:
            root = validate_production_authorization(request, verify_live=True)
            return {'command': request['command'], 'engineRequest': request, 'root': root}
        validate_operation(request['command'], args)
        if not args.get('labRoot'):
            raise ValueError('Engine command requires labRoot')
        root = validate_lab_root(args['labRoot'])
        if request['command'] != 'engine-preflight':
            WritePolicy(request.get('policy', {}).get('allowedWriteRoots', [])).assert_writable(root)
        return {'command': request['command'], 'engineRequest': request, 'root': root}
    if request['command'] == 'inspect':
        pid = args.get('pid')
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1 or not args.get('expectedExecutable'):
            raise ValueError('inspect requires pid and expectedExecutable')
        return {'command': 'inspect', 'pid': pid, 'expected': Path(args['expectedExecutable']).resolve(strict=True)}
    source = Path(args['sourceDirectory']).resolve(strict=True)
    if not source.is_dir() or any(is_reparse(p) for p in (source, *source.rglob('*'))):
        raise ValueError('Source directory must not contain reparse points')
    if sha256(source / 'MakeGameLogin.exe') != LAUNCHER_SHA256:
        raise ValueError('Launcher build does not match the verified 2026-09-27 executable')
    cfg, _ = read_ini(source / 'Config.ini')
    setup = cfg['Setup']
    for key in INPUT_KEYS:
        value = setup.get(key, '').strip()
        if value and (Path(value).is_absolute() or '..' in Path(value).parts):
            raise ValueError('Cannot stage external input path; copy it into the source bundle first: ' + key)
    original_output = setup.get('SaveFilePath', '').strip()
    if original_output and not PureWindowsPath(original_output).is_absolute():
        raise ValueError('Original SaveFilePath must be fully qualified')
    protected = (*DEFAULT_PROTECTED_ROOTS, Path(r'E:\11周年'), Path(r'E:\客户端'), source)
    if original_output:
        protected += (Path(original_output),)
    policy = WritePolicy(request.get('policy', {}).get('allowedWriteRoots', []), protected_roots=protected)
    output = policy.assert_writable(args['outputRoot'])
    if output.exists():
        raise FileExistsError('outputRoot must be a new job directory')
    if source.is_relative_to(output):
        raise ValueError('Job output must not contain its source')
    return {'command': request['command'], 'source': source, 'output': output, 'originalOutput': original_output}


def stage_launcher(plan):
    output = plan['output']
    output.mkdir(parents=True, exist_ok=False)
    staged = output / 'generator'
    shutil.copytree(plan['source'], staged)
    artifacts = output / 'artifacts'
    artifacts.mkdir()
    cfg, encoding = read_ini(staged / 'Config.ini')
    cfg['Setup']['SaveFilePath'] = str(artifacts) + '\\'
    stream = io.StringIO()
    cfg.write(stream, space_around_delimiters=False)
    (staged / 'Config.ini').write_bytes(stream.getvalue().replace('\n', '\r\n').encode(encoding))
    gui_path = staged / 'GUI_Config.ini'
    if gui_path.is_file():
        gui, encoding = read_ini(gui_path)
        if 'Setup' in gui:
            gui['Setup']['ImageLibrary'] = str(output / 'client')
            stream = io.StringIO()
            gui.write(stream, space_around_delimiters=False)
            gui_path.write_bytes(stream.getvalue().replace('\n', '\r\n').encode(encoding))
    return staged


def protected_output_fingerprints(plan):
    root = Path(plan['originalOutput']) if plan['originalOutput'] else None
    if root is None or not root.is_dir():
        return {}
    paths = set(p for p in root.iterdir() if p.is_file())
    patches = plan['source'] / '补丁文件夹'
    for source in patches.rglob('*'):
        if source.is_file():
            paths.add(root / source.relative_to(patches))
    return {str(p): sha256(p) if p.is_file() else None for p in sorted(paths)}


def include_native_form(cls, visible, top_level=False):
    return cls.casefold() == 'tfrmmain' or (visible and cls != 'TApplication' and
            (top_level or cls.casefold().startswith(('tfrm', 'tform', 'tmessage')) or cls == '#32770'))


def native_forms(pid):
    from ctypes import wintypes as w
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.EnumChildWindows.argtypes = [w.HWND, callback_type, w.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [w.HWND]
    handles = set()

    def collect_form(handle, top_level):
        owner = w.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == pid:
            cls = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(handle, cls, 256)
            if include_native_form(cls.value, bool(user.IsWindowVisible(handle)), top_level):
                handles.add(int(handle))
        return True

    @callback_type
    def collect(handle, _):
        return collect_form(handle, False)

    @callback_type
    def top(handle, _):
        collect_form(handle, True)
        user.EnumChildWindows(handle, collect, 0)
        return True

    user.EnumWindows(top, 0)
    return wrap_native_forms(sorted(handles), pid)


def wrap_native_forms(handles, pid):
    import pywintypes
    import win32gui
    import win32process
    from pywinauto.controls.hwndwrapper import HwndWrapper, InvalidWindowHandle
    forms = []
    for handle in handles:
        try:
            form = HwndWrapper(handle)
            if win32process.GetWindowThreadProcessId(handle)[1] == pid:
                forms.append(form)
        except (InvalidWindowHandle, pywintypes.error):
            if win32gui.IsWindow(handle):
                raise
    return forms


def inspect_process(pid, expected):
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    process = kernel.OpenProcess(0x1000, False, pid)
    if not process:
        raise ProcessLookupError('Process is not available for read-only inspection')
    try:
        size = w.DWORD(32768)
        text = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(process, 0, text, ctypes.byref(size)):
            raise OSError('Cannot confirm executable path')
        actual = Path(text.value).resolve(strict=True)
        if actual != expected:
            raise ValueError('PID belongs to a different executable')
    finally:
        kernel.CloseHandle(process)
    windows = []
    for main in native_forms(pid):
        controls = []
        for control in main.descendants():
            cls = control.class_name()
            if cls in ('TButton', 'TBitBtn', 'TCheckBox', 'TTabSheet', 'TProgressBar'):
                item = {'class': cls, 'visible': control.is_visible(), 'enabled': control.is_enabled()}
                if cls != 'TProgressBar':
                    item['caption'] = control.window_text()
                if cls == 'TCheckBox':
                    item['checked'] = bool(control.get_check_state())
                controls.append(item)
        item = {'hwnd': main.handle, 'class': main.class_name(), 'title': main.window_text(), 'visible': main.is_visible(), 'enabled': main.is_enabled(), 'controls': controls}
        try:
            menu = main.menu()
            item['menu'] = menu.get_properties() if menu else None
        except Exception:
            item['menu'] = None
        windows.append(item)
    return {'pid': pid, 'executable': str(actual), 'executableSha256': sha256(actual), 'readOnly': True, 'windows': windows}


def generation_dialog_kind(cls, title, texts):
    if cls == 'SoPY_Status':
        return 'wait'
    if cls == '#32770' and title == '浏览文件夹':
        return 'folder'
    if cls == '#32770' and title == '提示' and any(success_message_url(value) is not None for value in texts):
        return 'success'
    return 'unknown'


def success_message_url(text):
    match = re.fullmatch(r'配置成功 ！\n\n请把"gee\.txt"上传到你的网站，并确保下面的地址可以正常下载\n(https?://[^\n]+)', text.replace('\r\n', '\n'))
    return match.group(1) if match else None


def is_save_success_dialog(cls, title, texts):
    return cls == '#32770' and title == '提示信息' and [value for value in texts if value] == ['配置信息保存成功！！！']


def dialog_content_ready(texts, button_captions):
    return any(texts) and any(button_captions)


def folder_chain_matches(chain, expected):
    path = PureWindowsPath(expected)
    names = [part.casefold() for part in path.parts[1:]][::-1]
    if len(chain) <= len(names) or [part.casefold() for part in chain[:len(names)]] != names:
        return False
    drive = re.search(r'(?:\()?([A-Za-z]:)\)?$', chain[len(names)])
    return drive is not None and drive.group(1).casefold() == path.drive.casefold()


def selected_folder_chain(tree):
    from pywinauto.controls.common_controls import _treeview_element
    node = tree.send_message(0x110A, 9)  # TVM_GETNEXTITEM / TVGN_CARET
    chain = []
    while node and len(chain) < 128:
        chain.append(_treeview_element(node, tree).text())
        node = tree.send_message(0x110A, 3, node)  # TVGN_PARENT
    return chain


class Launcher(NativeEditor):
    def __init__(self, exe, workspace, password=None):
        self.phase = 'startup'
        self.copy_executable = Path(exe).resolve(strict=True)
        super().__init__(exe, workspace, password)
        config, _ = read_ini(workspace / 'Config.ini')
        self.success_urls = {v.strip() for v in config['Setup'].values() if re.fullmatch(r'https?://\S+', v.strip())}

    def keys(self, control, keys):
        from .native_engine import COMPLETE_SANDBOX_ROOT, sandbox_environment, process_image, active_thread_window
        exe = getattr(self, 'copy_executable', None)
        if exe is None or not exe.is_relative_to(COMPLETE_SANDBOX_ROOT):
            return super().keys(control, keys)
        import win32gui
        import win32process
        from pywinauto import Application
        sandbox_environment()
        if process_image(self.process.pid) != exe or sha256(exe) != LAUNCHER_SHA256:
            raise ValueError('Sandbox generator process identity changed')
        if (keys != '{SPACE}' or not control.is_visible() or not control.is_enabled()
                or win32process.GetWindowThreadProcessId(control.handle)[1] != self.process.pid):
            raise ValueError('Unverified sandbox generator button request')
        root_handle = win32gui.GetAncestor(control.handle, 2)
        cls, caption = control.class_name(), control.window_text()
        if cls == 'TButton':
            if (caption not in ('保存配置(&G)', '生成登录器(&M)') or root_handle != self.main.handle
                    or active_thread_window(root_handle) != root_handle):
                raise RuntimeError('Sandbox generator main button is not the exact active main form')
            control.post_message(0xF5, 0, 0)
            return
        if cls != 'Button' or caption != '确定':
            raise ValueError('Unverified sandbox generator dialog button')
        parent = Application(backend='win32').connect(process=self.process.pid).window(handle=root_handle)
        signature = (parent.class_name(), parent.window_text(), control.control_id())
        if signature not in (('#32770', '提示信息', 2), ('#32770', '提示', 2), ('#32770', '浏览文件夹', 1)):
            raise RuntimeError('Sandbox generator dialog signature differs')
        button = Application(backend='uia').connect(process=self.process.pid).window(handle=control.handle).wrapper_object()
        if (button.handle != control.handle or button.element_info.process_id != self.process.pid
                or button.element_info.control_type != 'Button'):
            raise RuntimeError('Sandbox generator Invoke target identity differs')
        sandbox_environment()
        if process_image(self.process.pid) != exe or sha256(exe) != LAUNCHER_SHA256:
            raise ValueError('Sandbox generator identity changed before Invoke')
        button.invoke()

    def click_named(self, name):
        self.main.wait('enabled', timeout=10)
        control = self.main.child_window(class_name='TButton', title=name)
        control.wait('visible enabled', timeout=5)
        self.keys(control, '{SPACE}')

    def visible_dialogs(self):
        return [self.app.window(handle=w.handle) for w in self.app.windows(visible_only=True)
                if w.class_name().casefold() not in ('tapplication', 'tfrmmain')]

    def diagnostic_dialogs(self):
        return [{'class': w.class_name(), 'title': w.window_text(), 'texts': [c.window_text() for c in w.descendants() if c.class_name() in ('Static', 'TLabel', 'TButton', 'Button')]} for w in self.visible_dialogs()]

    def confirm_ok(self, dialog, expected_id):
        buttons = [w for w in dialog.descendants(class_name='Button') if w.is_visible() and w.is_enabled()]
        signature = [(w.control_id(), w.window_text()) for w in buttons]
        if signature != [(expected_id, '确定')]:
            raise RuntimeError('Dialog button signature differs: ' + repr(signature))
        self.keys(dialog.child_window(class_name='Button', control_id=expected_id, title='确定'), '{SPACE}')

    def save(self):
        self.phase = 'save-config'
        self.click_named('保存配置(&G)')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            dialogs = self.visible_dialogs()
            if dialogs:
                if len(dialogs) != 1:
                    raise RuntimeError('Unexpected simultaneous save dialogs')
                dialog = dialogs[0]
                texts = [w.window_text() for w in dialog.descendants(class_name='Static')]
                if not dialog_content_ready(texts, [w.window_text() for w in dialog.descendants(class_name='Button')]):
                    time.sleep(0.1)
                    continue
                if not is_save_success_dialog(dialog.class_name(), dialog.window_text(), texts):
                    raise RuntimeError('Unexpected save dialog: ' + json.dumps(self.diagnostic_dialogs(), ensure_ascii=False))
                self.confirm_ok(dialog, 2)
                self.app.window(class_name='#32770', title='提示信息').wait_not('visible', timeout=15)
                self.main.wait('enabled', timeout=15)
                return
            time.sleep(0.1)
        raise TimeoutError('Native save acknowledgement was not observed')

    def build(self, artifacts):
        self.phase = 'generate-button'
        self.click_named('生成登录器(&M)')
        deadline = time.monotonic() + 180
        handled_save = False
        completion_confirmed = False
        folder_handle = None
        success_handle = None
        while time.monotonic() < deadline:
            dialogs = self.visible_dialogs()
            for dialog in dialogs:
                texts = [c.window_text() for c in dialog.descendants(class_name='Static')]
                if dialog.class_name() == '#32770' and not dialog_content_ready(texts, [w.window_text() for w in dialog.descendants(class_name='Button')]):
                    continue
                kind = generation_dialog_kind(dialog.class_name(), dialog.window_text(), texts)
                if kind == 'wait':
                    self.phase = 'packer-progress'
                    continue
                if kind == 'folder' and not handled_save:
                    self.phase = 'verify-output-folder'
                    tree = dialog.child_window(class_name='SysTreeView32').wrapper_object()
                    if not folder_chain_matches(selected_folder_chain(tree), str(artifacts)):
                        raise RuntimeError('Selected native folder is not the isolated artifact directory')
                    folder_handle = dialog.handle
                    self.keys(dialog.child_window(class_name='Button', control_id=1, title='确定'), '{SPACE}')
                    handled_save = True
                    self.phase = 'native-file-generation'
                elif kind == 'folder' and dialog.handle == folder_handle:
                    continue
                elif kind == 'success' and not completion_confirmed:
                    self.phase = 'verify-success-dialog'
                    urls = {success_message_url(value) for value in texts if success_message_url(value) is not None}
                    if len(urls) != 1 or not urls.issubset(self.success_urls):
                        raise RuntimeError('Success dialog source URL does not match')
                    success_handle = dialog.handle
                    self.confirm_ok(dialog, 2)
                    completion_confirmed = True
                elif kind == 'success' and dialog.handle == success_handle:
                    continue
                else:
                    raise RuntimeError('Unverified generation dialog: ' + json.dumps(self.diagnostic_dialogs(), ensure_ascii=False))
            if self.main.is_enabled() and not dialogs and completion_confirmed:
                if not any(artifacts.glob('*.exe')):
                    raise RuntimeError('Native success message appeared without an isolated executable')
                return
            time.sleep(0.2)
        raise TimeoutError('Native generation did not reach a verified completion state')


def validate_pe(path):
    import pefile
    size = path.stat().st_size
    try:
        with pefile.PE(str(path), fast_load=True) as pe:
            header = pe.FILE_HEADER
            optional = pe.OPTIONAL_HEADER
            end = pe.DOS_HEADER.e_lfanew + 24 + header.SizeOfOptionalHeader + 40 * header.NumberOfSections
            if not (1 <= header.NumberOfSections <= 96 and len(pe.sections) == header.NumberOfSections
                    and header.Characteristics & 2 and header.Machine in (0x14C, 0x8664)
                    and optional.Magic in (0x10B, 0x20B) and 0 < end <= optional.SizeOfHeaders <= size
                    and 0 < optional.AddressOfEntryPoint < optional.SizeOfImage):
                raise ValueError('Invalid executable COFF, optional header or section table')
            for section in pe.sections:
                if section.SizeOfRawData and not (optional.SizeOfHeaders <= section.PointerToRawData < size
                        and section.PointerToRawData + section.SizeOfRawData <= size):
                    raise ValueError('Executable section extends outside file bounds')
    except (pefile.PEFormatError, AttributeError, struct.error) as error:
        raise ValueError('Invalid or truncated executable structure') from error
    return {'path': str(path), 'size': size, 'sha256': sha256(path), 'peVerified': True}


def run(request):
    plan = validate_request(request)
    if 'eventRequest' in plan:
        from .native_events import run_evidence
        return run_evidence(plan['eventRequest'])
    if 'windowRequest' in plan:
        from .native_window import run_window
        return run_window(plan['windowRequest'])
    if 'gameRequest' in plan:
        from .native_game import run_game
        return run_game(plan['gameRequest'])
    if plan['command'] == 'inspect':
        return inspect_process(plan['pid'], plan['expected'])
    if 'engineRequest' in plan:
        from .native_engine import run_engine
        return run_engine(plan['engineRequest'])
    before = fingerprints(plan['source'])
    protected_before = protected_output_fingerprints(plan)
    staged = stage_launcher(plan)
    baseline = fingerprints(staged)
    ui = None
    try:
        ui = Launcher(staged / 'MakeGameLogin.exe', staged, None)
        ui.save()
        after_save = fingerprints(staged)
        cfg, _ = read_ini(staged / 'Config.ini')
        if Path(cfg['Setup']['SaveFilePath']).resolve() != (plan['output'] / 'artifacts').resolve():
            raise RuntimeError('Native save did not retain the isolated output path')
        result = {'outputRoot': str(plan['output']), 'savedConfigVerified': True,
                  'savedChangedFiles': [p for p in after_save if after_save[p] != baseline.get(p)]}
        if plan['command'] == 'launcher-build':
            ui.build(plan['output'] / 'artifacts')
    except Exception as error:
        if ui is not None:
            try:
                detail = json.dumps(ui.diagnostic_dialogs(), ensure_ascii=False)
            except Exception:
                detail = 'unavailable'
            raise RuntimeError(f'Native phase {ui.phase}: {type(error).__name__}: {error}; dialogs={detail}') from error
        raise
    finally:
        if ui is not None:
            ui.close()
        if fingerprints(plan['source']) != before:
            raise RuntimeError('Original generator files changed during the isolated job')
        if protected_output_fingerprints(plan) != protected_before:
            raise RuntimeError('Files in the original client output directory changed during the job')
    result['originalSourceUnchanged'] = True
    result['protectedOutputFilesUnchanged'] = True
    result['protectedOutputFingerprints'] = protected_before
    result['sourceFiles'] = before
    result['artifacts'] = [validate_pe(p) for p in (plan['output'] / 'artifacts').glob('*.exe')]
    result['outputFiles'] = fingerprints(plan['output'] / 'artifacts')
    if plan['command'] == 'launcher-build' and len(result['artifacts']) != 1:
        raise RuntimeError('Native generation must create exactly one launcher executable')
    return result


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Verified native application operations and observed window control')
    parser.add_argument('action', choices=('run', 'capabilities'))
    parser.add_argument('--request')
    args = parser.parse_args(argv)
    if args.action == 'capabilities':
        print(json.dumps({'version': VERSION, 'commands': COMMANDS,
                          'engineWrites': 'legacy engine workflows retain their contracts; window-action operates the explicitly selected and authorized native window',
                          'productionEngineWrites': 'window-action requires a concrete authorized task and exact observed target; legacy export retains its exact mode',
                          'productionEngineWritesDefault': False,
                          'productionAuthorizedOperation': 'custom-monster-export-plus-launcher-build',
                          'wholeEngineStartStop': False,
                          'wholeEngineScope': 'unreleased research only; no public whole-stack commands',
                          'launcherWritesCopiesOnly': True,
                          'gameWindowCommands': ['game-inspect', 'game-observe', 'game-input'],
                          'gameWindowScope': 'verified D:\\Mirserver100\\LabClient\\LFM2-100-LAB.exe only',
                          'gameInputRequiresFreshObservation': True,
                          'gameInputOutcome': 'input delivery and screenshot; visual task verification remains required',
                          'nativeWindowCommands': ['window-observe', 'window-action'],
                          'nativeWindowScope': 'M2, GameCenter, fixed LoginSrv/DBServer/RunGate/SelGate, fixed UpdateServer_x64/MirUpdateGate, MakeGameLogin and original WZL/PAK editor; explicit process, binary and current form',
                          'nativeInputRequiresFreshObservation': True,
                          'nativeWindowOutcome': 'control readback, dispatch status and fresh windows; saved files and business results must be verified',
                          'delphiEventEvidence': {'command': 'm2-event-evidence', 'profile': 'custom-monster-summon-v1',
                                                  'scope': 'verified D:\\Mirserver100\\Mir200\\M2Server.exe only; fixed mapped-module DFM, VMT, three published handler snippets and one fixed shared successor',
                                                  'fixedSharedSuccessor': {'rva': 0xFD1F30, 'snippetBytes': 512},
                                                  'arbitraryMemoryAccess': False, 'processMemoryWrites': False,
                                                  'analysisCarrierFormat': 'PE32+ AMD64 DLL for static analysis', 'targetExecutionPerformed': False,
                                                  'runtimeInstanceEventPointerVerified': False, 'businessBehaviorVerified': False},
                          'm2ClientBuild': 'sandbox WIL plus custom-monster chain, or exact production custom-monster export without WIL update',
                          'gameAcceptancePerformed': False}))
        return 0
    request = None
    try:
        request = json.load(sys.stdin) if args.request == '-' else json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message='32-bit application should be automated.*')
            data = run(request)
        response = {'schemaVersion': 1, 'version': VERSION, 'ok': True, 'command': request['command'], 'data': data}
        if 'outputRoot' in data:
            receipt = Path(data['outputRoot'], 'receipt.json')
            if request['command'] == 'm2-event-evidence':
                with receipt.open('x', encoding='utf-8') as stream:
                    stream.write(json.dumps(response, ensure_ascii=False, indent=2))
            else:
                receipt.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(response, ensure_ascii=False))
        return 0
    except Exception as error:
        detail = {'type': type(error).__name__, 'message': str(error)}
        if os.environ.get('XY_NATIVE_DIAGNOSTICS') == '1':
            detail['traceback'] = traceback.format_exc()
        print(json.dumps({'schemaVersion': 1, 'version': VERSION, 'ok': False, 'error': detail}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
