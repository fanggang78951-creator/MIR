"""Read-only target audit plus isolated transaction/rollback for the four-entry fix."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

from xydp.equipment_wash import (
    EquipmentWashImportService, MAIN_RELATIVE, WASH_DIRECTORY, RANDOM_CORE_RELATIVE,
    EFFECT_CORE_RELATIVE, QFUNCTION_RELATIVE, TEXTVAR_RELATIVE, ATTACK_SPEED_CORE_RELATIVE,
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify(platform: Path, server: Path):
    source = platform / '所需材料表格汇总/洗练属性.txt'
    direct = [WASH_DIRECTORY / f for f in ('仙级直出.txt', '圣级直出.txt', '天赐开光.txt', '神佑开光.txt')]
    paths = [MAIN_RELATIVE, QFUNCTION_RELATIVE, TEXTVAR_RELATIVE, ATTACK_SPEED_CORE_RELATIVE,
             RANDOM_CORE_RELATIVE, EFFECT_CORE_RELATIVE, *direct]
    original = {p: (server / p).read_bytes() for p in paths}
    service = EquipmentWashImportService(platform)
    plan = service.preflight(server, source)
    assert not plan.blockers, plan.blockers
    assert {Path(c.relative_path) for c in plan.changes} in (set(), set(direct))
    changed = []
    for change in plan.changes:
        # The active server correction is exactly two standalone brace lines.
        after_lines = change.after.splitlines(keepends=True)
        stripped = b''.join(x for x in after_lines if x.strip() not in (b'{', b'}'))
        assert stripped == change.before, change.relative_path
        changed.append(str(change.relative_path))

    texts = {p: data.decode('gb18030').replace('\r\n', '\n') for p, data in original.items()}
    texts.update({Path(c.relative_path): c.after.decode('gb18030').replace('\r\n', '\n') for c in plan.changes})
    # Includes both NPCs, all four direct entries, and QFunction's runtime calls.
    opening = Path('Mir200/Envir/Market_Def/玄渊实验室/装备开光-XY_NMGF_MAIN.txt')
    call_sources = [*texts.values(), (server / opening).read_bytes().decode('gb18030')]
    audited = set()
    for text in call_sources:
        for path, label in re.findall(r'(?im)^#CALL\s+\[([^\]]+)\]\s+(@\S+)', text):
            if '玄渊实验室\\装备洗练\\' not in path:
                continue
            relative = Path('Mir200/Envir/QuestDiary') / path.lstrip('\\').replace('\\', '/')
            body = texts[relative]
            assert re.search(rf'(?m)^\[{re.escape(label)}\]\n\{{\s*$', body), (relative, label)
            audited.add((str(relative), label))

    temp_parent = platform / 'runtime/temp'
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wash_direct_repair_', dir=temp_parent) as tmp:
        base = Path(tmp)
        target = base / 'server'
        for relative, data in original.items():
            file = target / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        sandbox_service = EquipmentWashImportService(base / 'platform')
        sandbox_plan = sandbox_service.preflight(target, source)
        assert not sandbox_plan.blockers, sandbox_plan.blockers
        receipt = sandbox_service.install(sandbox_plan)
        assert not sandbox_service.preflight(target, source).changes
        # Existing imported files altered by the user must not be overwritten.
        dirty = target / direct[0]
        clean = dirty.read_bytes()
        dirty.write_bytes(clean + b'; manual edit\r\n')
        assert sandbox_service.preflight(target, source).blockers
        dirty.write_bytes(clean)
        sandbox_service.rollback(target, receipt.transaction_id)
        assert all((target / p).read_bytes() == data for p, data in original.items())
    assert all((server / p).read_bytes() == data for p, data in original.items())
    return {
        'status': 'passed', 'changes': changed, 'call_targets': sorted(audited),
        'call_target_count': len(audited), 'exact_brace_only_patch': True,
        'isolated_install_idempotence_rollback': True, 'manual_edit_blocked': True,
        'target_read_only_hashes': {str(p): digest(data) for p, data in original.items()},
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', type=Path, required=True)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.platform, args.server)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'target_read_only_hashes'}, ensure_ascii=False))
