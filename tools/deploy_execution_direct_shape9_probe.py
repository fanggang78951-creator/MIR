from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path


TARGET = Path(r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊实验室\处决\处决重甲跪地外观.txt")
BACKUP_ROOT = Path(r"D:\MirServer\Backup")
EXPECTED_BEFORE = "0E6D50B31FD79538491E06364433CD3FA906DB69463363DF46E7AC997A40C835"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def main() -> None:
    before = TARGET.read_bytes()
    if sha256_bytes(before) != EXPECTED_BEFORE:
        raise ValueError(f"visual script drifted: {sha256_bytes(before)}")
    text = before.decode("gb18030")
    old_line = "SetItemShape 0 = 302"
    new_line = "SetItemShape 0 = 9"
    if text.count(old_line) != 1:
        raise ValueError("expected exactly one Shape302 probe command")
    for required in (
        "CheckShowFashion",
        "EQUAL N$XY_EXEC_CurrentDressId <$STR(N$XY_EXEC_OriginalDressId)>",
        "SetItemShape 0 = <$STR(N$XY_EXEC_OriginalDressShape)>",
    ):
        if required not in text:
            raise ValueError(f"visual safety contract missing: {required}")
    after = text.replace(old_line, new_line, 1).encode("gb18030")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_ROOT / f"XY_EXEC_DIRECT_SHAPE9_PROBE_{stamp}"
    backup.mkdir(parents=False, exist_ok=False)
    shutil.copy2(TARGET, backup / TARGET.name)
    report = {
        "operation": "direct_setitemshape_9_probe",
        "target": str(TARGET),
        "before_sha256": sha256_bytes(before),
        "after_sha256": sha256_bytes(after),
        "active_probe": "SetItemShape position 0 equals unused low Shape 9",
        "shape9_mapping": {"normal": "hum:5400", "series": "cbohum:18000"},
        "database_clothing_shape9_rows": 0,
        "platform_updated": False,
        "client_resources_updated": False,
        "engine_or_m2_operated": False,
        "backup": str(backup),
    }
    (backup / "before.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    temp = TARGET.with_name(f".{TARGET.name}.xy-exec-9-{uuid.uuid4().hex}.tmp")
    try:
        temp.write_bytes(after)
        if sha256_bytes(temp.read_bytes()) != report["after_sha256"]:
            raise RuntimeError("staged hash mismatch")
        os.replace(temp, TARGET)
    finally:
        if temp.exists():
            temp.unlink()
    if sha256_bytes(TARGET.read_bytes()) != report["after_sha256"]:
        rollback = TARGET.with_name(f".{TARGET.name}.xy-exec-rollback-{uuid.uuid4().hex}.tmp")
        shutil.copy2(backup / TARGET.name, rollback)
        os.replace(rollback, TARGET)
        raise RuntimeError("post-commit hash mismatch; backup restored")

    report["status"] = "COMMITTED"
    (backup / "after.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
