from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path


DEFAULT_QFUNCTION = Path(r"D:\MirServer\Mir200\Envir\Market_Def\QFunction-0.txt")
DEFAULT_QMANAGE = Path(r"D:\MirServer\Mir200\Envir\MapQuest_Def\QManage.txt")
DEFAULT_QFUNCTION_HASH = "E53CF1CF25758B89E5672CD13E610E4DD5DB43369A1682FE94FD45CFCF8039BE"
DEFAULT_QMANAGE_HASH = "7A16E6CCF767CD664163B52E746AA4A79C0E6199581FEC8C9AFD0999A9BA822B"
DEFAULT_BACKUP = Path(r"D:\MirServer\Backup\XY_EXEC_PVP_VICTIM_MESSAGE_20260803_1905")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def managed_hash(body: str) -> str:
    normalized = body.replace("\r\n", "\n").rstrip("\r\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def refresh_marker(text: str, begin_prefix: str, end_marker: str) -> str:
    begin = text.find(begin_prefix)
    if begin < 0:
        raise RuntimeError(f"managed begin missing: {begin_prefix}")
    begin_eol = text.find("\n", begin)
    end = text.find(end_marker, begin_eol + 1)
    if begin_eol < 0 or end < 0:
        raise RuntimeError(f"managed end missing: {end_marker}")
    body = text[begin_eol + 1:end]
    old_line = text[begin:begin_eol].rstrip("\r")
    marker_base = old_line.split(" SHA256=", 1)[0]
    new_line = f"{marker_base} SHA256={managed_hash(body)}"
    suffix = "\r" if text[begin_eol - 1:begin_eol] == "\r" else ""
    return text[:begin] + new_line + suffix + "\n" + text[begin_eol + 1:]


def patch_qfunction(text: str) -> str:
    anchor = (
        "SetHumVar <$C.USERNAME> N$XY_EXEC_SlowDurationMs N$XY_EXEC_DurationMs\r\n"
        "HCALL <$C.USERNAME> @XYDP_ExecutionApplySlow"
    )
    replacement = (
        "SetHumVar <$C.USERNAME> N$XY_EXEC_SlowDurationMs N$XY_EXEC_DurationMs\r\n"
        "SetHumVar <$C.USERNAME> N$XY_EXEC_SlowBonusPercent N$XY_EXEC_PVPBonusPercent\r\n"
        "HCALL <$C.USERNAME> @XYDP_ExecutionApplySlow"
    )
    if text.count(anchor) != 1:
        raise RuntimeError("PVP victim variable transfer anchor is not unique")
    updated = text.replace(anchor, replacement, 1)
    return refresh_marker(
        updated,
        "; XYDP-HOOK-BEGIN xy.lab.execution AttackDamage SHA256=",
        "; XYDP-HOOK-END xy.lab.execution AttackDamage",
    )


def patch_qmanage(text: str) -> str:
    apply_anchor = (
        r"#CALL [\玄渊实验室\处决\处决重甲跪地外观.txt] @XY_EXEC_VISUAL_APPLY" + "\r\n"
        "DelayCall <$STR(N$XY_EXEC_SlowDurationMs)> @XYDP_ExecutionClearSlow"
    )
    apply_replacement = (
        r"#CALL [\玄渊实验室\处决\处决重甲跪地外观.txt] @XY_EXEC_VISUAL_APPLY" + "\r\n"
        "FORMULATION <$STR(N$XY_EXEC_SlowDurationMs)>/1000 N$XY_EXEC_SlowDurationWholeSec\r\n"
        "FORMULATION (<$STR(N$XY_EXEC_SlowDurationMs)>-(<$STR(N$XY_EXEC_SlowDurationWholeSec)>*1000))/100 N$XY_EXEC_SlowDurationTenth\r\n"
        "MESSAGEBOX 您已被击倒！移动速度降低50%，持续<$STR(N$XY_EXEC_SlowDurationWholeSec)>.<$STR(N$XY_EXEC_SlowDurationTenth)>秒；持续期间受到<$STR(N$XY_EXEC_SlowBonusPercent)>%额外伤害。\r\n"
        "DelayCall <$STR(N$XY_EXEC_SlowDurationMs)> @XYDP_ExecutionClearSlow"
    )
    if text.count(apply_anchor) != 1:
        raise RuntimeError("PVP victim message anchor is not unique")
    updated = text.replace(apply_anchor, apply_replacement, 1)

    clear_anchor = (
        "MOV N$XY_EXEC_SlowActive 0\r\n"
        "MOV N$XY_EXEC_SlowDurationMs 0\r\n"
        "SENDMSG 6"
    )
    clear_replacement = (
        "MOV N$XY_EXEC_SlowActive 0\r\n"
        "MOV N$XY_EXEC_SlowDurationMs 0\r\n"
        "MOV N$XY_EXEC_SlowBonusPercent 0\r\n"
        "MOV N$XY_EXEC_SlowDurationWholeSec 0\r\n"
        "MOV N$XY_EXEC_SlowDurationTenth 0\r\n"
        "SENDMSG 6"
    )
    if updated.count(clear_anchor) != 1:
        raise RuntimeError("PVP victim message cleanup anchor is not unique")
    updated = updated.replace(clear_anchor, clear_replacement, 1)
    return refresh_marker(
        updated,
        "; XYDP-BEGIN xy.lab.execution SHA256=",
        "; XYDP-END xy.lab.execution",
    )


def atomic_replace(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.xy-exec-pvp-message-{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qfunction", default=str(DEFAULT_QFUNCTION))
    parser.add_argument("--qmanage", default=str(DEFAULT_QMANAGE))
    parser.add_argument("--qfunction-hash", default=DEFAULT_QFUNCTION_HASH)
    parser.add_argument("--qmanage-hash", default=DEFAULT_QMANAGE_HASH)
    parser.add_argument("--backup", default=str(DEFAULT_BACKUP))
    args = parser.parse_args()

    qfunction = Path(args.qfunction)
    qmanage = Path(args.qmanage)
    backup = Path(args.backup)
    expected_qfunction = args.qfunction_hash.upper()
    expected_qmanage = args.qmanage_hash.upper()
    if sha256(qfunction) != expected_qfunction or sha256(qmanage) != expected_qmanage:
        raise RuntimeError("live files changed after diagnosis; refusing transaction")

    qfunction_raw = qfunction.read_bytes()
    qmanage_raw = qmanage.read_bytes()
    qfunction_text = qfunction_raw.decode("gb18030")
    qmanage_text = qmanage_raw.decode("gb18030")
    qfunction_after = patch_qfunction(qfunction_text).encode("gb18030")
    qmanage_after = patch_qmanage(qmanage_text).encode("gb18030")

    backup.mkdir(parents=True, exist_ok=False)
    qfunction_before = backup / "QFunction-0.before.txt"
    qmanage_before = backup / "QManage.before.txt"
    qfunction_stage = backup / "QFunction-0.after.txt"
    qmanage_stage = backup / "QManage.after.txt"
    qfunction_before.write_bytes(qfunction_raw)
    qmanage_before.write_bytes(qmanage_raw)
    qfunction_stage.write_bytes(qfunction_after)
    qmanage_stage.write_bytes(qmanage_after)

    applied: list[tuple[Path, Path]] = []
    try:
        atomic_replace(qfunction_stage, qfunction)
        applied.append((qfunction, qfunction_before))
        atomic_replace(qmanage_stage, qmanage)
        applied.append((qmanage, qmanage_before))
    except Exception:
        for target, before in reversed(applied):
            atomic_replace(before, target)
        raise

    qfunction_after_hash = sha256(qfunction)
    qmanage_after_hash = sha256(qmanage)
    if qfunction_after_hash != sha256_bytes(qfunction_after) or qmanage_after_hash != sha256_bytes(qmanage_after):
        for target, before in reversed(applied):
            atomic_replace(before, target)
        raise RuntimeError("post-install hash mismatch; restored both files")

    receipt = {
        "schema": "xy-execution-pvp-victim-message/1",
        "status": "candidate-static-installed",
        "created_at": datetime.now().astimezone().isoformat(),
        "files": [
            {"target": str(qfunction), "before": expected_qfunction, "after": qfunction_after_hash},
            {"target": str(qmanage), "before": expected_qmanage, "after": qmanage_after_hash},
        ],
        "message": "您已被击倒！移动速度降低50%，持续X.X秒；持续期间受到XX%额外伤害。",
        "m2_operated": False,
        "platform_modified": False,
    }
    (backup / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
