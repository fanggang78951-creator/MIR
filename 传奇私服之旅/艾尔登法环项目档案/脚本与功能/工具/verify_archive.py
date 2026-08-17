#!/usr/bin/env python3
"""验证法环脚本/功能权威档案，不访问或修改正式服。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Documents\做传奇\传奇私服之旅\艾尔登法环项目档案")
REPORTS = ROOT / "脚本与功能" / "报告"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rows(name: str) -> list[dict]:
    with (REPORTS / name).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def validate() -> dict:
    checks = []
    required = [
        "README.md", "00_项目总纲.md", "01_当前任务指针.txt", "02_已确认规则与数值.xlsx",
        "03_变更记录.md", "04_每日设计更新.md", "05_当前有效游戏设计总档.md", "06_脚本功能总台账.xlsx",
    ]
    for name in required:
        p = ROOT / name
        checks.append({"检查": f"核心档案:{name}", "通过": p.is_file() and p.stat().st_size > 0, "详情": str(p)})

    functions = rows("功能总台账.csv")
    issues = rows("脚本引用问题清单.csv")
    scripts = rows("脚本文件清单.csv")
    drift = [r for r in functions if r["版本漂移"] == "是"]
    out_of_scope = [r["功能ID"] for r in functions if r["功能ID"].startswith(("xy.maps.", "xy.ui.world-map", "xy.npc.world-map", "xy.growth-stage."))]
    checks += [
        {"检查": "功能台账数量", "通过": len(functions) == 36, "详情": len(functions)},
        {"检查": "正式服收据范围数量", "通过": sum(bool(r["正式服版本"]) for r in functions) == 31, "详情": sum(bool(r["正式服版本"]) for r in functions)},
        {"检查": "明确版本漂移数量", "通过": len(drift) == 6, "详情": [r["功能ID"] for r in drift]},
        {"检查": "脚本静态问题为零", "通过": len(issues) == 0, "详情": len(issues)},
        {"检查": "正式服脚本数量", "通过": len(scripts) == 65, "详情": len(scripts)},
        {"检查": "无地图/装备内容包混入", "通过": len(out_of_scope) == 0, "详情": out_of_scope},
        {"检查": "地图核心表未生成", "通过": not (ROOT / "08_地图外显与多层传送.xlsx").exists(), "详情": "用户最终排除"},
    ]
    raw = ROOT / "脚本与功能" / "快照" / "正式服原始脚本"
    utf = ROOT / "脚本与功能" / "快照" / "正式服脚本UTF8"
    checks.append({"检查": "原始/UTF8脚本副本数量", "通过": len(list(raw.rglob("*.*"))) == 65 and len(list(utf.rglob("*.*"))) == 65, "详情": [len(list(raw.rglob("*.*"))), len(list(utf.rglob("*.*")))]})

    formula_files = [
        REPORTS / "表格检查" / "02_已确认规则与数值.xlsx.inspect.ndjson",
        REPORTS / "表格检查" / "06_脚本功能总台账.xlsx.inspect.ndjson",
        REPORTS / "表格检查" / "workbook_verification.json",
    ]
    formula_tokens = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!")
    found = []
    for p in formula_files:
        text = p.read_text(encoding="utf-8", errors="replace")
        found.extend(t for t in formula_tokens if t in text)
    checks.append({"检查": "XLSX公式错误", "通过": not found, "详情": sorted(set(found))})
    return {"passed": all(x["通过"] for x in checks), "checks": checks}


def check_manifest() -> dict:
    manifest = rows("文件清单.csv")
    bad = []
    for r in manifest:
        p = ROOT / Path(r["相对路径"])
        if not p.exists() or str(p.stat().st_size) != str(r["大小"]) or sha(p) != r["SHA256"]:
            bad.append(r["相对路径"])
    return {"passed": not bad, "entries": len(manifest), "bad": bad}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check-manifest", action="store_true")
    args = ap.parse_args()
    result = validate()
    if args.check_manifest:
        result["manifest"] = check_manifest()
        result["passed"] = result["passed"] and result["manifest"]["passed"]
    if args.write:
        (REPORTS / "最终验证.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
