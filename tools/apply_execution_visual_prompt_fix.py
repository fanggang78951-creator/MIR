from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import uuid
from datetime import datetime
from pathlib import Path


QF_OLD = (
    "MESSAGEBOX 您已被击倒！移动速度降低50%，持续"
    "<$STR(N$XY_EXEC_MONSTER_DurationWholeSec)>.<$STR(N$XY_EXEC_MONSTER_DurationTenth)>秒；"
    "持续期间受到<$STR(N$XY_EXEC_MONSTER_BonusPercent)>%额外伤害。"
)
QF_NEW = (
    "SendNewLineMsg 1 251 0 16 120 5 0 您已被击倒！||"
    "移动速度降低50%，持续<$STR(N$XY_EXEC_MONSTER_DurationWholeSec)>.<$STR(N$XY_EXEC_MONSTER_DurationTenth)>秒||"
    "持续期间受到<$STR(N$XY_EXEC_MONSTER_BonusPercent)>%额外伤害。"
)
QM_OLD = (
    "MESSAGEBOX 您已被击倒！移动速度降低50%，持续"
    "<$STR(N$XY_EXEC_SlowDurationWholeSec)>.<$STR(N$XY_EXEC_SlowDurationTenth)>秒；"
    "持续期间受到<$STR(N$XY_EXEC_SlowBonusPercent)>%额外伤害。"
)
QM_NEW = (
    "SendNewLineMsg 1 251 0 16 120 5 0 您已被击倒！||"
    "移动速度降低50%，持续<$STR(N$XY_EXEC_SlowDurationWholeSec)>.<$STR(N$XY_EXEC_SlowDurationTenth)>秒||"
    "持续期间受到<$STR(N$XY_EXEC_SlowBonusPercent)>%额外伤害。"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def managed_hash(body: str) -> str:
    normalized = body.replace("\r\n", "\n").rstrip("\r\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def refresh_managed_hash(text: str, begin_prefix: str, end_line: str) -> str:
    begin_at = text.find(begin_prefix)
    if begin_at < 0:
        raise ValueError(f"managed begin marker not found: {begin_prefix}")
    begin_eol = text.find("\n", begin_at)
    if begin_eol < 0:
        raise ValueError(f"managed begin marker has no body: {begin_prefix}")
    body_start = begin_eol + 1
    end_at = text.find(end_line, body_start)
    if end_at < 0:
        raise ValueError(f"managed end marker not found: {end_line}")
    body = text[body_start:end_at]
    old_begin = text[begin_at:begin_eol].rstrip("\r")
    if " SHA256=" not in old_begin:
        return text
    marker_base = old_begin.split(" SHA256=", 1)[0]
    new_begin = f"{marker_base} SHA256={managed_hash(body)}"
    newline_suffix = "\r" if text[begin_eol - 1:begin_eol] == "\r" else ""
    return text[:begin_at] + new_begin + newline_suffix + text[begin_eol:]


def patch_text(path: Path, old: str, new: str, begin_prefix: str, end_line: str) -> bytes:
    raw = path.read_bytes()
    text = raw.decode("gb18030")
    if text.count(old) != 1:
        raise ValueError(f"expected exactly one old victim message in {path}, got {text.count(old)}")
    if new in text:
        raise ValueError(f"new victim message already exists in {path}")
    text = text.replace(old, new, 1)
    text = refresh_managed_hash(text, begin_prefix, end_line)
    updated = text.encode("gb18030")
    if b"\r\n" in raw and b"\r\n" not in updated:
        raise ValueError(f"CRLF was not preserved in {path}")
    return updated


def validate_human_library(wzl: Path, wzx: Path) -> None:
    magic = b"www.shandagames.com\x00"
    wzl_header = wzl.read_bytes()[:48]
    wzx_header = wzx.read_bytes()[:48]
    if not wzl_header.startswith(magic) or not wzx_header.startswith(magic):
        raise ValueError("candidate WZL/WZX does not use the standard human-library header")
    if struct.unpack_from("<I", wzl_header, 44)[0] != 600:
        raise ValueError("candidate WZL frame count is not 600")
    if struct.unpack_from("<I", wzx_header, 44)[0] != 600:
        raise ValueError("candidate WZX frame count is not 600")


def atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def atomic_copy(source: Path, target: Path) -> None:
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    shutil.copy2(source, temp)
    os.replace(temp, target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--library", required=True)
    parser.add_argument("--backup-root", required=True)
    args = parser.parse_args()

    server = Path(args.server)
    client = Path(args.client)
    library = Path(args.library)
    backup = Path(args.backup_root)
    qfunction = server / "Mir200/Envir/Market_Def/QFunction-0.txt"
    qmanage = server / "Mir200/Envir/MapQuest_Def/QManage.txt"
    target_wzl = client / "data/XYExecKneel.wzl"
    target_wzx = client / "data/XYExecKneel.wzx"
    source_wzl = library / "XYExecKneel.wzl"
    source_wzx = library / "XYExecKneel.wzx"
    targets = [qfunction, qmanage, target_wzl, target_wzx]
    if any(not path.is_file() for path in [*targets, source_wzl, source_wzx]):
        missing = [str(path) for path in [*targets, source_wzl, source_wzx] if not path.is_file()]
        raise FileNotFoundError(missing)

    validate_human_library(source_wzl, source_wzx)
    if target_wzl.read_bytes()[:20] == source_wzl.read_bytes()[:20]:
        raise ValueError("live WZL already has the standard header; refusing ambiguous reapply")

    qf_after = patch_text(
        qfunction,
        QF_OLD,
        QF_NEW,
        "; XYDP-HOOK-BEGIN xy.lab.execution.monster-map0 StruckDamage",
        "; XYDP-HOOK-END xy.lab.execution.monster-map0 StruckDamage",
    )
    qm_after = patch_text(
        qmanage,
        QM_OLD,
        QM_NEW,
        "; XYDP-BEGIN xy.lab.execution SHA256=",
        "; XYDP-END xy.lab.execution",
    )

    before = {str(path): sha256(path) for path in targets}
    backup.mkdir(parents=True, exist_ok=False)
    for path in targets:
        relative = path.relative_to(server) if path.is_relative_to(server) else Path("client") / path.relative_to(client)
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    atomic_write(qfunction, qf_after)
    atomic_write(qmanage, qm_after)
    atomic_copy(source_wzl, target_wzl)
    atomic_copy(source_wzx, target_wzx)

    after = {str(path): sha256(path) for path in targets}
    if after[str(target_wzl)] != sha256(source_wzl) or after[str(target_wzx)] != sha256(source_wzx):
        raise RuntimeError("published human library hash mismatch")
    receipt = {
        "schema": "xy-execution-visual-prompt-fix/1",
        "status": "candidate-static-applied",
        "created_at": datetime.now().astimezone().isoformat(),
        "cause": "generic image-library headers were not accepted by the client human renderer",
        "prompt": "MESSAGEBOX replaced by personal SendNewLineMsg transparent prompt",
        "before_sha256": before,
        "after_sha256": after,
        "source_library_sha256": {str(source_wzl): sha256(source_wzl), str(source_wzx): sha256(source_wzx)},
    }
    (backup / "transaction_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
