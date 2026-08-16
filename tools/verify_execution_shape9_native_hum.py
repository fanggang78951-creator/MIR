from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from stage_execution_shape9_native_hum import load_pair, validate_merge


DATA = Path(r"D:\11周年\data")
ROOT = Path(r"D:\MirServer\Backup\XY_EXEC_SHAPE9_NATIVE_HUM_20260804_184447")
BEFORE = ROOT / "before"
STAGE = ROOT / "stage"
SCRIPT = Path(r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊实验室\处决\处决重甲跪地外观.txt")
QFUNCTION = Path(r"D:\MirServer\Mir200\Envir\Market_Def\QFunction-0.txt")
QMANAGE = Path(r"D:\MirServer\Mir200\Envir\MapQuest_Def\QManage.txt")
DRESS = DATA / "dress.txt"

ORIGINAL = {
    "Hum.wzl": "CBB0C27CF648132D4C4E647981F1ADDB124F5538BE6AF4341A036DBD975DE1BE",
    "Hum.wzx": "AE9653FF8BE0EC8489BD46F5E0B8B28747DC62D387A2659F399D67CE8D2D0605",
    "cbohum.wzl": "142EF6CFAFAF60CB10ECE5169960858F3CDA3858E9BF8BCE1A8A8E3687B3E51B",
    "cbohum.wzx": "8D3BC10057F0F8BAC2BB663C38B64CC0895AFA9E293AFFAB27587F8A7D421F16",
}
DEPLOYED = {
    "Hum.wzl": "44DA7372E16A9C34CE41FE71392A4DDEF096AFB7525F1DCF4B36A1F653DF6F4D",
    "Hum.wzx": "672BFCE6C2B11583617B6A6301DC51B5E6048E5019B9E07A84C960DC0AA0BC80",
    "cbohum.wzl": "ED86E47874BD157516262F7559643FCE6170F715050C4529E6327FD478D52065",
    "cbohum.wzx": "5BC8579875EFBCD621830CCE71409BF08526B6A4A0C15C28D72CD1A81E9F6B8A",
}
UNCHANGED = {
    DRESS: "2FC2878CF07526A8E0FBC9821A118AE2E3F766C7BDAE96885CC7CDD053C86186",
    SCRIPT: "E4DC73C3632BA28A83923EA5210D0D874039E7C9FFA6132548385C1F16CDE0E3",
    QFUNCTION: "A6EE1F87632A864525BE1FE9818485EE806ED905AFBE96B668B05389A9666475",
    QMANAGE: "201BC1F5BFE8C095BB393E93C5B397267D7F51AA278F981F02607C8519E532E5",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def require_hashes(folder: Path, expected: dict[str, str]) -> None:
    for name, expected_hash in expected.items():
        actual = sha256(folder / name)
        if actual != expected_hash:
            raise RuntimeError(f"hash mismatch: {folder / name}: {actual} != {expected_hash}")


def rollback_rehearsal() -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="rollback_rehearsal_", dir=ROOT) as temp_name:
        temp_root = Path(temp_name)
        for name in ORIGINAL:
            shutil.copy2(DATA / name, temp_root / name)
        require_hashes(temp_root, DEPLOYED)
        for name in ORIGINAL:
            incoming = temp_root / f".{name}.restore.tmp"
            shutil.copyfile(BEFORE / name, incoming)
            os.replace(incoming, temp_root / name)
        require_hashes(temp_root, ORIGINAL)
        return {name: sha256(temp_root / name) for name in ORIGINAL}


def main() -> None:
    require_hashes(DATA, DEPLOYED)
    require_hashes(STAGE, DEPLOYED)
    require_hashes(BEFORE, ORIGINAL)

    normal_before = load_pair(BEFORE / "Hum.wzl", BEFORE / "Hum.wzx")
    normal_source = load_pair(DATA / "XYExecKneel.wzl", DATA / "XYExecKneel.wzx")
    normal_result = validate_merge(
        normal_before,
        normal_source,
        (DATA / "Hum.wzl").read_bytes(),
        (DATA / "Hum.wzx").read_bytes(),
        5400,
    )

    series_before = load_pair(BEFORE / "cbohum.wzl", BEFORE / "cbohum.wzx")
    series_source = load_pair(DATA / "XYExecKneelS.wzl", DATA / "XYExecKneelS.wzx")
    series_result = validate_merge(
        series_before,
        series_source,
        (DATA / "cbohum.wzl").read_bytes(),
        (DATA / "cbohum.wzx").read_bytes(),
        18000,
    )

    unchanged_result: dict[str, str] = {}
    for path, expected_hash in UNCHANGED.items():
        actual = sha256(path)
        if actual != expected_hash:
            raise RuntimeError(f"unrelated file changed: {path}: {actual} != {expected_hash}")
        unchanged_result[str(path)] = actual

    script_text = SCRIPT.read_text(encoding="gb18030")
    if "SetItemShape 0 = 9" not in script_text:
        raise RuntimeError("execution visual script is no longer bound to Shape9")
    residues = sorted(str(path) for path in DATA.glob(".*.xy_exec_*.tmp"))
    if residues:
        raise RuntimeError(f"deployment temporary residue remains: {residues}")

    report = {
        "schema": "xy-execution-shape9-native-hum-verification/1",
        "status": "STATIC_AND_ROLLBACK_REHEARSAL_PASS_PENDING_GAME_ACCEPTANCE",
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "deployed_hashes": DEPLOYED,
        "normal": normal_result,
        "series": series_result,
        "rollback_rehearsal": rollback_rehearsal(),
        "unchanged_files": unchanged_result,
        "script_binding": "SetItemShape 0 = 9",
        "platform_updated": False,
        "engine_or_m2_operated": False,
    }
    output = ROOT / "verification_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
