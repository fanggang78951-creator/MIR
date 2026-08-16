from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


TARGET = Path(r"D:\11周年\data\dress.txt")
BACKUP = Path(r"D:\MirServer\Backup\XY_EXEC_DRESS_KNOWN_ARMOR_PROBE_20260804_143309\dress.txt")
VISUAL_SCRIPT = Path(r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊实验室\处决\处决重甲跪地外观.txt")
DATA = Path(r"D:\11周年\data")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def shape_block(data: bytes, shape: int) -> bytes:
    match = re.search(
        rb'"' + str(shape).encode("ascii") + rb'"\s*:\s*\{.*?\}(?=\r?\n,"|\s*$)',
        data,
        re.DOTALL,
    )
    if match is None:
        raise ValueError(f"shape {shape} mapping not found")
    return match.group(0)


def main() -> None:
    before = BACKUP.read_bytes()
    after = TARGET.read_bytes()
    before306 = shape_block(before, 306)
    after306 = shape_block(after, 306)
    known3_before = shape_block(before, 3)
    known3_after = shape_block(after, 3)

    expected = before306
    replacements = (
        (b'"OffSet":0', b'"OffSet":1800'),
        (b'"WhichLib":"XYExecKneel"', b'"WhichLib":"hum"'),
        (b'"SeriesOffSet":0', b'"SeriesOffSet":6000'),
        (b'"WhichSeriesLib":"XYExecKneelS"', b'"WhichSeriesLib":"cbohum"'),
    )
    for old, new in replacements:
        assert expected.count(old) == 1
        expected = expected.replace(old, new, 1)
    assert after306 == expected
    assert known3_before == known3_after
    assert after.replace(after306, before306, 1) == before
    assert sha256(VISUAL_SCRIPT) == "6B2E3EA961F7022F868CEE1BA46ACB2522BBDD2D993CA5337E1DAF2B68FEC9DA"

    report = {
        "status": "PASS",
        "dress_before_sha256": sha256(BACKUP),
        "dress_after_sha256": sha256(TARGET),
        "only_shape306_changed": True,
        "shape306_normal": "hum:1800",
        "shape306_series": "cbohum:6000",
        "matches_known_shape3": True,
        "execution_visual_script_unchanged": True,
        "custom_kneel_libraries_preserved": {
            name: sha256(DATA / name)
            for name in ("XYExecKneel.wzl", "XYExecKneel.wzx", "XYExecKneelS.wzl", "XYExecKneelS.wzx")
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
