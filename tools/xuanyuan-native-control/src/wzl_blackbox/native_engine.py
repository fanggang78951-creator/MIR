"""Explicit native engine operations restricted to disposable isolated labs."""
from __future__ import annotations

import configparser
import re
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import uuid
import shutil
import io
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

from .native_editor import sha256
from .policy import WritePolicy

LAB_BASE = Path(r'D:\codex临时工作区')
SANDBOX_ROOT = Path(r'C:\NativeLab')
COMPLETE_SANDBOX_ROOT = Path(r'C:\NativeDirectoryLab')
BINARIES = {
    'GameCenter.exe': '497C03D8C323258069EB4582F1C291BA5C67E190D8C31DDC5FAD5A79C2D72857',
    'Mir200/M2Server.exe': '1D4D58A4C49EE97D2844FCB2BB31EA3E1F11E7FEDE4DBC857A3FE21979723F1A',
    'DBServer/DBServer.exe': '86868707C18D36D044109BF913535F37BB85B40318F04F5510089E4A8A708AE7',
    'Mir200/Mir.dat': 'FCF7EBE937439596CFF00DE4AC25B8CA7BBAA5109EAE65D33C81900A103C6D48',
}
STACK_BINARIES = {**BINARIES,
    'DBServer/DBServer.exe': '06DA830E181A7DFDD913A4D322422AD01C755C8A105CA69AE08A7716C25DC6BE',
    'LoginGate/LoginGate.exe': 'C410A16962D4E5D556AB0B18AD003D7C769EF7883B5FC2ECEEBA151370707183',
    'LoginSrv/LoginSrv.exe': '1CC15D5A3848E2EB3DD2FB52947331527D8708C165F3266D5AC7DA80C8D9BC57',
    'LogServer/LogDataServer.exe': 'E5F092ECA627B887FB7E3D164A15C9BC7D53F0419AAE865AE0A60B1889DAB330',
    'RunGate/RunGate.exe': 'F6494D1A560D9D7D4B2A7BB8EAAEB24D4B38ECE39A84D0630E35E0C3CE23FDC4',
    'SelGate/SelGate.exe': '4A707773A3AB6CBC93A0C0239B8DCED39EFDD07F31D70DBF50F417EC022E3E55',
}
STACK_COMPONENTS = ('DBServer/DBServer.exe', 'Mir200/M2Server.exe', 'LoginGate/LoginGate.exe',
                    'LoginSrv/LoginSrv.exe', 'LogServer/LogDataServer.exe', 'RunGate/RunGate.exe', 'SelGate/SelGate.exe')
STACK_CHECKS = {'游戏数据库(DBServer)', '游戏主程序(M2Server)', '游戏登陆网关(LoginGate)',
                '游戏登陆服务器(LoginSrv)', '游戏日志服务(LogServer)', '游戏网关一(Rungate)', '游戏角色网关一(SelGate)'}
CONFIGS = ('Config.ini', 'Mir200/!Setup.txt', 'DBServer/dbsrc.ini', 'LoginSrv/Logsrv.ini', 'LogServer/LogData.ini')
SHARE_DIRECTORIES = {'BaseDir': 'Mir200/Share', 'GuildDir': 'Mir200/GuildBase/Guilds', 'VentureDir': 'Mir200/ShareV',
                     'ConLogDir': 'Mir200/ConLog', 'LogDir': 'Mir200/Log', 'PlugDir': 'Mir200', 'BoxsDir': 'Mir200/Envir/Boxs',
                     'CastleDir': 'Mir200/Castle', 'EnvirDir': 'Mir200/Envir', 'MapDir': 'Mir200/Map',
                     'NoticeDir': 'Mir200/Notice', 'SortDir': 'Mir200/Sort', 'ChatDir': 'Mir200/ChatLog'}
NETWORK = {
    'Mir200/!Setup.txt': {'Server': {'DBAddr': '127.0.0.1', 'DBPort': '26000', 'IDSAddr': '127.0.0.1', 'IDSPort': '25600',
                                    'GateAddr': '127.0.0.1', 'GatePort': '25000', 'MsgSrvAddr': '127.0.0.1', 'MsgSrvPort': '24900',
                                    'LogServerAddr': '127.0.0.1', 'LogServerPort': '30000'}},
    'DBServer/dbsrc.ini': {'Setup': {'ServerAddr': '127.0.0.1', 'ServerPort': '26000', 'GateAddr': '127.0.0.1', 'GatePort': '25100'},
                         'Server': {'IDSAddr': '127.0.0.1', 'IDSPort': '25600'}},
    'LoginSrv/Logsrv.ini': {'Server': {'GateAddr': '127.0.0.1', 'GatePort': '25500', 'ServerAddr': '127.0.0.1', 'ServerPort': '25600', 'MonAddr': '127.0.0.1', 'MonPort': '23000'}},
    'LogServer/LogData.ini': {'Setup': {'Port': '30000'}},
}
RELOADS = {
    'qfunction': 'QFunction 功能脚本(&Q)', 'qmanage': 'QManage 登录脚本(&R)',
    'parameters': '参数设置(&C)', 'items': '物品数据库(&I)', 'skills': '技能数据库(&S)',
    'monsters': '怪物数据库(&M)', 'npcs': '所有NPC(&N)',
}
COMMANDS = ('engine-preflight', 'engine-controller-start', 'engine-controller-stop',
            'm2-start', 'm2-stop', 'm2-reload', 'engine-parameter', 'engine-start', 'engine-stop', 'm2-client-build')
PRODUCTION_MODE = 'production-authorized'
PRODUCTION_AUTHORIZATION = 'AUTHORIZED_M2_CUSTOM_MONSTER_EXPORT_AND_LAUNCHER_BUILD'
PRODUCTION_ROOT = Path(r'D:\MirServer')
PRODUCTION_EXECUTABLE = PRODUCTION_ROOT / 'Mir200/M2Server.exe'
PRODUCTION_SOURCE = PRODUCTION_ROOT / '登录器'
PRODUCTION_CLIENT = Path(r'E:\客户端\热血传奇16周年客户端')
PRODUCTION_OUTPUT_BASE = Path(r'D:\codex临时工作区\20261013_封神V4装备属性\装备窗口施工\九龙宝宝与接引使修正')
PRODUCTION_TITLE = '01区 [无限版]'
PRODUCTION_OPERATIONS = ['custom-monster-export', 'launcher-build']


def validate_sandbox_observation(state):
    if (state.get('username') != 'WDAGUtilityAccount' or state.get('nonLoopbackAddresses') != []
            or state.get('defaultRoutes') != []):
        raise PermissionError('Whole-engine calls require a network-disabled WDAG guest')
    return state


class _Sockaddr4(ctypes.Structure):
    _fields_ = [('family', ctypes.c_uint16), ('port', ctypes.c_uint16),
                ('address', ctypes.c_ubyte * 4), ('zero', ctypes.c_ubyte * 8)]


class _Sockaddr6(ctypes.Structure):
    _fields_ = [('family', ctypes.c_uint16), ('port', ctypes.c_uint16), ('flow', ctypes.c_uint32),
                ('address', ctypes.c_ubyte * 16), ('scope', ctypes.c_uint32)]


class _SockaddrInet(ctypes.Union):
    _fields_ = [('v4', _Sockaddr4), ('v6', _Sockaddr6), ('family', ctypes.c_uint16)]


class _IpPrefix(ctypes.Structure):
    _fields_ = [('address', _SockaddrInet), ('length', ctypes.c_ubyte)]


class _UnicastRow(ctypes.Structure):
    _fields_ = [('address', _SockaddrInet), ('luid', ctypes.c_uint64), ('index', ctypes.c_uint32),
                ('prefixOrigin', ctypes.c_uint32), ('suffixOrigin', ctypes.c_uint32),
                ('validLifetime', ctypes.c_uint32), ('preferredLifetime', ctypes.c_uint32),
                ('prefixLength', ctypes.c_ubyte), ('skipAsSource', ctypes.c_ubyte),
                ('dadState', ctypes.c_uint32), ('scopeId', ctypes.c_uint32), ('created', ctypes.c_int64)]


class _RouteRow(ctypes.Structure):
    _fields_ = [('luid', ctypes.c_uint64), ('index', ctypes.c_uint32), ('destination', _IpPrefix),
                ('nextHop', _SockaddrInet), ('sitePrefixLength', ctypes.c_ubyte),
                ('validLifetime', ctypes.c_uint32), ('preferredLifetime', ctypes.c_uint32),
                ('metric', ctypes.c_uint32), ('protocol', ctypes.c_uint32),
                ('loopback', ctypes.c_ubyte), ('autoconfigure', ctypes.c_ubyte),
                ('publish', ctypes.c_ubyte), ('immortal', ctypes.c_ubyte),
                ('age', ctypes.c_uint32), ('origin', ctypes.c_uint32)]


def _read_ip_table(api, name, row_type):
    class Table(ctypes.Structure):
        _fields_ = [('count', ctypes.c_uint32), ('rows', row_type * 1)]
    query = getattr(api, name)
    query.argtypes = [ctypes.c_uint16, ctypes.POINTER(ctypes.c_void_p)]
    query.restype = ctypes.c_uint32
    pointer = ctypes.c_void_p()
    status = query(socket.AF_UNSPEC, ctypes.byref(pointer))
    try:
        if status or not pointer.value:
            raise OSError(status, name + ' could not verify network isolation')
        table = ctypes.cast(pointer, ctypes.POINTER(Table)).contents
        if table.count > 65536:
            raise ValueError('Invalid native IP table count')
        base = pointer.value + Table.rows.offset
        return [row_type.from_buffer_copy(ctypes.string_at(base + i * ctypes.sizeof(row_type), ctypes.sizeof(row_type)))
                for i in range(table.count)]
    finally:
        if pointer.value:
            api.FreeMibTable(pointer)


def _ip_text(address):
    if address.family == socket.AF_INET:
        return socket.inet_ntop(socket.AF_INET, bytes(address.v4.address))
    if address.family == socket.AF_INET6:
        return socket.inet_ntop(socket.AF_INET6, bytes(address.v6.address))
    raise ValueError('Unknown native IP address family')


def native_network_observation():
    import ipaddress
    api = ctypes.WinDLL('iphlpapi', use_last_error=True)
    api.FreeMibTable.argtypes = [ctypes.c_void_p]
    api.FreeMibTable.restype = None
    addresses = [_ip_text(r.address) for r in _read_ip_table(api, 'GetUnicastIpAddressTable', _UnicastRow)]
    routes = []
    for row in _read_ip_table(api, 'GetIpForwardTable2', _RouteRow):
        address = ipaddress.ip_address(_ip_text(row.destination.address))
        if row.destination.length == 0:
            if not address.is_unspecified:
                raise ValueError('Invalid native default-route prefix')
            routes.append('0.0.0.0/0' if address.version == 4 else '::/0')
    user = ctypes.WinDLL('advapi32', use_last_error=True)
    user.GetUserNameW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    user.GetUserNameW.restype = ctypes.c_int
    name, size = ctypes.create_unicode_buffer(257), ctypes.c_uint32(257)
    if not user.GetUserNameW(name, ctypes.byref(size)):
        raise OSError(ctypes.get_last_error(), 'Could not verify native username')
    return {'username': name.value, 'nonLoopbackAddresses': [a for a in addresses if not ipaddress.ip_address(a).is_loopback],
            'defaultRoutes': routes}


def sandbox_environment():
    return validate_sandbox_observation(native_network_observation())


def independent_directory(path):
    original = Path(path).absolute()
    for p in (original, *original.parents):
        try:
            attributes = p.lstat().st_file_attributes
        except FileNotFoundError:
            continue
        if attributes & 0x400:
            raise ValueError('Lab path must not contain reparse points')
    return original.resolve(strict=False)


def validate_lab_root(root):
    candidate = independent_directory(root)
    if candidate in (independent_directory(SANDBOX_ROOT), independent_directory(COMPLETE_SANDBOX_ROOT)):
        sandbox_environment()
        base = candidate
    else:
        base = LAB_BASE.resolve()
        if candidate == base or not candidate.is_relative_to(base):
            raise PermissionError('Engine writes are limited to disposable lab directories')
    WritePolicy([base]).assert_writable(candidate)
    return candidate


def validate_operation(command, args):
    if command not in COMMANDS:
        raise ValueError('Unknown engine command')
    if command == 'm2-client-build':
        if args.get('exportKind') != 'custom-monsters':
            raise ValueError('exportKind must explicitly be custom-monsters')
        if args.get('mode') == PRODUCTION_MODE:
            return
        if not args.get('labRoot') or validate_lab_root(args['labRoot']) != independent_directory(COMPLETE_SANDBOX_ROOT):
            raise PermissionError('Client build requires the complete network-disabled WDAG copy')
    if command in ('engine-start', 'engine-stop'):
        if not args.get('labRoot'):
            raise ValueError('Whole-engine command requires the fixed sandbox labRoot')
        if validate_lab_root(args['labRoot']) not in (independent_directory(SANDBOX_ROOT), independent_directory(COMPLETE_SANDBOX_ROOT)):
            raise PermissionError('Whole-engine calls are unavailable in host labs or production')
    if command == 'm2-reload' and args.get('target') not in RELOADS:
        raise ValueError('Unknown reload target')
    if command == 'engine-parameter':
        if args.get('parameter') != 'console-user-count-interval':
            raise ValueError('Parameter has no verified native mapping')
        for key in ('value', 'expectedValue'):
            value = args.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3600:
                raise ValueError(key + ' must be an explicit integer in 1..3600 seconds')


def _exact_path(value, expected, label, *, must_exist=True):
    if not isinstance(value, str) or not value:
        raise ValueError(label + ' is required')
    try:
        actual = Path(value).resolve(strict=must_exist)
        wanted = Path(expected).resolve(strict=must_exist)
    except OSError as error:
        raise PermissionError(label + ' does not resolve to the authorized path') from error
    if actual != wanted:
        raise PermissionError(label + ' is outside the exact production authorization')
    return actual


def _validate_production_bindings(request, *, verify_live=True):
    if not isinstance(request, dict) or request.get('schemaVersion') != 1 or request.get('command') != 'm2-client-build':
        raise PermissionError('Production authorization only supports m2-client-build')
    args, policy = request.get('arguments', {}), request.get('policy', {})
    if args.get('mode') != PRODUCTION_MODE:
        raise PermissionError('Production mode requires explicit authorization')
    if args.get('exportKind') != 'custom-monsters':
        raise ValueError('Production exportKind must be custom-monsters')
    root = _exact_path(args.get('labRoot'), PRODUCTION_ROOT, 'labRoot')
    executable = _exact_path(args.get('expectedExecutable'), PRODUCTION_EXECUTABLE, 'expectedExecutable')
    _exact_path(args.get('sourceDirectory'), PRODUCTION_SOURCE, 'sourceDirectory')
    _exact_path(args.get('clientRoot'), PRODUCTION_CLIENT, 'clientRoot')
    if args.get('expectedWindowTitle') != PRODUCTION_TITLE:
        raise PermissionError('Production window title binding differs')
    pid = args.get('pid')
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        raise ValueError('Production mode requires an explicit live M2 PID')
    if policy.get('productionAuthorization') != PRODUCTION_AUTHORIZATION:
        raise PermissionError('Production authorization token differs')
    _exact_path(policy.get('authorizedServerRoot'), PRODUCTION_ROOT, 'authorizedServerRoot')
    _exact_path(policy.get('authorizedClientRoot'), PRODUCTION_CLIENT, 'authorizedClientRoot')
    if policy.get('allowedOperations') != PRODUCTION_OPERATIONS:
        raise PermissionError('Production operation set differs')
    write_roots = policy.get('allowedWriteRoots')
    if not isinstance(write_roots, list) or len(write_roots) != 1:
        raise PermissionError('Production mode requires exactly one task write root')
    _exact_path(write_roots[0], PRODUCTION_OUTPUT_BASE, 'allowedWriteRoots')
    output = Path(args.get('outputRoot', '')).resolve(strict=False)
    base = PRODUCTION_OUTPUT_BASE.resolve(strict=True)
    if output == base or not output.is_relative_to(base):
        raise PermissionError('Production outputRoot is outside the authorized task root')
    if verify_live:
        if process_image(pid) != executable or sha256(executable) != BINARIES['Mir200/M2Server.exe']:
            raise ValueError('Production M2 PID, path or version no longer matches authorization')
    return root, executable, output, args


def validate_resume_export(args, output):
    from .native_control import fingerprints
    expected_hash, expected_size = args.get('resumeExportSha256'), args.get('resumeExportSize')
    if args.get('resumeExistingExport') is not True:
        raise PermissionError('Existing production output is not authorized for resume')
    if not isinstance(expected_hash, str) or re.fullmatch(r'[0-9A-F]{64}', expected_hash) is None:
        raise ValueError('Resume requires the exact uppercase DAT SHA256')
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or not 0 < expected_size <= 64 * 1024 * 1024:
        raise ValueError('Resume requires the exact bounded DAT size')
    if not output.is_dir() or {p.name for p in output.iterdir()} != {'input'}:
        raise PermissionError('Resume output must contain only the interrupted input bundle')
    source, bundle = PRODUCTION_SOURCE.resolve(strict=True), (output / 'input').resolve(strict=True)
    if not bundle.is_dir() or any(p.lstat().st_file_attributes & 0x400 for p in (bundle, *bundle.rglob('*'))):
        raise PermissionError('Resume input bundle is missing or contains a reparse point')
    target = bundle / 'native-custom-monsters.dat'
    if not target.is_file() or target.stat().st_size != expected_size or sha256(target) != expected_hash:
        raise PermissionError('Resume DAT does not match the authorized interrupted export')
    evidence_value, evidence_hash = args.get('resumeEvidencePath'), args.get('resumeEvidenceSha256')
    if not isinstance(evidence_value, str) or not isinstance(evidence_hash, str) or re.fullmatch(r'[0-9A-F]{64}', evidence_hash) is None:
        raise ValueError('Resume requires the exact failure-evidence path and SHA256')
    evidence = Path(evidence_value).resolve(strict=True)
    base = PRODUCTION_OUTPUT_BASE.resolve(strict=True)
    if not evidence.is_relative_to(base) or sha256(evidence) != evidence_hash:
        raise PermissionError('Resume failure evidence is outside the task or has changed')
    record = json.loads(evidence.read_text(encoding='utf-8-sig'))
    if (record.get('outputRoot') != str(output) or record.get('datPath') != str(target)
            or record.get('datSize') != expected_size or record.get('datSha256') != expected_hash
            or record.get('failure') != 'FileExistsError: Production outputRoot must be new'
            or record.get('rootCause') != 'runtime confirmation guard reused entry-only new-output precondition'):
        raise PermissionError('Resume failure evidence does not bind the interrupted operation')
    copied = fingerprints(bundle)
    copied.pop(target.name, None)
    if copied != fingerprints(source):
        raise PermissionError('Resume input bundle no longer matches the formal generator source')
    return {'target': target, 'sha256': expected_hash, 'size': expected_size}


def validate_production_authorization(request, *, verify_live=True, require_new_output=True):
    root, _, output, args = _validate_production_bindings(request, verify_live=verify_live)
    if require_new_output:
        if output.exists():
            if args.get('resumeExistingExport') is True:
                validate_resume_export(args, output)
            else:
                raise FileExistsError('Production outputRoot must be new')
        elif args.get('resumeExistingExport') is True:
            raise FileNotFoundError('Resume requires the exact interrupted outputRoot')
    elif not output.is_dir():
        raise FileNotFoundError('Active production outputRoot is missing')
    return root


def validate_production_runtime(request, target):
    validate_production_authorization(request, verify_live=True, require_new_output=False)
    output = Path(request['arguments']['outputRoot']).resolve(strict=True)
    expected = (output / 'input/native-custom-monsters.dat').resolve(strict=True)
    actual = Path(target).resolve(strict=True)
    if actual != expected or not actual.is_file() or not 0 < actual.stat().st_size <= 64 * 1024 * 1024:
        raise PermissionError('Active production DAT is outside the bound interrupted output')
    digest = sha256(actual)
    args = request['arguments']
    if args.get('resumeExistingExport') is True:
        if digest != args.get('resumeExportSha256') or actual.stat().st_size != args.get('resumeExportSize'):
            raise PermissionError('Active resume DAT changed after authorization')
    return {'exportSha256': digest, 'exportSize': actual.stat().st_size}


def verify_production_main_title(main, expected, *, allow_disabled=False):
    if (expected != PRODUCTION_TITLE or main.window_text() != expected or not main.is_visible()
            or (not allow_disabled and not main.is_enabled())):
        raise ValueError('Production M2 main window title or state differs')
    return True


def ini_bytes(raw):
    from .native_control import parse_ini_bytes
    parser, _ = parse_ini_bytes(raw, strict=True)
    return {(section, key): value for section in parser.sections() for key, value in parser.items(section)}


def single_ini_change(before, after, expected):
    old, new = ini_bytes(before), ini_bytes(after)
    delta = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    if delta != {expected} or expected not in old or expected not in new:
        raise ValueError('Native save changed more than the expected single parameter')
    return old[expected], new[expected]


def preflight(root):
    from .native_control import read_ini
    root = validate_lab_root(root)
    for p in root.rglob('*'):
        stat = p.lstat()
        if stat.st_file_attributes & 0x400:
            raise ValueError('Lab contains reparse points')
        if p.is_file() and stat.st_nlink != 1:
            raise ValueError('Lab file has hard links and is not an independent copy')
    complete = root == independent_directory(COMPLETE_SANDBOX_ROOT)
    sandbox = complete or root == independent_directory(SANDBOX_ROOT)
    binaries = STACK_BINARIES if sandbox else BINARIES
    for name, expected in binaries.items():
        p = root / name
        if not p.is_file() or sha256(p) != expected:
            raise ValueError('Unverified engine binary: ' + name)
    configs = {name: read_ini(root / name)[0] for name in CONFIGS}
    gc = configs['Config.ini']
    if not PureWindowsPath(gc['GameConf'].get('GameDirectory', '')).is_absolute() or Path(gc['GameConf'].get('GameDirectory', '')).resolve() != root:
        raise ValueError('Controller target directory is not the lab')
    if any(gc['GameConf'].get(key, '0') != '0' for key in ('GetAutoStartServer', 'GetAutoStartBackUpServer')):
        raise ValueError('Controller auto start must be disabled')
    retained = {}
    for filename, cfg in configs.items():
        for section in cfg:
            for key, value in cfg[section].items():
                windows_path = PureWindowsPath(value)
                if '..' in windows_path.parts or (windows_path.root or windows_path.drive) and not windows_path.is_absolute():
                    raise ValueError('Relative or parent-jumping configuration path: ' + filename + '/' + key)
                if value.startswith('\\\\') or re.match(r'^[A-Za-z]:[\\/]', value):
                    if not Path(value).resolve().is_relative_to(root):
                        if complete and key.casefold() == 'accessfilename' and cfg[section].get('UseSqliteDB') == '1':
                            retained[filename + '/' + section + '/' + key] = value
                            continue
                        if (complete and filename == 'Mir200/!Setup.txt' and section == 'Share'
                                and key in ('BoxsFile', 'SortDir', 'ChatDir')
                                and windows_path.drive.casefold() == 'g:' and not Path(windows_path.anchor).exists()):
                            retained[filename + '/' + section + '/' + key] = value
                            continue
                        raise ValueError('External configuration path: ' + filename + '/' + section + '/' + key)
        if cfg.has_section('DataSaveDB') and cfg['DataSaveDB'].get('DataSaveDBType', '0') != '0':
            raise ValueError('External account database is not allowed')
    share = configs['Mir200/!Setup.txt']['Share']
    for key, relative in SHARE_DIRECTORIES.items():
        if 'Mir200/!Setup.txt/Share/' + key in retained:
            continue
        value = share.get(key, '')
        if not PureWindowsPath(value).is_absolute() or Path(value).resolve() != root / relative:
            raise ValueError('Native directory binding differs from the audited lab path: ' + key)
    for p in (root / 'Mir200').rglob('*'):
        if p.is_file() and p.suffix.casefold() in ('.lua', '.dll'):
            raise ValueError('Unverified Lua or plugin code in the minimal lab')
    for filename, section in (('Config.ini', 'GameConf'), ('Mir200/!Setup.txt', 'Server'), ('DBServer/dbsrc.ini', 'Setup')):
        cfg = configs[filename][section]
        database = root / 'Mud2/DB/ApexM2.DB'
        if cfg.get('UseSqliteDB') != '1' or any(not PureWindowsPath(cfg.get(key, '')).is_absolute() or Path(cfg.get(key, '')).resolve() != database for key in ('SqliteDBName', 'SqliteDBFile')):
            raise ValueError('The private SQLite database path is required in both keys')
    database = root / 'Mud2/DB/ApexM2.DB'
    if not database.is_file() or database.read_bytes()[:16] != b'SQLite format 3\0':
        raise ValueError('Private test database is missing or invalid')
    for filename, sections in NETWORK.items():
        for section, fields in sections.items():
            for key, expected in fields.items():
                actual = configs[filename][section].get(key)
                if complete:
                    if 'Addr' in key:
                        allowed = ('127.0.0.1', '0.0.0.0') if key in ('GateAddr', 'ServerAddr', 'MonAddr', 'MsgSrvAddr') else ('127.0.0.1',)
                        if actual not in allowed:
                            raise ValueError('Non-loopback peer or listener address: ' + filename + '/' + key)
                    elif actual is None or not actual.isdecimal() or not 1 <= int(actual) <= 65535:
                        raise ValueError('Invalid native port: ' + filename + '/' + key)
                    continue
                if actual != expected:
                    raise ValueError(('Non-loopback address' if 'Addr' in key else 'Unisolated port') + ': ' + filename + '/' + key)
    if (root / 'Mir200/PlugList.txt').read_bytes().strip():
        raise ValueError('External plugins must be disabled')
    plugin, _ = read_ini(root / 'Mir200/系统插件.ini')
    if any(value != '0' for value in plugin['setup'].values()):
        raise ValueError('System plugins must be disabled')
    qf = root / 'Mir200/Envir/Market_Def/QFunction-0.txt'
    qm = root / 'Mir200/Envir/MapQuest_def/QManage.txt'
    script_files = [root / 'Mir200/Envir' / name for name in ('Robot.txt', 'RobotManage.txt', 'Merchant.txt', 'Npc.txt', 'MonGen.txt', 'MapInfo.txt')]
    for folder in ('Envir/Market_Def', 'Envir/MapQuest_def', 'Envir/Npc_Def', 'Envir/Robot_def', 'Envir/QuestDiary', 'QuestDiary'):
        script_files.extend((root / 'Mir200' / folder).rglob('*'))
    if complete:
        script_files = []
    for p in script_files:
        if not p.is_file() or not p.read_bytes().strip():
            continue
        if not any(line.strip() and not line.lstrip().startswith(';') for line in p.read_bytes().decode('gb18030').splitlines()):
            continue
        if p in (qf, qm) and p.read_bytes() == b'[@main]\r\n#ACT\r\nBREAK\r\n':
            continue
        if p.name == 'MapInfo.txt' and p.read_bytes() == b'[0 NativeControlLab 0] SAFE\r\n':
            continue
        raise ValueError('Unverified startup or reload script: ' + str(p.relative_to(root)))
    if sandbox:
        iddir = configs['LoginSrv/Logsrv.ini']['DB'].get('IdDir', '')
        if not PureWindowsPath(iddir).is_absolute() or Path(iddir).resolve() != root / 'LoginSrv/IDDB' or not (root / 'LoginSrv/IDDB').is_dir():
            raise ValueError('The private account IDDB directory must exist')
    return {'root': str(root), 'isolated': True, 'configurationOnly': True,
            'mode': 'network-disabled-WDAG-complete' if complete else ('network-disabled-WDAG-stack' if sandbox else 'minimal-lab'),
            'retainedLegacyPaths': retained, 'businessScriptsPreserved': complete,
            'components': list(STACK_COMPONENTS) if sandbox else ['M2Server'],
            'wholeEngineStartStop': sandbox, 'networkIsolation': 'WDAG-no-addresses-or-default-routes' if sandbox else 'M2-loopback-only',
            'blockedReason': None if sandbox else 'Whole-engine calls require the network-disabled WDAG guest',
            'binaries': binaries.copy(), 'configSha256': {name: sha256(root / name) for name in CONFIGS}}


def menu_command_id(menu, path):
    current = menu
    for index, caption in enumerate(path):
        matches = [item for item in current.get('menu_items', []) if item.get('text') == caption]
        if len(matches) != 1 or matches[0].get('state', 0) & 3:
            raise ValueError('Native menu is missing, ambiguous or disabled')
        item = matches[0]
        if index == len(path) - 1:
            if 'menu_items' in item or not 0 < item.get('item_id', 0) < 65536:
                raise ValueError('Menu endpoint must be an enabled leaf')
            return item['item_id']
        current = item.get('menu_items', {})


def reload_acknowledged(target, delta):
    markers = {'qfunction': ('QFunction 脚本加载完成...',), 'qmanage': ('QManage 脚本加载完成...',),
               'items': ('重新加载物品数据库完成...',), 'skills': ('重新加载技能数据库完成...',),
               'monsters': ('重新加载怪物数据库完成...',),
               'npcs': ('交易NPC重新加载完成...', '管理NPC重新加载完成...')}
    return target in markers and all(text in delta for text in markers[target])


def new_log_text(before, after):
    if not after.startswith(before):
        raise ValueError('Native log baseline changed or was truncated; acknowledgement is ambiguous')
    return after[len(before):]


def verify_saved_parameter(before, after, old_seconds, new_seconds):
    key = ('Setup', 'ConsoleShowUserCountTime')
    if old_seconds == new_seconds:
        if ini_bytes(before) != ini_bytes(after):
            raise ValueError('An equal-value native save changed another configuration key')
    else:
        old, new = single_ini_change(before, after, key)
        if (old, new) != (str(old_seconds * 1000), str(new_seconds * 1000)):
            raise ValueError('Native saved parameter values differ from the requested seconds')


@contextmanager
def serial_engine_operation():
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    kernel.CreateMutexW.restype = w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.ReleaseMutex.argtypes = [w.HANDLE]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateMutexW(None, False, 'Local\\XuanYuanNativeControlEngine')
    if not handle:
        raise OSError('Cannot acquire native-operation serialization')
    acquired = False
    try:
        acquired = kernel.WaitForSingleObject(handle, 0) in (0, 128)
        if not acquired:
            raise ValueError('Another native engine operation is already running')
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def raise_process_error(code):
    if code in (87, 1168):
        raise ProcessLookupError('Native process no longer exists')
    if code == 5:
        raise PermissionError('Native process query was denied; this is not exit evidence')
    raise OSError(code, 'Native process query failed; state is unknown')


def query_image_failed(code, exit_status):
    if exit_status is not None and exit_status != 259:
        raise ProcessLookupError('Native process has exited')
    if code == 5:
        raise PermissionError('Native image query was denied; this is not exit evidence')
    raise OSError(code, 'Cannot query the image of an open process; exit is unproven')


def process_image(pid):
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    process = kernel.OpenProcess(0x1000, False, pid)
    if not process:
        raise_process_error(ctypes.get_last_error())
    try:
        size = w.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            error = ctypes.get_last_error()
            exit_code = w.DWORD()
            obtained = kernel.GetExitCodeProcess(process, ctypes.byref(exit_code))
            query_image_failed(error, exit_code.value if obtained else None)
        return Path(buffer.value).resolve(strict=True)
    finally:
        kernel.CloseHandle(process)


def named_processes(name):
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class Entry(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD), ('heap', ctypes.c_size_t),
                    ('module', w.DWORD), ('threads', w.DWORD), ('parent', w.DWORD), ('priority', w.LONG),
                    ('flags', w.DWORD), ('executable', w.WCHAR * 260)]
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), 'Cannot enumerate native process identities')
    result = []
    entry = Entry()
    entry.size = ctypes.sizeof(entry)
    try:
        available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            if entry.executable.casefold() == name.casefold():
                result.append(entry.pid)
            available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            raise OSError(ctypes.get_last_error(), 'Native process enumeration is incomplete')
        return result
    finally:
        kernel.CloseHandle(snapshot)


def matching_processes(executable, *, strict=False):
    import win32process
    result = []
    for pid in named_processes(executable.name) if strict else win32process.EnumProcesses():
        try:
            if process_image(pid) == executable:
                result.append(pid)
        except ProcessLookupError:
            continue
        except OSError:
            if strict:
                raise
    return result


def tcp_listeners(pid):
    from ctypes import wintypes as w
    api = ctypes.WinDLL('iphlpapi', use_last_error=True)
    api.GetExtendedTcpTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.ULONG), w.BOOL, w.ULONG, ctypes.c_int, w.ULONG]
    size = w.ULONG()
    api.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 3, 0)
    buffer = ctypes.create_string_buffer(size.value)
    code = api.GetExtendedTcpTable(buffer, ctypes.byref(size), False, 2, 3, 0)
    if code:
        raise OSError(code, 'Cannot read actual TCP listeners')
    class Row(ctypes.Structure):
        _fields_ = [(name, w.DWORD) for name in ('state', 'address', 'port', 'remote', 'remotePort', 'pid')]
    count = w.DWORD.from_buffer(buffer).value
    rows = []
    for index in range(count):
        row = Row.from_buffer(buffer, 4 + index * ctypes.sizeof(Row))
        if row.pid == pid:
            rows.append({'address': socket.inet_ntoa(int(row.address).to_bytes(4, 'little')), 'port': socket.ntohs(row.port & 65535)})
    return rows


def active_thread_window(handle):
    from ctypes import wintypes as w
    user = ctypes.WinDLL('user32', use_last_error=True)
    class Gui(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('flags', w.DWORD),
                    *[(name, w.HWND) for name in ('active', 'focus', 'capture', 'menu', 'move', 'caret')],
                    ('rect', w.RECT)]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.GetGUIThreadInfo.argtypes = [w.DWORD, ctypes.POINTER(Gui)]
    owner = w.DWORD()
    thread = user.GetWindowThreadProcessId(handle, ctypes.byref(owner))
    gui = Gui()
    gui.size = ctypes.sizeof(gui)
    if not thread or not user.GetGUIThreadInfo(thread, ctypes.byref(gui)):
        raise OSError(ctypes.get_last_error(), 'Cannot read native thread active window')
    return gui.active


def confirm_native_yes(dialog, expected_body, *, require_foreground=True):
    texts = [c.window_text() for c in dialog.descendants(class_name='Static') if c.window_text()]
    buttons = [c for c in dialog.descendants(class_name='Button') if c.is_visible() and c.is_enabled()]
    if dialog.class_name() != '#32770' or dialog.window_text() != '确认信息' or texts != [expected_body] or [(c.control_id(), c.window_text()) for c in buttons] != [(6, '是(&Y)'), (7, '否(&N)')]:
        raise RuntimeError('Exit confirmation signature differs')
    if require_foreground:
        dialog.set_focus()
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetForegroundWindow.restype = ctypes.c_void_p
        if user.GetForegroundWindow() != dialog.handle:
            raise RuntimeError('The exact native confirmation dialog did not obtain foreground focus')
    elif active_thread_window(dialog.handle) != dialog.handle:
        raise RuntimeError('The exact native confirmation is not the thread active dialog')
    buttons[0].post_message(0xF5, 0, 0)


def unique_main_form(mains):
    if not mains:
        raise LookupError('Native main form has not been constructed yet')
    if len(mains) != 1:
        raise ValueError('Expected exactly one native main form')
    return mains[0]


PARAMETER_RELOAD_ACK_TIMEOUT_MS = 60000


def synchronous_menu_command(handle, command):
    synchronous_native_message(handle, 0x111, command)


def synchronous_button_click(handle):
    synchronous_native_message(handle, 0xF5, 0)


def synchronous_native_message(handle, message, parameter):
    from ctypes import wintypes as w
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SendMessageTimeoutW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM, w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    result = ctypes.c_size_t()
    ctypes.set_last_error(0)
    if not user.SendMessageTimeoutW(handle, message, parameter, 0, 2, PARAMETER_RELOAD_ACK_TIMEOUT_MS, ctypes.byref(result)):
        raise OSError(ctypes.get_last_error(), 'Native handler did not acknowledge synchronous dispatch; do not resend automatically')


def hidden_client_form(handle, pid):
    import win32gui
    import win32process
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
        return False
    try:
        return (bool(win32gui.IsWindow(handle))
                and win32process.GetWindowThreadProcessId(handle)[1] == pid
                and not win32gui.IsWindowVisible(handle)
                and win32gui.GetClassName(handle) == 'TFrmConfigClient'
                and win32gui.GetWindowText(handle) == '客户端控制')
    except Exception:
        return False


class EngineUI:
    def __init__(self, root, pid, relative, *, expected_title=None, allow_blocked_main=False):
        from .native_control import native_forms
        from pywinauto import Application
        self.root, self.pid, self.executable = root, pid, root / relative
        self.verify()
        self.app = Application(backend='win32').connect(process=pid, timeout=10)
        mains = [w for w in native_forms(pid) if w.class_name().casefold() == 'tfrmmain']
        self.main = unique_main_form(mains)
        if expected_title is not None:
            verify_production_main_title(self.main, expected_title, allow_disabled=allow_blocked_main)

    def verify(self):
        if process_image(self.pid) != self.executable or sha256(self.executable) != BINARIES[self.executable.relative_to(self.root).as_posix()]:
            raise ValueError('Native PID, path or version no longer matches this lab')

    def dialogs(self):
        from .native_control import native_forms
        return [w for w in native_forms(self.pid) if w.class_name().casefold() != 'tfrmmain' and w.is_visible() and w.is_enabled()]

    def prepare_form(self, form, *, direct_menu=False):
        self.verify()
        if self.root in (independent_directory(SANDBOX_ROOT), independent_directory(COMPLETE_SANDBOX_ROOT)):
            sandbox_environment()
            if not form.is_visible():
                form.restore()
            if direct_menu:
                if form.handle != self.main.handle or not form.is_visible() or not form.is_enabled() or self.dialogs():
                    raise ValueError('Direct native menu requires the unblocked visible main form')
                active = active_thread_window(form.handle)
                if active not in (None, 0, form.handle):
                    if not hidden_client_form(active, getattr(self, 'pid', None)):
                        raise RuntimeError('Another native form is the thread active window')
                return True
            if not active_thread_window(form.handle):
                form.set_focus()
                self.verify()
            if active_thread_window(form.handle) != form.handle:
                raise RuntimeError('The exact native form is not the thread active window')
            return True
        form.set_focus()
        return False

    def menu(self, path, synchronous=False):
        self.verify()
        if not self.main.is_enabled() or self.dialogs():
            raise ValueError('Native main form is blocked by an existing dialog')
        menu = self.main.menu()
        command = menu_command_id(menu.get_properties(), path)
        self.prepare_form(self.main, direct_menu=True)
        self.verify()
        if synchronous:
            synchronous_menu_command(self.main.handle, command)
        else:
            self.main.post_message(0x111, command)

    def wait_dialog(self, cls, title, timeout=15, *, transition_from=None):
        previous = transition_from
        if previous is not None and (not isinstance(previous, tuple) or len(previous) != 3
                                     or not isinstance(previous[0], int) or isinstance(previous[0], bool)
                                     or previous[0] <= 0 or not all(isinstance(v, str) for v in previous[1:])):
            raise ValueError('Dialog transition requires a signature captured before dispatch')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dialogs = self.dialogs()
            if len(dialogs) == 1 and dialogs[0].class_name() == cls and dialogs[0].window_text() == title:
                return dialogs[0]
            if (previous is not None and len(dialogs) == 1
                    and (dialogs[0].handle, dialogs[0].class_name(), dialogs[0].window_text()) == previous):
                time.sleep(.1)
                continue
            if dialogs and any(w.class_name() != cls or w.window_text() != title for w in dialogs):
                observed = [{'handle': w.handle, 'class': w.class_name(), 'title': w.window_text()} for w in dialogs]
                raise RuntimeError('An unverified native dialog appeared; expected=' + repr((cls, title))
                                   + '; previous=' + repr(previous) + '; observed=' + json.dumps(observed, ensure_ascii=False))
            time.sleep(0.1)
        raise TimeoutError('The expected native dialog did not appear')

    def confirm_exit(self):
        dialog = self.wait_dialog('#32770', '确认信息')
        self.verify()
        guest = self.prepare_form(dialog)
        confirm_native_yes(dialog, '是否确认关闭游戏服务器？', require_foreground=not guest)


def wait_stopped(pid, executable, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if process_image(pid) != executable:
                return
        except ProcessLookupError:
            return
        time.sleep(0.25)
    raise TimeoutError('The copied native process did not finish its normal shutdown; no force-kill was used')


def stack_button(ui, caption):
    ui.verify()
    if not ui.main.is_enabled() or ui.dialogs():
        raise ValueError('Native controller is blocked by an existing dialog')
    controls = [c for c in ui.main.descendants(class_name='TButton')
                if c.is_visible() and c.is_enabled() and c.window_text() == caption]
    if len(controls) != 1:
        raise ValueError('Native stack button is missing, ambiguous or disabled')
    return controls[0]


def wait_stack_button(ui, caption, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ui.verify()
        if not ui.main.is_enabled() or ui.dialogs():
            raise RuntimeError('Controller became blocked while waiting for native finalization')
        try:
            return stack_button(ui, caption)
        except ValueError:
            time.sleep(.1)
    raise TimeoutError('Controller did not finish restoring its native button state')


def stack_ready(running, m2_initialized):
    return set(running) == set(STACK_COMPONENTS) and all(len(pids) == 1 for pids in running.values()) and m2_initialized


def stack_running(root):
    return {name: matching_processes(root / name, strict=True) for name in STACK_COMPONENTS}


def verify_controller_target(ui):
    from .native_control import read_ini
    ui.verify()
    configured = read_ini(ui.root / 'Config.ini')[0]['GameConf'].get('GameDirectory', '')
    match = re.search(r' \[([A-Za-z]:[\\/][^\]\r\n]+)\]$', ui.main.window_text())
    if (not PureWindowsPath(configured).is_absolute() or Path(configured).absolute() != ui.root
            or match is None or Path(match[1]).absolute() != ui.root):
        raise PermissionError('Native controller runtime/configuration target is not the fixed lab')


def stack_m2_ready(root, running):
    from .native_control import read_ini
    try:
        m2 = EngineUI(root, running['Mir200/M2Server.exe'][0], 'Mir200/M2Server.exe')
    except LookupError:
        return False
    log = m2.main.descendants(class_name='TRichView')
    text = log[0].window_text() if len(log) == 1 else ''
    listeners = tcp_listeners(running['Mir200/M2Server.exe'][0])
    if not listeners:
        return False
    if listeners != expected_m2_listeners(root):
        raise ValueError('Actual sandbox M2 listener differs from its native contract')
    cfg = read_ini(root / 'Mir200/!Setup.txt')[0]['Server']
    return all(marker in text for marker in ('游戏处理引擎初始化成功...',
        f"登录服务器({cfg['IDSAddr']}:{cfg['IDSPort']})连接成功...",
        f"数据库服务器({cfg['DBAddr']}:{cfg['DBPort']})连接成功..."))


def stack_confirm(ui, body):
    import win32process
    dialog = ui.wait_dialog('#32770', '确认信息')
    ui.verify()
    if win32process.GetWindowThreadProcessId(dialog.handle)[1] != ui.pid:
        raise ValueError('Native stack confirmation belongs to another process')
    confirm_native_yes(dialog, body, require_foreground=False)


def start_stack(root):
    from pywinauto.controls.common_controls import TabControlWrapper
    from pywinauto.controls.win32_controls import ButtonWrapper
    if matching_processes(root / 'GameCenter.exe', strict=True) or any(stack_running(root).values()):
        raise ValueError('The sandbox stack must be fully stopped before a new start')
    started = start_program(root, 'GameCenter.exe')
    ui = EngineUI(root, started['pid'], 'GameCenter.exe')
    verify_controller_target(ui)
    ui.main.restore()
    pages = [c for c in ui.main.descendants(class_name='TPageControl') if c.parent().handle == ui.main.handle]
    if len(pages) != 1:
        raise ValueError('Native controller page structure differs')
    TabControlWrapper(pages[0].element_info).select(0)
    checks = [c for c in ui.main.descendants(class_name='TCheckBox') if c.is_visible()]
    captions = [c.window_text() for c in checks]
    if len(captions) != len(set(captions)) or not STACK_CHECKS.issubset(captions):
        raise ValueError('Native server component checkboxes differ')
    for control in checks:
        desired = control.window_text() in STACK_CHECKS
        if bool(ButtonWrapper(control.element_info).get_check_state()) != desired:
            ui.verify()
            control.post_message(0xF5, 0, 0)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and bool(ButtonWrapper(control.element_info).get_check_state()) != desired:
                time.sleep(.05)
        if bool(ButtonWrapper(control.element_info).get_check_state()) != desired:
            raise RuntimeError('Native component checkbox did not retain its state')
    stack_button(ui, '启动游戏服务器(&S)').post_message(0xF5, 0, 0)
    stack_confirm(ui, '是否确认启动游戏服务器?')
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        ui.verify()
        if ui.dialogs():
            raise RuntimeError('Native stack start opened an unverified dialog')
        running = stack_running(root)
        if all(len(pids) == 1 for pids in running.values()):
            if stack_ready(running, stack_m2_ready(root, running)):
                wait_stack_button(ui, '停止游戏服务器(&T)')
                return {'pid': ui.pid, 'allSevenComponentsRunning': True, 'nativeInitialized': True,
                        'components': {name: {'pid': pids[0], 'listeners': tcp_listeners(pids[0])} for name, pids in running.items()},
                        'networkIsolation': sandbox_environment(), 'gameAcceptancePerformed': False}
        time.sleep(.5)
    raise TimeoutError(f'Sandbox controller PID {ui.pid} did not reach complete native readiness; no force-kill was used')


def stop_stack(root, pid):
    for name, expected in STACK_BINARIES.items():
        if sha256(root / name) != expected:
            raise ValueError('Sandbox stack binary changed before stop: ' + name)
    ui = EngineUI(root, pid, 'GameCenter.exe')
    verify_controller_target(ui)
    before = stack_running(root)
    stack_button(ui, '停止游戏服务器(&T)').post_message(0xF5, 0, 0)
    stack_confirm(ui, '是否确认停止游戏服务器?')
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and any(stack_running(root).values()):
        ui.verify()
        if ui.dialogs():
            raise RuntimeError('Native stack stop opened an unverified dialog')
        time.sleep(.5)
    after = stack_running(root)
    if any(after.values()):
        raise TimeoutError('The sandbox components did not finish normal shutdown; no force-kill was used')
    wait_stack_button(ui, '启动游戏服务器(&S)')
    verify_controller_target(ui)
    ui.main.post_message(0x10)
    stack_confirm(ui, '是否确认关闭控制台 ?')
    wait_stopped(pid, ui.executable, timeout=25)
    return {'pid': pid, 'normalShutdownVerified': True, 'controllerNormalShutdownVerified': True,
            'componentsBeforeStop': before, 'componentsAfterStop': after, 'gameAcceptancePerformed': False}


def expected_m2_listeners(root):
    root = independent_directory(root)
    if root == independent_directory(COMPLETE_SANDBOX_ROOT):
        from .native_control import read_ini
        cfg = read_ini(root / 'Mir200/!Setup.txt')[0]['Server']
        return [{'address': cfg['GateAddr'], 'port': int(cfg['GatePort'])}]
    return [{'address': '127.0.0.1', 'port': 25000}]


def start_program(root, relative):
    exe = root / relative
    if matching_processes(exe):
        raise ValueError('A copied instance is already running; refuse to launch a duplicate')
    if relative == 'GameCenter.exe' and any(matching_processes(root / name) for name in ('Mir200/M2Server.exe', 'DBServer/DBServer.exe')):
        raise ValueError('Stop copied components before starting a controller that regenerates configuration')
    if relative.startswith('Mir200/'):
        listener_contract = expected_m2_listeners(root)
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((listener_contract[0]['address'], listener_contract[0]['port']))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    configs_before = {name: (root / name).read_bytes() for name in CONFIGS} if relative == 'GameCenter.exe' else {}
    child = subprocess.Popen([str(exe)], cwd=exe.parent, startupinfo=startup)
    ready = False
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError('The native copy exited before readiness')
            try:
                ui = EngineUI(root, child.pid, relative)
                if relative == 'GameCenter.exe':
                    title = ui.main.window_text()
                    if title == '翎风引擎控制台':
                        time.sleep(.1)
                        continue
                    if str(root) not in title:
                        raise ValueError('Native controller title does not identify the private root')
                    if ui.main.is_enabled() and not ui.dialogs():
                        changed = [name for name, raw in configs_before.items() if (root / name).read_bytes() != raw]
                        for name in changed:
                            (root / name).write_bytes(configs_before[name])
                        preflight(root)
                        ready = True
                        return {'pid': child.pid, 'executable': str(exe), 'controllerOnly': True,
                                'nativeRegeneratedConfigsRestored': changed}
                else:
                    rows = tcp_listeners(child.pid)
                    if rows and rows != listener_contract:
                        raise ValueError('Actual copied M2 listeners are not isolated')
                    if rows and ui.main.is_enabled() and not ui.dialogs():
                        log = ui.main.descendants(class_name='TRichView')
                        if len(log) == 1 and '游戏处理引擎初始化成功...' in log[0].window_text():
                            ready = True
                            return {'pid': child.pid, 'executable': str(exe), 'listeners': rows, 'nativeInitialized': True}
            except ValueError:
                raise
            except Exception:
                pass
            time.sleep(0.25)
        raise TimeoutError(f'Native copy PID {child.pid} did not reach verified readiness')
    finally:
        if not ready:
            initial = sys.exception()
            failures = []
            try:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)
            except Exception as error:
                failures.append('copied PID ' + str(child.pid) + ' cleanup: ' + str(error))
            for name, raw in configs_before.items():
                try:
                    (root / name).write_bytes(raw)
                except Exception as error:
                    failures.append('configuration restore ' + name + ': ' + str(error))
            if failures:
                raise RuntimeError('Native startup failed: ' + str(initial) + '; ' + '; '.join(failures)) from initial


def open_parameter_field(ui):
    from pywinauto.controls.win32_controls import EditWrapper
    ui.menu(['选项(&P)', '参数设置(&O)'])
    form = ui.wait_dialog('TfrmGameConfig', '游戏参数')
    groups = [c for c in form.descendants(class_name='TGroupBox') if c.window_text() == '控制台显示人数时间(秒)' and c.is_visible()]
    fields = groups[0].descendants(class_name='TSpinEditEx') if len(groups) == 1 else []
    if len(fields) != 1:
        form.post_message(0x10)
        raise ValueError('The verified parameter group is not available')
    return form, EditWrapper(fields[0].element_info)


def close_parameter_form(ui, form):
    ui.verify()
    form.post_message(0x10)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if ui.main.is_enabled() and not ui.dialogs():
            return
        time.sleep(0.1)
    raise TimeoutError('Native parameter form did not close')


def change_parameter(ui, args):
    path = ui.root / 'Mir200/!Setup.txt'
    before = path.read_bytes()
    key = ('Setup', 'ConsoleShowUserCountTime')
    if ini_bytes(before).get(key) != str(args['expectedValue'] * 1000):
        raise ValueError('Parameter file precondition differs')
    backup = ui.root / '_NativeControlBackups' / (uuid.uuid4().hex + '.ini')
    backup.parent.mkdir(exist_ok=True)
    backup.write_bytes(before)

    form, field = open_parameter_field(ui)
    try:
        if field.window_text() != str(args['expectedValue']):
            raise ValueError('Native parameter precondition differs')
        ui.verify()
        field.set_edit_text(str(args['value']))
        if field.window_text() != str(args['value']):
            raise RuntimeError('Native field did not retain the requested value')
        buttons = [c for c in form.descendants(class_name='TButton') if c.window_text() == '保存(&S)' and c.is_visible() and c.is_enabled()]
        if len(buttons) != 1:
            raise ValueError('Native parameter save button differs')
        ui.verify()
        if ui.prepare_form(form):
            buttons[0].post_message(0xF5, 0, 0)
        else:
            buttons[0].click_input()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and ini_bytes(path.read_bytes()).get(key) != str(args['value'] * 1000):
            time.sleep(0.1)
        after = path.read_bytes()
        verify_saved_parameter(before, after, args['expectedValue'], args['value'])
        if ini_bytes(after).get(key) != str(args['value'] * 1000):
            raise RuntimeError('Native parameter save was not read back')
    finally:
        close_parameter_form(ui, form)
    form, field = open_parameter_field(ui)
    try:
        if field.window_text() != str(args['value']):
            raise RuntimeError('Reopened native parameter did not retain the saved value')
    finally:
        close_parameter_form(ui, form)
    return {'parameter': args['parameter'], 'oldValue': args['expectedValue'], 'newValue': args['value'], 'unit': 'seconds',
            'fileUnit': 'milliseconds', 'backupPath': str(backup), 'nativeSaveAndReopenVerified': True, 'fileSha256': sha256(path)}


def run_engine(request):
    if request['command'] == 'engine-preflight':
        return _run_engine(request)
    with serial_engine_operation():
        return _run_engine(request)


def client_build_paths(root, source, output):
    root, source, output = map(independent_directory, (root, source, output))
    if (not source.is_dir() or source == root or not source.is_relative_to(root)
            or output == root or not output.is_relative_to(root)
            or output.is_relative_to(source) or source.is_relative_to(output)):
        raise ValueError('Client build paths must be separate children of the copied lab')
    if output.exists():
        raise FileExistsError('Client build outputRoot must be new')
    if any(p.lstat().st_file_attributes & 0x400 for p in source.rglob('*')):
        raise ValueError('Generator bundle contains reparse points')
    return source, output


def production_client_build_paths(source, output, *, resume=False):
    source = _exact_path(source, PRODUCTION_SOURCE, 'sourceDirectory')
    output = Path(output).resolve(strict=False)
    base = PRODUCTION_OUTPUT_BASE.resolve(strict=True)
    if output == base or not output.is_relative_to(base):
        raise PermissionError('Production build output is outside the authorized task root')
    if output.exists() and not resume:
        raise FileExistsError('Production build outputRoot must be new')
    if resume and not output.is_dir():
        raise FileNotFoundError('Production resume outputRoot is missing')
    if any(p.lstat().st_file_attributes & 0x400 for p in source.rglob('*')):
        raise ValueError('Generator bundle contains reparse points')
    return source, output


def update_wil_resources(ui):
    from pywinauto.controls.common_controls import TabControlWrapper
    ui.menu(['查看(&V)', '列表信息二(&T)'])
    form = ui.wait_dialog('TFrmViewList2', '查看列表信息', timeout=30)
    pages = [c for c in form.descendants(class_name='TPageControl')
             if 'WIL资源' in TabControlWrapper(c.element_info).texts()]
    if len(pages) != 1:
        raise RuntimeError('Native WIL page signature differs')
    ui.prepare_form(form)
    TabControlWrapper(pages[0].element_info).select('WIL资源')
    buttons = [c for c in form.descendants(class_name='TButton')
               if c.window_text() == '更新到客户端(&R)' and c.is_visible() and c.is_enabled()]
    if len(buttons) != 1:
        raise RuntimeError('Native WIL update button signature differs')
    before = (ui.root / 'Mir200/Envir/EffectImageList.txt').read_bytes()
    ui.prepare_form(form)
    ui.verify()
    synchronous_button_click(buttons[0].handle)
    ui.verify()
    if (ui.root / 'Mir200/Envir/EffectImageList.txt').read_bytes() != before:
        raise RuntimeError('Unexpected WIL source list mutation')
    forms = ui.dialogs()
    if len(forms) != 1 or forms[0].handle != form.handle:
        raise RuntimeError('WIL update opened an unverified native dialog')
    form.post_message(0x10)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not ui.dialogs() and ui.main.is_enabled():
            return {'nativeButtonDispatchAcknowledged': True, 'sourceListUnchanged': True,
                    'clientDeliveryVerified': False, 'clientDatGenerated': False}
        time.sleep(.1)
    raise TimeoutError('WIL list form did not close')


def monster_export_message_verified(texts):
    return texts == ['已经生成自定义怪物登录器配置文件']


def confirm_monster_export(ui, target, previous=None):
    from pywinauto import Application
    dialog = ui.wait_dialog('#32770', 'M2server', timeout=30, transition_from=previous)
    wrapper = Application(backend='uia').connect(process=ui.pid).window(handle=dialog.handle)
    controls = wrapper.descendants()
    texts = [c.window_text() for c in controls
             if c.element_info.control_type == 'Text' and c.element_info.automation_id == 'ContentText']
    buttons = [c for c in dialog.descendants(class_name='Button') if c.is_visible() and c.is_enabled()]
    if not monster_export_message_verified(texts) or [c.window_text() for c in buttons] != ['OK']:
        raise RuntimeError('Unverified native monster export completion dialog')
    if not target.is_file() or not 0 < target.stat().st_size <= 64 * 1024 * 1024:
        raise RuntimeError('Native completion lacks a bounded nonempty exported DAT')
    invokes = [c for c in controls if c.element_info.control_type == 'Button'
               and c.element_info.automation_id == 'CommandButton_1' and c.window_text() == 'OK'
               and c.handle == buttons[0].handle]
    if len(invokes) != 1:
        raise RuntimeError('Native task-dialog Invoke target differs from the verified OK button')
    guard = ui.__dict__.get('production_guard')
    if guard is None:
        sandbox_environment()
    else:
        guard()
    ui.verify()
    invokes[0].invoke()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        forms = ui.dialogs()
        if len(forms) == 1 and forms[0].class_name() == 'TfrmMonsterConfig' and forms[0].is_enabled():
            forms[0].post_message(0x10)
            break
        time.sleep(.1)
    else:
        raise TimeoutError('Monster settings did not return after export')
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not ui.dialogs() and ui.main.is_enabled():
            return {'path': str(target), 'size': target.stat().st_size, 'sha256': sha256(target),
                    'nativeCompletionVerified': True}
        time.sleep(.1)
    raise TimeoutError('Monster settings did not close after native export')


def inspect_resume_monster_export_state(ui):
    forms = ui.dialogs()
    if ui.main.is_enabled() or len(forms) != 1:
        raise RuntimeError('Interrupted export is not at the verified success or post-confirm monster-settings state')
    form = forms[0]
    if (form.class_name() == '#32770' and form.window_text() == 'M2server'
            and form.is_visible() and form.is_enabled()):
        return 'success-dialog', form
    if (form.class_name() == 'TfrmMonsterConfig' and form.window_text() == '怪物设置'
            and form.is_visible() and form.is_enabled()):
        return 'post-confirm-monster-settings', form
    raise RuntimeError('Interrupted export is not at the verified success or post-confirm monster-settings state')


def resume_monster_export(ui, target):
    state, form = inspect_resume_monster_export_state(ui)
    if state == 'success-dialog':
        return {**confirm_monster_export(ui, target), 'resumedAt': 'success-dialog'}
    guard = ui.__dict__.get('production_guard')
    if guard is None:
        raise PermissionError('Production resume requires runtime identity and DAT revalidation')
    runtime = guard()
    form.post_message(0x10)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not ui.dialogs() and ui.main.is_enabled():
            return {'path': str(target), 'size': target.stat().st_size, 'sha256': sha256(target),
                    'nativeCompletionVerified': True, 'resumedAt': 'post-confirm-monster-settings',
                    'runtimeBinding': runtime}
        time.sleep(.1)
    raise TimeoutError('Monster settings did not close during interrupted export resume')


def export_monsters(ui, target):
    from pywinauto.controls.common_controls import TabControlWrapper
    from pywinauto.controls.win32_controls import EditWrapper
    if target.exists() or not target.parent.is_dir():
        raise ValueError('Export requires a new file in an existing private job directory')
    ui.menu(['选项(&P)', '怪物设置(&G)'])
    form = ui.wait_dialog('TfrmMonsterConfig', '怪物设置', timeout=30)
    pages = [c for c in form.descendants(class_name='TPageControl')
             if '自定义怪物' in TabControlWrapper(c.element_info).texts()]
    if len(pages) != 1:
        raise RuntimeError('Native custom-monster page signature differs')
    ui.prepare_form(form)
    TabControlWrapper(pages[0].element_info).select('自定义怪物')
    buttons = [c for c in form.descendants(class_name='TButton')
               if c.window_text() == '生成登录器集成文件' and c.is_visible() and c.is_enabled()]
    if len(buttons) != 1:
        raise RuntimeError('Native monster export button signature differs')
    ui.prepare_form(form)
    ui.verify()
    previous = (form.handle, form.class_name(), form.window_text())
    buttons[0].post_message(0xF5, 0, 0)
    dialog = ui.wait_dialog('#32770', '生成登录器配置文件', transition_from=previous)
    filters = [c for c in dialog.descendants(class_name='ComboBox')
               if c.window_text() == '怪物配置文件(*.dat)' and c.is_visible()]
    edits = [c for c in dialog.descendants(class_name='Edit') if c.is_visible() and c.is_enabled()]
    saves = [c for c in dialog.descendants(class_name='Button')
             if c.window_text() == '保存(&S)' and c.is_visible() and c.is_enabled()]
    if len(filters) != 1 or len(edits) != 1 or len(saves) != 1:
        raise RuntimeError('Native monster save dialog signature differs')
    ui.prepare_form(dialog)
    field = EditWrapper(edits[0].element_info)
    field.set_edit_text(str(target))
    if field.window_text() != str(target):
        raise RuntimeError('Native export filename readback differs')
    ui.verify()
    previous = (dialog.handle, dialog.class_name(), dialog.window_text())
    saves[0].post_message(0xF5, 0, 0)
    return confirm_monster_export(ui, target, previous=previous)


def client_build(ui, args, *, production=False, production_request=None):
    from .native_control import fingerprints, read_ini, run, validate_request, LAUNCHER_SHA256
    resume = production and args.get('resumeExistingExport') is True
    source, output = (production_client_build_paths(args['sourceDirectory'], args['outputRoot'], resume=resume)
                      if production else client_build_paths(ui.root, args['sourceDirectory'], args['outputRoot']))
    if sha256(source / 'MakeGameLogin.exe') != LAUNCHER_SHA256:
        raise ValueError('Generator version differs from the verified build')
    validate_request({'schemaVersion': 1, 'command': 'launcher-build',
                      'arguments': {'sourceDirectory': str(source), 'outputRoot': str(output / 'build')},
                      'policy': {'allowedWriteRoots': [str(output)]}})
    original = fingerprints(source)
    if resume:
        bundle = output / 'input'
    else:
        output.mkdir(parents=True, exist_ok=False)
        bundle = output / 'input'
        shutil.copytree(source, bundle)
    target = bundle / 'native-custom-monsters.dat'
    if target.exists() and not resume:
        raise FileExistsError('Reserved export filename already exists in source bundle')
    wil_update = {'requested': False, 'performed': False} if production else update_wil_resources(ui)
    if production and production_request is not None:
        def production_guard():
            verify_production_main_title(ui.main, production_request['arguments']['expectedWindowTitle'], allow_disabled=True)
            return validate_production_runtime(production_request, target)
        ui.production_guard = production_guard
    export = resume_monster_export(ui, target) if resume else export_monsters(ui, target)
    cfg, encoding = read_ini(bundle / 'Config.ini')
    cfg['Setup']['集成怪物配置'] = '1'
    cfg['Setup']['怪物配置文件'] = target.name
    stream = io.StringIO()
    cfg.write(stream, space_around_delimiters=False)
    (bundle / 'Config.ini').write_bytes(stream.getvalue().replace('\n', '\r\n').encode(encoding))
    try:
        built = run({'schemaVersion': 1, 'command': 'launcher-build',
                     'arguments': {'sourceDirectory': str(bundle), 'outputRoot': str(output / 'build')},
                     'policy': {'allowedWriteRoots': [str(output)]}})
        saved, _ = read_ini(output / 'build/generator/Config.ini')
        if (saved['Setup'].get('集成怪物配置') != '1'
                or saved['Setup'].get('怪物配置文件') != target.name
                or built['sourceFiles'].get(target.name) != export['sha256']
                or sha256(output / 'build/generator' / target.name) != export['sha256']):
            raise RuntimeError('Native exported DAT integration binding differs after build')
        return {'outputRoot': str(output), 'exportKind': 'custom-monsters', 'wilUpdate': wil_update, 'export': export, 'build': built,
                'exportInputBindingVerified': True, 'gameAcceptancePerformed': False,
                'wilOnlineUpdateVerified': False, 'productionServerTouched': production,
                'productionServerFilesChanged': False, 'actualClientRootWritePerformed': False,
                'resumedExistingExport': resume}
    finally:
        if fingerprints(source) != original:
            raise RuntimeError('Original copied generator source changed')
def _run_engine(request):
    args, command = request.get('arguments', {}), request['command']
    validate_operation(command, args)
    production = args.get('mode') == PRODUCTION_MODE
    root = validate_production_authorization(request, verify_live=True) if production else validate_lab_root(args['labRoot'])
    stopping = command in ('m2-stop', 'engine-controller-stop', 'engine-stop')
    report = None if production or stopping else preflight(root)
    if command == 'engine-preflight':
        return report
    if not production:
        WritePolicy(request.get('policy', {}).get('allowedWriteRoots', [])).assert_writable(root)
    if command == 'engine-start':
        return {**start_stack(root), 'retainedLegacyPaths': report['retainedLegacyPaths']}
    if command == 'engine-stop':
        pid = args.get('pid')
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
            raise ValueError('An explicit current sandbox controller PID is required')
        return stop_stack(root, pid)
    relative = 'GameCenter.exe' if command.startswith('engine-controller-') else 'Mir200/M2Server.exe'
    if command.endswith('-start'):
        return {**start_program(root, relative), 'retainedLegacyPaths': report['retainedLegacyPaths']}
    pid = args.get('pid')
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        raise ValueError('An explicit current copied PID is required')
    resume = production and command == 'm2-client-build' and args.get('resumeExistingExport') is True
    ui = EngineUI(root, pid, relative, expected_title=args.get('expectedWindowTitle') if production else None,
                  allow_blocked_main=resume)
    if resume:
        inspect_resume_monster_export_state(ui)
    if command == 'm2-client-build':
        return client_build(ui, args, production=production, production_request=request if production else None)
    if command == 'm2-stop':
        ui.menu(['控制(&C)', '退出(&X)'])
        ui.confirm_exit()
        wait_stopped(pid, ui.executable)
        return {'pid': pid, 'normalShutdownVerified': True}
    if command == 'engine-controller-stop':
        if matching_processes(root / 'Mir200/M2Server.exe') or matching_processes(root / 'DBServer/DBServer.exe'):
            raise ValueError('Stop the copied components first; controller bulk stop is not exposed')
        buttons = [c.window_text() for c in ui.main.descendants(class_name='TButton')]
        if '启动游戏服务器(&S)' not in buttons or '停止游戏服务器(&T)' in buttons:
            raise ValueError('Controller managed-server stop is not verified')
        dialogs = ui.dialogs()
        if not dialogs:
            if not ui.main.is_enabled():
                raise ValueError('Controller is blocked by a dialog')
            ui.main.post_message(0x10)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    ui.verify()
                except ProcessLookupError:
                    return {'pid': pid, 'controllerOnly': True, 'normalShutdownVerified': True}
                dialogs = ui.dialogs()
                if dialogs:
                    break
                time.sleep(0.1)
        if dialogs:
            if len(dialogs) != 1:
                raise ValueError('Controller has multiple dialogs')
            ui.verify()
            guest = ui.prepare_form(dialogs[0])
            confirm_native_yes(dialogs[0], '是否确认关闭控制台 ?', require_foreground=not guest)
        wait_stopped(pid, ui.executable, timeout=15)
        return {'pid': pid, 'controllerOnly': True, 'normalShutdownVerified': True}
    if command == 'engine-parameter':
        return change_parameter(ui, args)
    log = ui.main.descendants(class_name='TRichView')
    if len(log) != 1:
        raise ValueError('Native M2 log control differs')
    before = log[0].window_text()
    ui.menu(['控制(&C)', '重新加载(&R)', RELOADS[args['target']]], synchronous=args['target'] == 'parameters')
    if args['target'] == 'parameters':
        expected = ini_bytes((root / 'Mir200/!Setup.txt').read_bytes())[('Setup', 'ConsoleShowUserCountTime')]
        form, field = open_parameter_field(ui)
        try:
            if str(int(field.window_text()) * 1000) != expected:
                raise RuntimeError('Supported native parameter readback differs after reload')
        finally:
            close_parameter_form(ui, form)
        return {'pid': pid, 'target': 'parameters', 'nativeDispatchVerified': True,
                'readbackParameter': 'ConsoleShowUserCountTime', 'readbackMilliseconds': int(expected),
                'otherParameterEffectsVerified': False, 'gameAcceptancePerformed': False}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        current = log[0].window_text()
        delta = new_log_text(before, current)
        if ui.dialogs():
            raise RuntimeError('Reload opened an unverified dialog')
        if any(text in delta for text in ('Access violation', 'Invalid pointer', '失败', 'Error', '异常')):
            raise RuntimeError('The native reload reported an error')
        if reload_acknowledged(args['target'], delta) and ui.main.is_enabled():
            return {'pid': pid, 'target': args['target'], 'nativeAcknowledgement': delta[-3000:], 'gameAcceptancePerformed': False}
        time.sleep(0.1)
    raise TimeoutError('Reload was dispatched but no matching native acknowledgement was observed')
