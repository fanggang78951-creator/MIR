from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DB = Path(r"D:\MirServer\Mud2\DB\ApexM2.DB")
DRESS = Path(r"D:\11周年\data\dress.txt")


def decode_dress(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise UnicodeDecodeError("dress", raw, 0, len(raw), "unsupported encoding")


def parse_dress(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith(","):
        stripped = "{" + stripped[1:] + "}"
    return json.loads(stripped)


def main() -> None:
    text, encoding = decode_dress(DRESS)
    mapping = parse_dress(text)

    with sqlite3.connect(DB) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(StdItems)")]
        selected = [name for name in ("Idx", "Name", "StdMode", "Shape", "Looks") if name in columns]
        sql = f"SELECT {', '.join(selected)} FROM StdItems WHERE StdMode IN (10,11) ORDER BY Idx"
        rows = [dict(zip(selected, row)) for row in connection.execute(sql)]
        high_sql = f"SELECT {', '.join(selected)} FROM StdItems WHERE Shape BETWEEN 300 AND 306 ORDER BY Shape, Idx"
        high_shape_rows = [dict(zip(selected, row)) for row in connection.execute(high_sql)]

    used_shapes = sorted({int(row["Shape"]) for row in rows if row.get("Shape") is not None})
    shape_mappings = {str(shape): mapping.get(str(shape)) for shape in used_shapes}
    print(json.dumps({
        "dress_encoding": encoding,
        "dress_count": len(mapping),
        "shape306": mapping.get("306"),
        "shapes300_306": {str(shape): mapping.get(str(shape)) for shape in range(300, 307)},
        "probe_shape_mappings": {
            str(shape): mapping.get(str(shape))
            for shape in list(range(9, 21)) + [32, 64, 96, 128, 160, 192, 224, 240, 248, 255]
        },
        "database_rows_shape300_306": high_shape_rows,
        "armor_rows": rows,
        "used_shape_mappings": shape_mappings,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
