#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch wrapper for xy_equip_maker.

CSV rows are converted to the same equipment TXT format used by the single-item
maker, then checked or generated through xy_equip_maker's existing pipeline.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
import traceback
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from . import xy_equip_maker


TOOL_DIR = Path(__file__).resolve().parent
EQUIPMENT_ROOT = TOOL_DIR.parents[2]
SOURCE_TABLE_DIR = EQUIPMENT_ROOT / "templates"
PLATFORM_ROOT = EQUIPMENT_ROOT.parent
CENTRAL_SOURCE_XLSX = PLATFORM_ROOT / "所需材料表格汇总" / "09_装备批量生成.xlsx"
DEFAULT_SOURCE_XLSX = CENTRAL_SOURCE_XLSX if CENTRAL_SOURCE_XLSX.exists() else SOURCE_TABLE_DIR / "XuanYuanItems.xlsx"
DEFAULT_SOURCE_CSV = SOURCE_TABLE_DIR / "XuanYuanItems.csv"
DEFAULT_SOURCE_TABLE = DEFAULT_SOURCE_XLSX if DEFAULT_SOURCE_XLSX.exists() else DEFAULT_SOURCE_CSV
OUTPUT_DIR = EQUIPMENT_ROOT / "outputs"
TEXT_ENCODING = "utf-8-sig"


class BatchMakerError(RuntimeError):
    pass


FIXED_EQUIPMENT_DURABILITY = 60000


@dataclass
class BatchResult:
    row_number: int
    name: str
    status: str
    message: str
    txt_path: str


BASE_DIRECT_KEYS = {
    "名称",
    "部位",
    "StdMode",
    "Shape",
    "Weight",
    "重量",
    "Looks",
    "持久",
    "DuraMax",
    "等级",
    "NeedLevel",
    "Need",
    "Color",
    "颜色",
    "价格",
    "Price",
    "库存",
    "Stock",
    "攻击",
    "魔法",
    "道术",
    "防御",
    "魔御",
    "HP",
    "MP",
    "幸运",
    "准确",
    "攻击速度",
    "强度",
}

OPTIONAL_EQUIP_KEYS = {"模板"}

FIXED_TABLE_PROPERTY_NAMES = {
    "攻击加成",
    "魔法加成",
    "道术加成",
}

RESERVED_PROPERTY_NAMES = {
    "HP百分比",
}

REMARK_KEYS = {
    "备注",
    "说明",
    "剧情说明",
}

IGNORED_METADATA_KEYS = {
    "套装序号",
    "套装名",
    "CustomItem模板ID",
    "素材目录",
    "诅咒",
}

ALIASES = {
    "装备名": "名称",
    "模板装备": "模板",
    "生命": "HP",
    "魔法值": "MP",
    "鞭尸": "鞭尸概率",
    "处决": "处决概率",
    "处决增伤": "处决倍率",
    "失衡时间": "处决时间",
}

RANGE_PAIRS = {
    "攻击": ("攻击下限", "攻击上限"),
    "魔法": ("魔法下限", "魔法上限"),
    "道术": ("道术下限", "道术上限"),
    "防御": ("防御下限", "防御上限"),
    "魔御": ("魔御下限", "魔御上限"),
}


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def make_unique_dir(base: Path) -> Path:
    if not base.exists():
        base.mkdir(parents=True, exist_ok=False)
        return base
    for index in range(1, 100):
        candidate = base.with_name(f"{base.name}_{index:02d}")
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
    raise BatchMakerError(f"输出目录重名过多，已停止：{base}")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    data = path.read_bytes()
    text = ""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = data.decode("utf-8", errors="replace")
    rows = list(csv.DictReader(text.splitlines()))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in rows]


def excel_col_to_index(ref: str) -> int:
    match = re.match(r"([A-Z]+)", ref.upper())
    if not match:
        return 0
    index = 0
    for ch in match.group(1):
        index = index * 26 + ord(ch) - ord("A") + 1
    return index - 1


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    try:
        with zipfile.ZipFile(path) as zf:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.findall("main:si", ns):
                    parts = [node.text or "" for node in si.findall(".//main:t", ns)]
                    shared.append("".join(parts))

            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            rel_map = {
                rel.attrib["Id"]: rel.attrib["Target"]
                for rel in rels.findall("pkgrel:Relationship", ns)
            }
            first_sheet = workbook.find("main:sheets/main:sheet", ns)
            if first_sheet is None:
                raise BatchMakerError(f"XLSX 没有工作表：{path}")
            rid = first_sheet.attrib.get(f"{{{ns['rel']}}}id", "")
            target = rel_map.get(rid, "worksheets/sheet1.xml")
            sheet_path = "xl/" + target.lstrip("/")
            sheet_path = sheet_path.replace("xl/xl/", "xl/")
            sheet = ET.fromstring(zf.read(sheet_path))
    except KeyError as exc:
        raise BatchMakerError(f"XLSX 文件结构不完整：{path}，缺少 {exc}") from exc
    except zipfile.BadZipFile as exc:
        raise BatchMakerError(f"不是有效 XLSX 文件：{path}") from exc

    table: list[list[str]] = []
    for row in sheet.findall(".//main:sheetData/main:row", ns):
        values: list[str] = []
        for cell in row.findall("main:c", ns):
            col = excel_col_to_index(cell.attrib.get("r", ""))
            while len(values) <= col:
                values.append("")
            cell_type = cell.attrib.get("t", "")
            value = ""
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.findall(".//main:t", ns))
            else:
                node = cell.find("main:v", ns)
                if node is not None and node.text is not None:
                    raw = node.text
                    if cell_type == "s":
                        idx = int(float(raw))
                        value = shared[idx] if 0 <= idx < len(shared) else ""
                    else:
                        value = raw[:-2] if raw.endswith(".0") else raw
            values[col] = value.strip()
        if any(values):
            table.append(values)

    if not table:
        return []
    headers = [h.strip() for h in table[0]]
    rows: list[dict[str, str]] = []
    for values in table[1:]:
        row = {
            header: (values[index].strip() if index < len(values) else "")
            for index, header in enumerate(headers)
            if header
        }
        if any(row.values()):
            rows.append(row)
    return rows


def read_table_rows(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return read_xlsx_rows(path)
    if suffix in (".csv", ".txt"):
        return read_csv_rows(path)
    raise BatchMakerError(f"不支持的源表格式：{path}。当前支持 .xlsx / .csv")


def clean_value(value: str) -> str:
    return value.strip()


def is_nonzero(value: str) -> bool:
    value = clean_value(value)
    if not value:
        return False
    return value.replace("%", "") not in ("0", "0.0")


def range_from_pair(row: dict[str, str], low_key: str, high_key: str) -> str:
    low = clean_value(row.get(low_key, ""))
    high = clean_value(row.get(high_key, ""))
    if low and high:
        return f"{low}-{high}"
    return low or high


def script_property_names() -> set[str]:
    return set(xy_equip_maker.load_script_props().get("properties", {}).keys())


def row_name(row: dict[str, str]) -> str:
    return clean_value(row.get("名称", "")) or clean_value(row.get("装备名", ""))


def append_section(lines: list[str], title: str, values: dict[str, str]) -> None:
    if not values:
        return
    lines.append("")
    lines.append(f"[{title}]")
    for key, value in values.items():
        lines.append(f"{key}={value}")


def row_to_equipment_txt(row: dict[str, str]) -> str:
    normalized = dict(row)
    for old, new in ALIASES.items():
        if old in normalized and normalized.get(old) and not normalized.get(new):
            normalized[new] = normalized[old]

    name = row_name(normalized)
    if not name:
        raise BatchMakerError("CSV 行缺少 名称/装备名。")
    slot = clean_value(normalized.get("部位", ""))
    if not slot:
        raise BatchMakerError(f"{name} 缺少 部位。")

    equip: dict[str, str] = {
        "名称": name,
        "部位": slot,
    }
    if slot == xy_equip_maker.TITLE_SCROLL_SLOT:
        equip["DuraMax"] = "1"
    elif slot != xy_equip_maker.BACKPACK_ARTIFACT_SLOT:
        # 可穿戴装备持久由平台统一管理。特殊背包物品不伪装成60000持久装备。
        equip["DuraMax"] = str(FIXED_EQUIPMENT_DURABILITY)
    template = clean_value(normalized.get("模板", ""))
    if template:
        equip["模板"] = template

    for key in BASE_DIRECT_KEYS:
        if key in ("名称", "部位", "模板", "持久", "DuraMax"):
            continue
        value = clean_value(normalized.get(key, ""))
        if value:
            equip[key] = value

    for output_key, (low_key, high_key) in RANGE_PAIRS.items():
        if output_key not in equip:
            value = range_from_pair(normalized, low_key, high_key)
            if value:
                equip[output_key] = value

    icon_source: dict[str, str] = {}
    source_id = clean_value(normalized.get("来源编号", "")) or clean_value(normalized.get("SourceId", ""))
    if source_id:
        icon_source["来源编号"] = source_id

    native: dict[str, str] = {}
    script: dict[str, str] = {}
    fixed_table: dict[str, str] = {}
    reserved: dict[str, str] = {}
    remarks: dict[str, str] = {}
    scripts = script_property_names()
    for key, value in normalized.items():
        key = key.strip()
        value = clean_value(value)
        if not value:
            continue
        canonical = ALIASES.get(key, key)
        if (
            canonical in BASE_DIRECT_KEYS
            or canonical in OPTIONAL_EQUIP_KEYS
            or canonical in IGNORED_METADATA_KEYS
            or canonical in {"来源编号", "SourceId"}
        ):
            continue
        if canonical in xy_equip_maker.NATIVE_ELEMENT_FIELD_MAP:
            native[canonical] = value
        elif canonical in scripts:
            script[canonical] = value
        elif canonical in FIXED_TABLE_PROPERTY_NAMES:
            fixed_table[canonical] = value
        elif canonical in RESERVED_PROPERTY_NAMES:
            reserved[canonical] = value
        elif canonical in REMARK_KEYS:
            remarks["说明"] = value

    for i in range(1, 21):
        type_key = f"绿字{i}类型"
        value_key = f"绿字{i}数值"
        prop = clean_value(normalized.get(type_key, ""))
        value = clean_value(normalized.get(value_key, ""))
        if not prop or not is_nonzero(value):
            continue
        if prop in xy_equip_maker.NATIVE_ELEMENT_FIELD_MAP:
            native[prop] = value
        elif prop in scripts:
            script[prop] = value
        elif prop in FIXED_TABLE_PROPERTY_NAMES:
            fixed_table[prop] = value
        elif prop in RESERVED_PROPERTY_NAMES:
            reserved[prop] = value
        else:
            raise BatchMakerError(f"{name} 未识别绿字属性：{prop}。请先登记原生字段或脚本属性接口。")

    lines = ["[装备]"]
    for key, value in equip.items():
        if value:
            lines.append(f"{key}={value}")
    append_section(lines, "图标来源", icon_source)
    append_section(lines, "原生属性", native)
    append_section(lines, "显示属性", native)
    append_section(lines, "固定表属性", fixed_table)
    append_section(lines, "预留属性", reserved)
    append_section(lines, "特殊属性", script)
    append_section(lines, "备注", remarks)
    return "\n".join(lines) + "\n"


def write_report(output_dir: Path, results: Iterable[BatchResult]) -> Path:
    report = output_dir / "batch_report.md"
    lines = ["# 批量做装备报告", ""]
    for result in results:
        lines.append(f"- 第{result.row_number}行 `{result.name}`：{result.status}")
        lines.append(f"  - TXT：`{result.txt_path}`")
        lines.append(f"  - 信息：{result.message}")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def run_batch(input_path: Path, apply: bool, update: bool = False, continue_on_error: bool = False) -> tuple[Path, list[BatchResult]]:
    if not input_path.exists():
        raise BatchMakerError(f"源表不存在：{input_path}")
    rows = read_table_rows(input_path)
    if not rows:
        raise BatchMakerError(f"源表没有数据行：{input_path}")

    output_dir = make_unique_dir(OUTPUT_DIR / f"batch_{now_stamp()}")
    txt_dir = output_dir / "generated_txt"
    txt_dir.mkdir(parents=True, exist_ok=False)

    results: list[BatchResult] = []
    seen_names: set[str] = set()
    for index, row in enumerate(rows, start=2):
        name = row_name(row) or f"row_{index}"
        try:
            if name in seen_names:
                raise BatchMakerError(f"CSV 内部重复装备名：{name}")
            seen_names.add(name)
            text = row_to_equipment_txt(row)
            txt_path = txt_dir / f"{xy_equip_maker.safe_filename(name)}.txt"
            txt_path.write_text(text, encoding="utf-8")
            if update:
                message = xy_equip_maker.update_equipment(txt_path)
                status = "已修改"
            elif apply:
                message = xy_equip_maker.make_equipment(txt_path)
                status = "已生成"
            else:
                message = xy_equip_maker.check_equipment(txt_path)
                status = "检查通过"
            results.append(BatchResult(index, name, status, message, str(txt_path)))
        except Exception as exc:
            message = str(exc)
            trace_path = output_dir / f"error_row_{index}_{xy_equip_maker.safe_filename(name)}.txt"
            trace_path.write_text(message + "\n\n" + traceback.format_exc(), encoding="utf-8")
            results.append(BatchResult(index, name, "失败", f"{message}；详见 {trace_path}", ""))
            if not continue_on_error:
                break

    report = write_report(output_dir, results)
    return report, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="玄渊批量做装备工具")
    parser.add_argument("--input", type=Path, default=DEFAULT_SOURCE_TABLE, help="装备源表路径，支持 .xlsx / .csv")
    parser.add_argument("--apply", action="store_true", help="正式生成；不加则只预检查")
    parser.add_argument("--update", action="store_true", help="修改已存在装备；会更新DB基础字段、原生属性、固定表属性和显示文本")
    parser.add_argument("--continue-on-error", action="store_true", help="遇到失败继续处理后续行")
    args = parser.parse_args(argv)

    if args.apply and args.update:
        raise BatchMakerError("--apply 和 --update 不能同时使用")
    report, results = run_batch(args.input, apply=args.apply, update=args.update, continue_on_error=args.continue_on_error)
    failed = [r for r in results if r.status == "失败"]
    print(f"报告={report}")
    print(f"总行数={len(results)}")
    print(f"失败数={len(failed)}")
    if failed:
        for r in failed:
            print(f"失败 第{r.row_number}行 {r.name}: {r.message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
