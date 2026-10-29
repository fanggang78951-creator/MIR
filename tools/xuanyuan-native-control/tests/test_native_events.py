"""Fixed-profile evidence tests: fake OS memory, no process or GUI access."""
import copy
import hashlib
import importlib
import json
import struct
from pathlib import Path

import pytest


EXE = r'D:\Mirserver100\Mir200\M2Server.exe'
HASH = '1D4D58A4C49EE97D2844FCB2BB31EA3E1F11E7FEDE4DBC857A3FE21979723F1A'


def module():
    return importlib.import_module('wzl_blackbox.native_events')


def request(tmp_path):
    return {'schemaVersion': 1, 'command': 'm2-event-evidence',
            'arguments': {'pid': 12, 'expectedExecutable': EXE, 'expectedSha256': HASH,
                          'profile': 'custom-monster-summon-v1', 'outputRoot': str(tmp_path/'job')},
            'policy': {'allowedWriteRoots': [str(tmp_path)]}}


class Memory:
    """Synthetic layout has all 243 records at the audited profile RVAs."""
    def __init__(self, e, monkeypatch):
        self.e = e
        self.base = 0x140000000
        self.info = {'pid': 12, 'executable': EXE, 'modulePath': EXE, 'sha256': HASH,
                     'processCreated': '12345', 'base': self.base, 'size': 0x3941000,
                     'machine': 0x8664, 'resource': {'path': [10, 'TFRMMONSTERCONFIG', 0],
                                                  'rva': 0x28452B8, 'size': 94135, 'rawFileOffset': None}}
        self.meta = bytearray(0x20000)
        self.dfm = b'TPF0'+b'\x00'*(94135-4)
        monkeypatch.setattr(e, 'DFM_SHA256', hashlib.sha256(self.dfm).hexdigest().upper())
        self.calls = []
        self.snapshots = 0
        self.drift = None
        self.bad_page = None
        self.short_read = False
        self.closed = False
        self.setq(0xFB4360, self.base+0xFB4428)
        self.setq(0xFB4390, self.base+0xFBC476)
        self.setq(0xFB43A0, self.base+0xFBF248)
        self.put(0xFBF248, b'\x11TfrmMonsterConfig')
        self.put(0xFBC476, struct.pack('<H', 243))
        lengths = [36]*62+[35]*42+[32, 34]+[36]*10+[35]*18+[35]+[37]*93+[36]*15
        targets = {104: ('edtCallMonster1Change', 0xFCFC90),
                   105: ('seCallMonsterNum1Change', 0xFCFD90),
                   134: ('seCallMonstersRateChange', 0xFCFC50)}
        self.records = {}
        cursor = 0xFBC478
        for index, length in enumerate(lengths):
            name, code = targets.get(index, (('fixture%03d'%index).ljust(length-11, 'x'), 0xFC0000))
            raw = struct.pack('<HQB', length, self.base+code, len(name))+name.encode('ascii')
            assert len(raw) == length
            self.records[index] = (cursor, raw)
            self.put(cursor, raw)
            cursor += length
        assert cursor == 0xFBE6BE

    def put(self, rva, raw):
        offset = rva-0xFA0000
        self.meta[offset:offset+len(raw)] = raw

    def setq(self, rva, value):
        self.put(rva, struct.pack('<Q', value))

    def open(self, pid, access):
        self.calls.append(('open', pid, access))
        return 777

    def identity(self, handle):
        self.snapshots += 1
        result = copy.deepcopy(self.info)
        if self.snapshots == 2 and self.drift:
            key, value = self.drift
            result[key] = value
        return result

    def query(self, handle, address):
        rva = address-self.base
        result = {'base': address & ~0xFFF, 'size': 0x1000, 'allocationBase': self.base,
                  'state': 0x1000, 'type': 0x1000000,
                  'protect': 0x20 if 0xFC0000 <= rva < 0xFE0000 else 0x02}
        if self.bad_page:
            result.update(self.bad_page)
        self.calls.append(('query', address))
        return result

    def read(self, handle, address, size):
        self.calls.append(('read', address, size))
        rva = address-self.base
        if 0xFA0000 <= rva < 0xFC0000:
            raw = bytes(self.meta[rva-0xFA0000:rva-0xFA0000+size])
        elif 0x28452B8 <= rva < 0x28452B8+94135:
            raw = self.dfm[rva-0x28452B8:rva-0x28452B8+size]
        elif 0xFCFC50 <= rva < 0xFCFF90 or 0xFD1F30 <= rva < 0xFD2130:
            raw = bytes((address+i) & 255 for i in range(size))
        else:
            raise AssertionError('out-of-profile memory read')
        return raw[:-1] if self.short_read else raw

    def close(self, handle):
        self.closed = True


@pytest.fixture
def memory(monkeypatch):
    return Memory(module(), monkeypatch)


def test_success_proves_dfm_vmt_table_and_three_bounded_entry_snippets(tmp_path, memory):
    e = module()
    result = e.run_evidence(request(tmp_path), backend=memory)
    assert memory.calls[0] == ('open', 12, 0x410)
    assert memory.closed and memory.snapshots == 2
    assert result['source']['sha256'] == HASH
    assert result['source']['actualBase'] == memory.base
    relation = result['relationship']
    assert relation['formClass'] == 'TfrmMonsterConfig'
    assert relation['methodTable']['count'] == 243
    assert relation['methodTable']['endRva'] == 0xFBE6BE
    assert len(relation['controls']) == 9
    assert [x['tag'] for x in relation['controls'] if x['name'].startswith('edt')] == [0, 1, 2, 3]
    assert len(result['handlers']) == 3
    for item in result['handlers']:
        record_rva, raw = memory.records[item['methodIndex']]
        assert item['record']['rva'] == record_rva
        assert item['record']['sha256'] == hashlib.sha256(raw).hexdigest().upper()
        snippet = item['snippet']
        assert snippet['kind'] == 'bounded entry snippet'
        assert snippet['size'] == 512 and snippet['va'] == memory.base+snippet['rva']
        path = Path(result['outputRoot'])/snippet['file']
        assert path.stat().st_size == 512
        assert hashlib.sha256(path.read_bytes()).hexdigest().upper() == snippet['sha256']
    written = json.loads((Path(result['outputRoot'])/'event-evidence.json').read_text('utf-8'))
    assert written == result and not (Path(result['outputRoot'])/'receipt.json').exists()
    assert 'runtime instance' in ' '.join(result['limitations'])


def test_fixed_shared_successor_is_separate_from_three_dfm_handlers(tmp_path, memory):
    result = module().run_evidence(request(tmp_path), backend=memory)
    successor = result['sharedSuccessor']
    assert successor['kind'] == 'bounded fixed shared-successor snippet'
    assert successor['rva'] == 0xFD1F30
    assert successor['va'] == memory.base+0xFD1F30
    assert successor['size'] == 512
    assert successor['file'] == 'fixed-shared-successor.entry.bin'
    raw = (Path(result['outputRoot'])/successor['file']).read_bytes()
    assert raw == bytes((memory.base+0xFD1F30+i) & 255 for i in range(512))
    assert successor['sha256'] == hashlib.sha256(raw).hexdigest().upper()
    assert successor['provenance'] == 'loaded-memory' and successor['originalFileOffset'] is None
    assert successor['carrierFileOffset'] == 0x200+0xFD1F30-0xFCF000
    assert 'not a DFM handler' in successor['role']
    assert len(result['handlers']) == 3 and len(result['relationship']['controls']) == 9
    assert len(result['analysisCarrier']['exports']) == 3
    assert [call for call in memory.calls if call[0] == 'read' and
            memory.base+0xFD1F30 <= call[1] < memory.base+0xFD2130] == [
                ('read', memory.base+0xFD1F30, 0xD0), ('read', memory.base+0xFD2000, 0x130)]
    assert len(successor['memoryPages']) == 2
    assert all(page['protect'] == 0x20 for page in successor['memoryPages'])
    assert memory.closed and memory.snapshots == 2


@pytest.mark.parametrize('indices', [[], [0], [0, 242]])
def test_shared_successor_published_matches_are_all_exact_code_matches(tmp_path, memory, indices):
    for index in indices:
        rva, _ = memory.records[index]
        memory.setq(rva+2, memory.base+0xFD1F30)
    result = module().run_evidence(request(tmp_path), backend=memory)
    matches = result['relationship']['sharedSuccessorPublishedMethods']
    assert matches['calleeRva'] == 0xFD1F30 and matches['calleeVa'] == memory.base+0xFD1F30
    assert matches['tableFullyValidated'] is True
    assert matches['tableRva'] == 0xFBC476 and matches['tableCount'] == 243
    assert matches['tableEndRva'] == 0xFBE6BE
    assert matches['matchCount'] == len(indices)
    assert [item['methodIndex'] for item in matches['matches']] == indices
    assert 'no match does not establish function absence' in matches['interpretation']
    for match, index in zip(matches['matches'], indices):
        rva, fixture = memory.records[index]
        raw = bytes(memory.meta[rva-0xFA0000:rva-0xFA0000+len(fixture)])
        assert match['name'] == raw[11:].decode('ascii')
        assert match['codeRva'] == 0xFD1F30
        assert match['record']['rva'] == rva
        assert match['record']['sha256'] == hashlib.sha256(raw).hexdigest().upper()
        assert match['record']['hex'] == raw.hex().upper()
        assert match['record']['provenance'] == 'loaded-memory'
        assert match['record']['rawFileOffset'] is None
    assert (Path(result['outputRoot'])/result['sharedSuccessor']['file']).stat().st_size == 512


def test_shared_successor_match_does_not_stop_full_table_validation(tmp_path, memory):
    memory.setq(memory.records[0][0]+2, memory.base+0xFD1F30)
    memory.put(memory.records[242][0], struct.pack('<H', 0xFFFF))
    with pytest.raises(ValueError, match='record length'):
        module().run_evidence(request(tmp_path), backend=memory)
    assert memory.closed and not (tmp_path/'job').exists()


@pytest.mark.parametrize('bad_page', [{'protect': 0x02}, {'type': 0x20000}, {'protect': 0x120}])
def test_shared_successor_second_page_denied_causes_no_partial_range_read(tmp_path, memory, bad_page):
    query = memory.query
    def reject_second_page(handle, address):
        value = query(handle, address)
        if address == memory.base+0xFD2000:
            value.update(bad_page)
        return value
    memory.query = reject_second_page
    with pytest.raises(PermissionError):
        module().run_evidence(request(tmp_path), backend=memory)
    assert memory.closed and not (tmp_path/'job').exists()
    assert not any(call[0] == 'read' and memory.base+0xFD1F30 <= call[1] < memory.base+0xFD2130
                   for call in memory.calls)


def test_shared_successor_short_read_is_rejected_without_output(tmp_path, memory):
    read = memory.read
    def short_successor(handle, address, size):
        raw = read(handle, address, size)
        return raw[:-1] if address == memory.base+0xFD2000 else raw
    memory.read = short_successor
    with pytest.raises(ValueError, match='short read'):
        module().run_evidence(request(tmp_path), backend=memory)
    assert memory.closed and not (tmp_path/'job').exists()


@pytest.mark.parametrize('field,value', [('pid', True), ('pid', 0), ('pid', 2**32),
    ('expectedExecutable', r'D:\MirServer\Mir200\M2Server.exe'),
    ('expectedExecutable', r'D:\copy\M2Server.exe'), ('expectedSha256', '0'*64),
    ('profile', 'other'), ('profile', None)])
def test_invalid_identity_or_profile_is_rejected_before_open(tmp_path, memory, field, value):
    req = request(tmp_path); req['arguments'][field] = value
    with pytest.raises((ValueError, PermissionError)):
        module().run_evidence(req, backend=memory)
    assert memory.calls == []


@pytest.mark.parametrize('extra', ['address', 'rva', 'length', 'events', 'handler', 'labRoot', 'mode'])
def test_unknown_arguments_cannot_expand_reads(tmp_path, memory, extra):
    req = request(tmp_path); req['arguments'][extra] = 1
    with pytest.raises(ValueError, match='field'):
        module().run_evidence(req, backend=memory)
    assert memory.calls == []


@pytest.mark.parametrize('scope', ['request', 'policy'])
def test_unknown_contract_fields_rejected(tmp_path, scope):
    req = request(tmp_path)
    (req if scope == 'request' else req['policy'])['unexpected'] = True
    with pytest.raises(ValueError, match='field'):
        module().validate_request(req)


@pytest.mark.parametrize('path', [r'D:\MirServer\evidence-new', r'D:\Mirserver100\evidence-new',
                                r'E:\XuanYuanDevPlatform\evidence-new'])
def test_protected_output_rejected_even_when_policy_allows(tmp_path, path):
    req = request(tmp_path); req['arguments']['outputRoot'] = path
    req['policy']['allowedWriteRoots'] = [str(Path(path).parent)]
    with pytest.raises(PermissionError):
        module().validate_request(req)


def test_output_must_be_new_and_allowed_and_reentry_rejected(tmp_path, memory):
    req = request(tmp_path)
    denied = copy.deepcopy(req); denied['policy']['allowedWriteRoots'] = []
    with pytest.raises(PermissionError): module().validate_request(denied)
    module().run_evidence(req, backend=memory)
    with pytest.raises(FileExistsError): module().run_evidence(req, backend=memory)
    assert memory.snapshots == 2


@pytest.mark.parametrize('change', [
    {'protect': 0x100|0x02}, {'protect': 0x01}, {'protect': 0x10},
    {'state': 0x2000}, {'type': 0x20000}, {'allocationBase': 0x55550000}, {'size': 0}])
def test_unreadable_uncommitted_guard_heap_or_other_module_page_rejected(tmp_path, memory, change):
    memory.bad_page = change
    with pytest.raises((PermissionError, ValueError)):
        module().run_evidence(request(tmp_path), backend=memory)
    assert memory.closed and not (tmp_path/'job').exists()
    assert not any(call[0] == 'read' for call in memory.calls)


def test_code_requires_executable_page(tmp_path, memory):
    query = memory.query
    def non_exec(handle, address):
        value = query(handle, address)
        if 0xFC0000 <= address-memory.base < 0xFE0000: value['protect'] = 0x02
        return value
    memory.query = non_exec
    with pytest.raises(PermissionError, match='executable'):
        module().run_evidence(request(tmp_path), backend=memory)
    assert not (tmp_path/'job').exists()


@pytest.mark.parametrize('kind', ['self', 'class-pointer', 'method-pointer', 'class-name', 'count',
                                   'record-length', 'record-name', 'record-code', 'duplicate'])
def test_ambiguous_or_broken_binding_chain_is_fail_closed(tmp_path, memory, kind):
    if kind == 'self': memory.setq(0xFB4360, memory.base+0xFB4429)
    elif kind == 'class-pointer': memory.setq(0xFB43A0, memory.base+0xFBF249)
    elif kind == 'method-pointer': memory.setq(0xFB4390, memory.base+0xFBC477)
    elif kind == 'class-name': memory.put(0xFBF248, b'\x11XfrmMonsterConfig')
    elif kind == 'count': memory.put(0xFBC476, struct.pack('<H', 244))
    elif kind == 'record-length': memory.put(0xFBD2EE, struct.pack('<H', 0xFFFF))
    elif kind == 'record-name': memory.put(0xFBD2EE+11, b'X')
    elif kind == 'record-code': memory.setq(0xFBD2EE+2, memory.base+0x3941000)
    elif kind == 'duplicate':
        _, raw = memory.records[1]; memory.put(memory.records[0][0], raw)
    with pytest.raises((ValueError, PermissionError)):
        module().run_evidence(request(tmp_path), backend=memory)
    assert memory.closed and not (tmp_path/'job').exists()


@pytest.mark.parametrize('key,value', [('sha256', '0'*64), ('processCreated', '23456'),
    ('executable', r'D:\MirServer\Mir200\M2Server.exe'), ('modulePath', r'D:\other.exe'),
    ('base', 0x400000), ('size', 1)])
def test_identity_is_reverified_after_read_and_drift_emits_no_evidence(tmp_path, memory, key, value):
    memory.drift = (key, value)
    with pytest.raises((ValueError, PermissionError)):
        module().run_evidence(request(tmp_path), backend=memory)
    assert memory.closed and memory.snapshots == 2 and not (tmp_path/'job').exists()


def test_dfm_hash_mismatch_is_rejected(tmp_path, memory):
    memory.dfm = b'X'+memory.dfm[1:]
    with pytest.raises(ValueError, match='DFM.*SHA256'):
        module().run_evidence(request(tmp_path), backend=memory)
    assert not (tmp_path/'job').exists()


def test_fixed_resource_directory_entry_is_required(tmp_path, memory):
    memory.info['resource']['rva'] += 1
    with pytest.raises(ValueError, match='resource'):
        module().run_evidence(request(tmp_path), backend=memory)
    assert not any(call[0] == 'read' for call in memory.calls)


def test_short_os_read_is_rejected(tmp_path, memory):
    memory.short_read = True
    with pytest.raises(ValueError, match='short'):
        module().run_evidence(request(tmp_path), backend=memory)
    assert memory.closed and not (tmp_path/'job').exists()


def test_out_of_image_range_rejected_before_query(memory):
    with pytest.raises(ValueError, match='image'):
        module().read_image(memory, 777, memory.info, 0x3940FFF, 2)
    assert memory.calls == []


def test_analysis_carrier_is_standard_amd64_dll_for_static_analysis(tmp_path, memory):
    import pefile
    result = module().run_evidence(request(tmp_path), backend=memory)
    manifest = result['analysisCarrier']
    raw = (Path(result['outputRoot'])/manifest['file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest().upper() == manifest['sha256']
    assert manifest['file'] == 'code-entry-snippets.analysis.dll'
    assert len(raw) == 17408
    pe = pefile.PE(data=raw)
    assert pe.FILE_HEADER.Machine == 0x8664 and pe.OPTIONAL_HEADER.Magic == 0x20B
    assert pe.FILE_HEADER.Characteristics == 0x2022
    assert pe.FILE_HEADER.NumberOfSections == 2
    assert pe.OPTIONAL_HEADER.ImageBase == memory.base
    assert pe.OPTIONAL_HEADER.AddressOfEntryPoint == 0
    assert pe.OPTIONAL_HEADER.Subsystem == 2
    assert pe.OPTIONAL_HEADER.SizeOfImage == 0xFD4000
    assert pe.OPTIONAL_HEADER.SizeOfHeaders == 0x200
    assert not hasattr(pe, 'DIRECTORY_ENTRY_IMPORT')
    assert not hasattr(pe, 'DIRECTORY_ENTRY_TLS')
    assert pe.OPTIONAL_HEADER.DATA_DIRECTORY[1].VirtualAddress == 0
    assert pe.OPTIONAL_HEADER.DATA_DIRECTORY[9].VirtualAddress == 0
    assert len(pe.sections) == 2
    text, exports = pe.sections
    assert text.Name.rstrip(b'\0') == b'.text'
    assert text.VirtualAddress == 0xFCF000 and text.PointerToRawData == 0x200
    assert text.Misc_VirtualSize == text.SizeOfRawData == 0x4000
    assert text.Characteristics == 0x60000020
    assert exports.Name.rstrip(b'\0') == b'.edata'
    assert exports.VirtualAddress == 0xFD3000 and exports.PointerToRawData == 0x4200
    assert 0 < exports.Misc_VirtualSize <= exports.SizeOfRawData == 0x200
    assert exports.Characteristics == 0x40000040
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[0]
    assert directory.VirtualAddress == exports.VirtualAddress
    assert directory.Size == exports.Misc_VirtualSize
    assert manifest['executableImage'] is True and manifest['dll'] is True
    assert manifest['analysisOnly'] is True
    assert manifest['addressOfEntryPoint'] == 0 and manifest['subsystem'] == 2
    assert manifest['originalFileOffset'] is None
    assert 'format flag' in manifest['executableImageMeaning']
    assert 'never execute' in manifest['purpose'] and 'LoadLibrary' in manifest['purpose']
    pe.close()


def test_analysis_carrier_exports_only_verified_published_handler_names(memory):
    import pefile
    e = module()
    entries = [(rva, bytes((memory.base+rva+i) & 255 for i in range(e.SNIPPET_SIZE)))
               for *_, rva in e.HANDLERS]
    entries.append((0xFD1F30, bytes((memory.base+0xFD1F30+i) & 255 for i in range(512))))
    raw, manifest = e.analysis_carrier(memory.base, entries)
    pe = pefile.PE(data=raw)
    expected = [(name, rva) for name, *_, rva in e.HANDLERS]
    assert [(symbol.name.decode('ascii'), symbol.address)
            for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols] == expected
    assert all(symbol.forwarder is None for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols)
    assert pe.DIRECTORY_ENTRY_EXPORT.struct.NumberOfFunctions == 3
    assert pe.DIRECTORY_ENTRY_EXPORT.struct.NumberOfNames == 3
    assert pe.DIRECTORY_ENTRY_EXPORT.name == b'code-entry-snippets.analysis.dll'
    assert [(item['name'], item['rva']) for item in manifest['exports']] == expected
    assert [item['ordinal'] for item in manifest['exports']] == [1, 2, 3]
    assert manifest['exportNameSource'] == 'source-derived verified published-method metadata'
    assert manifest['exportPurpose'] == 'Carrier analysis aid; not evidence of original PE exports or debug symbols'
    assert e.analysis_carrier(memory.base, list(reversed(entries))) == (raw, manifest)
    assert memory.calls == []
    pe.close()


def test_analysis_carrier_preserves_raw_snippets_coverage_padding_and_mapping(tmp_path, memory):
    import pefile
    result = module().run_evidence(request(tmp_path), backend=memory)
    manifest = result['analysisCarrier']
    raw = (Path(result['outputRoot'])/manifest['file']).read_bytes()
    pe = pefile.PE(data=raw)
    assert pe.get_data(0xFCF000, 0xC50) == b'\xCC'*0xC50
    assert pe.get_data(0xFCFF90, 0xFD1F30-0xFCFF90) == b'\xCC'*(0xFD1F30-0xFCFF90)
    assert pe.get_data(0xFD2130, 0xFD3000-0xFD2130) == b'\xCC'*(0xFD3000-0xFD2130)
    for snippet in [*(handler['snippet'] for handler in result['handlers']), result['sharedSuccessor']]:
        expected = (Path(result['outputRoot'])/snippet['file']).read_bytes()
        assert pe.get_data(snippet['rva'], snippet['size']) == expected
        assert snippet['originalFileOffset'] is None
        assert snippet['carrierFileOffset'] == pe.get_offset_from_rva(snippet['rva'])
    assert manifest['coverage'] == [{'rva': 0xFCFC50, 'size': 0x340}, {'rva': 0xFD1F30, 'size': 512}]
    assert manifest['paddingByte'] == 'CC'
    assert manifest['authoritativeSource'] == 'three raw handler entry bin files and one fixed shared-successor entry bin file'
    assert manifest['sectionRva'] == 0xFCF000 and manifest['sectionSize'] == 0x4000
    assert manifest['sectionFileOffset'] == 0x200
    assert 'Synthetic padding' in manifest['paddingMeaning']
    pe.close()


@pytest.mark.parametrize('kind', ['missing-handler', 'missing-successor', 'duplicate', 'wrong-rva', 'short', 'mutable', 'extra'])
def test_analysis_carrier_rejects_nonprofile_or_incomplete_raw_entries(memory, kind):
    e = module()
    entries = [(rva, b'\x90'*e.SNIPPET_SIZE) for *_, rva in e.HANDLERS]
    entries.append((0xFD1F30, b'\x90'*512))
    if kind == 'missing-handler': entries.pop(0)
    elif kind == 'missing-successor': entries.pop()
    elif kind == 'duplicate': entries[1] = entries[0]
    elif kind == 'wrong-rva': entries[0] = (entries[0][0]+1, entries[0][1])
    elif kind == 'short': entries[0] = (entries[0][0], entries[0][1][:-1])
    elif kind == 'mutable': entries[0] = (entries[0][0], bytearray(entries[0][1]))
    elif kind == 'extra': entries.append((0xFD2200, b'\x90'*512))
    with pytest.raises(ValueError, match='four fixed bounded'):
        e.analysis_carrier(memory.base, entries)
    assert memory.calls == []


def test_overlapping_entry_snippet_drift_is_rejected_before_any_output(tmp_path, memory):
    original = memory.read
    reads = 0
    def drift(handle, address, size):
        nonlocal reads
        raw = original(handle, address, size)
        if 0xFC0000 <= address-memory.base < 0xFE0000:
            reads += 1
            if reads == 2: raw = bytes([raw[0]^1])+raw[1:]
        return raw
    memory.read = drift
    with pytest.raises(ValueError, match='overlap'):
        module().run_evidence(request(tmp_path), backend=memory)
    assert not (tmp_path/'job').exists()


def test_truncated_metadata_and_table_ending_are_rejected(memory):
    e = module()
    with pytest.raises(ValueError, match='truncated'):
        e.published_binding(bytes(memory.meta[:-1]), memory.base)
    cursor, _ = memory.records[242]
    memory.put(cursor, struct.pack('<H', 35))
    with pytest.raises(ValueError):
        e.published_binding(bytes(memory.meta), memory.base)


def test_write_output_race_does_not_overwrite(tmp_path, memory):
    original = memory.identity
    def competing_writer(handle):
        result = original(handle)
        if memory.snapshots == 2:
            (tmp_path/'job').mkdir()
            (tmp_path/'job'/'existing').write_bytes(b'keep')
        return result
    memory.identity = competing_writer
    with pytest.raises(FileExistsError):
        module().run_evidence(request(tmp_path), backend=memory)
    assert (tmp_path/'job'/'existing').read_bytes() == b'keep'
    assert len(list((tmp_path/'job').iterdir())) == 1


def test_tool_source_directory_cannot_be_used_for_output(tmp_path):
    e = module()
    req = request(tmp_path)
    source = Path(e.__file__).parent
    req['arguments']['outputRoot'] = str(source/'new-evidence')
    req['policy']['allowedWriteRoots'] = [str(source)]
    with pytest.raises(PermissionError): e.validate_request(req)


def test_memory_provenance_and_unknown_disk_offsets_are_explicit(tmp_path, memory):
    result = module().run_evidence(request(tmp_path), backend=memory)
    assert result['source']['provenance'] == 'loaded-memory'
    for proof in [result['relationship']['vmtPointerWindow'], result['relationship']['classShortString'],
                  *(item['record'] for item in result['handlers'])]:
        assert proof['provenance'] == 'loaded-memory' and proof['rawFileOffset'] is None


def test_all_pages_preflight_before_rpm_and_wrong_in_image_code_rejected(tmp_path, memory):
    query = memory.query
    count = 0
    def second_page_denied(handle, address):
        nonlocal count
        count += 1
        value = query(handle, address)
        if count == 2: value['type'] = 0x20000
        return value
    memory.query = second_page_denied
    with pytest.raises(PermissionError): module().run_evidence(request(tmp_path), backend=memory)
    assert not any(call[0] == 'read' for call in memory.calls)
    memory.query = query
    memory.setq(0xFBD2EE+2, memory.base+0xFCFC50)
    with pytest.raises(ValueError, match='record changed'):
        module().run_evidence(request(tmp_path), backend=memory)


def test_output_reparse_point_is_rejected(tmp_path):
    target = tmp_path/'target'; target.mkdir()
    alias = tmp_path/'alias'
    alias.symlink_to(target, target_is_directory=True)
    req = request(tmp_path); req['arguments']['outputRoot'] = str(alias/'job')
    with pytest.raises(ValueError, match='reparse'): module().validate_request(req)


class QueryOnlyKernel:
    """Exercises real open() path preflight without invoking Windows APIs."""
    def __init__(self, path=EXE, second_created=None):
        self.path = path
        self.second_created = second_created
        self.opens = []
        self.closed = []
    def OpenProcess(self, access, inherit, pid):
        self.opens.append((access, inherit, pid))
        return 101 if access == 0x1000 else 102
    def CloseHandle(self, handle):
        self.closed.append(handle); return True
    def QueryFullProcessImageNameW(self, handle, flags, output, size):
        output.value = self.path; size._obj.value = len(self.path); return True
    def GetProcessId(self, handle): return 12
    def GetProcessTimes(self, handle, created, exited, kernel, user):
        created._obj.dwLowDateTime = self.second_created if handle == 102 and self.second_created else 12345
        created._obj.dwHighDateTime = 0
        return True


def readonly_backend(monkeypatch, kernel):
    import ctypes.wintypes
    e = module()
    backend = e.Win32EventBackend.__new__(e.Win32EventBackend)
    backend.w, backend.kernel = ctypes.wintypes, kernel
    monkeypatch.setattr(e, '_file_hash', lambda path: HASH)
    return backend


def test_real_open_rejects_wrong_pid_path_before_any_vm_read_handle(monkeypatch):
    kernel = QueryOnlyKernel(r'D:\MirServer\Mir200\M2Server.exe')
    backend = readonly_backend(monkeypatch, kernel)
    with pytest.raises(PermissionError): backend.open(12, 0x410)
    assert kernel.opens == [(0x1000, False, 12)]
    assert kernel.closed == [101]


def test_real_open_matches_creation_before_releasing_query_guard(monkeypatch):
    kernel = QueryOnlyKernel()
    backend = readonly_backend(monkeypatch, kernel)
    assert backend.open(12, 0x410) == 102
    assert kernel.opens == [(0x1000, False, 12), (0x410, False, 12)]
    assert kernel.closed == [101]
    changed = QueryOnlyKernel(second_created=54321)
    backend = readonly_backend(monkeypatch, changed)
    with pytest.raises(ValueError, match='creation'): backend.open(12, 0x410)
    assert set(changed.closed) == {101, 102}


def test_relative_allowed_write_root_is_rejected(tmp_path):
    req = request(tmp_path); req['policy']['allowedWriteRoots'] = ['.']
    with pytest.raises(ValueError, match='absolute'): module().validate_request(req)
