from __future__ import annotations

"""Workbook and NPC-assignment driven generic item synthesis for LFM2.

The workbook is the sole recipe source; the adjacent text document only assigns
recipes to independent map NPCs.  Every enabled backpack item and every output
name is resolved against the target server's unique ``StdItems`` row during
preflight; native currencies never fall back to similarly named items.
"""

import hashlib
import re
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .encoding import TextDocument, encode_text_document, read_text_document
from .installer import InstallPlan, InstallReceipt, Installer, PlannedChange
from .repository import PackageRepository
from .target import TargetInspector, is_executable_running
from .textpatch import TextPatchError, install_managed_block, scan_labels, set_exclusive_unique_line
from .user_documents import documents_root


PACKAGE_ID = "xy.optional.item-synthesis"
PACKAGE_VERSION = "1.1.0-candidate.4"
DEFAULT_WORKBOOK = "34_通用物品合成.xlsx"
DEFAULT_NPC_CONFIG = "35_合成NPC与配方分配.txt"
SCRIPT_PATH = "玄渊功能/通用合成"
MERCHANT = "Mir200/Envir/MerChant.txt"
MAPINFO = "Mir200/Envir/MapInfo.txt"
MAIN_OUTPUT_ITEMSHOW_X = 260
MAIN_OUTPUT_ITEMSHOW_Y = -30
MAIN_OUTPUT_ITEMSHOW_COLUMN_STEP = 58
MAIN_OUTPUT_ITEMSHOW_ROW_STEP = 58
MAIN_OUTPUT_ITEMSHOW_COLUMNS = 3
NATIVE_CURRENCIES = {
    "金币": ("CHECKGOLD {amount}", "GOLDCOUNT - {amount}"),
    "原生金币": ("CHECKGOLD {amount}", "GOLDCOUNT - {amount}"),
    "元宝": ("CHECKGAMEGOLD > {threshold}", "GAMEGOLD - {amount}"),
    "原生元宝": ("CHECKGAMEGOLD > {threshold}", "GAMEGOLD - {amount}"),
    "灵符": ("CHECKGAMEGIRD > {threshold}", "GAMEGIRD - {amount}"),
    "原生灵符": ("CHECKGAMEGIRD > {threshold}", "GAMEGIRD - {amount}"),
    "账户灵符": ("CHECKGAMEGIRD > {threshold}", "GAMEGIRD - {amount}"),
    "金刚石": ("CHECKGAMEDIAMOND {amount}", "GAMEDIAMOND - {amount}"),
    "原生金刚石": ("CHECKGAMEDIAMOND {amount}", "GAMEDIAMOND - {amount}"),
    "账户金刚石": ("CHECKGAMEDIAMOND {amount}", "GAMEDIAMOND - {amount}"),
}


class ItemSynthesisError(ValueError):
    pass


@dataclass(frozen=True)
class SynthesisInput:
    input_type: str
    name: str
    amount: int
    order: int


@dataclass(frozen=True)
class SynthesisRecipe:
    recipe_id: str
    category: str
    display_name: str
    output_name: str
    output_amount: int
    order: int
    inputs: tuple[SynthesisInput, ...]


@dataclass(frozen=True)
class SynthesisSettings:
    npc_name: str
    map_code: str
    x: int
    y: int
    appearance: int
    title: str
    page_size: int


@dataclass(frozen=True)
class SynthesisNpc:
    npc_id: str
    settings: SynthesisSettings
    order: int
    recipe_ids: tuple[str, ...]


@dataclass(frozen=True)
class SynthesisWorkbook:
    path: str
    sha256: str
    settings: SynthesisSettings
    recipes: tuple[SynthesisRecipe, ...]


@dataclass
class ItemSynthesisPlan:
    server: str
    workbook: str
    workbook_hash: str = ""
    npc_config: str = ""
    npc_config_hash: str = ""
    npcs: list[dict[str, object]] = field(default_factory=list)
    recipes: list[dict[str, object]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[PlannedChange] = field(default_factory=list)
    install_plan: InstallPlan | None = None
    operation: str = "item-synthesis-config"


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _integer(value: object, field_name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError) as exc:
        raise ItemSynthesisError(f"{field_name}必须填写整数：{value}") from exc
    if number < minimum or (maximum is not None and number > maximum):
        limit = f"且不能大于{maximum}" if maximum is not None else ""
        raise ItemSynthesisError(f"{field_name}不能小于{minimum}{limit}：{number}")
    return number


def _enabled(value: object) -> bool:
    return _text(value).casefold() in {"是", "可安装", "启用", "1", "true", "yes"}


def _safe_token(value: object, field_name: str, *, maximum: int = 40) -> str:
    token = _text(value)
    if not token or len(token) > maximum or re.search(r"[<>@;\\\r\n\t]", token):
        raise ItemSynthesisError(f"{field_name}无效：{token}")
    return token


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    if not letters:
        return 0
    value = 0
    for letter in letters.group(0):
        value = value * 26 + ord(letter) - 64
    return value - 1


def _cell_value(cell: ET.Element, shared: list[str], ns: dict[str, str]) -> object:
    value = cell.find("m:v", ns)
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(item.text or "" for item in cell.findall(".//m:t", ns))
    if value is None or value.text is None:
        return ""
    raw = value.text
    if cell_type == "s":
        return shared[int(raw)]
    if cell_type in {"str", "e"}:
        return raw
    try:
        number = float(raw)
        return int(number) if number.is_integer() else number
    except ValueError:
        return raw


def _read_xlsx(path: Path) -> tuple[dict[str, list[list[object]]], str]:
    raw = path.read_bytes()
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    try:
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = [
                    "".join(node.text or "" for node in item.findall(".//m:t", ns))
                    for item in root.findall("m:si", ns)
                ]
            book = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels.findall("r:Relationship", rel_ns)}
            result: dict[str, list[list[object]]] = {}
            for sheet in book.findall("m:sheets/m:sheet", ns):
                name = sheet.attrib["name"]
                rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                target = targets[rid].lstrip("/")
                xml_name = target if target.startswith("xl/") else "xl/" + target
                root = ET.fromstring(archive.read(xml_name))
                matrix: list[list[object]] = []
                for row in root.findall(".//m:sheetData/m:row", ns):
                    row_number = int(row.attrib.get("r", len(matrix) + 1))
                    while len(matrix) < row_number:
                        matrix.append([])
                    values = matrix[row_number - 1]
                    for cell in row.findall("m:c", ns):
                        index = _column_index(cell.attrib.get("r", "A1"))
                        while len(values) <= index:
                            values.append("")
                        values[index] = _cell_value(cell, shared, ns)
                result[name] = matrix
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ItemSynthesisError(f"无法读取通用物品合成表：{exc}") from exc
    return result, hashlib.sha256(raw).hexdigest()


def _rows(matrix: list[list[object]], sheet_name: str, header_row: int) -> list[dict[str, object]]:
    if len(matrix) <= header_row:
        raise ItemSynthesisError(f"工作表缺少表头：{sheet_name}")
    headers = [_text(value) for value in matrix[header_row]]
    rows: list[dict[str, object]] = []
    for values in matrix[header_row + 1:]:
        item = {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers) if header
        }
        if any(_text(value) for value in item.values()):
            rows.append(item)
    return rows


def read_item_synthesis_workbook(
    path: Path,
    *,
    allow_auto_coordinates: bool = False,
) -> SynthesisWorkbook:
    path = Path(path).resolve()
    if not path.is_file():
        raise ItemSynthesisError(f"通用物品合成表不存在：{path}")
    sheets, digest = _read_xlsx(path)
    required = {"界面设置", "合成配方", "消耗明细"}
    missing = sorted(required - set(sheets))
    if missing:
        raise ItemSynthesisError("通用物品合成表缺少工作表：" + "、".join(missing))

    settings_values: dict[str, object] = {}
    for row in _rows(sheets["界面设置"], "界面设置", 2):
        key = _text(row.get("设置项"))
        if key:
            settings_values[key] = row.get("当前值", "")
    raw_x = _text(settings_values.get("X", 104))
    raw_y = _text(settings_values.get("Y", 75))
    if allow_auto_coordinates and not raw_x and not raw_y:
        x = y = 0
    else:
        if allow_auto_coordinates and bool(raw_x) != bool(raw_y):
            raise ItemSynthesisError("NPC坐标X/Y必须同时填写或同时留空")
        x = _integer(settings_values.get("X", 104), "NPC坐标X", minimum=1)
        y = _integer(settings_values.get("Y", 75), "NPC坐标Y", minimum=1)
    settings = SynthesisSettings(
        npc_name=_safe_token(settings_values.get("NPC名称", "装备合成"), "NPC名称"),
        map_code=_safe_token(settings_values.get("地图", "XY_NMGF_MAIN"), "地图"),
        x=x,
        y=y,
        appearance=_integer(settings_values.get("外观", 220), "NPC外观", minimum=0),
        title=_safe_token(settings_values.get("界面标题", "装备与材料合成"), "界面标题"),
        page_size=_integer(settings_values.get("每页配方数", 8), "每页配方数", minimum=1, maximum=10),
    )

    raw_costs: dict[str, list[SynthesisInput]] = {}
    for row_number, row in enumerate(_rows(sheets["消耗明细"], "消耗明细", 2), start=4):
        recipe_id = _safe_token(row.get("配方ID"), f"消耗明细第{row_number}行配方ID", maximum=32)
        input_type = _text(row.get("输入类型"))
        if input_type not in {"物品", "货币"}:
            raise ItemSynthesisError(f"消耗明细第{row_number}行输入类型只能填写物品或货币")
        name = _safe_token(row.get("名称"), f"消耗明细第{row_number}行名称")
        if input_type == "货币" and name not in NATIVE_CURRENCIES:
            raise ItemSynthesisError(
                f"消耗明细第{row_number}行不支持的原生货币：{name}；可用金币、元宝、灵符、金刚石"
            )
        raw_costs.setdefault(recipe_id.casefold(), []).append(SynthesisInput(
            input_type, name,
            _integer(row.get("数量"), f"消耗明细第{row_number}行数量", minimum=1),
            _integer(row.get("顺序"), f"消耗明细第{row_number}行顺序", minimum=1),
        ))

    recipes: list[SynthesisRecipe] = []
    seen_ids: set[str] = set()
    all_recipe_ids: set[str] = set()
    for row_number, row in enumerate(_rows(sheets["合成配方"], "合成配方", 2), start=4):
        recipe_id = _safe_token(row.get("配方ID"), f"合成配方第{row_number}行配方ID", maximum=32)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", recipe_id):
            raise ItemSynthesisError(f"合成配方第{row_number}行配方ID只能使用英文字母、数字、下划线或短横线")
        key = recipe_id.casefold()
        if key in all_recipe_ids:
            raise ItemSynthesisError(f"配方ID重复：{recipe_id}")
        all_recipe_ids.add(key)
        if not _enabled(row.get("状态")):
            continue
        seen_ids.add(key)
        raw_output_amount = _text(row.get("产出数量"))
        output_amount = 1 if raw_output_amount == "" else _integer(
            raw_output_amount, f"合成配方第{row_number}行产出数量", minimum=1
        )
        combined: dict[tuple[str, str], SynthesisInput] = {}
        for item in raw_costs.get(key, []):
            input_key = (item.input_type, item.name.casefold())
            previous = combined.get(input_key)
            combined[input_key] = SynthesisInput(
                item.input_type, previous.name if previous else item.name,
                (previous.amount if previous else 0) + item.amount,
                min(previous.order, item.order) if previous else item.order,
            )
        inputs = tuple(sorted(combined.values(), key=lambda item: (item.order, item.input_type, item.name)))
        if not inputs:
            raise ItemSynthesisError(f"配方{recipe_id}没有填写任何消耗明细")
        recipes.append(SynthesisRecipe(
            recipe_id=recipe_id,
            category=_safe_token(row.get("分类") or "通用", f"合成配方第{row_number}行分类"),
            display_name=_safe_token(row.get("配方名称"), f"合成配方第{row_number}行配方名称"),
            output_name=_safe_token(row.get("产出名称"), f"合成配方第{row_number}行产出名称"),
            output_amount=output_amount,
            order=_integer(row.get("顺序"), f"合成配方第{row_number}行顺序", minimum=1),
            inputs=inputs,
        ))
    orphaned = sorted(key for key in raw_costs if key not in all_recipe_ids)
    if orphaned:
        raise ItemSynthesisError("消耗明细引用了不存在的配方ID：" + "、".join(orphaned))
    if not recipes:
        raise ItemSynthesisError("没有启用配方；请把需要发布的配方状态改为“是”")
    recipes.sort(key=lambda recipe: (recipe.order, recipe.recipe_id.casefold()))
    return SynthesisWorkbook(str(path), digest, settings, tuple(recipes))


def read_synthesis_npc_config(
    path: Path | None,
    workbook: SynthesisWorkbook,
) -> tuple[tuple[SynthesisNpc, ...], str]:
    """Read optional multi-NPC INI-like configuration.

    Missing configuration keeps the candidate.1 single-NPC contract, so old
    third-party workbooks remain installable.  Once the central 35 file is
    present, every enabled recipe must belong to exactly one enabled NPC.
    """
    if path is None or not Path(path).is_file():
        recipe_ids = tuple(recipe.recipe_id for recipe in workbook.recipes)
        return (SynthesisNpc("LEGACY", workbook.settings, 1, recipe_ids),), ""

    config_path = Path(path).resolve()
    raw = config_path.read_bytes()
    document = read_text_document(config_path)
    sections: dict[str, dict[str, str]] = {}
    section_names: dict[str, str] = {}
    current: dict[str, str] | None = None
    current_id = ""
    for line_number, raw_line in enumerate(document.text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        match = re.fullmatch(r"\[([^\]]+)\]", line)
        if match:
            npc_id = _safe_token(match.group(1), f"NPC配置第{line_number}行NPC ID", maximum=32)
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", npc_id):
                raise ItemSynthesisError(f"NPC配置第{line_number}行NPC ID只能使用英文字母、数字、下划线或短横线")
            key = npc_id.casefold()
            if key in sections:
                raise ItemSynthesisError(f"NPC配置重复区块：{npc_id}")
            current, current_id = {}, npc_id
            sections[key] = current
            section_names[key] = npc_id
            continue
        if current is None or "=" not in line:
            raise ItemSynthesisError(f"NPC配置第{line_number}行格式错误：{line}")
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or key in current:
            raise ItemSynthesisError(f"NPC配置[{current_id}]设置项重复或为空：{key}")
        current[key] = value

    if not sections:
        raise ItemSynthesisError("NPC配置没有任何[NPC_ID]区块")
    known = {recipe.recipe_id.casefold(): recipe.recipe_id for recipe in workbook.recipes}
    assigned: dict[str, str] = {}
    npcs: list[SynthesisNpc] = []
    names: set[str] = set()
    places: set[tuple[str, int, int]] = set()
    for key, values in sections.items():
        if not _enabled(values.get("状态")):
            continue
        npc_id = section_names[key]
        npc_name = _safe_token(values.get("NPC名称"), f"NPC配置[{npc_id}]NPC名称")
        map_code = _safe_token(values.get("地图"), f"NPC配置[{npc_id}]地图")
        x = _integer(values.get("X"), f"NPC配置[{npc_id}]X", minimum=1)
        y = _integer(values.get("Y"), f"NPC配置[{npc_id}]Y", minimum=1)
        appearance = _integer(values.get("外观"), f"NPC配置[{npc_id}]外观", minimum=0)
        title = _safe_token(values.get("界面标题"), f"NPC配置[{npc_id}]界面标题")
        page_size = _integer(values.get("每页配方数", 8), f"NPC配置[{npc_id}]每页配方数", minimum=1, maximum=10)
        order = _integer(values.get("顺序"), f"NPC配置[{npc_id}]顺序", minimum=1)
        recipe_tokens = [token for token in re.split(r"[,，、\s]+", values.get("配方ID", "").strip()) if token]
        if not recipe_tokens:
            raise ItemSynthesisError(f"NPC配置[{npc_id}]没有填写配方ID")
        recipe_ids: list[str] = []
        for token in recipe_tokens:
            canonical = known.get(token.casefold())
            if canonical is None:
                raise ItemSynthesisError(f"NPC配置[{npc_id}]引用了未启用或不存在的配方ID：{token}")
            previous = assigned.get(canonical.casefold())
            if previous is not None:
                raise ItemSynthesisError(f"配方{canonical}同时分配给NPC {previous}和{npc_id}")
            assigned[canonical.casefold()] = npc_id
            recipe_ids.append(canonical)
        name_key = npc_name.casefold()
        place_key = (map_code.casefold(), x, y)
        if name_key in names:
            raise ItemSynthesisError(f"启用的NPC名称重复：{npc_name}")
        if place_key in places:
            raise ItemSynthesisError(f"启用的NPC坐标重复：{map_code}({x},{y})")
        names.add(name_key)
        places.add(place_key)
        npcs.append(SynthesisNpc(
            npc_id,
            SynthesisSettings(npc_name, map_code, x, y, appearance, title, page_size),
            order,
            tuple(recipe_ids),
        ))
    if not npcs:
        raise ItemSynthesisError("NPC配置没有启用任何NPC；请把需要发布的区块状态改为“是”")
    missing = [recipe.recipe_id for recipe in workbook.recipes if recipe.recipe_id.casefold() not in assigned]
    if missing:
        raise ItemSynthesisError("以下启用配方没有分配给任何启用NPC：" + "、".join(missing))
    npcs.sort(key=lambda npc: (npc.order, npc.npc_id.casefold()))
    return tuple(npcs), hashlib.sha256(raw).hexdigest()


def _database(server: Path) -> Path:
    for candidate in (server / "Mud2" / "DB" / "ApexM2.DB", server / "Mud2" / "DB" / "StdItems.DB"):
        if candidate.is_file():
            return candidate
    raise ItemSynthesisError("目标服缺少 Mud2/DB/ApexM2.DB（或兼容StdItems.DB）")


def _resolve_names(server: Path, workbook: SynthesisWorkbook) -> dict[str, int]:
    names = sorted({recipe.output_name for recipe in workbook.recipes} | {
        item.name for recipe in workbook.recipes for item in recipe.inputs if item.input_type == "物品"
    })
    marks = ",".join("?" for _ in names)
    try:
        connection = sqlite3.connect(f"file:{_database(server).as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                f"SELECT Idx, Name FROM StdItems WHERE Name IN ({marks}) ORDER BY Idx", names
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ItemSynthesisError(f"无法只读检查目标服StdItems：{exc}") from exc
    by_name: dict[str, list[int]] = {}
    for idx, name in rows:
        by_name.setdefault(str(name), []).append(int(idx))
    errors: list[str] = []
    resolved: dict[str, int] = {}
    for name in names:
        matches = by_name.get(name, [])
        if not matches:
            errors.append(f"目标服物品不存在：{name}")
        elif len(matches) > 1:
            errors.append(f"目标服物品名称不唯一：{name}")
        else:
            resolved[name] = matches[0]
    if errors:
        raise ItemSynthesisError("\n".join(errors))
    return resolved


def _map_exists(mapinfo: str, map_code: str) -> None:
    count = 0
    for line in mapinfo.splitlines():
        match = re.match(r"^\s*\[\s*([^|\s\]]+)(?:\|[^\s\]]+)?\s+", line, re.IGNORECASE)
        if match and match.group(1).casefold() == map_code.casefold():
            count += 1
    if count != 1:
        raise ItemSynthesisError(f"MapInfo中地图代码{map_code}匹配到{count}行")


def _cost_check(item: SynthesisInput) -> str:
    if item.input_type == "物品":
        return f"CHECKITEM {item.name} {item.amount}"
    template = NATIVE_CURRENCIES[item.name][0]
    return template.format(amount=item.amount, threshold=item.amount - 1)


def _cost_action(item: SynthesisInput) -> str:
    if item.input_type == "物品":
        return f"TAKE {item.name} {item.amount}"
    template = NATIVE_CURRENCIES[item.name][1]
    return template.format(amount=item.amount, threshold=item.amount - 1)


def _cost_summary(recipe: SynthesisRecipe) -> str:
    return "、".join(f"{item.name}×{item.amount}" for item in recipe.inputs)


def _main_output_itemshows(
    recipes: tuple[SynthesisRecipe, ...],
    indices: dict[str, int],
) -> str:
    """Render target-server output items in the main page's right-hand area."""
    itemshows: list[str] = []
    for slot, recipe in enumerate(recipes):
        column = slot % MAIN_OUTPUT_ITEMSHOW_COLUMNS
        row = slot // MAIN_OUTPUT_ITEMSHOW_COLUMNS
        x = MAIN_OUTPUT_ITEMSHOW_X + column * MAIN_OUTPUT_ITEMSHOW_COLUMN_STEP
        y = MAIN_OUTPUT_ITEMSHOW_Y + row * MAIN_OUTPUT_ITEMSHOW_ROW_STEP
        itemshows.append(f"<ItemShow:{indices[recipe.output_name]}:0:{x}:{y}:1>")
    return "".join(itemshows)


def _compile_npc_script(
    settings: SynthesisSettings,
    recipes: tuple[SynthesisRecipe, ...],
    indices: dict[str, int],
) -> str:
    page_size = settings.page_size
    page_count = (len(recipes) + page_size - 1) // page_size
    recipe_pages: dict[str, int] = {}
    lines = ["[@Main]", "#IF", "#ACT", "GOTO @XY_SYN_PAGE_1", "BREAK", ""]
    for page in range(1, page_count + 1):
        page_recipes = recipes[(page - 1) * page_size:page * page_size]
        lines.extend([f"[@XY_SYN_PAGE_{page}]", "#IF", "#SAY", f"【{settings.title}】第{page}/{page_count}页\\"])
        current_category = ""
        for recipe in page_recipes:
            recipe_pages[recipe.recipe_id] = page
            if recipe.category != current_category:
                lines.append(f"---------- {recipe.category} ----------\\")
                current_category = recipe.category
            lines.append(f"<{recipe.display_name}/@XY_SYN_VIEW_{recipe.recipe_id}>　产出{recipe.output_name}×{recipe.output_amount}\\")
        # Output icons are read from the target server's real StdItems Idx. They
        # are display-only; synthesis remains bound to the named links above.
        lines.append(f"{_main_output_itemshows(page_recipes, indices)}\\")
        navigation: list[str] = []
        if page > 1:
            navigation.append(f"<上一页/@XY_SYN_PAGE_{page - 1}>")
        if page < page_count:
            navigation.append(f"<下一页/@XY_SYN_PAGE_{page + 1}>")
        navigation.append("<关闭/@exit>")
        lines.extend(["　".join(navigation), ""])

    for recipe in recipes:
        return_label = f"@XY_SYN_PAGE_{recipe_pages[recipe.recipe_id]}"
        lines.extend([
            f"[@XY_SYN_VIEW_{recipe.recipe_id}]", "#IF", "#SAY",
            f"【{recipe.display_name}】\\",
            f"产出：{recipe.output_name}×{recipe.output_amount}\\",
            f"所需：{_cost_summary(recipe)}\\",
            f"<ItemShow:{indices[recipe.output_name]}:0:260:-30:1>　<确认合成/@XY_SYN_APPLY_{recipe.recipe_id}>　<返回/{return_label}>　<关闭/@exit>",
            "",
            f"[@XY_SYN_APPLY_{recipe.recipe_id}]", "#IF",
            f"CHECKBAGSIZE {recipe.output_amount}",
        ])
        lines.extend(_cost_check(item) for item in recipe.inputs)
        lines.append("#ACT")
        lines.extend(_cost_action(item) for item in recipe.inputs)
        lines.extend([
            f"GIVE {recipe.output_name} {recipe.output_amount}",
            f"MESSAGEBOX 合成成功，获得{recipe.output_name}×{recipe.output_amount}。",
            f"GOTO @XY_SYN_VIEW_{recipe.recipe_id}", "BREAK", "#ELSEACT",
            "MESSAGEBOX 所需物品或货币不足，或背包空间不足。", "BREAK", "",
        ])
    return "\n".join(lines).rstrip()


def _compile_script(workbook: SynthesisWorkbook, indices: dict[str, int]) -> str:
    """Compatibility wrapper for candidate.1 single-NPC workbooks/tests."""
    return _compile_npc_script(workbook.settings, workbook.recipes, indices)


def _change(root: Path, relative: str, after: bytes, operation: str) -> PlannedChange:
    path = root / Path(relative.replace("/", "\\"))
    before = path.read_bytes() if path.exists() else None
    return PlannedChange(relative, before, after, operation, PACKAGE_ID)


class ItemSynthesisService:
    def __init__(self, platform_root: Path):
        self.root = Path(platform_root).resolve()
        self.default_workbook = documents_root(self.root) / DEFAULT_WORKBOOK
        self.default_npc_config = documents_root(self.root) / DEFAULT_NPC_CONFIG
        self.repository = PackageRepository(self.root / "packages")
        self.repository.refresh()
        self.installer = Installer(self.repository, self.root / "backups")

    def inspect_workbook(self, workbook: Path) -> SynthesisWorkbook:
        return read_item_synthesis_workbook(workbook)

    def preflight(
        self,
        workbook_path: Path,
        server: Path,
        npc_config_path: Path | None = None,
    ) -> ItemSynthesisPlan:
        plan = ItemSynthesisPlan(str(Path(server).absolute()), str(Path(workbook_path).absolute()))
        try:
            workbook = read_item_synthesis_workbook(workbook_path)
            plan.workbook = workbook.path
            plan.workbook_hash = workbook.sha256
            selected_config = Path(npc_config_path).resolve() if npc_config_path else (
                self.default_npc_config if self.default_npc_config.is_file() else None
            )
            npcs, npc_config_hash = read_synthesis_npc_config(selected_config, workbook)
            if selected_config is not None:
                plan.npc_config = str(selected_config)
                plan.npc_config_hash = npc_config_hash
            target = TargetInspector.inspect(Path(server))
            indices = _resolve_names(target.root, workbook)
            mapinfo_path = target.root / Path(MAPINFO.replace("/", "\\"))
            merchant_path = target.root / Path(MERCHANT.replace("/", "\\"))
            if not merchant_path.is_file():
                raise ItemSynthesisError(f"目标服缺少NPC注册表：{merchant_path}")
            mapinfo_doc = read_text_document(mapinfo_path)
            merchant_doc = read_text_document(merchant_path)
            for npc in npcs:
                _map_exists(mapinfo_doc.text, npc.settings.map_code)

            recipe_by_id = {recipe.recipe_id.casefold(): recipe for recipe in workbook.recipes}
            npc_paths = {
                npc.npc_id: (SCRIPT_PATH if npc.npc_id == "LEGACY" else f"{SCRIPT_PATH}/{npc.npc_id}")
                for npc in npcs
            }
            active_paths = {path.casefold() for path in npc_paths.values()}
            # Remove registrations of previously managed synthesis NPCs that
            # are no longer configured.  Foreign rows under the same prefix
            # block instead of being guessed away.
            merchant_lines: list[str] = []
            for line in merchant_doc.text.splitlines():
                fields = line.split("\t")
                if len(fields) < 8:
                    merchant_lines.append(line)
                    continue
                registered_path, map_code, x, y, npc_name = fields[:5]
                registered_key = registered_path.strip().casefold()
                managed_family = registered_key == SCRIPT_PATH.casefold() or registered_key.startswith(SCRIPT_PATH.casefold() + "/")
                if managed_family and registered_key not in active_paths:
                    stale_script = target.envir / "Market_Def" / Path(
                        f"{registered_path}-{map_code}.txt".replace("/", "\\")
                    )
                    if not stale_script.is_file() or f"; XYDP-BEGIN {PACKAGE_ID}" not in read_text_document(stale_script).text:
                        raise ItemSynthesisError(f"发现非受管的历史合成NPC注册，已阻止移除：{registered_path}")
                    continue
                for npc in npcs:
                    own_path = npc_paths[npc.npc_id].casefold()
                    same_place = (
                        map_code.casefold() == npc.settings.map_code.casefold()
                        and x.strip() == str(npc.settings.x)
                        and y.strip() == str(npc.settings.y)
                    )
                    if same_place and registered_key != own_path:
                        raise ItemSynthesisError(f"NPC坐标已被占用：{map_code}({x},{y}) {npc_name}")
                    if npc_name.strip().casefold() == npc.settings.npc_name.casefold() and registered_key != own_path:
                        raise ItemSynthesisError(f"NPC名称已被其他脚本占用：{npc.settings.npc_name}")
                merchant_lines.append(line)
            merchant_text = merchant_doc.newline.join(merchant_lines)
            if merchant_doc.text.endswith(("\n", "\r")) and merchant_text:
                merchant_text += merchant_doc.newline

            changes: list[PlannedChange] = []
            for npc in npcs:
                settings = npc.settings
                script_root = npc_paths[npc.npc_id]
                script_relative = f"Mir200/Envir/Market_Def/{script_root}-{settings.map_code}.txt"
                script_path = target.root / Path(script_relative.replace("/", "\\"))
                if script_path.is_file():
                    script_doc = read_text_document(script_path)
                    if f"; XYDP-BEGIN {PACKAGE_ID}" not in script_doc.text:
                        raise ItemSynthesisError(f"目标合成脚本不是平台受管文件，已阻止覆盖：{script_path}")
                else:
                    script_doc = TextDocument("", "gb18030", "\r\n")
                npc_recipes = tuple(recipe_by_id[recipe_id.casefold()] for recipe_id in npc.recipe_ids)
                script_text = install_managed_block(
                    script_doc.text,
                    PACKAGE_ID,
                    _compile_npc_script(settings, npc_recipes, indices),
                    script_doc.newline,
                ).text
                labels = scan_labels(script_text)
                if labels.duplicates:
                    raise ItemSynthesisError(f"NPC {settings.npc_name}生成脚本存在重复标签：{labels.duplicates}")
                changes.append(_change(
                    target.root,
                    script_relative,
                    encode_text_document(script_doc, script_text),
                    "item-synthesis-script",
                ))
                merchant_line = (
                    f"{script_root}\t{settings.map_code}\t{settings.x}\t{settings.y}"
                    f"\t{settings.npc_name}\t0\t{settings.appearance}\t0"
                )
                merchant_text = set_exclusive_unique_line(
                    merchant_text, merchant_line, [0], merchant_doc.newline
                ).text
            changes.append(_change(
                target.root, MERCHANT, encode_text_document(merchant_doc, merchant_text),
                "item-synthesis-npc-register",
            ))
            plan.changes = [change for change in changes if change.before != change.after]
            recipe_to_npc = {
                recipe_id.casefold(): npc for npc in npcs for recipe_id in npc.recipe_ids
            }
            plan.npcs = [{
                "npc_id": npc.npc_id,
                "npc_name": npc.settings.npc_name,
                "map_code": npc.settings.map_code,
                "x": npc.settings.x,
                "y": npc.settings.y,
                "appearance": npc.settings.appearance,
                "recipe_count": len(npc.recipe_ids),
                "script_path": npc_paths[npc.npc_id],
            } for npc in npcs]
            plan.recipes = [{
                "recipe_id": recipe.recipe_id,
                "npc_id": recipe_to_npc[recipe.recipe_id.casefold()].npc_id,
                "npc_name": recipe_to_npc[recipe.recipe_id.casefold()].settings.npc_name,
                "display_name": recipe.display_name,
                "output": recipe.output_name,
                "output_amount": recipe.output_amount,
                "input_count": len(recipe.inputs),
                "output_idx": indices[recipe.output_name],
            } for recipe in workbook.recipes]
            plan.warnings.extend([
                "所有物品输入和产出均按目标服StdItems唯一名称解析；不会引用其他服务端编号。",
                "每个启用NPC生成独立脚本，只显示35号配置分配给自己的配方；支持同图多NPC和跨地图NPC。",
                "每次点击都会重新检查背包空间、全部物品和原生货币；检查全部通过后才统一扣除。",
                "M2运行时允许写入；新NPC脚本需要由你重载或重启M2后才会生效。",
            ])
            if is_executable_running(target.mir200 / "M2Server.exe"):
                plan.warnings.append("检测到M2Server.exe正在运行：本次只提示，不阻止预检或确认更新。")
            plan.install_plan = InstallPlan(
                target_root=str(target.root), client_root=None,
                package_ids=[PACKAGE_ID], package_versions={PACKAGE_ID: PACKAGE_VERSION},
                parameters={
                    "workbook": workbook.path,
                    "workbook_hash": workbook.sha256,
                    "npc_config": str(selected_config) if selected_config else "legacy-workbook-settings",
                    "npc_config_hash": npc_config_hash,
                    "recipe_count": len(workbook.recipes),
                    "npc_count": len(npcs),
                    "npc_ids": [npc.npc_id for npc in npcs],
                    "output_default_count": 1,
                },
                changes=plan.changes, warnings=list(plan.warnings),
                operation_type=plan.operation, candidate_packages=[PACKAGE_ID],
            )
        except (OSError, ValueError, RuntimeError, sqlite3.Error, TextPatchError) as exc:
            plan.blockers.append(str(exc))
        return plan

    def install(self, plan: ItemSynthesisPlan) -> InstallReceipt:
        if plan.blockers or plan.install_plan is None:
            raise ItemSynthesisError("通用物品合成配置被阻止：\n" + "\n".join(plan.blockers))
        workbook = Path(plan.workbook)
        if not workbook.is_file() or hashlib.sha256(workbook.read_bytes()).hexdigest() != plan.workbook_hash:
            raise ItemSynthesisError("预检后通用物品合成表已变化，请重新预检")
        if plan.npc_config:
            npc_config = Path(plan.npc_config)
            if not npc_config.is_file() or hashlib.sha256(npc_config.read_bytes()).hexdigest() != plan.npc_config_hash:
                raise ItemSynthesisError("预检后合成NPC配置已变化，请重新预检")
        if not plan.changes:
            raise ItemSynthesisError("没有需要应用的变更，目标已处于当前合成配置")
        return self.installer.install(plan.install_plan)

    def rollback(self, server: Path, transaction_id: str) -> str:
        self.installer.rollback(server, transaction_id)
        return transaction_id
