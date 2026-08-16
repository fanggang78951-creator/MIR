from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


MALE_ITEM = "玄渊处决重甲跪地男"
FEMALE_ITEM = "玄渊处决重甲跪地女"
VISUAL_CALL_PATH = r"\玄渊实验室\处决\处决重甲跪地外观.txt"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def managed_hash(body: str) -> str:
    normalized = body.replace("\r\n", "\n").rstrip("\r\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def read_gb18030(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    text = raw.decode("gb18030")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    return text, newline


def write_gb18030(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("gb18030"))


def update_managed_region(text: str, begin_prefix: str, end_line: str, transform) -> str:
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
    updated = transform(body)
    if not updated.endswith(("\n", "\r")):
        updated += "\n"
    old_begin = text[begin_at:begin_eol].rstrip("\r")
    marker_base = old_begin.split(" SHA256=", 1)[0]
    new_begin = f"{marker_base} SHA256={managed_hash(updated)}"
    newline_suffix = "\r" if text[begin_eol - 1:begin_eol] == "\r" else ""
    return text[:begin_at] + new_begin + newline_suffix + "\n" + updated + text[end_at:]


def patch_qmanage(source: Path, target: Path) -> None:
    text, newline = read_gb18030(source)

    def transform(body: str) -> str:
        normalized = body.replace("\r\n", "\n")
        apply_call = f"#CALL [{VISUAL_CALL_PATH}] @XY_EXEC_VISUAL_APPLY"
        clear_call = f"#CALL [{VISUAL_CALL_PATH}] @XY_EXEC_VISUAL_CLEAR"
        if apply_call not in normalized:
            needle = "ChangeSpeed 1 -10\nDelayCall"
            if needle not in normalized:
                raise ValueError("execution slow apply anchor not found")
            normalized = normalized.replace(needle, f"ChangeSpeed 1 -10\n{apply_call}\nDelayCall", 1)
        if clear_call not in normalized:
            needle = "#ACT\nChangeSpeed 1 0\nMOV N$XY_EXEC_SlowActive 0"
            if needle not in normalized:
                raise ValueError("execution slow clear anchor not found")
            normalized = normalized.replace(needle, f"#ACT\n{clear_call}\nChangeSpeed 1 0\nMOV N$XY_EXEC_SlowActive 0", 1)
        return normalized.replace("\n", newline)

    text = update_managed_region(
        text,
        "; XYDP-BEGIN xy.lab.execution SHA256=",
        "; XYDP-END xy.lab.execution",
        transform,
    )
    write_gb18030(target, text)


def patch_qfunction(source: Path, target: Path) -> None:
    text, newline = read_gb18030(source)
    clear_call = f"#CALL [{VISUAL_CALL_PATH}] @XY_EXEC_VISUAL_CLEAR"

    for hook in ("PlayOffLine", "PlayDie", "PlayLogin"):
        def transform(body: str, hook_name: str = hook) -> str:
            normalized = body.replace("\r\n", "\n")
            if clear_call in normalized:
                return normalized.replace("\n", newline)
            prefix = f"#IF\n#ACT\n{clear_call}\n"
            return (prefix + normalized).replace("\n", newline)

        text = update_managed_region(
            text,
            f"; XYDP-HOOK-BEGIN xy.lab.execution {hook} SHA256=",
            f"; XYDP-HOOK-END xy.lab.execution {hook}",
            transform,
        )
    write_gb18030(target, text)


def patch_dress(source: Path, target: Path, shape_id: int) -> None:
    raw = source.read_bytes()
    encoding = "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "gb18030"
        text = raw.decode(encoding)
    parsed = json.loads(text)
    if str(shape_id) in parsed:
        raise ValueError(f"dress shape id already exists: {shape_id}")
    entry = {
        "Id": shape_id,
        "Name": "处决重甲跪地",
        "OffSet": 0,
        "WhichLib": "XYExecKneel",
        "EffectOffSet": -1,
        "WihichEffectLib": "",
        "SeriesOffSet": 0,
        "WhichSeriesLib": "cbohum",
        "SeriesEffectOffSet": -1,
        "WhichSeriesEffectLib": "",
        "StandActEffectCount": -1,
        "Job": ["zjob", "fjob", "djob", "cjob"],
    }
    newline = "\r\n" if "\r\n" in text else "\n"
    closing = text.rfind("}")
    if closing < 0:
        raise ValueError("dress.txt is not an object")
    fragment = "," + json.dumps(str(shape_id), ensure_ascii=False) + ":" + json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    updated = text[:closing].rstrip() + newline + fragment + newline + "}" + text[closing + 1:]
    json.loads(updated)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(updated.encode(encoding))


def patch_database(source: Path, target: Path, shape_id: int) -> list[dict[str, object]]:
    shutil.copy2(source, target)
    connection = sqlite3.connect(target)
    try:
        conflicts = connection.execute(
            "SELECT Idx,Name,StdMode,Shape FROM StdItems WHERE Name IN (?,?) OR Shape=?",
            (MALE_ITEM, FEMALE_ITEM, shape_id),
        ).fetchall()
        if conflicts:
            raise ValueError(f"database conflict: {conflicts}")
        columns = [row[1] for row in connection.execute("PRAGMA table_info(StdItems)")]
        max_idx = connection.execute("SELECT COALESCE(MAX(Idx),0) FROM StdItems").fetchone()[0]
        rows: list[dict[str, object]] = []
        for offset, (name, std_mode) in enumerate(((MALE_ITEM, 66), (FEMALE_ITEM, 67)), start=1):
            values: dict[str, object] = {column: 0 for column in columns}
            values.update({
                "Idx": int(max_idx) + offset,
                "Name": name,
                "StdMode": std_mode,
                "Shape": shape_id,
                "Weight": 0,
                "Looks": 0,
                "DuraMax": 10000,
                "Need": 0,
                "NeedLevel": 0,
                "Price": 0,
                "Stock": 0,
                "Job": 99,
                "CustomItem": 0,
            })
            placeholders = ",".join("?" for _ in columns)
            connection.execute(
                f"INSERT INTO StdItems ({','.join(columns)}) VALUES ({placeholders})",
                [values[column] for column in columns],
            )
            rows.append({"Idx": values["Idx"], "Name": name, "StdMode": std_mode, "Shape": shape_id})
        connection.commit()
        readback = connection.execute(
            "SELECT Idx,Name,StdMode,Shape,Job FROM StdItems WHERE Name IN (?,?) ORDER BY Idx",
            (MALE_ITEM, FEMALE_ITEM),
        ).fetchall()
        if len(readback) != 2:
            raise RuntimeError("database read-back failed")
        return rows
    finally:
        connection.close()


def visual_script() -> str:
    return f"""; 处决临时身体外观候选：重盔甲双膝跪地、双手撑地
; 仅改变时装衣服外显，武器层继续使用玩家当前武器动作。
; 当前为测试服 candidate，游戏验收前禁止沉淀到平台正式包。

[@XY_EXEC_VISUAL_APPLY]
{{
#IF
EQUAL N$XY_EXEC_VisualActive 1
#ACT
BREAK

#IF
NOT CHECKBAGSIZE 2
#ACT
MOV N$XY_EXEC_VisualActive 0
BREAK

#IF
#ACT
MOV N$XY_EXEC_OriginalFashionId 0
MOV N$XY_EXEC_OriginalFashionVisible 0
MOV N$XY_EXEC_VisualSex 0
MOV S$XY_EXEC_VisualCurrentItem 0
GetItemFieldValue 18 makeindex N$XY_EXEC_OriginalFashionId
GetPlayInfo sex N$XY_EXEC_VisualSex

#IF
CheckShowFashion
#ACT
MOV N$XY_EXEC_OriginalFashionVisible 1

#IF
LARGE N$XY_EXEC_OriginalFashionId 0
#ACT
TakeOffItem 18

#IF
EQUAL N$XY_EXEC_VisualSex 0
#ACT
GIVE {MALE_ITEM} 1
AutoTakeOnItem {MALE_ITEM} 18
#ELSEACT
GIVE {FEMALE_ITEM} 1
AutoTakeOnItem {FEMALE_ITEM} 18

#IF
#ACT
GetItemFieldValue 18 name S$XY_EXEC_VisualCurrentItem

#IF
EQUAL S$XY_EXEC_VisualCurrentItem {MALE_ITEM}
#ACT
MOV N$XY_EXEC_VisualActive 1
ShowFashion 1

#IF
EQUAL S$XY_EXEC_VisualCurrentItem {FEMALE_ITEM}
#ACT
MOV N$XY_EXEC_VisualActive 1
ShowFashion 1

#IF
EQUAL N$XY_EXEC_VisualActive 0
#ACT
TAKE {MALE_ITEM} 1
TAKE {FEMALE_ITEM} 1

#IF
EQUAL N$XY_EXEC_VisualActive 0
LARGE N$XY_EXEC_OriginalFashionId 0
#ACT
AutoTakeOnItemEx <$STR(N$XY_EXEC_OriginalFashionId)> 18

#IF
EQUAL N$XY_EXEC_VisualActive 0
EQUAL N$XY_EXEC_OriginalFashionVisible 0
#ACT
ShowFashion 0
}}

[@XY_EXEC_VISUAL_CLEAR]
{{
#IF
EQUAL N$XY_EXEC_VisualActive 0
#ACT
BREAK

#IF
#ACT
GetItemFieldValue 18 name S$XY_EXEC_VisualCurrentItem

#IF
EQUAL S$XY_EXEC_VisualCurrentItem {MALE_ITEM}
#ACT
TakeOffItem 18

#IF
EQUAL S$XY_EXEC_VisualCurrentItem {FEMALE_ITEM}
#ACT
TakeOffItem 18

#IF
#ACT
TAKE {MALE_ITEM} 1
TAKE {FEMALE_ITEM} 1

#IF
LARGE N$XY_EXEC_OriginalFashionId 0
#ACT
AutoTakeOnItemEx <$STR(N$XY_EXEC_OriginalFashionId)> 18

#IF
EQUAL N$XY_EXEC_OriginalFashionVisible 0
#ACT
ShowFashion 0

#IF
#ACT
MOV N$XY_EXEC_VisualActive 0
MOV N$XY_EXEC_OriginalFashionId 0
MOV N$XY_EXEC_OriginalFashionVisible 0
MOV N$XY_EXEC_VisualSex 0
MOV S$XY_EXEC_VisualCurrentItem 0
}}
""".replace("\n", "\r\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage the execution heavy-armor visual candidate without writing the live server/client.")
    parser.add_argument("--server", required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--library", required=True)
    parser.add_argument("--sprites", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shape-id", type=int, default=306)
    args = parser.parse_args()

    server = Path(args.server)
    client = Path(args.client)
    library = Path(args.library)
    sprites = Path(args.sprites)
    output = Path(args.output)
    if output.exists():
        shutil.rmtree(output)
    (output / "server").mkdir(parents=True)
    (output / "client").mkdir(parents=True)
    (output / "evidence").mkdir(parents=True)

    sources = {
        "db": server / "Mud2/DB/ApexM2.DB",
        "qmanage": server / "Mir200/Envir/MapQuest_Def/QManage.txt",
        "qfunction": server / "Mir200/Envir/Market_Def/QFunction-0.txt",
        "dress": client / "data/dress.txt",
    }
    for name, path in sources.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing {name}: {path}")
    if not (library / "XYExecKneel.wzl").is_file() or not (library / "XYExecKneel.wzx").is_file():
        raise FileNotFoundError("built XYExecKneel WZL/WZX pair is missing")

    staged_db = output / "server/Mud2/DB/ApexM2.DB"
    staged_db.parent.mkdir(parents=True, exist_ok=True)
    db_rows = patch_database(sources["db"], staged_db, args.shape_id)
    patch_qmanage(sources["qmanage"], output / "server/Mir200/Envir/MapQuest_Def/QManage.txt")
    patch_qfunction(sources["qfunction"], output / "server/Mir200/Envir/Market_Def/QFunction-0.txt")
    visual_path = output / "server/Mir200/Envir/QuestDiary/玄渊实验室/处决/处决重甲跪地外观.txt"
    write_gb18030(visual_path, visual_script())
    patch_dress(sources["dress"], output / "client/data/dress.txt", args.shape_id)
    shutil.copy2(library / "XYExecKneel.wzl", output / "client/data/XYExecKneel.wzl")
    shutil.copy2(library / "XYExecKneel.wzx", output / "client/data/XYExecKneel.wzx")
    shutil.copy2(library / "build_receipt.json", output / "evidence/library_build_receipt.json")
    shutil.copy2(sprites / "contact_sheet_directions.png", output / "evidence/contact_sheet_directions.png")
    shutil.copy2(sprites / "cells.json", output / "evidence/sprite_geometry.json")

    targets = {
        "server/Mud2/DB/ApexM2.DB": sources["db"],
        "server/Mir200/Envir/MapQuest_Def/QManage.txt": sources["qmanage"],
        "server/Mir200/Envir/Market_Def/QFunction-0.txt": sources["qfunction"],
        "server/Mir200/Envir/QuestDiary/玄渊实验室/处决/处决重甲跪地外观.txt": server / "Mir200/Envir/QuestDiary/玄渊实验室/处决/处决重甲跪地外观.txt",
        "client/data/dress.txt": sources["dress"],
        "client/data/XYExecKneel.wzl": client / "data/XYExecKneel.wzl",
        "client/data/XYExecKneel.wzx": client / "data/XYExecKneel.wzx",
    }
    files = []
    for relative, target in targets.items():
        staged = output / relative
        files.append({
            "relative": relative,
            "target": str(target),
            "target_exists": target.exists(),
            "before_sha256": sha256(target) if target.exists() else None,
            "after_sha256": sha256(staged),
            "after_size": staged.stat().st_size,
        })
    manifest = {
        "schema": "xy-execution-heavy-armor-stage/1",
        "status": "candidate-static-stage-passed",
        "shape_id": args.shape_id,
        "library": "XYExecKneel",
        "items": db_rows,
        "files": files,
        "notes": [
            "No live server or client file was written by this staging command.",
            "M2 and the launcher were not opened, closed, or restarted.",
            "Formal platform package remains unchanged pending in-game acceptance.",
        ],
    }
    (output / "stage_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
