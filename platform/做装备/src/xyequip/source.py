from __future__ import annotations

from pathlib import Path

from .legacy.xy_batch_equip_maker import read_table_rows


def read_equipment_rows(path: Path) -> list[dict[str, str]]:
    path = Path(path)
    if path.suffix.lower() not in {".xlsx", ".csv", ".txt"}:
        raise ValueError(f"不支持的装备源表格式：{path.suffix}")
    return read_table_rows(path)
