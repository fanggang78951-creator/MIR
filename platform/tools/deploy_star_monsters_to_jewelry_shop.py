from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path


PLATFORM_ROOT = Path(r"D:\XuanYuanDevPlatform")
SERVER_ROOT = Path(r"D:\MirServer")
CLIENT_DATA = Path(r"D:\11周年\data")
GENERATOR_LOGIN_DIR = Path(r"D:\素材文件夹\LFM2[20260707]\登录器")
CANDIDATE_CATALOG = PLATFORM_ROOT / "outputs" / "star-monster-visual-scan-20260812" / "怪物库" / "catalog.sqlite"
MAP_CODE = "0105"
MAP_NAME = "首饰店"
BASE_MONSTER = "稻草人"
START_MARKER = "; XYDP-BEGIN star-monsters-jewelry-shop-v1"
END_MARKER = "; XYDP-END star-monsters-jewelry-shop-v1"
POSITIONS = (
    (15, 17), (11, 19), (10, 15), (16, 9), (17, 14),
    (5, 22), (23, 8), (8, 20), (14, 20), (12, 22),
    (3, 20), (13, 14), (12, 16), (15, 12), (13, 18),
    (17, 11), (9, 18), (18, 16), (19, 8),
)
MODEL_FIELDS = (
    "Race", "RaceImg", "Appr", "CoolEye", "SPEED", "WalkStep", "WalkWait",
    "AttackState", "AttackSource", "ExploreItem", "DisableSimpleActor",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="通过玄渊平台把19个星辰模型生成到0105首饰店")
    parser.add_argument("--platform-root", type=Path, default=PLATFORM_ROOT)
    parser.add_argument("--server", type=Path, default=SERVER_ROOT)
    parser.add_argument("--client-data", type=Path, default=CLIENT_DATA)
    parser.add_argument("--generator-login-dir", type=Path, default=GENERATOR_LOGIN_DIR)
    parser.add_argument("--candidate-catalog", type=Path, default=CANDIDATE_CATALOG)
    parser.add_argument("--respawn-seconds", type=int, default=600)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def add_source_path(platform_root: Path) -> None:
    source_root = platform_root / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def catalog_records(catalog: Path, library_no: int, limit: int) -> list[object]:
    from xydp.monster_library import _catalog_row

    if not catalog.is_file():
        raise RuntimeError(f"怪物库不存在：{catalog}")
    connection = sqlite3.connect(f"file:{catalog.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT * FROM monsters
            WHERE status='ready' AND library_no=?
            ORDER BY slot_no, monster_id
            """,
            (library_no,),
        ).fetchall()
    finally:
        connection.close()
    unique: dict[int, object] = {}
    for row in rows:
        unique.setdefault(int(row["slot_no"]), _catalog_row(row))
    selected = [unique[key] for key in sorted(unique)[:limit]]
    if len(selected) != limit:
        raise RuntimeError(f"Mon{library_no}只找到{len(selected)}个唯一可用槽位，需要{limit}个")
    return selected


def ensure_active_libraries(platform_root: Path, candidate_catalog: Path, apply: bool) -> tuple[list[object], list[int]]:
    active_catalog = platform_root / "怪物库" / "catalog.sqlite"
    missing: list[int] = []
    available: dict[int, list[object]] = {}
    for library_no, limit in ((116, 7), (113, 10)):
        try:
            available[library_no] = catalog_records(active_catalog, library_no, limit)
        except RuntimeError:
            missing.append(library_no)
    if apply and missing:
        importer = platform_root / "tools" / "import_star_monster_visual_pack.py"
        command = [sys.executable, str(importer), "--platform-root", str(platform_root), "--libraries"]
        command.extend(str(value) for value in missing)
        subprocess.run(command, check=True)
        available = {
            116: catalog_records(active_catalog, 116, 7),
            113: catalog_records(active_catalog, 113, 10),
        }
        missing = []
    elif missing:
        for library_no, limit in ((116, 7), (113, 10)):
            if library_no in missing:
                available[library_no] = catalog_records(candidate_catalog, library_no, limit)
    # Mon116供体只有槽0-6是完整怪物；为保留星辰怪1-19，槽0、1各重复一次补足两只。
    return available[116] + available[116][:2] + available[113], missing


def baseline_values(server_root: Path) -> dict[str, object]:
    from xydp.monster_library import _monster_rows

    database = server_root / "Mud2" / "DB" / "ApexM2.DB"
    matches = [values for _, values in _monster_rows(database) if str(values["Name"]).casefold() == BASE_MONSTER.casefold()]
    if len(matches) != 1:
        raise RuntimeError(f"目标Monster表无法唯一找到属性基准：{BASE_MONSTER}（找到{len(matches)}行）")
    return matches[0]


def build_records(source_records: list[object], baseline: dict[str, object]) -> tuple[list[object], list[dict[str, object]]]:
    from xydp.monster_library import _monster_hash

    records: list[object] = []
    assignments: list[dict[str, object]] = []
    for index, (source, position) in enumerate(zip(source_records, POSITIONS), start=1):
        name = f"星辰怪{index}"
        source_values = source.monster_values
        values = dict(baseline)
        values["Name"] = name
        for field in MODEL_FIELDS:
            values[field] = source_values[field]
        serialized, row_hash = _monster_hash(values)
        record = replace(
            source,
            monster_name=name,
            level=int(values["Lvl"]),
            exp=int(values["Exp"]),
            hp=int(values["HP"]),
            hit=int(values["HIT"]),
            monster_json=serialized,
            monster_hash=row_hash,
        )
        records.append(record)
        assignments.append(
            {
                "name": name,
                "model_id": int(source.monster_id),
                "source_label": str(source.monster_name),
                "library_no": int(source.library_no),
                "slot_no": int(source.slot_no),
                "appearance_id": int(source.appearance_id),
                "race": int(source.race),
                "race_img": int(source.race_img),
                "x": position[0],
                "y": position[1],
            }
        )
    return records, assignments


def map_geometry(data: bytes) -> tuple[int, int, int]:
    if len(data) < 52:
        raise RuntimeError("0105.map小于52字节")
    width, height = struct.unpack_from("<HH", data, 0)
    for cell_size in (12, 14, 36):
        if len(data) == 52 + width * height * cell_size:
            return width, height, cell_size
    raise RuntimeError("0105.map不是平台支持的地图格式")


def walkable(data: bytes, width: int, height: int, cell_size: int, x: int, y: int) -> bool:
    if not (1 <= x < width - 1 and 1 <= y < height - 1):
        return False
    offset = 52 + (x * height + y) * cell_size
    front = struct.unpack_from("<H", data, offset + 4)[0]
    door = data[offset + 6] & 0x7F
    return not (front & 0x8000) and door == 0


def validate_map(server_root: Path) -> dict[str, object]:
    map_info = (server_root / "Mir200" / "Envir" / "MapInfo.txt").read_bytes().decode("gb18030")
    match = re.search(r"(?im)^\s*\[\s*0105(?:\|[^\s\]]+)?\s+([^\]]+)\]", map_info)
    if not match or MAP_NAME not in match.group(1):
        raise RuntimeError("MapInfo.txt未把0105登记为首饰店")
    map_path = server_root / "Mir200" / "Map" / "0105.map"
    data = map_path.read_bytes()
    width, height, cell_size = map_geometry(data)
    invalid = [point for point in POSITIONS if not walkable(data, width, height, cell_size, *point)]
    if invalid:
        raise RuntimeError(f"0105预定刷新坐标不可走：{invalid}")
    minimum_distance = min(
        abs(x1 - x2) + abs(y1 - y2)
        for index, (x1, y1) in enumerate(POSITIONS)
        for x2, y2 in POSITIONS[index + 1 :]
    )
    if minimum_distance < 3:
        raise RuntimeError(f"刷新点间距过小：{minimum_distance}")
    return {"map": MAP_CODE, "name": MAP_NAME, "width": width, "height": height, "cell_size": cell_size, "minimum_distance": minimum_distance}


def decode_document(data: bytes) -> tuple[str, str, bytes, str]:
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    body = data[len(bom) :]
    for encoding in ("utf-8", "gb18030"):
        try:
            text = body.decode(encoding)
            newline = "\r\n" if "\r\n" in text else "\n"
            return text, encoding, bom, newline
        except UnicodeDecodeError:
            continue
    raise RuntimeError("MonGen.txt编码无法识别")


def make_mongen_after(path: Path, respawn_seconds: int) -> tuple[bytes, int]:
    if respawn_seconds <= 0:
        raise RuntimeError("死亡重刷秒数必须大于0")
    before = path.read_bytes()
    text, encoding, bom, newline = decode_document(before)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    had_final_newline = bool(lines and lines[-1] == "")
    if had_final_newline:
        lines.pop()
    start_indexes = [i for i, line in enumerate(lines) if line.strip() == START_MARKER]
    end_indexes = [i for i, line in enumerate(lines) if line.strip() == END_MARKER]
    if len(start_indexes) != len(end_indexes) or len(start_indexes) > 1:
        raise RuntimeError("MonGen星辰怪受管标记不完整或重复")
    if start_indexes:
        start, end = start_indexes[0], end_indexes[0]
        if end < start:
            raise RuntimeError("MonGen星辰怪受管标记顺序错误")
        del lines[start : end + 1]
        while lines and not lines[0].strip():
            lines.pop(0)
    for line_number, line in enumerate(lines, start=1):
        parts = re.split(r"\s+", line.strip()) if line.strip() and not line.lstrip().startswith(";") else []
        if len(parts) >= 4 and parts[0].casefold() == MAP_CODE.casefold() and re.fullmatch(r"星辰怪(?:[1-9]|1\d)", parts[3]):
            raise RuntimeError(f"MonGen第{line_number}行已有非受管星辰怪刷新，停止避免重复")
    block = [START_MARKER]
    for index, (x, y) in enumerate(POSITIONS, start=1):
        block.append(f"{MAP_CODE}\t{x}\t{y}\t星辰怪{index}\t1\t1\t{respawn_seconds}\t0\t151")
    block.append(END_MARKER)
    merged_lines = block + ([""] if lines else []) + lines
    merged = newline.join(merged_lines)
    if had_final_newline:
        merged += newline
    after = bom + merged.encode(encoding)
    return after, len(block) - 2


def add_mongen_change(plan: object, server_root: Path, respawn_seconds: int) -> None:
    from xydp.monster_library import MonsterLibraryChange, _sha256_file

    mon_gen = server_root / "Mir200" / "Envir" / "MonGen.txt"
    after, count = make_mongen_after(mon_gen, respawn_seconds)
    plan.mon_gen_after = after
    plan.changes.append(
        MonsterLibraryChange(
            scope="server",
            target_path=str(mon_gen),
            source_path=None,
            before_hash=_sha256_file(mon_gen),
            after_hash=sha256_bytes(after),
            kind="monster-name-colors",
        )
    )
    plan.name_color_assignments = tuple(
        {"monster_name": f"星辰怪{index}", "matched_rows": 1, "color": 151}
        for index in range(1, count + 1)
    )


def verify_after(server_root: Path, client_data: Path, assignments: list[dict[str, object]], respawn_seconds: int) -> dict[str, object]:
    from xydp.monster_library import _monster_rows

    expected = {item["name"]: item for item in assignments}
    rows = {str(values["Name"]): values for _, values in _monster_rows(server_root / "Mud2" / "DB" / "ApexM2.DB") if str(values["Name"]) in expected}
    if set(rows) != set(expected):
        raise RuntimeError(f"写后Monster名称回读不完整：{sorted(set(expected) - set(rows))}")
    for name, assignment in expected.items():
        values = rows[name]
        actual = (int(values["Race"]), int(values["RaceImg"]), int(values["Appr"]))
        wanted = (int(assignment["race"]), int(assignment["race_img"]), int(assignment["appearance_id"]))
        if actual != wanted:
            raise RuntimeError(f"{name}模型字段回读不一致：{actual} != {wanted}")
    mon_gen = (server_root / "Mir200" / "Envir" / "MonGen.txt").read_bytes().decode("gb18030")
    managed = [line for line in mon_gen.splitlines() if re.match(r"^0105\s+\d+\s+\d+\s+星辰怪(?:[1-9]|1\d)\s+1\s+1\s+", line)]
    if len(managed) != 19 or any(f"\t{respawn_seconds}\t0\t151" not in line for line in managed):
        raise RuntimeError(f"MonGen写后回读异常：{len(managed)}行")
    for library_no in (113, 116):
        if not (client_data / f"Mon{library_no}.pak").is_file():
            raise RuntimeError(f"客户端缺少Mon{library_no}.pak")
    connection = sqlite3.connect(server_root / "Mud2" / "DB" / "ApexM2.DB")
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if not integrity or integrity[0] != "ok":
        raise RuntimeError(f"目标数据库完整性失败：{integrity}")
    return {"monster_rows": 19, "mongen_rows": 19, "client_paks": ["Mon113.pak", "Mon116.pak"], "sqlite_integrity": "ok"}


def main() -> int:
    args = parse_args()
    if args.apply and not args.yes:
        raise RuntimeError("正式写入必须同时提供 --apply --yes")
    platform_root = args.platform_root.resolve()
    server_root = args.server.resolve()
    client_data = args.client_data.resolve()
    generator_login_dir = args.generator_login_dir.resolve()
    add_source_path(platform_root)
    from xydp.monster_library import MonsterLibraryService

    map_summary = validate_map(server_root)
    source_records, missing_before_apply = ensure_active_libraries(
        platform_root, args.candidate_catalog.resolve(), args.apply
    )
    baseline = baseline_values(server_root)
    records, assignments = build_records(source_records, baseline)
    service = MonsterLibraryService(platform_root)
    plan = service.preflight_records(
        records,
        server_root,
        client_data,
        resource_required_names=(record.monster_name for record in records),
        conflicts_are_blockers=True,
        generator_login_dir=generator_login_dir,
    )
    plan.operation = "star-monsters-jewelry-shop-v1"
    plan.model_assignments = tuple(assignments)
    add_mongen_change(plan, server_root, args.respawn_seconds)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "status": "blocked" if plan.blockers else ("ready-to-apply" if not args.apply else "applying"),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "server": str(server_root),
        "client_data": str(client_data),
        "generator_login_dir": str(generator_login_dir),
        "map": map_summary,
        "baseline_monster": BASE_MONSTER,
        "baseline_combat": {key: baseline[key] for key in ("Lvl", "Exp", "HP", "AC", "MAC", "DC", "DCMAX", "HIT")},
        "respawn_seconds": args.respawn_seconds,
        "first_spawn_policy": "MonGen受管块前置；历史实测M2重载后约20秒首刷，仍需本轮游戏验收",
        "catalog_libraries": [116, 113],
        "libraries_pending_platform_append": missing_before_apply,
        "assignments": assignments,
        "plan": service.plan_summary(plan),
    }
    report_dir = platform_root / "build" / "star-monsters-jewelry-shop"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{stamp}_{'apply' if args.apply else 'preflight'}.json"
    if plan.blockers:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(report_path), **report}, ensure_ascii=False, indent=2))
        return 2
    if args.apply:
        receipt = service.install(plan)
        verification = verify_after(server_root, client_data, assignments, args.respawn_seconds)
        report.update(
            {
                "status": "completed-awaiting-login-generator-and-game-validation",
                "receipt": receipt.receipt_path,
                "transaction_id": receipt.transaction_id,
                "verification": verification,
            }
        )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
