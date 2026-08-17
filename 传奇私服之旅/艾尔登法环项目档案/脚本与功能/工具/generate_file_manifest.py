#!/usr/bin/env python3
"""为权威档案生成稳定的文件和SHA-256清单。"""

import csv
import hashlib
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Documents\做传奇\传奇私服之旅\艾尔登法环项目档案")
CSV_PATH = ROOT / "脚本与功能" / "报告" / "文件清单.csv"
SHA_PATH = ROOT / "脚本与功能" / "报告" / "SHA256SUMS.txt"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    excluded = {CSV_PATH.resolve(), SHA_PATH.resolve()}
    files = sorted((p for p in ROOT.rglob("*") if p.is_file() and p.resolve() not in excluded), key=lambda p: str(p.relative_to(ROOT)).lower())
    rows = []
    for p in files:
        rows.append({"相对路径": p.relative_to(ROOT).as_posix(), "大小": p.stat().st_size, "SHA256": digest(p)})
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["相对路径", "大小", "SHA256"])
        w.writeheader()
        w.writerows(rows)
    SHA_PATH.write_text("\n".join(f"{r['SHA256']}  {r['相对路径']}" for r in rows) + "\n", encoding="utf-8", newline="\n")
    print(f"files={len(rows)}")


if __name__ == "__main__":
    main()
