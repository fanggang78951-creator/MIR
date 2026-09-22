from __future__ import annotations

import html
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .legacy import xy_batch_equip_maker as batch_legacy
from .legacy import xy_equip_maker as maker
from .item_hint import FINAL_SUFFIX
from .source import read_equipment_rows
from .target import inspect_target


RAW_PROTECTED_UPDATE_COLUMNS = frozenset({"Looks", "StdMode", "Shape"})
IGNORED_DURABILITY_COLUMNS = frozenset({"持久", "DuraMax"})
FIXED_EQUIPMENT_DURABILITY = batch_legacy.FIXED_EQUIPMENT_DURABILITY
_SLOT_BY_STDMODE = dict(maker.CANONICAL_SLOT_BY_STDMODE)


class EquipmentUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedUpdate:
    spec: maker.EquipmentSpec
    base_zero_fields: dict[str, int]
    native_updates: dict[str, int]
    fixed_updates: dict[str, int]
    script_updates: dict[str, int]


def _source_id(row: dict[str, str]) -> int | None:
    raw = row.get("来源编号", "").strip() or row.get("SourceId", "").strip()
    if not raw:
        return None
    try:
        value = maker.parse_int(raw)
    except Exception as exc:
        raise EquipmentUpdateError(f"{batch_legacy.row_name(row)}：来源编号不是整数：{raw}") from exc
    if value < 0:
        raise EquipmentUpdateError(f"{batch_legacy.row_name(row)}：来源编号不能小于 0：{raw}")
    return value


def _apply_update_icon(
    spec: maker.EquipmentSpec,
    source_id: int | None,
    old_looks: int,
    icon_cache: dict[int, int],
) -> dict[str, object]:
    if source_id is None:
        return {
            "name": spec.name,
            "source_id": None,
            "old_looks": old_looks,
            "new_looks": old_looks,
            "action": "preserve_old_looks",
        }
    if maker.CLIENT_DATA is None:
        raise EquipmentUpdateError(f"{spec.name}：填写了来源编号，必须选择客户端 data 目录。")
    if source_id in icon_cache:
        new_looks = icon_cache[source_id]
        spec.fields["Looks"] = new_looks
        return {
            "name": spec.name,
            "source_id": source_id,
            "old_looks": old_looks,
            "new_looks": new_looks,
            "action": "reuse_batch_source_id",
        }
    maker.reuse_static_icon_source(spec)
    new_looks = int(spec.fields["Looks"])
    icon_cache[source_id] = new_looks
    return {
        "name": spec.name,
        "source_id": source_id,
        "old_looks": old_looks,
        "new_looks": new_looks,
        "action": "reuse_source_id",
    }


def update_headers(platform_root) -> list[str]:
    platform_root = maker.Path(platform_root).resolve()
    master = platform_root / "所需材料表格汇总" / "09_装备批量生成.xlsx"
    if not master.is_file():
        master = platform_root / "做装备" / "templates" / "XuanYuanItems.xlsx"
    rows = read_equipment_rows(master)
    headers = list(rows[0]) if rows else _read_xlsx_headers(master)
    if not headers:
        raise EquipmentUpdateError(f"无法读取平台装备母表表头：{master}")
    return [header for header in headers if header not in IGNORED_DURABILITY_COLUMNS | RAW_PROTECTED_UPDATE_COLUMNS]


def _read_xlsx_headers(path) -> list[str]:
    """Read the first sheet header even when the shared workbook has no data rows."""
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    try:
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = [
                    "".join(node.text or "" for node in item.findall(".//main:t", ns))
                    for item in root.findall("main:si", ns)
                ]
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            relation_map = {
                relation.attrib["Id"]: relation.attrib["Target"]
                for relation in relationships.findall("pkgrel:Relationship", ns)
            }
            first = workbook.find("main:sheets/main:sheet", ns)
            if first is None:
                return []
            relation_id = first.attrib.get(f"{{{ns['rel']}}}id", "")
            target = relation_map.get(relation_id, "worksheets/sheet1.xml")
            sheet_path = ("xl/" + target.lstrip("/")).replace("xl/xl/", "xl/")
            sheet = ET.fromstring(archive.read(sheet_path))
            first_row = sheet.find(".//main:sheetData/main:row", ns)
            if first_row is None:
                return []
            headers: list[str] = []
            for cell in first_row.findall("main:c", ns):
                column = batch_legacy.excel_col_to_index(cell.attrib.get("r", ""))
                while len(headers) <= column:
                    headers.append("")
                if cell.attrib.get("t") == "inlineStr":
                    value = "".join(node.text or "" for node in cell.findall(".//main:t", ns))
                else:
                    node = cell.find("main:v", ns)
                    raw = node.text if node is not None and node.text is not None else ""
                    value = shared[int(raw)] if cell.attrib.get("t") == "s" and raw else raw
                headers[column] = value.strip()
            return [header for header in headers if header]
    except Exception as exc:
        raise EquipmentUpdateError(f"读取平台装备母表表头失败：{path}：{exc}") from exc


def _excel_column(index: int) -> str:
    index += 1
    text = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        text = chr(65 + remainder) + text
    return text


def _write_xlsx(path, rows: list[list[str]]) -> None:
    sheet = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    sheet.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
    for row_index, row in enumerate(rows, start=1):
        sheet.append(f'<row r="{row_index}">')
        for column_index, value in enumerate(row):
            if value == "":
                continue
            reference = f"{_excel_column(column_index)}{row_index}"
            sheet.append(f'<c r="{reference}" t="inlineStr"><is><t>{html.escape(str(value), quote=False)}</t></is></c>')
        sheet.append("</row>")
    sheet.append("</sheetData></worksheet>")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="修改装备源表" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", "".join(sheet))


def export_update_workbook(platform_root, server_root, output) -> None:
    target = inspect_target(server_root)
    connection = sqlite3.connect(target.database)
    try:
        names = [str(row[0]) for row in connection.execute("SELECT Name FROM StdItems ORDER BY Idx")]
    finally:
        connection.close()
    headers = update_headers(platform_root)
    _write_xlsx(maker.Path(output), [headers] + [[name] + [""] * (len(headers) - 1) for name in names])


def validate_update_columns(row: dict[str, str]) -> None:
    forbidden = sorted(set(row) & RAW_PROTECTED_UPDATE_COLUMNS)
    if forbidden:
        raise EquipmentUpdateError("修改装备源表不允许包含：" + "、".join(forbidden))
    if not batch_legacy.row_name(row):
        raise EquipmentUpdateError("修改装备源表缺少 名称。")


def _is_explicit_zero(value: str) -> bool:
    return value.strip().replace("%", "") in {"0", "0.0"}


def _slot_for_mode(stdmode: int) -> str:
    return _SLOT_BY_STDMODE.get(int(stdmode), "")


def prepare_update(row: dict[str, str], stdmode: int) -> PreparedUpdate:
    validate_update_columns(row)
    slot = _slot_for_mode(stdmode)
    if not slot:
        raise EquipmentUpdateError(f"{batch_legacy.row_name(row)}：StdMode={stdmode} 无法识别部位，禁止修改。")
    requested_slot = row.get("部位", "").strip()
    if requested_slot:
        requested_mode = maker.STD_MODE_BY_SLOT.get(requested_slot)
        if requested_mode is None:
            raise EquipmentUpdateError(f"{batch_legacy.row_name(row)}：无法识别填写的部位：{requested_slot}")
        if int(requested_mode) != int(stdmode):
            raise EquipmentUpdateError(
                f"{batch_legacy.row_name(row)}：填写部位 {requested_slot} 与目标装备真实部位"
                f"（StdMode={stdmode}）不一致。"
            )
    try:
        maker.validate_slot_attribute_contract(slot, row.items(), stdmode)
    except maker.EquipMakerError as exc:
        raise EquipmentUpdateError(str(exc)) from exc
    source = dict(row)
    source["部位"] = slot
    text = batch_legacy.row_to_equipment_txt(source)
    parser_path = maker.Path(".")
    # parse_spec needs a file, therefore callers write the generated text in their transaction workspace.
    base_zero_fields: dict[str, int] = {}
    native_updates: dict[str, int] = {}
    fixed_updates: dict[str, int] = {}
    script_updates: dict[str, int] = {}
    aliases = batch_legacy.ALIASES
    range_fields = {
        "攻击": ("Dc", "Dc2"), "魔法": ("Mc", "Mc2"), "道术": ("Sc", "Sc2"),
        "防御": ("Ac", "Ac2"), "魔御": ("Mac", "Mac2"),
    }
    for raw_key, raw_value in row.items():
        key = aliases.get(raw_key.strip(), raw_key.strip())
        value = raw_value.strip()
        if key in maker.FIXED_TABLE_ATTRS:
            fixed_updates[key] = maker.parse_int(value) if value else 0
        elif key in maker.load_script_props().get("properties", {}):
            script_updates[key] = maker.parse_int(value) if value else 0
        elif key in maker.NATIVE_ELEMENT_FIELD_MAP:
            native_updates[maker.NATIVE_ELEMENT_FIELD_MAP[key]] = maker.parse_int(value) if value else 0
        elif not value and key in range_fields:
            # Ac/Ac2/Mac/Mac2 are overloaded by the engine for weapons and
            # necklaces.  A full update workbook always contains blank
            # 防御/魔御 columns; treating those blanks as ordinary defence
            # clears would overwrite a non-blank 幸运/准确/攻击速度 value that
            # is parsed later into the same database columns.
            #
            # On these overloaded slots the dedicated property columns below
            # are the sole owners of the shared fields.  Normal armour keeps
            # the original blank-means-zero behaviour.
            if slot in maker.WEAPON_SLOTS | maker.NECKLACE_SLOTS and key in {"防御", "魔御"}:
                continue
            for field in range_fields[key]:
                base_zero_fields[field] = 0
        elif not value and key == "幸运":
            if slot in maker.WEAPON_SLOTS:
                base_zero_fields["Ac"] = 0
            elif slot in maker.NECKLACE_SLOTS:
                base_zero_fields["Mac2"] = 0
            else:
                base_zero_fields["Source"] = 0
        elif not value and key == "准确":
            base_zero_fields["Ac2" if slot in maker.WEAPON_SLOTS else "Ac"] = 0
        elif not value and key == "攻击速度":
            base_zero_fields["Mac2" if slot in maker.WEAPON_SLOTS else "Reserved"] = 0
        elif key in IGNORED_DURABILITY_COLUMNS:
            continue
        elif not value and key in maker.BASE_FIELD_MAP:
            field = maker.BASE_FIELD_MAP[key]
            if field not in {"StdMode", "Looks", "DuraMax", "Shape"}:
                base_zero_fields[field] = 0
    spec = maker.EquipmentSpec(name=batch_legacy.row_name(row), slot=slot)
    spec.icon_source = {"_generated_text": text}
    return PreparedUpdate(spec, base_zero_fields, native_updates, fixed_updates, script_updates)


def build_spec_from_prepared(prepared: PreparedUpdate, spec_path) -> maker.EquipmentSpec:
    spec_path.write_text(prepared.spec.icon_source["_generated_text"], encoding="utf-8")
    spec = maker.parse_spec(spec_path)
    for field in ("StdMode", "Looks", "Shape"):
        spec.fields.pop(field, None)
    spec.fields["DuraMax"] = FIXED_EQUIPMENT_DURABILITY
    return spec


def _existing_fixed_attrs(name: str) -> dict[str, int]:
    if not maker.GROUP_ITEM.exists():
        return {}
    marker = "\t" + name + "\t"
    for line in maker.read_text_auto(maker.GROUP_ITEM).splitlines():
        if marker not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            raise EquipmentUpdateError(f"{name}：GroupItemList 行格式无法识别。")
        values = parts[5].split("|")
        result = {}
        for key, meta in maker.FIXED_TABLE_ATTRS.items():
            index = int(meta["group_index"])
            if index < len(values) and values[index].strip() not in {"", "0"}:
                result[key] = int(values[index])
        return result
    return {}


def _native_display_fields() -> dict[str, str]:
    """Return one stable display label for each native Element database field."""
    result: dict[str, str] = {}
    for label, field in maker.NATIVE_ELEMENT_FIELD_MAP.items():
        result.setdefault(field, label)
    return result


def _existing_native_display_attrs(name: str) -> dict[str, int]:
    """Read native Element values so an unrelated update does not erase green text."""
    display_fields = _native_display_fields()
    connection = maker.connect_db()
    try:
        columns = set(maker.table_columns(connection))
        fields = [field for field in display_fields if field in columns]
        if not fields:
            return {}
        row = connection.execute(
            f"SELECT {', '.join(fields)} FROM StdItems WHERE Name=? ORDER BY Idx LIMIT 1", (name,)
        ).fetchone()
        if row is None:
            return {}
        return {
            display_fields[field]: int(value)
            for field, value in zip(fields, row)
            if value not in (None, "", 0, "0")
        }
    finally:
        connection.close()


def _remove_named_fixed_rows(name: str) -> None:
    for path, marker in ((maker.ITEM_RULE, name + "\t"), (maker.GROUP_ITEM, "\t" + name + "\t")):
        if not path.exists():
            continue
        lines = [line for line in maker.read_text_auto(path).splitlines() if marker not in line]
        maker.write_mir_text(path, "\r\n".join(lines) + ("\r\n" if lines else ""))


def _existing_managed_item_hint_suffix(name: str) -> str:
    if not maker.ITEM_DESC.exists():
        return ""
    prefix = name + "="
    matches = [line for line in maker.read_text_auto(maker.ITEM_DESC).splitlines() if line.startswith(prefix)]
    if len(matches) > 1:
        raise EquipmentUpdateError(f"{name}：ItemDescList 存在重复显示行，已阻止修改。")
    if not matches:
        return ""
    value = matches[0].split("=", 1)[1]
    return FINAL_SUFFIX if value.endswith(FINAL_SUFFIX) else ""


def _comment_pattern(name: str, template: str) -> re.Pattern[str] | None:
    if "{value}" not in template:
        return None
    prefix, suffix = template.split("{value}", 1)
    prefix = prefix.replace("{item}", name)
    return re.compile("^" + re.escape(prefix) + r"(-?\d+)" + re.escape(suffix) + r"$")


def _managed_script_attrs(text: str, name: str, registry: dict) -> tuple[dict[str, int], int]:
    found: dict[str, list[int]] = {}
    markers = 0
    for property_name, meta in registry.get("properties", {}).items():
        for outlet in meta.get("outlets", []):
            for line in outlet.get("block", []):
                if not line.startswith("; XY-EQUIP-MAKER "):
                    continue
                pattern = _comment_pattern(name, line)
                if pattern is None:
                    continue
                for candidate in text.splitlines():
                    match = pattern.match(candidate)
                    if match:
                        found.setdefault(property_name, []).append(int(match.group(1)))
                        markers += 1
    result: dict[str, int] = {}
    for property_name, values in found.items():
        if len(set(values)) != 1:
            raise EquipmentUpdateError(f"{name}：受管脚本属性 {property_name} 数值不一致。")
        result[property_name] = values[0]
    return result, markers


def _remove_managed_effect_blocks(text: str, name: str) -> tuple[str, int]:
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    removed = 0
    marker = f"; XY-EQUIP-MAKER {name}:"
    while index < len(lines):
        if lines[index].startswith(marker):
            block = lines[index:index + 5]
            if len(block) != 5 or block[1:4] != ["#IF", f"CHECKITEMW {name} 1", "#ACT"]:
                raise EquipmentUpdateError(f"{name}：发现无法安全替换的受管脚本块。")
            removed += 1
            index += 5
            continue
        output.append(lines[index])
        index += 1
    return "\r\n".join(output) + ("\r\n" if output else ""), removed


def _remove_display_block(text: str, name: str) -> str:
    marker = f"; XY-EQUIP-MAKER-DISPLAY {name}"
    start = text.find(marker)
    if start < 0:
        return text
    next_marker = text.find("; XY-EQUIP-MAKER-DISPLAY ", start + len(marker))
    next_event = text.find("[@", start + len(marker))
    candidates = [item for item in (next_marker, next_event) if item >= 0]
    end = min(candidates) if candidates else len(text)
    return text[:start] + text[end:]


def _remove_attribute_panel_blocks(text: str, name: str) -> tuple[str, int]:
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    removed = 0
    marker = f"; XY-ATTR-PANEL {name}:"
    while index < len(lines):
        if lines[index].startswith(marker):
            block = lines[index:index + 5]
            if len(block) != 5 or block[1:4] != ["#IF", f"CHECKITEMW {name} 1", "#ACT"]:
                raise EquipmentUpdateError(f"{name}：发现无法安全替换的属性图标受管块。")
            removed += 1
            index += 5
            continue
        output.append(lines[index])
        index += 1
    return "\r\n".join(output) + ("\r\n" if output else ""), removed


def _update_all_stditems_by_name(spec: maker.EquipmentSpec) -> int:
    """Apply editable DB fields to every definition sharing one equipment name."""
    connection = maker.connect_db()
    try:
        items = connection.execute(
            "SELECT Idx, StdMode FROM StdItems WHERE Name=? ORDER BY Idx", (spec.name,)
        ).fetchall()
        if not items:
            raise EquipmentUpdateError(f"{spec.name}：目标装备不存在。")
        if len({int(item[1]) for item in items}) != 1:
            raise EquipmentUpdateError(f"{spec.name}：同名装备部位不一致，无法统一修改。")
        if not spec.fields:
            return int(items[0][0])
        columns = maker.table_columns(connection)
        assignments: list[str] = []
        values: list[int] = []
        for key, value in spec.fields.items():
            if key in columns:
                assignments.append(f"{key}=?")
                values.append(value)
        if assignments:
            values.append(spec.name)
            connection.execute(f"UPDATE StdItems SET {', '.join(assignments)} WHERE Name=?", values)
            connection.commit()
        return int(items[0][0])
    finally:
        connection.close()


def update_equipment_row(
    row: dict[str, str],
    spec_path,
    *,
    icon_cache: dict[int, int] | None = None,
    icon_metadata: list[dict[str, object]] | None = None,
) -> int:
    connection = maker.connect_db()
    try:
        items = connection.execute(
            "SELECT Idx, StdMode, Looks, Shape FROM StdItems WHERE Name=? ORDER BY Idx",
            (batch_legacy.row_name(row),),
        ).fetchall()
    finally:
        connection.close()
    if not items:
        raise EquipmentUpdateError(f"{batch_legacy.row_name(row)}：目标装备不存在。")
    definitions = {(int(item[1]), int(item[2]), int(item[3])) for item in items}
    if len(definitions) != 1:
        raise EquipmentUpdateError(
            f"{batch_legacy.row_name(row)}：同名装备的 StdMode/Looks/Shape 定义不唯一，无法统一修改。"
        )
    prepared = prepare_update(row, int(items[0][1]))
    spec = build_spec_from_prepared(prepared, spec_path)
    spec.fields.update(prepared.base_zero_fields)
    spec.fields.update(prepared.native_updates)
    cache = icon_cache if icon_cache is not None else {}
    icon_result = _apply_update_icon(spec, _source_id(row), int(items[0][2]), cache)
    if icon_metadata is not None:
        icon_metadata.append(icon_result)
    spec.fixed_attrs = _existing_fixed_attrs(spec.name)
    for key, value in prepared.fixed_updates.items():
        if value:
            spec.fixed_attrs[key] = value
        else:
            spec.fixed_attrs.pop(key, None)

    registry = maker.load_script_props()
    original_qfunction = maker.read_text_auto(maker.QFUNCTION)
    original_qmanage = maker.read_text_auto(maker.QMANAGE)
    combined_scripts = original_qfunction + "\r\n" + original_qmanage
    existing_script, marker_count = _managed_script_attrs(combined_scripts, spec.name, registry)
    all_checks = sum(
        text.count(f"CHECKITEMW {spec.name} 1")
        for text in (original_qfunction, original_qmanage)
    )
    if all_checks != marker_count:
        raise EquipmentUpdateError(f"{spec.name}：发现非受管同名脚本分支，已阻止覆盖。")
    for key, value in prepared.script_updates.items():
        if value:
            existing_script[key] = value
        else:
            existing_script.pop(key, None)
    spec.script_attrs = existing_script
    panel_relevant = any(
        key in existing_script or key in prepared.script_updates
        for key in maker.EXECUTION_PANEL_SPECS
    )
    native_display_attrs = _existing_native_display_attrs(spec.name)
    for field, label in _native_display_fields().items():
        if field not in spec.fields:
            continue
        value = int(spec.fields[field])
        if value:
            native_display_attrs[label] = value
        else:
            native_display_attrs.pop(label, None)
    spec.desc_attrs = {**native_display_attrs, **spec.fixed_attrs, **spec.script_attrs}

    qfunction, _removed = _remove_managed_effect_blocks(original_qfunction, spec.name)
    qmanage, _removed_qmanage = _remove_managed_effect_blocks(original_qmanage, spec.name)
    qfunction = _remove_display_block(qfunction, spec.name)
    maker.write_mir_text(maker.QFUNCTION, qfunction)
    maker.write_mir_text(maker.QMANAGE, qmanage)
    if panel_relevant:
        if not maker.ATTRIBUTE_PANEL.is_file():
            raise EquipmentUpdateError(f"{spec.name}：目标服缺少属性图标脚本。")
        attribute_panel = maker.read_text_auto(maker.ATTRIBUTE_PANEL)
        attribute_panel, _removed_panel = _remove_attribute_panel_blocks(attribute_panel, spec.name)
        maker.write_mir_text(maker.ATTRIBUTE_PANEL, attribute_panel)
    if spec.script_attrs:
        maker.write_script_texts(maker.build_script_texts(spec, registry))

    idx = _update_all_stditems_by_name(spec)
    if spec.fixed_attrs:
        maker.patch_fixed_tables(spec)
    elif prepared.fixed_updates:
        _remove_named_fixed_rows(spec.name)
    native_fields = set(_native_display_fields())
    if prepared.fixed_updates or prepared.script_updates or native_fields.intersection(spec.fields):
        maker.replace_item_desc(
            spec,
            registry,
            trailing_suffix=_existing_managed_item_hint_suffix(spec.name),
        )
    return idx
