from __future__ import annotations

import hashlib
import json
import math
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


SERVER = Path(r"D:\MirServer")
DB = SERVER / "Mud2" / "DB" / "ApexM2.DB"
MON_ITEMS = SERVER / "Mir200" / "Envir" / "MonItems"

# 经典三职业祖玛与赤月三圣；龙文剑在当前 StdItems 中不存在，不能写入掉落表。
ONLINE_GROUPS = [
    ("祖玛", 5, [
        "黑铁头盔", "绿色项链", "骑士手镯", "力量戒指", "裁决之杖",
        "恶魔铃铛", "龙之手镯", "紫碧螺", "骨玉权杖",
        "灵魂项链", "三眼手镯", "泰坦戒指",
    ]),
    ("赤月三圣", 10, [
        "圣战头盔", "圣战宝甲", "圣战项链", "圣战手镯", "圣战戒指",
        "法神头盔", "法神披风", "法神项链", "法神手镯", "法神戒指",
        "天尊头盔", "天尊道袍", "天尊项链", "天尊手镯", "天尊戒指",
    ]),
]
EXCLUDED_ONLINE_ITEMS = {
    "龙文剑": "网上祖玛道士武器，但当前 StdItems 不存在；按要求只生成可直接掉落的现有装备，不擅自新增装备。",
}

LOCAL_GROUPS = [
    ("雷狱战士", 15, ["雷狱战刃", "雷狱战甲", "雷狱战盔", "雷狱项链", "雷狱战镯", "雷狱战戒", "雷狱腰带", "雷狱战靴"]),
    ("焚星法师", 20, ["焚星法杖", "焚星魔衣", "焚星法冠", "焚星项链", "焚星护腕", "焚星魔戒", "焚星腰带", "焚星魔靴"]),
    ("玄光道士", 25, ["玄光道剑", "玄光道袍", "玄光道冠", "玄光项链", "玄光护腕", "玄光道戒", "玄光腰带", "玄光道靴"]),
    ("天戮战士", 30, ["天戮神刃", "天戮神甲", "天戮神盔", "天戮项链", "天戮战镯", "天戮战戒", "天戮腰带", "天戮战靴"]),
    ("圣烬法师", 35, ["圣烬魔杖", "圣烬法衣", "圣烬法冠", "圣烬项链", "圣烬护腕", "圣烬魔戒", "圣烬腰带", "圣烬魔靴"]),
    ("太虚道士", 40, ["太虚玄剑", "太虚道袍", "太虚道冠", "太虚项链", "太虚护腕", "太虚道戒", "太虚腰带", "太虚道靴"]),
]

WAVES = [
    (1, "玄渊恶灵", "玄渊恶灵boss", "祖玛雕像", "祖玛教主"),
    (2, "玄渊恶鬼", "玄渊恶鬼boss", "黑锷蜘蛛", "双头金刚"),
    (3, "玄渊魔将", "玄渊魔将boss", "牛魔斗士", "黄泉教主"),
    (4, "玄渊魔王", "玄渊魔王boss", "祖玛卫士", "暗之牛魔王"),
    (5, "玄渊终焉使", "玄渊终焉使boss", "触龙神", "赤月恶魔"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def drop_denominator(base: int, wave: int) -> int:
    # 1/base 每波翻倍；传统 MonItems 只写整数分母，向上取整并封顶 1/1。
    return max(1, math.ceil(base / (2 ** (wave - 1))))


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = SERVER / "Backup" / f"XuanYuanWaveMonsters_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    if not DB.exists() or not MON_ITEMS.exists():
        raise FileNotFoundError("当前服务端 DB 或 MonItems 目录不存在")

    all_groups = ONLINE_GROUPS + LOCAL_GROUPS
    all_items = [item for _, _, items in all_groups for item in items]
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        std_names = {row[0] for row in con.execute("SELECT Name FROM StdItems")}
        missing_items = sorted(set(all_items) - std_names)
        if missing_items != []:
            # 缺失物品不写入表，避免引擎读表时报不存在；本轮唯一缺失项留在收据中。
            all_groups = [
                (label, base, [item for item in items if item in std_names])
                for label, base, items in all_groups
            ]

        target_names = [name for _, normal, boss, _, _ in WAVES for name in (normal, boss)]
        existing_monsters = [row[0] for row in con.execute(
            "SELECT Name FROM Monster WHERE Name IN (%s)" % ",".join("?" * len(target_names)),
            target_names,
        )]
        existing_drop_files = [name for name in target_names if (MON_ITEMS / f"{name}.txt").exists()]
        if existing_monsters or existing_drop_files:
            raise FileExistsError(json.dumps({"existing_monsters": existing_monsters, "existing_drop_files": existing_drop_files}, ensure_ascii=False))

        source_names = [source for _, _, _, source, boss_source in WAVES for source in (source, boss_source)]
        placeholders = ",".join("?" * len(source_names))
        source_rows = {
            row["Name"]: row
            for row in con.execute(f"SELECT * FROM Monster WHERE Name IN ({placeholders})", source_names)
        }
        missing_sources = sorted(set(source_names) - set(source_rows))
        if missing_sources:
            raise LookupError(f"怪物外观模板不存在: {missing_sources}")

        db_backup = backup / "ApexM2.DB"
        shutil.copy2(DB, db_backup)
        before_hash = sha256(DB)

        monster_columns = [row[1] for row in con.execute("PRAGMA table_info(Monster)")]
        inserted = []
        try:
            con.execute("BEGIN IMMEDIATE")
            for _, normal, boss, normal_source, boss_source in WAVES:
                for target, source in ((normal, normal_source), (boss, boss_source)):
                    values = [target if col == "Name" else source_rows[source][col] for col in monster_columns]
                    cols = ",".join(f'"{col}"' for col in monster_columns)
                    marks = ",".join("?" * len(values))
                    con.execute(f"INSERT INTO Monster ({cols}) VALUES ({marks})", values)
                    inserted.append(target)
            con.commit()

            files = {}
            for wave, normal, boss, _, _ in WAVES:
                denominator_by_item = {}
                for _, base, items in all_groups:
                    for item in items:
                        denominator_by_item[item] = drop_denominator(base, wave)
                content = "".join(f"1/{denominator_by_item[item]}\t{item}\r\n" for item in denominator_by_item)
                encoded = content.encode("gbk")
                for target in (normal, boss):
                    path = MON_ITEMS / f"{target}.txt"
                    path.write_bytes(encoded)
                    files[target] = {"path": str(path), "sha256": sha256(path), "lines": len(denominator_by_item)}
        except Exception:
            con.execute("BEGIN")
            con.executemany("DELETE FROM Monster WHERE Name=?", [(name,) for name in inserted])
            con.commit()
            for _, normal, boss, _, _ in WAVES:
                for target in (normal, boss):
                    path = MON_ITEMS / f"{target}.txt"
                    if path.exists():
                        path.unlink()
            raise

        manifest = {
            "task": "新增玄渊五波怪物与只装备爆率表",
            "timestamp": stamp,
            "status": "待验证",
            "db": str(DB),
            "db_backup": str(db_backup),
            "db_sha256_before": before_hash,
            "db_sha256_backup": sha256(db_backup),
            "db_sha256_after": sha256(DB),
            "mon_gen_modified": False,
            "client_modified": False,
            "missing_online_items": missing_items,
            "excluded_online_items": EXCLUDED_ONLINE_ITEMS,
            "drop_policy": "传统 MonItems 1/整数格式；每波概率相对上一波翻倍，分母向上取整，封顶 1/1；普通/Boss同波同概率",
            "groups": [{"name": label, "base_denominator": base, "items": items} for label, base, items in all_groups],
            "waves": [
                {
                    "wave": wave,
                    "normal": normal,
                    "boss": boss,
                    "normal_template": normal_source,
                    "boss_template": boss_source,
                    "denominators": {str(base): drop_denominator(base, wave) for _, base, _ in all_groups},
                }
                for wave, normal, boss, normal_source, boss_source in WAVES
            ],
            "drop_files": files,
        }
        (backup / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "status": manifest["status"],
            "backup": str(backup),
            "inserted_monsters": inserted,
            "drop_lines_per_file": len(all_items) - len(missing_items),
            "missing_online_items": missing_items,
            "db_integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
        }, ensure_ascii=False))
    finally:
        con.close()


if __name__ == "__main__":
    main()
