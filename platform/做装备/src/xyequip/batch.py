from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .legacy import xy_batch_equip_maker as legacy_batch
from .legacy import xy_equip_maker as legacy_core
from .paths import EquipmentPaths
from .source import read_equipment_rows
from .target import inspect_target


class BatchSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkbookInspection:
    source: Path
    headers: tuple[str, ...]
    row_count: int


@dataclass(frozen=True)
class CompiledEquipmentRow:
    source_row: int
    name: str
    equipment_text: str
    source_values: tuple[tuple[str, str], ...] = ()
    operation: str = "create"


@dataclass(frozen=True)
class BatchCompileResult:
    source: Path
    workbook_hash: str
    rows: tuple[CompiledEquipmentRow, ...]
    operation: str = "create"
    enforce_create_source: bool = False


class BatchEquipmentService:
    def __init__(self, platform_root: Path):
        self.platform_root = Path(platform_root).resolve()
        self.equipment_root = self.platform_root / "做装备"
        self.output_root = self.equipment_root / "outputs"
        legacy_core.configure_paths(EquipmentPaths.default(self.platform_root))

    def inspect(self, workbook: Path) -> WorkbookInspection:
        workbook = Path(workbook)
        rows = read_equipment_rows(workbook)
        if rows:
            headers = tuple(rows[0].keys())
        elif workbook.suffix.lower() == ".xlsx":
            from .update import _read_xlsx_headers
            headers = tuple(_read_xlsx_headers(workbook))
        else:
            headers = ()
        return WorkbookInspection(workbook, headers, len(rows))

    def compile(self, workbook: Path) -> BatchCompileResult:
        workbook = Path(workbook)
        if not workbook.exists():
            raise BatchSourceError(f"装备源表不存在：{workbook}")
        rows = read_equipment_rows(workbook)
        return self.compile_rows(
            rows,
            workbook,
            hashlib.sha256(workbook.read_bytes()).hexdigest(),
            enforce_create_source=True,
        )

    def compile_mixed(self, workbook: Path, server_root: Path) -> BatchCompileResult:
        """The shared workbook creates missing names and updates existing names."""
        from dataclasses import replace
        workbook = Path(workbook)
        target = inspect_target(server_root)
        with closing(sqlite3.connect(f"file:{target.database.as_posix()}?mode=ro", uri=True)) as connection:
            existing = {str(row[0]) for row in connection.execute("SELECT Name FROM StdItems")}
        rows = read_equipment_rows(workbook)
        digest = hashlib.sha256(workbook.read_bytes()).hexdigest()
        compiled = []
        seen = set()
        for source_row, row in enumerate(rows, start=2):
            name = legacy_batch.row_name(row)
            if not name or name in seen:
                raise BatchSourceError(f"第{source_row}行：名称为空或源表内部重复装备名：{name}")
            seen.add(name)
            try:
                if name in existing:
                    item = self.compile_update_rows([row], workbook, digest).rows[0]
                    item = replace(item, operation="update")
                else:
                    item = self.compile_rows([row], workbook, digest, enforce_create_source=True).rows[0]
            except Exception as exc:
                raise BatchSourceError(f"第{source_row}行 {name}：{exc}") from exc
            compiled.append(replace(item, source_row=source_row))
        if not compiled:
            raise BatchSourceError("装备源表没有数据行")
        return BatchCompileResult(workbook, digest, tuple(compiled), enforce_create_source=True)

    def compile_materials(self, workbook: Path) -> BatchCompileResult:
        from .materials import compile_material_rows

        workbook = Path(workbook)
        if not workbook.exists():
            raise BatchSourceError(f"材料源表不存在：{workbook}")
        return compile_material_rows(
            read_equipment_rows(workbook),
            workbook,
            hashlib.sha256(workbook.read_bytes()).hexdigest(),
        )

    def compile_hints(self, workbook: Path) -> BatchCompileResult:
        workbook = Path(workbook)
        if not workbook.exists():
            raise BatchSourceError(f"装备悬浮分类表不存在：{workbook}")
        return self.compile_hint_rows(
            read_equipment_rows(workbook),
            workbook,
            hashlib.sha256(workbook.read_bytes()).hexdigest(),
        )

    def compile_hint_rows(
        self,
        rows: list[dict[str, str]],
        source: Path,
        workbook_hash: str = "memory",
    ) -> BatchCompileResult:
        from .item_hint import CATEGORY_EFFECT

        compiled: list[CompiledEquipmentRow] = []
        seen: set[str] = set()
        allowed = set(CATEGORY_EFFECT) | {"不处理"}
        for source_row, row in enumerate(rows, start=2):
            name = legacy_batch.row_name(row)
            category = row.get("悬浮分类", "").strip()
            if not name:
                raise BatchSourceError(f"第{source_row}行：名称不能为空")
            if name in seen:
                raise BatchSourceError(f"装备悬浮分类表内部重复装备名：{name}")
            if category not in allowed:
                raise BatchSourceError(
                    f"第{source_row}行 {name}：悬浮分类必须是制式装备、稀有专属、追梦神器或不处理"
                )
            seen.add(name)
            compiled.append(CompiledEquipmentRow(source_row, name, "", tuple(row.items())))
        if not compiled:
            raise BatchSourceError("装备悬浮分类表没有数据行")
        return BatchCompileResult(Path(source), workbook_hash, tuple(compiled), "item_hint_sync")

    def compile_rows(
        self,
        rows: list[dict[str, str]],
        source: Path,
        workbook_hash: str = "memory",
        enforce_create_source: bool = False,
    ) -> BatchCompileResult:
        compiled: list[CompiledEquipmentRow] = []
        seen: set[str] = set()
        for source_row, row in enumerate(rows, start=2):
            name = legacy_batch.row_name(row) or f"第{source_row}行"
            if name in seen:
                raise BatchSourceError(f"源表内部重复装备名：{name}")
            seen.add(name)
            try:
                text = legacy_batch.row_to_equipment_txt(row)
            except Exception as exc:
                raise BatchSourceError(f"第{source_row}行 {name}：{exc}") from exc
            compiled.append(CompiledEquipmentRow(source_row, name, text, tuple(row.items())))
        if not compiled:
            raise BatchSourceError("装备源表没有数据行")
        return BatchCompileResult(
            Path(source),
            workbook_hash,
            tuple(compiled),
            enforce_create_source=enforce_create_source,
        )

    def compile_update(self, workbook: Path) -> BatchCompileResult:
        workbook = Path(workbook)
        if not workbook.exists():
            raise BatchSourceError(f"修改装备源表不存在：{workbook}")
        return self.compile_update_rows(read_equipment_rows(workbook), workbook, hashlib.sha256(workbook.read_bytes()).hexdigest())

    def compile_update_rows(self, rows: list[dict[str, str]], source: Path, workbook_hash: str = "memory") -> BatchCompileResult:
        from .update import EquipmentUpdateError, validate_update_columns

        compiled: list[CompiledEquipmentRow] = []
        seen: set[str] = set()
        for source_row, row in enumerate(rows, start=2):
            try:
                validate_update_columns(row)
            except EquipmentUpdateError as exc:
                raise BatchSourceError(str(exc)) from exc
            name = legacy_batch.row_name(row)
            if name in seen:
                raise BatchSourceError(f"修改装备源表内部重复装备名：{name}")
            seen.add(name)
            compiled.append(CompiledEquipmentRow(source_row, name, "", tuple(row.items())))
        if not compiled:
            raise BatchSourceError("修改装备源表没有数据行")
        return BatchCompileResult(Path(source), workbook_hash, tuple(compiled), "update")

    def export_update_workbook(self, server_root: Path, output: Path) -> None:
        from .update import export_update_workbook
        export_update_workbook(self.platform_root, server_root, output)

    def search_equipment(self, server_root: Path, keyword: str) -> list[dict[str, int | str]]:
        keyword = keyword.strip()
        if not keyword:
            raise BatchSourceError("请输入装备名称或关键词。")
        target = inspect_target(server_root)
        connection = sqlite3.connect(f"file:{target.database.as_posix()}?mode=ro", uri=True)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(StdItems)")}
            select = ["Idx", "Name", "StdMode"]
            if "Looks" in columns:
                select.append("Looks")
            rows = connection.execute(
                f"SELECT {', '.join(select)} FROM StdItems WHERE Name LIKE ? ORDER BY Idx LIMIT 100",
                (f"%{keyword}%",),
            ).fetchall()
        finally:
            connection.close()
        return [
            {"idx": int(row[0]), "name": str(row[1]), "stdmode": int(row[2]), "looks": int(row[3]) if len(row) > 3 and row[3] is not None else 0}
            for row in rows
        ]
