from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path


DEFAULT_LIBRARIES = (111, 113)
NEUTRAL_FIELDS = {
    "Lvl": 1,
    "Exp": 0,
    "HP": 1,
    "MP": 0,
    "AC": 0,
    "MAC": 0,
    "DC": 0,
    "DCMAX": 0,
    "MC": 0,
    "SC": 0,
    "HIT": 0,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def monster_hash(values: dict[str, object]) -> tuple[str, str]:
    text = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def catalog_rows(connection: sqlite3.Connection, libraries: tuple[int, ...]) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in libraries)
    rows = connection.execute(
        f"""
        SELECT * FROM monsters
        WHERE status='ready' AND library_no IN ({placeholders})
        ORDER BY library_no, slot_no, monster_id
        """,
        libraries,
    ).fetchall()
    unique: dict[tuple[int, int], sqlite3.Row] = {}
    for row in rows:
        unique.setdefault((int(row["library_no"]), int(row["slot_no"])), row)
    return list(unique.values())


def copy_verified(source: Path, target: Path, expected_hash: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        if sha256_file(target) != expected_hash:
            raise RuntimeError(f"目标资源同名但哈希不同：{target}")
        return
    temporary = target.with_name(target.name + ".xydp.tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(source, temporary)
    if sha256_file(temporary) != expected_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"资源复制后哈希不一致：{source}")
    os.replace(temporary, target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把星辰供体的纯怪物模型安全追加到玄渊平台怪物库")
    parser.add_argument("--platform-root", type=Path, default=Path(r"D:\XuanYuanDevPlatform"))
    parser.add_argument(
        "--donor-catalog",
        type=Path,
        default=Path(r"D:\XuanYuanDevPlatform\outputs\star-monster-visual-scan-20260812\怪物库\catalog.sqlite"),
    )
    parser.add_argument(
        "--libraries",
        type=int,
        nargs="+",
        default=list(DEFAULT_LIBRARIES),
        help="要从候选库追加的Mon编号，例如 --libraries 116",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_libraries = tuple(dict.fromkeys(int(value) for value in args.libraries))
    if not selected_libraries or any(value <= 0 for value in selected_libraries):
        raise RuntimeError("--libraries 必须提供正整数Mon编号")
    platform_root = args.platform_root.resolve()
    active_catalog = platform_root / "怪物库" / "catalog.sqlite"
    donor_catalog = args.donor_catalog.resolve()
    if not active_catalog.is_file() or not donor_catalog.is_file():
        raise RuntimeError("活动怪物库或星辰候选怪物库不存在")

    donor = sqlite3.connect(donor_catalog)
    try:
        donor.row_factory = sqlite3.Row
        rows = catalog_rows(donor, selected_libraries)
    finally:
        donor.close()
    by_library: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_library.setdefault(int(row["library_no"]), []).append(row)
    missing = [number for number in selected_libraries if number not in by_library]
    if missing:
        raise RuntimeError(f"星辰候选库缺少可用图库：{missing}")

    active = sqlite3.connect(active_catalog)
    try:
        placeholders = ",".join("?" for _ in selected_libraries)
        conflicts = active.execute(
            f"SELECT DISTINCT library_no FROM monsters WHERE library_no IN ({placeholders}) AND status='ready'",
            selected_libraries,
        ).fetchall()
        max_id = int(active.execute("SELECT COALESCE(MAX(monster_id),0) FROM monsters").fetchone()[0])
    finally:
        active.close()
    if conflicts:
        raise RuntimeError(f"活动怪物库已占用目标Mon号：{[int(item[0]) for item in conflicts]}")

    resources: list[dict[str, object]] = []
    for library_no in selected_libraries:
        row = by_library[library_no][0]
        source = Path(str(row["source_path"]))
        expected_hash = str(row["source_hash"])
        if not source.is_file() or sha256_file(source) != expected_hash:
            raise RuntimeError(f"星辰来源资源缺失或哈希变化：{source}")
        target = platform_root / "怪物库" / "assets" / "pak" / expected_hash[:16] / source.name
        resources.append(
            {
                "library_no": library_no,
                "source": str(source),
                "target": str(target),
                "sha256": expected_hash,
                "bytes": source.stat().st_size,
                "models": len(by_library[library_no]),
            }
        )

    plan = {
        "status": "dry-run" if args.dry_run else "pending",
        "selected_libraries": list(selected_libraries),
        "models": sum(len(items) for items in by_library.values()),
        "active_catalog": str(active_catalog),
        "donor_catalog": str(donor_catalog),
        "next_model_id": max_id + 1,
        "resources": resources,
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = platform_root / "backups" / f"monster-visual-star-{stamp}"
    backup_root.mkdir(parents=True, exist_ok=False)
    backup_catalog = backup_root / "catalog.sqlite"
    shutil.copy2(active_catalog, backup_catalog)

    for resource in resources:
        copy_verified(Path(str(resource["source"])), Path(str(resource["target"])), str(resource["sha256"]))

    temporary = active_catalog.with_name("catalog.sqlite.star-append.tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(active_catalog, temporary)
    inserted: list[dict[str, object]] = []
    try:
        active = sqlite3.connect(temporary)
        donor = sqlite3.connect(donor_catalog)
        try:
            active.row_factory = sqlite3.Row
            donor.row_factory = sqlite3.Row
            fields = [str(item[1]) for item in active.execute("PRAGMA table_info(monsters)").fetchall()]
            placeholders = ",".join("?" for _ in fields)
            max_id = int(active.execute("SELECT COALESCE(MAX(monster_id),0) FROM monsters").fetchone()[0])
            for source_row in rows:
                library_no = int(source_row["library_no"])
                slot_no = int(source_row["slot_no"])
                resource = next(item for item in resources if item["library_no"] == library_no)
                max_id += 1
                alias = f"星辰模型_Mon{library_no}_{slot_no:02d}_{source_row['monster_name']}"
                values = json.loads(str(source_row["monster_json"]))
                values.update(NEUTRAL_FIELDS)
                values["Name"] = alias
                values["Appr"] = int(source_row["appearance_id"])
                values["Race"] = int(source_row["race"])
                values["RaceImg"] = int(source_row["race_img"])
                serialized, row_hash = monster_hash(values)
                record = dict(source_row)
                record.update(
                    {
                        "monster_id": max_id,
                        "source_rowid": max_id,
                        "monster_name": alias,
                        "level": 1,
                        "exp": 0,
                        "hp": 1,
                        "hit": 0,
                        "monster_json": serialized,
                        "monster_hash": row_hash,
                        "source_path": str(resource["target"]),
                        "source_size": int(resource["bytes"]),
                        "preview_path": None,
                        "preview_state": "missing",
                        "status": "ready",
                        "skip_reason": None,
                    }
                )
                active.execute(
                    f"INSERT INTO monsters ({','.join(fields)}) VALUES ({placeholders})",
                    [record.get(field) for field in fields],
                )
                inserted.append(
                    {
                        "model_id": max_id,
                        "label": alias,
                        "appearance_id": int(source_row["appearance_id"]),
                        "library_no": library_no,
                        "slot_no": slot_no,
                        "source_label": str(source_row["monster_name"]),
                    }
                )
            active.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
                ("last_visual_append_at", dt.datetime.now().isoformat(timespec="seconds")),
            )
            current_meta = active.execute(
                "SELECT value FROM meta WHERE key=?", ("additional_visual_sources",)
            ).fetchone()
            try:
                visual_sources = json.loads(str(current_meta[0])) if current_meta else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                visual_sources = {}
            if not isinstance(visual_sources, dict):
                visual_sources = {}
            star_source = visual_sources.get("星辰剑歌", {})
            if not isinstance(star_source, dict):
                star_source = {}
            prior_libraries = {
                int(value) for value in star_source.get("libraries", [])
                if str(value).strip().isdigit()
            }
            star_source.update(
                {
                    "server": r"D:\MirServer10",
                    "client": r"D:\星辰剑歌",
                    "libraries": sorted(prior_libraries | set(selected_libraries)),
                    "model_only": True,
                }
            )
            visual_sources["星辰剑歌"] = star_source
            active.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
                (
                    "additional_visual_sources",
                    json.dumps(visual_sources, ensure_ascii=False, sort_keys=True),
                ),
            )
            integrity = active.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError(f"追加后的怪物库完整性失败：{integrity}")
            active.commit()
        finally:
            donor.close()
            active.close()
        os.replace(temporary, active_catalog)
    finally:
        temporary.unlink(missing_ok=True)

    receipt = {
        **plan,
        "status": "completed-awaiting-game-validation",
        "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "backup_catalog": str(backup_catalog),
        "catalog_sha256": sha256_file(active_catalog),
        "inserted": inserted,
        "attribute_policy": "仅保留Appr、Race、RaceImg及动作控制元数据；战斗数值已中和",
    }
    library_label = "_".join(str(value) for value in selected_libraries)
    receipt_path = platform_root / "怪物库" / "build" / f"{stamp}_星辰Mon{library_label}纯模型追加.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"receipt": str(receipt_path), **receipt}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
