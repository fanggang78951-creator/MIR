"""Passive, version-pinned Delphi published-method evidence for one fixed form.

This module cannot select addresses, change page protection, attach a debugger,
inject, read heap objects, invoke handlers, or prove live-instance event pointers.
All target reads are limited to the fixed main-image profile below.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import struct
from pathlib import Path, PureWindowsPath

from .policy import DEFAULT_PROTECTED_ROOTS, WritePolicy

COMMAND = 'm2-event-evidence'
PROFILE = 'custom-monster-summon-v1'
EXECUTABLE = r'D:\Mirserver100\Mir200\M2Server.exe'
EXECUTABLE_SHA256 = '1D4D58A4C49EE97D2844FCB2BB31EA3E1F11E7FEDE4DBC857A3FE21979723F1A'
IMAGE_SIZE = 0x3941000
PROCESS_READ_ACCESS = 0x0400 | 0x0010
METADATA_RVA, METADATA_SIZE = 0xFA0000, 0x20000
VMT_RVA, SELF_RVA = 0xFB4428, 0xFB4360
METHOD_POINTER_RVA, CLASS_POINTER_RVA = 0xFB4390, 0xFB43A0
CLASS_RVA, CLASS_NAME = 0xFBF248, 'TfrmMonsterConfig'
TABLE_RVA, TABLE_COUNT, TABLE_END_RVA = 0xFBC476, 243, 0xFBE6BE
DFM_RVA, DFM_SIZE = 0x28452B8, 94135
DFM_SHA256 = 'B93FEA8C41F1508C5F6F61B32B7A07967216575060432C1B7BB6421D31A80AA9'
RESOURCE_PATH = [10, 'TFRMMONSTERCONFIG', 0]
SNIPPET_SIZE = 512
SHARED_SUCCESSOR_RVA = 0xFD1F30
HANDLERS = (
    ('edtCallMonster1Change', 104, 0xFBD2EE, 32, 0xFCFC90),
    ('seCallMonsterNum1Change', 105, 0xFBD30E, 34, 0xFCFD90),
    ('seCallMonstersRateChange', 134, 0xFBD70E, 35, 0xFCFC50),
)
# Source-derived constants from the fully consumed 94135-byte DFM inventory.
# Tag is the effective Delphi default (0) where no Tag property is serialized.
# The runtime DFM SHA256 binds this profile; no generic DFM parser is exposed.
CONTROLS = (
    ('edtCallMonster1', 'TEdit', 'edtCallMonster1Change', 0, 62057),
    ('seCallMonsterNum1', 'TSpinEditEx', 'seCallMonsterNum1Change', 0, 62154),
    ('edtCallMonster2', 'TEdit', 'edtCallMonster1Change', 1, 62292),
    ('seCallMonsterNum2', 'TSpinEditEx', 'seCallMonsterNum1Change', 1, 62395),
    ('edtCallMonster3', 'TEdit', 'edtCallMonster1Change', 2, 62539),
    ('seCallMonsterNum3', 'TSpinEditEx', 'seCallMonsterNum1Change', 2, 62642),
    ('edtCallMonster4', 'TEdit', 'edtCallMonster1Change', 3, 62786),
    ('seCallMonsterNum4', 'TSpinEditEx', 'seCallMonsterNum1Change', 3, 62889),
    ('seCallMonstersRate', 'TSpinEditEx', 'seCallMonstersRateChange', 0, 63033),
)
PROTECTED_ROOTS = (*DEFAULT_PROTECTED_ROOTS, Path(r'D:\Mirserver100'),
                   Path(r'E:\XuanYuanDevPlatform'), Path(__file__).resolve().parents[1])


def _hash(raw):
    return hashlib.sha256(raw).hexdigest().upper()


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest().upper()


def _same_path(left, right):
    return isinstance(left, str) and str(PureWindowsPath(left)).casefold() == str(PureWindowsPath(right)).casefold()


def _integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(label+' is outside its integer range')
    return value


def _independent(value):
    if not isinstance(value, str) or not value or '\x00' in value or not Path(value).is_absolute():
        raise ValueError('outputRoot must be an absolute path')
    original = Path(value).absolute()
    for item in (original, *original.parents):
        try:
            if getattr(item.lstat(), 'st_file_attributes', 0) & 0x400 or item.is_symlink():
                raise ValueError('Evidence paths must not contain reparse points')
        except FileNotFoundError:
            pass
    return original.resolve(strict=False)


def validate_request(request):
    if not isinstance(request, dict) or set(request)-{'schemaVersion', 'command', 'arguments', 'policy'}:
        raise ValueError('Unexpected request fields')
    if type(request.get('schemaVersion')) is not int or request['schemaVersion'] != 1 or request.get('command') != COMMAND:
        raise ValueError('Unknown event evidence command or schemaVersion')
    args = request.get('arguments')
    fields = {'pid', 'expectedExecutable', 'expectedSha256', 'profile', 'outputRoot'}
    if not isinstance(args, dict) or set(args) != fields:
        raise ValueError('Event evidence requires exactly the fixed argument fields')
    _integer(args['pid'], 'pid', 1, 0xFFFFFFFF)
    if not _same_path(args['expectedExecutable'], EXECUTABLE):
        raise PermissionError('Only the fixed disposable M2 executable path is supported')
    if not isinstance(args['expectedSha256'], str) or args['expectedSha256'].upper() != EXECUTABLE_SHA256:
        raise PermissionError('Only the version-pinned original M2 SHA256 is supported')
    if args['profile'] != PROFILE:
        raise ValueError('Only the fixed custom-monster-summon-v1 profile is supported')
    policy_args = request.get('policy')
    if not isinstance(policy_args, dict) or set(policy_args) != {'allowedWriteRoots'}:
        raise ValueError('Unexpected or missing policy fields')
    roots = policy_args['allowedWriteRoots']
    if not isinstance(roots, list) or any(not isinstance(root, str) or not root or '\x00' in root for root in roots):
        raise ValueError('allowedWriteRoots must be a path list')
    if any(not Path(root).is_absolute() for root in roots):
        raise ValueError('allowedWriteRoots must contain absolute paths')
    output = _independent(args['outputRoot'])
    WritePolicy(roots, protected_roots=PROTECTED_ROOTS).assert_writable(output)
    if output.exists():
        raise FileExistsError('outputRoot must be a new independent directory')
    return {'command': COMMAND, 'arguments': dict(args), 'output': output}


def _check_identity(info, pid):
    if not isinstance(info, dict) or info.get('pid') != pid:
        raise ValueError('Process identity is incomplete or changed')
    if not _same_path(info.get('executable'), EXECUTABLE) or not _same_path(info.get('modulePath'), EXECUTABLE):
        raise PermissionError('Process or main module executable path changed')
    if info.get('sha256') != EXECUTABLE_SHA256:
        raise PermissionError('Process executable SHA256 changed')
    created = info.get('processCreated')
    if not isinstance(created, str) or not created.isdigit() or int(created) <= 0:
        raise ValueError('Process creation identity is missing')
    _integer(info.get('base'), 'main image base', 0x10000, (1 << 64)-1-IMAGE_SIZE)
    if info.get('size') != IMAGE_SIZE or info.get('machine') != 0x8664:
        raise ValueError('Main image size or machine differs from fixed profile')
    if info.get('resource') != {'path': RESOURCE_PATH, 'rva': DFM_RVA, 'size': DFM_SIZE, 'rawFileOffset': None}:
        raise ValueError('Fixed TFRMMONSTERCONFIG PE resource directory entry changed')
    return info


def read_image(backend, handle, image, rva, size, *, executable=False):
    """Read only a proven, committed, readable range of the current main image."""
    _integer(rva, 'image RVA', 0, image['size']-1)
    _integer(size, 'image read size', 1, METADATA_SIZE)
    if rva+size > image['size']:
        raise ValueError('Read would escape main image bounds')
    address, end = image['base']+rva, image['base']+rva+size
    pieces, pages, chunks = [], [], []
    while address < end:
        page = backend.query(handle, address)
        if not isinstance(page, dict):
            raise ValueError('VirtualQueryEx did not return a memory region')
        for field in ('base', 'size', 'allocationBase', 'state', 'type', 'protect'):
            _integer(page.get(field), 'memory region '+field, 0, (1 << 64)-1)
        page_end = page['base']+page['size']
        if page['size'] == 0 or not page['base'] <= address < page_end:
            raise ValueError('VirtualQueryEx region does not cover requested address')
        protection = page['protect']
        if (page['state'] != 0x1000 or page['type'] != 0x1000000 or
                page['allocationBase'] != image['base'] or protection & (0x100 | 0x01) or
                protection & 0xFF not in (0x02, 0x04, 0x08, 0x20, 0x40, 0x80)):
            raise PermissionError('Read requires committed readable MEM_IMAGE pages in the main module')
        if executable and protection & 0xFF not in (0x20, 0x40, 0x80):
            raise PermissionError('Entry snippet requires a readable executable image page')
        count = min(end, page_end)-address
        chunks.append((address, count))
        pages.append({key: page[key] for key in ('base', 'size', 'allocationBase', 'state', 'type', 'protect')})
        address += count
    # A denied later page must not cause a partial RPM of this requested range.
    for address, count in chunks:
        raw = backend.read(handle, address, count)
        if not isinstance(raw, bytes) or len(raw) != count:
            raise ValueError('ReadProcessMemory returned a short read')
        pieces.append(raw)
    return b''.join(pieces), pages


def _bounded(metadata, rva, size):
    offset = rva-METADATA_RVA
    if offset < 0 or size <= 0 or offset+size > len(metadata):
        raise ValueError('Published method proof is truncated or outside its fixed metadata window')
    return metadata[offset:offset+size]


def _proof(metadata, rva, size, base):
    raw = _bounded(metadata, rva, size)
    return {'rva': rva, 'va': base+rva, 'size': size, 'sha256': _hash(raw), 'hex': raw.hex().upper(),
            'provenance': 'loaded-memory', 'rawFileOffset': None}


def published_binding(metadata, base):
    """Validate the complete audited table and VMT chain; never scan for names."""
    if len(metadata) != METADATA_SIZE:
        raise ValueError('Fixed metadata proof window is truncated')
    for slot, expected in ((SELF_RVA, VMT_RVA), (METHOD_POINTER_RVA, TABLE_RVA), (CLASS_POINTER_RVA, CLASS_RVA)):
        if struct.unpack('<Q', _bounded(metadata, slot, 8))[0] != base+expected:
            raise ValueError('Fixed VMT self/class/method-table pointer relationship changed')
    if _bounded(metadata, CLASS_RVA, len(CLASS_NAME)+1) != bytes([len(CLASS_NAME)])+CLASS_NAME.encode('ascii'):
        raise ValueError('Fixed VMT class ShortString changed')
    if struct.unpack('<H', _bounded(metadata, TABLE_RVA, 2))[0] != TABLE_COUNT:
        raise ValueError('Published method table count changed')
    cursor, names, target_records, shared_matches = TABLE_RVA+2, set(), {}, []
    targets = {item[1]: item for item in HANDLERS}
    for index in range(TABLE_COUNT):
        length = struct.unpack('<H', _bounded(metadata, cursor, 2))[0]
        if length < 12 or cursor+length > TABLE_END_RVA:
            raise ValueError('Published method record length escapes fixed table bounds')
        raw = _bounded(metadata, cursor, length)
        if length != 11+raw[10]:
            raise ValueError('Published method record has unsupported trailing or truncated data')
        try:
            name = raw[11:].decode('ascii')
        except UnicodeDecodeError as exc:
            raise ValueError('Published method name is not ASCII') from exc
        if not name or any(not (character.isascii() and (character.isalnum() or character == '_')) for character in name) or name in names:
            raise ValueError('Published method table contains invalid or ambiguous names')
        names.add(name)
        code = struct.unpack_from('<Q', raw, 2)[0]
        if not base <= code < base+IMAGE_SIZE:
            raise ValueError('Published method code pointer is outside main image')
        if index in targets:
            expected_name, _, record_rva, expected_length, code_rva = targets[index]
            if (name, cursor, length, code) != (expected_name, record_rva, expected_length, base+code_rva):
                raise ValueError('Fixed published method record changed')
            target_records[name] = _proof(metadata, cursor, length, base)
        if code == base+SHARED_SUCCESSOR_RVA:
            shared_matches.append({'name': name, 'methodIndex': index, 'codeRva': SHARED_SUCCESSOR_RVA,
                                   'record': _proof(metadata, cursor, length, base)})
        cursor += length
    if cursor != TABLE_END_RVA or set(target_records) != {item[0] for item in HANDLERS}:
        raise ValueError('Published method table end or required binding is incomplete')
    return target_records, {
        'calleeRva': SHARED_SUCCESSOR_RVA, 'calleeVa': base+SHARED_SUCCESSOR_RVA,
        'tableRva': TABLE_RVA, 'tableCount': TABLE_COUNT, 'tableEndRva': TABLE_END_RVA,
        'tableFullyValidated': True, 'matchCount': len(shared_matches), 'matches': shared_matches,
        'interpretation': 'Exact code-pointer matches within the complete published-method table; '
                          'no match does not establish function absence',
    }


def analysis_carrier(base, entries):
    """Serialize three handlers and one fixed successor into an analysis DLL.

    Raw entry files remain authoritative. 0xCC bytes outside their union are
    synthetic padding, not observations from the source process or disk image.
    DLL/EXECUTABLE_IMAGE are format roles for analysis-tool compatibility, not
    permission to execute or load the carrier. No automatic entry point exists.
    """
    _integer(base, 'analysis image base', 0x10000, (1 << 64)-1-IMAGE_SIZE)
    expected = {item[4] for item in HANDLERS} | {SHARED_SUCCESSOR_RVA}
    if (len(entries) != 4 or {rva for rva, _ in entries} != expected or
            any(not isinstance(raw, bytes) or len(raw) != SNIPPET_SIZE for _, raw in entries)):
        raise ValueError('Analysis carrier accepts only the four fixed bounded entry snippets')
    section_rva, raw_offset = 0xFCF000, 0x200
    section = bytearray(b'\xCC'*0x4000)
    observed = bytearray(len(section))
    for rva, raw in entries:
        start = rva-section_rva
        if start < 0 or start+len(raw) > len(section):
            raise ValueError('Entry snippet escapes fixed analysis section')
        for index, value in enumerate(raw, start):
            if observed[index] and section[index] != value:
                raise ValueError('Overlapping entry snippets disagree; collection overlap drift detected')
            section[index], observed[index] = value, 1
    filename = 'code-entry-snippets.analysis.dll'
    export_rva, export_raw_offset = 0xFD3000, raw_offset+len(section)
    exports = [{'name': name, 'rva': rva, 'ordinal': index+1}
               for index, (name, *_, rva) in enumerate(HANDLERS)]
    export_section = bytearray(0x200)
    # IMAGE_EXPORT_DIRECTORY, then EAT, name RVAs and zero-based ordinals.
    functions_offset, names_offset, ordinals_offset = 40, 52, 64
    cursor = 70
    dll_name_offset = cursor
    dll_name = filename.encode('ascii')+b'\0'
    export_section[cursor:cursor+len(dll_name)] = dll_name
    cursor += len(dll_name)
    for index, item in enumerate(exports):
        name = item['name'].encode('ascii')+b'\0'
        struct.pack_into('<I', export_section, functions_offset+index*4, item['rva'])
        struct.pack_into('<I', export_section, names_offset+index*4, export_rva+cursor)
        struct.pack_into('<H', export_section, ordinals_offset+index*2, index)
        export_section[cursor:cursor+len(name)] = name
        cursor += len(name)
    struct.pack_into('<IIHHIIIIIII', export_section, 0, 0, 0, 0, 0,
                     export_rva+dll_name_offset, 1, len(exports), len(exports),
                     export_rva+functions_offset, export_rva+names_offset,
                     export_rva+ordinals_offset)
    headers = bytearray(raw_offset)
    headers[:2] = b'MZ'
    struct.pack_into('<I', headers, 0x3C, 0x80)
    headers[0x80:0x84] = b'PE\0\0'
    # Standard AMD64 DLL role: EXECUTABLE_IMAGE | LARGE_ADDRESS_AWARE | DLL.
    struct.pack_into('<HHIIIHH', headers, 0x84, 0x8664, 2, 0, 0, 0, 0xF0, 0x2022)
    optional = 0x98
    struct.pack_into('<H', headers, optional, 0x20B)
    struct.pack_into('<I', headers, optional+4, len(section))
    struct.pack_into('<I', headers, optional+8, len(export_section))
    struct.pack_into('<I', headers, optional+16, 0)  # no entry point
    struct.pack_into('<I', headers, optional+20, section_rva)
    struct.pack_into('<Q', headers, optional+24, base)
    struct.pack_into('<II', headers, optional+32, 0x1000, 0x200)
    struct.pack_into('<HH', headers, optional+40, 6, 0)  # OS version
    struct.pack_into('<HH', headers, optional+48, 6, 0)  # subsystem version
    struct.pack_into('<II', headers, optional+56, export_rva+0x1000, raw_offset)
    struct.pack_into('<H', headers, optional+68, 2)  # IMAGE_SUBSYSTEM_WINDOWS_GUI
    struct.pack_into('<I', headers, optional+108, 16)
    struct.pack_into('<II', headers, optional+112, export_rva, cursor)
    # Import and TLS directories remain zero; no loader callbacks are provided.
    section_header = optional+0xF0
    struct.pack_into('<8sIIIIIIHHI', headers, section_header, b'.text', len(section), section_rva,
                     len(section), raw_offset, 0, 0, 0, 0, 0x60000020)
    struct.pack_into('<8sIIIIIIHHI', headers, section_header+40, b'.edata', cursor, export_rva,
                     len(export_section), export_raw_offset, 0, 0, 0, 0, 0x40000040)
    raw = bytes(headers+section+export_section)
    return raw, {'file': filename, 'sha256': _hash(raw),
                 'purpose': 'Ghidra static analysis carrier only; never execute or LoadLibrary',
                 'authoritativeSource': 'three raw handler entry bin files and one fixed shared-successor entry bin file',
                 'imageBase': base,
                 'sectionRva': section_rva, 'sectionSize': len(section), 'sectionFileOffset': raw_offset,
                 'coverage': [{'rva': 0xFCFC50, 'size': 0x340}, {'rva': SHARED_SUCCESSOR_RVA, 'size': SNIPPET_SIZE}],
                 'paddingByte': 'CC',
                 'paddingMeaning': 'Synthetic padding outside coverage; not source-process bytes',
                 'originalFileOffset': None, 'executableImage': True,
                 'executableImageMeaning': 'PE format flag only; static analysis use only',
                 'dll': True, 'analysisOnly': True, 'addressOfEntryPoint': 0, 'subsystem': 2,
                 'exports': exports, 'exportNameSource': 'source-derived verified published-method metadata',
                 'exportPurpose': 'Carrier analysis aid; not evidence of original PE exports or debug symbols'}


def run_evidence(request, *, backend=None):
    plan = validate_request(request)
    backend = Win32EventBackend() if backend is None else backend
    handle = backend.open(plan['arguments']['pid'], PROCESS_READ_ACCESS)
    if not handle:
        raise OSError('OpenProcess did not return a read-only process handle')
    try:
        before = _check_identity(backend.identity(handle), plan['arguments']['pid'])
        metadata, metadata_pages = read_image(backend, handle, before, METADATA_RVA, METADATA_SIZE)
        records, shared_methods = published_binding(metadata, before['base'])
        dfm, dfm_pages = read_image(backend, handle, before, DFM_RVA, DFM_SIZE)
        if _hash(dfm) != DFM_SHA256:
            raise ValueError('Runtime DFM resource SHA256 differs from the source-derived fixed profile')
        snippets, handlers = {}, []
        for name, index, record_rva, length, code_rva in HANDLERS:
            raw, pages = read_image(backend, handle, before, code_rva, SNIPPET_SIZE, executable=True)
            filename = name+'.entry.bin'
            snippets[filename] = raw
            handlers.append({'name': name, 'methodIndex': index, 'record': records[name],
                             'snippet': {'kind': 'bounded entry snippet', 'rva': code_rva,
                                         'va': before['base']+code_rva, 'size': len(raw),
                                         'file': filename, 'sha256': _hash(raw),
                                         'originalFileOffset': None, 'provenance': 'loaded-memory', 'memoryPages': pages}})
        raw, pages = read_image(backend, handle, before, SHARED_SUCCESSOR_RVA, SNIPPET_SIZE, executable=True)
        filename = 'fixed-shared-successor.entry.bin'
        snippets[filename] = raw
        shared_successor = {
            'kind': 'bounded fixed shared-successor snippet',
            'role': 'Source-derived fixed shared successor; not a DFM handler',
            'rva': SHARED_SUCCESSOR_RVA, 'va': before['base']+SHARED_SUCCESSOR_RVA,
            'size': len(raw), 'file': filename, 'sha256': _hash(raw),
            'originalFileOffset': None, 'provenance': 'loaded-memory', 'memoryPages': pages,
        }
        after = _check_identity(backend.identity(handle), plan['arguments']['pid'])
        if after != before:
            raise ValueError('Process creation/path/hash/main-image identity changed during evidence collection')
    finally:
        backend.close(handle)
    base = before['base']
    carrier_entries = [(item['snippet']['rva'], snippets[item['snippet']['file']]) for item in handlers]
    carrier_entries.append((shared_successor['rva'], snippets[shared_successor['file']]))
    carrier, carrier_manifest = analysis_carrier(base, carrier_entries)
    for snippet in [*(item['snippet'] for item in handlers), shared_successor]:
        snippet['carrierFileOffset'] = carrier_manifest['sectionFileOffset']+snippet['rva']-carrier_manifest['sectionRva']
    data = {
        'schemaVersion': 1, 'command': COMMAND, 'profile': PROFILE, 'outputRoot': str(plan['output']),
        'source': {'pid': before['pid'], 'executable': before['executable'], 'sha256': before['sha256'],
                   'provenance': 'loaded-memory', 'sha256Provenance': 'original on-disk executable',
                   'processCreated': before['processCreated'], 'actualBase': base, 'sizeOfImage': before['size'],
                   'machine': 'AMD64', 'identityVerifiedBeforeAndAfter': True, 'processAccessMask': PROCESS_READ_ACCESS,
                   'metadataWindow': {'rva': METADATA_RVA, 'va': base+METADATA_RVA, 'size': METADATA_SIZE,
                                      'provenance': 'loaded-memory', 'rawFileOffset': None, 'memoryPages': metadata_pages},
                   'dfmResource': {'path': RESOURCE_PATH, 'rva': DFM_RVA, 'va': base+DFM_RVA,
                                   'size': DFM_SIZE, 'sha256': _hash(dfm), 'rawFileOffset': None,
                                   'provenance': 'loaded-memory', 'memoryPages': dfm_pages}},
        'relationship': {'formClass': CLASS_NAME, 'vmtRva': VMT_RVA, 'vmtVa': base+VMT_RVA,
                         'vmtPointerWindow': _proof(metadata, SELF_RVA, CLASS_POINTER_RVA+8-SELF_RVA, base),
                         'classShortString': _proof(metadata, CLASS_RVA, len(CLASS_NAME)+1, base),
                         'methodTable': {'rva': TABLE_RVA, 'va': base+TABLE_RVA, 'count': TABLE_COUNT,
                                         'endRva': TABLE_END_RVA, 'allRecordsValidated': True, 'allNamesUnique': True,
                                         'countProof': _proof(metadata, TABLE_RVA, 2, base)},
                         'sharedSuccessorPublishedMethods': shared_methods,
                         'controls': [{'name': name, 'class': cls, 'event': 'OnChange', 'publishedMethod': event,
                                       'tag': tag, 'dfmObjectOffset': offset, 'parent': 'grpCallMob',
                                       'bindingSource': 'source-derived DFM inventory, runtime resource hash verified'}
                                      for name, cls, event, tag, offset in CONTROLS]},
        'handlers': handlers,
        'sharedSuccessor': shared_successor,
        'analysisCarrier': carrier_manifest,
        'limitations': ['Published-method metadata and source-derived DFM event names establish the documented association.',
                        'No runtime instance OnChange pointer, heap object, handler invocation, or business behavior is verified.',
                        'The three bounded entry snippets can overlap; they are not complete functions.',
                        'The fixed shared-successor snippet is bounded and is not a fourth DFM handler or proof of business behavior.',
                        'Original packed-file offsets are unknown; no unpacking or page protection change was performed.'],
    }
    # Revalidate the new, policy-authorized output immediately before exclusive creation.
    fresh = validate_request(request)
    if fresh['output'] != plan['output']:
        raise ValueError('Output directory identity changed')
    output = fresh['output']
    output.mkdir(parents=True, exist_ok=False)
    if _independent(str(output)) != output:
        raise ValueError('Output directory changed after creation')
    for filename, raw in snippets.items():
        with (output/filename).open('xb') as stream:
            stream.write(raw)
    with (output/carrier_manifest['file']).open('xb') as stream:
        stream.write(carrier)
    with (output/'event-evidence.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return data


class Win32EventBackend:
    """Small read-only OS boundary; no GUI, write, injection or debug APIs."""
    def __init__(self):
        if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise OSError('Fixed AMD64 evidence profile requires 64-bit Windows Python')
        from ctypes import wintypes as w
        self.w = w
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel = self.kernel
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle.restype = w.BOOL
        kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        kernel.QueryFullProcessImageNameW.restype = w.BOOL
        kernel.GetProcessId.argtypes = [w.HANDLE]
        kernel.GetProcessId.restype = w.DWORD
        kernel.GetProcessTimes.argtypes = [w.HANDLE, *[ctypes.POINTER(w.FILETIME)]*4]
        kernel.GetProcessTimes.restype = w.BOOL
        kernel.K32EnumProcessModulesEx.argtypes = [w.HANDLE, ctypes.POINTER(w.HMODULE), w.DWORD, ctypes.POINTER(w.DWORD), w.DWORD]
        kernel.K32EnumProcessModulesEx.restype = w.BOOL
        kernel.K32GetModuleFileNameExW.argtypes = [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]
        kernel.K32GetModuleFileNameExW.restype = w.DWORD
        class ModuleInfo(ctypes.Structure):
            _fields_ = [('base', ctypes.c_void_p), ('size', w.DWORD), ('entry', ctypes.c_void_p)]
        class MemoryInfo(ctypes.Structure):
            _fields_ = [('base', ctypes.c_void_p), ('allocationBase', ctypes.c_void_p),
                        ('allocationProtect', w.DWORD), ('partitionId', w.WORD), ('size', ctypes.c_size_t),
                        ('state', w.DWORD), ('protect', w.DWORD), ('type', w.DWORD)]
        self.ModuleInfo, self.MemoryInfo = ModuleInfo, MemoryInfo
        kernel.K32GetModuleInformation.argtypes = [w.HANDLE, w.HMODULE, ctypes.POINTER(ModuleInfo), w.DWORD]
        kernel.K32GetModuleInformation.restype = w.BOOL
        kernel.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.POINTER(MemoryInfo), ctypes.c_size_t]
        kernel.VirtualQueryEx.restype = ctypes.c_size_t
        kernel.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        kernel.ReadProcessMemory.restype = w.BOOL

    def _check(self, result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def open(self, pid, access):
        if access != PROCESS_READ_ACCESS:
            raise PermissionError('Only QUERY_INFORMATION | VM_READ access is supported')
        # Wrong PIDs never receive a VM_READ handle. Keep this query-only handle
        # alive until the read handle is bound to the same creation identity.
        guard = self._check(self.kernel.OpenProcess(0x1000, False, pid))
        read_handle = None
        try:
            initial = self._process_identity(guard)
            if initial['pid'] != pid:
                raise ValueError('Query-only process PID identity changed')
            read_handle = self._check(self.kernel.OpenProcess(PROCESS_READ_ACCESS, False, pid))
            if self._process_identity(read_handle) != initial:
                raise ValueError('Process creation/path/hash changed between query and read handles')
            return read_handle
        except BaseException:
            if read_handle:
                self.close(read_handle)
            raise
        finally:
            self.close(guard)

    def close(self, handle):
        self._check(self.kernel.CloseHandle(handle))

    def _process_identity(self, handle):
        w, kernel = self.w, self.kernel
        path = ctypes.create_unicode_buffer(32768)
        size = w.DWORD(len(path))
        self._check(kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)))
        executable = path.value
        if not _same_path(executable, EXECUTABLE):
            raise PermissionError('Read-only process handle does not identify the fixed executable')
        created, exited, kerneltime, usertime = (w.FILETIME() for _ in range(4))
        self._check(kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kerneltime), ctypes.byref(usertime)))
        digest = _file_hash(executable)
        if digest != EXECUTABLE_SHA256:
            raise PermissionError('On-disk original M2 SHA256 changed')
        return {'pid': int(kernel.GetProcessId(handle)), 'executable': executable, 'sha256': digest,
                'processCreated': str((created.dwHighDateTime << 32)|created.dwLowDateTime)}

    def identity(self, handle):
        w, kernel = self.w, self.kernel
        process = self._process_identity(handle)
        executable = process['executable']
        modules = (w.HMODULE*1024)()
        needed = w.DWORD()
        self._check(kernel.K32EnumProcessModulesEx(handle, modules, ctypes.sizeof(modules), ctypes.byref(needed), 3))
        if not needed.value or needed.value > ctypes.sizeof(modules) or needed.value % ctypes.sizeof(w.HMODULE):
            raise ValueError('Main-module enumeration is incomplete')
        module = modules[0]
        module_path = ctypes.create_unicode_buffer(32768)
        copied = self._check(kernel.K32GetModuleFileNameExW(handle, module, module_path, len(module_path)))
        if copied >= len(module_path)-1:
            raise ValueError('Main-module path is truncated')
        if not _same_path(module_path.value, EXECUTABLE):
            raise PermissionError('Enumerated main module differs from the fixed executable')
        info = self.ModuleInfo()
        self._check(kernel.K32GetModuleInformation(handle, module, ctypes.byref(info), ctypes.sizeof(info)))
        import pefile
        pe = pefile.PE(executable, fast_load=True)
        try:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
            found = []
            def visit(directory, ancestors):
                for entry in directory.entries:
                    key = str(entry.name) if entry.name is not None else entry.id
                    parts = ancestors+[key]
                    if hasattr(entry, 'directory'):
                        if len(parts) < 3:
                            visit(entry.directory, parts)
                    elif parts == RESOURCE_PATH and hasattr(entry, 'data'):
                        found.append({'path': parts, 'rva': entry.data.struct.OffsetToData,
                                      'size': entry.data.struct.Size, 'rawFileOffset': None})
            visit(pe.DIRECTORY_ENTRY_RESOURCE, [])
            if len(found) != 1:
                raise ValueError('Fixed PE resource directory binding is missing or ambiguous')
            if pe.OPTIONAL_HEADER.Magic != 0x20B or pe.OPTIONAL_HEADER.SizeOfImage != info.size:
                raise ValueError('Static PE headers differ from current main-image identity')
            return {**process, 'modulePath': module_path.value, 'base': int(info.base),
                    'size': info.size, 'machine': pe.FILE_HEADER.Machine, 'resource': found[0]}
        finally:
            pe.close()

    def query(self, handle, address):
        info = self.MemoryInfo()
        count = self._check(self.kernel.VirtualQueryEx(handle, address, ctypes.byref(info), ctypes.sizeof(info)))
        if count != ctypes.sizeof(info):
            raise ValueError('VirtualQueryEx returned a truncated memory descriptor')
        return {key: int(getattr(info, key) or 0) for key in ('base', 'size', 'allocationBase', 'state', 'type', 'protect')}

    def read(self, handle, address, size):
        buffer = ctypes.create_string_buffer(size)
        copied = ctypes.c_size_t()
        self._check(self.kernel.ReadProcessMemory(handle, address, buffer, size, ctypes.byref(copied)))
        if copied.value != size:
            raise ValueError('ReadProcessMemory returned a short read')
        return buffer.raw
