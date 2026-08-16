from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path


DEFAULT_TARGET = Path(r"D:\MirServer\Mir200\Envir\Market_Def\QFunction-0.txt")
DEFAULT_EXPECTED_BEFORE = "307487E26320DA12FED5CD2570588F1793DD5F1BCA0E2E5863D7D9CD1522AF9B"
DEFAULT_BACKUP = Path(r"D:\MirServer\Backup\XY_EXEC_MONSTER_VISUAL_20260803_185451")
APPLY_CALL = r"#CALL [\玄渊实验室\处决\处决重甲跪地外观.txt] @XY_EXEC_VISUAL_APPLY"
CLEAR_CALL = r"#CALL [\玄渊实验室\处决\处决重甲跪地外观.txt] @XY_EXEC_VISUAL_CLEAR"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=str(DEFAULT_TARGET))
    parser.add_argument("--backup", default=str(DEFAULT_BACKUP))
    parser.add_argument("--expected-before", default=DEFAULT_EXPECTED_BEFORE)
    args = parser.parse_args()
    target = Path(args.target)
    backup = Path(args.backup)
    expected_before = args.expected_before.upper()

    if sha256(target) != expected_before:
        raise RuntimeError("QFunction changed after diagnosis; refusing to patch")
    raw = target.read_bytes()
    text = raw.decode("gb18030")
    if b"\r\n" not in raw:
        raise RuntimeError("QFunction is not CRLF")

    begin_marker = "; XYDP-LAB-BEGIN xy.lab.execution.monster-map0"
    end_marker = "; XYDP-LAB-END xy.lab.execution.monster-map0"
    begin = text.find(begin_marker)
    end = text.find(end_marker, begin)
    if begin < 0 or end < 0:
        raise RuntimeError("monster execution lab block is missing")
    block = text[begin:end]
    if APPLY_CALL in block or CLEAR_CALL in block:
        raise RuntimeError("monster visual hook already exists")

    apply_anchor = (
        "ChangeSpeed 1 -10\r\n"
        "MOV N$XY_EXEC_MONSTER_SlowActive 1"
    )
    apply_replacement = (
        "ChangeSpeed 1 -10\r\n"
        f"{APPLY_CALL}\r\n"
        "FORMULATION <$STR(N$XY_EXEC_MONSTER_DurationMs)>/1000 N$XY_EXEC_MONSTER_DurationWholeSec\r\n"
        "FORMULATION (<$STR(N$XY_EXEC_MONSTER_DurationMs)>-(<$STR(N$XY_EXEC_MONSTER_DurationWholeSec)>*1000))/100 N$XY_EXEC_MONSTER_DurationTenth\r\n"
        "MESSAGEBOX 您已被击倒！移动速度降低50%，持续<$STR(N$XY_EXEC_MONSTER_DurationWholeSec)>.<$STR(N$XY_EXEC_MONSTER_DurationTenth)>秒；持续期间受到<$STR(N$XY_EXEC_MONSTER_BonusPercent)>%额外伤害。\r\n"
        "MOV N$XY_EXEC_MONSTER_SlowActive 1"
    )
    if block.count(apply_anchor) != 1:
        raise RuntimeError("monster visual apply anchor is not unique")
    block = block.replace(apply_anchor, apply_replacement, 1)

    clear_label = "[@XYDP_ExecutionMonsterClear]"
    clear_at = block.find(clear_label)
    if clear_at < 0:
        raise RuntimeError("monster clear label is missing")
    clear_head = block[:clear_at]
    clear_body = block[clear_at:]
    clear_anchor = (
        "#ACT\r\n"
        "ChangeSpeed 1 0\r\n"
        "MOV N$XY_EXEC_MONSTER_SlowActive 0"
    )
    clear_replacement = (
        "#ACT\r\n"
        f"{CLEAR_CALL}\r\n"
        "ChangeSpeed 1 0\r\n"
        "MOV N$XY_EXEC_MONSTER_SlowActive 0"
    )
    if clear_body.count(clear_anchor) != 1:
        raise RuntimeError("monster visual clear anchor is not unique")
    clear_body = clear_body.replace(clear_anchor, clear_replacement, 1)
    updated_block = clear_head + clear_body
    updated = text[:begin] + updated_block + text[end:]

    if updated.count(APPLY_CALL) != text.count(APPLY_CALL) + 1:
        raise RuntimeError("unexpected APPLY call count")
    if updated.count(CLEAR_CALL) != text.count(CLEAR_CALL) + 1:
        raise RuntimeError("unexpected CLEAR call count")
    updated_bytes = updated.encode("gb18030")

    backup.mkdir(parents=True, exist_ok=False)
    before_file = backup / "QFunction-0.before.txt"
    before_file.write_bytes(raw)
    if sha256(before_file) != expected_before:
        raise RuntimeError("backup hash mismatch")

    temporary = target.with_name(f".{target.name}.xy-exec-monster-visual-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(updated_bytes)
        expected_after = sha256(temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()

    actual_after = sha256(target)
    if actual_after != expected_after:
        raise RuntimeError("live read-back hash mismatch")

    receipt = {
        "schema": "xy-execution-monster-visual-hook/1",
        "status": "candidate-static-installed",
        "created_at": datetime.now().astimezone().isoformat(),
        "target": str(target),
        "before_sha256": expected_before,
        "after_sha256": actual_after,
        "changes": [
            "monster StruckDamage success branch calls XY_EXEC_VISUAL_APPLY",
            "monster victim receives a numeric knockdown message with speed, duration, and extra damage",
            "XYDP_ExecutionMonsterClear calls XY_EXEC_VISUAL_CLEAR before speed reset",
        ],
        "m2_operated": False,
        "platform_modified": False,
    }
    (backup / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
