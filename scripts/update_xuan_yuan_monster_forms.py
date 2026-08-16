from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


DB = Path(r"D:\MirServer\Mud2\DB\ApexM2.DB")
SERVER = Path(r"D:\MirServer")
FORMS = {
    "玄渊恶灵": "稻草人",
    "玄渊恶灵boss": "白野猪",
    "玄渊终焉使": "沃玛教主",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = SERVER / "Backup" / f"XuanYuanMonsterForms_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    db_backup = backup / "ApexM2.DB"
    shutil.copy2(DB, db_backup)
    before_hash = sha256(DB)

    con = sqlite3.connect(DB)
    try:
        columns = [row[1] for row in con.execute("PRAGMA table_info(Monster)")]
        copy_columns = [column for column in columns if column != "Name"]
        before = {}
        for target, source in FORMS.items():
            target_row = con.execute("SELECT * FROM Monster WHERE Name=?", (target,)).fetchone()
            source_row = con.execute("SELECT * FROM Monster WHERE Name=?", (source,)).fetchone()
            if target_row is None or source_row is None:
                raise LookupError(f"缺少目标或形态模板：{target} <- {source}")
            before[target] = {
                "source": source,
                "values": dict(zip(columns, target_row)),
            }

        con.execute("BEGIN IMMEDIATE")
        for target, source in FORMS.items():
            source_row = con.execute("SELECT * FROM Monster WHERE Name=?", (source,)).fetchone()
            values = [source_row[columns.index(column)] for column in copy_columns]
            assignments = ", ".join(f'"{column}"=?' for column in copy_columns)
            con.execute(f'UPDATE Monster SET {assignments} WHERE "Name"=?', values + [target])
        con.commit()

        after = {}
        for target, source in FORMS.items():
            row = con.execute("SELECT * FROM Monster WHERE Name=?", (target,)).fetchone()
            source_row = con.execute("SELECT * FROM Monster WHERE Name=?", (source,)).fetchone()
            after[target] = {
                "source": source,
                "values": dict(zip(columns, row)),
                "matches_source_except_name": row[1:] == source_row[1:],
            }

        manifest = {
            "task": "修正玄渊波次怪物形态",
            "timestamp": stamp,
            "status": "待验证",
            "db": str(DB),
            "db_backup": str(db_backup),
            "db_sha256_before": before_hash,
            "db_sha256_backup": sha256(db_backup),
            "db_sha256_after": sha256(DB),
            "changed_fields": copy_columns,
            "before": before,
            "after": after,
            "names_unchanged": True,
            "drop_files_modified": False,
            "flow_modified": False,
            "client_resources_modified": False,
            "db_integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
        }
        (backup / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "status": manifest["status"],
            "backup": str(backup),
            "changed": after,
            "db_integrity": manifest["db_integrity"],
            "backup_hash_match": manifest["db_sha256_before"] == manifest["db_sha256_backup"],
        }, ensure_ascii=False))
    finally:
        con.close()


if __name__ == "__main__":
    main()
