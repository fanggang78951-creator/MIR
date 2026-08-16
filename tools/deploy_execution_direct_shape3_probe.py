from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path


VISUAL = Path(r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊实验室\处决\处决重甲跪地外观.txt")
DRESS = Path(r"D:\11周年\data\dress.txt")
ORIGINAL_DRESS = Path(r"D:\MirServer\Backup\XY_EXEC_DRESS_KNOWN_ARMOR_PROBE_20260804_143309\dress.txt")
BACKUP_ROOT = Path(r"D:\MirServer\Backup")
EXPECTED_VISUAL = "6B2E3EA961F7022F868CEE1BA46ACB2522BBDD2D993CA5337E1DAF2B68FEC9DA"
EXPECTED_PROBE_DRESS = "A2369281B77D7E4F88CB113BAF317D29F2C6C33966FCF7EC38C40463FBC54980"
EXPECTED_ORIGINAL_DRESS = "2FC2878CF07526A8E0FBC9821A118AE2E3F766C7BDAE96885CC7CDD053C86186"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> None:
    visual_before = VISUAL.read_bytes()
    dress_before = DRESS.read_bytes()
    dress_original = ORIGINAL_DRESS.read_bytes()
    if sha256_bytes(visual_before) != EXPECTED_VISUAL:
        raise ValueError(f"visual script drifted: {sha256_bytes(visual_before)}")
    if sha256_bytes(dress_before) != EXPECTED_PROBE_DRESS:
        raise ValueError(f"dress probe drifted: {sha256_bytes(dress_before)}")
    if sha256_bytes(dress_original) != EXPECTED_ORIGINAL_DRESS:
        raise ValueError(f"original dress backup drifted: {sha256_bytes(dress_original)}")

    visual_text = visual_before.decode("gb18030")
    old_line = "SetItemShape 0 = 306"
    new_line = "SetItemShape 0 = 3"
    if visual_text.count(old_line) != 1:
        raise ValueError("expected exactly one Shape306 apply command")
    if "SetItemShape 0 = <$STR(N$XY_EXEC_OriginalDressShape)>" not in visual_text:
        raise ValueError("original shape restore command missing")
    visual_after = visual_text.replace(old_line, new_line, 1).encode("gb18030")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_ROOT / f"XY_EXEC_DIRECT_SHAPE3_PROBE_{stamp}"
    backup.mkdir(parents=False, exist_ok=False)
    shutil.copy2(VISUAL, backup / VISUAL.name)
    shutil.copy2(DRESS, backup / DRESS.name)

    before_report = {
        "operation": "direct_setitemshape_3_probe",
        "visual_before_sha256": sha256_bytes(visual_before),
        "dress_before_sha256": sha256_bytes(dress_before),
        "dress_restore_source": str(ORIGINAL_DRESS),
        "dress_restore_sha256": sha256_bytes(dress_original),
        "platform_updated": False,
        "engine_or_m2_operated": False,
    }
    (backup / "before.json").write_text(json.dumps(before_report, ensure_ascii=False, indent=2), encoding="utf-8")

    candidates = {
        VISUAL: visual_after,
        DRESS: dress_original,
    }
    temps: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        for target, data in candidates.items():
            temp = target.with_name(f".{target.name}.xy-exec-shape3-{uuid.uuid4().hex}.tmp")
            temp.write_bytes(data)
            if sha256(temp) != sha256_bytes(data):
                raise RuntimeError(f"staged hash mismatch: {target}")
            temps[target] = temp
        for target, temp in temps.items():
            os.replace(temp, target)
            committed.append(target)
        if sha256(VISUAL) != sha256_bytes(visual_after) or sha256(DRESS) != EXPECTED_ORIGINAL_DRESS:
            raise RuntimeError("post-commit hash mismatch")
    except Exception:
        for target in reversed(committed):
            source = backup / target.name
            rollback = target.with_name(f".{target.name}.xy-exec-rollback-{uuid.uuid4().hex}.tmp")
            shutil.copy2(source, rollback)
            os.replace(rollback, target)
        raise
    finally:
        for temp in temps.values():
            if temp.exists():
                temp.unlink()

    after_report = {
        **before_report,
        "status": "COMMITTED",
        "backup": str(backup),
        "visual_after_sha256": sha256(VISUAL),
        "dress_after_sha256": sha256(DRESS),
        "active_probe": "SetItemShape position 0 equals built-in Shape 3",
        "fashion_visible_behavior": "skip visual",
    }
    (backup / "after.json").write_text(json.dumps(after_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(after_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
