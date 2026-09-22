from __future__ import annotations

from pathlib import Path

from .batch import BatchCompileResult, BatchSourceError, CompiledEquipmentRow
from .legacy import xy_batch_equip_maker as legacy_batch


MATERIAL_STD_MODE = 46
MATERIAL_OVERLAP = 2
MATERIAL_MAX_STACK = 99999
MATERIAL_DEFAULT_WEIGHT = 1
MATERIAL_DEFAULT_PRICE = 0
MATERIAL_DEFAULT_COLOR = 251


def _clean(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _integer(
    row: dict[str, str],
    keys: tuple[str, ...],
    default: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    raw = _clean(row, *keys)
    if not raw:
        return default
    try:
        value = int(float(raw))
    except ValueError as exc:
        raise BatchSourceError(f"{label}必须是整数：{raw}") from exc
    if value < minimum or value > maximum:
        raise BatchSourceError(f"{label}必须在 {minimum}-{maximum} 之间：{value}")
    return value


def material_row_to_text(row: dict[str, str]) -> tuple[str, str]:
    name = _clean(row, "名称", "材料名")
    if not name:
        raise BatchSourceError("材料行缺少名称。")
    if not _clean(row, "来源编号", "SourceId"):
        raise BatchSourceError("材料必须填写来源编号。")
    source_id = _integer(row, ("来源编号", "SourceId"), 0, 0, 2_147_483_647, "来源编号")
    weight = _integer(row, ("重量", "Weight"), MATERIAL_DEFAULT_WEIGHT, 0, 255, "重量")
    price = _integer(row, ("价格", "Price"), MATERIAL_DEFAULT_PRICE, 0, 2_147_483_647, "价格")
    color = _integer(row, ("颜色", "Color"), MATERIAL_DEFAULT_COLOR, 0, 255, "颜色")
    text = (
        "[装备]\n"
        f"名称={name}\n"
        "部位=材料\n"
        f"StdMode={MATERIAL_STD_MODE}\n"
        "Shape=1\n"
        f"Weight={weight}\n"
        "Anicount=0\n"
        "Source=0\n"
        "Reserved=0\n"
        f"DuraMax={MATERIAL_MAX_STACK}\n"
        "Need=0\n"
        "NeedLevel=0\n"
        f"Price={price}\n"
        "Stock=5\n"
        f"Color={color}\n"
        f"OverLap={MATERIAL_OVERLAP}\n"
        "\n[图标来源]\n"
        f"来源编号={source_id}\n"
    )
    return name, text


def compile_material_rows(
    rows: list[dict[str, str]],
    source: Path,
    workbook_hash: str,
) -> BatchCompileResult:
    compiled: list[CompiledEquipmentRow] = []
    seen: set[str] = set()
    for source_row, row in enumerate(rows, start=2):
        try:
            name, text = material_row_to_text(row)
        except BatchSourceError as exc:
            label = legacy_batch.row_name(row) or _clean(row, "材料名") or f"第{source_row}行"
            raise BatchSourceError(f"第{source_row}行 {label}：{exc}") from exc
        if name in seen:
            raise BatchSourceError(f"材料源表内部重复名称：{name}")
        seen.add(name)
        compiled.append(CompiledEquipmentRow(source_row, name, text, tuple(row.items())))
    if not compiled:
        raise BatchSourceError("材料源表没有数据行")
    return BatchCompileResult(Path(source), workbook_hash, tuple(compiled), "material_create")
