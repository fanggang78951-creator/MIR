from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path

from .batch import BatchCompileResult
from .paths import EquipmentPaths
from .target import EquipmentTarget, EquipmentTargetError, inspect_target
from .legacy import xy_equip_maker as legacy_core
from .item_hint import (
    ItemHintError,
    item_hint_asset_paths,
    preflight_item_hints,
    selections_from_compiled,
)


class EquipmentPreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class EquipmentChange:
    relative_path: str
    kind: str
    before_hash: str | None
    scope: str = "server"


@dataclass
class EquipmentPlan:
    target: EquipmentTarget
    paths: EquipmentPaths
    workbook_hash: str
    equipment_names: list[str]
    compiled: BatchCompileResult
    changes: list[EquipmentChange]
    blockers: list[str]
    warnings: list[str]
    base_templates: dict[str, str]
    operation: str = "create"
    skipped_existing: tuple[str, ...] = ()


def _hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _requires_qmanage(compiled: BatchCompileResult, mode: str) -> bool:
    if mode == "update" or (mode == "create" and any(row.operation == "update" for row in compiled.rows)):
        # 修改任意属性时都要同时读取旧的受管脚本；目标装备可能已经带回血。
        return True
    if mode != "create":
        return False
    registry = legacy_core.load_script_props()
    qmanage_properties = {
        name
        for name, meta in registry.get("properties", {}).items()
        if any(legacy_core.outlet_target(outlet) == "qmanage" for outlet in meta.get("outlets", []))
    }
    return any(
        any(f"{name}=" in row.equipment_text for name in qmanage_properties)
        for row in compiled.rows
    )


def _requires_attribute_panel(compiled: BatchCompileResult) -> bool:
    for row in compiled.rows:
        if any(f"{name}=" in row.equipment_text for name in legacy_core.EXECUTION_PANEL_SPECS):
            return True
        source_values = dict(row.source_values)
        if (row.operation == "update" or compiled.operation == "update") and any(
            name in source_values for name in legacy_core.EXECUTION_PANEL_SPECS
        ):
            # The shared update sheet uses blank cells to clear old values, so an
            # existing item still needs the panel file even when all three new
            # execution values are blank or zero.
            return True
    return False


def _contains_slot(compiled: BatchCompileResult, slot: str) -> bool:
    return any(f"部位={slot}" in row.equipment_text for row in compiled.rows)


class EquipmentPlanner:
    def __init__(self, platform_root: Path):
        self.platform_root = Path(platform_root).resolve()

    def preflight(
        self,
        server_root: Path,
        compiled: BatchCompileResult,
        client_data: Path | None = None,
        mode: str = "create",
    ) -> EquipmentPlan:
        if mode not in {"create", "repair_display", "update", "material_create", "item_hint_sync"}:
            raise EquipmentPreflightError(f"未知装备操作：{mode}")
        try:
            target = inspect_target(server_root)
        except EquipmentTargetError as exc:
            raise EquipmentPreflightError(str(exc)) from exc
        paths = EquipmentPaths.for_target(self.platform_root, target.root, client_data)
        blockers: list[str] = []
        warnings: list[str] = []
        base_templates: dict[str, str] = {}
        skipped_existing: list[str] = []
        updating_names = {row.name for row in compiled.rows if mode == "update" or (mode == "create" and row.operation == "update")}
        update_resources = any(
            row.name in updating_names and (dict(row.source_values).get("来源编号", "").strip()
                                            or dict(row.source_values).get("SourceId", "").strip())
            for row in compiled.rows
        )
        try:
            hint_selections = selections_from_compiled(compiled) if mode in {"create", "item_hint_sync"} else ()
        except ItemHintError as exc:
            hint_selections = ()
            blockers.append(str(exc))
        if mode == "item_hint_sync" and not hint_selections:
            blockers.append("装备悬浮分类表没有可同步项；将需要同步的行改为制式装备、稀有专属或追梦神器")
        needs_qmanage = _requires_qmanage(compiled, mode)
        needs_attribute_panel = _requires_attribute_panel(compiled)
        needs_title_client = mode == "create" and _contains_slot(compiled, legacy_core.TITLE_SCROLL_SLOT)
        if needs_qmanage and not paths.qmanage.is_file():
            blockers.append(f"目标服缺少 QManage：{paths.qmanage}")
        if needs_attribute_panel and not paths.attribute_panel.is_file():
            blockers.append(f"目标服缺少属性图标脚本：{paths.attribute_panel}")
        if target.m2_running:
            warnings.append(
                f"目标服 M2 正在运行：允许生成；若数据库或文件被锁定，事务会安全停止。"
                f"QFunction、ItemDescList 等静态内容需在 M2 重载或重启后生效：{target.m2server}"
            )

        try:
            connection = sqlite3.connect(f"file:{paths.db_path.as_posix()}?mode=ro", uri=True)
            try:
                target_rows = connection.execute(
                    "SELECT Name, COUNT(*), MIN(StdMode), MAX(StdMode) FROM StdItems GROUP BY Name"
                ).fetchall()
                target_names = {str(name) for name, _count, _min_mode, _max_mode in target_rows}
                target_modes = {
                    str(name): (int(count), int(min_mode), int(max_mode))
                    for name, count, min_mode, max_mode in target_rows
                }
                source_names = {row.name for row in compiled.rows}
                if mode == "update":
                    for name in sorted(source_names - target_names):
                        blockers.append(f"目标服不存在，无法修改：{name}")
                elif mode == "item_hint_sync":
                    for name in sorted({item.name for item in hint_selections} - target_names):
                        blockers.append(f"目标服不存在，无法同步装备悬浮：{name}")
                elif mode == "material_create":
                    pending_rows = []
                    for row in compiled.rows:
                        target_mode = target_modes.get(row.name)
                        if target_mode is None:
                            pending_rows.append(row)
                            continue
                        _count, min_mode, max_mode = target_mode
                        if min_mode == max_mode == 46:
                            skipped_existing.append(row.name)
                        else:
                            blockers.append(f"同名物品已存在但不是材料，无法新增材料：{row.name}")
                    compiled = BatchCompileResult(
                        compiled.source,
                        compiled.workbook_hash,
                        tuple(pending_rows),
                        compiled.operation,
                        compiled.enforce_create_source,
                    )
                    if skipped_existing:
                        warnings.append(
                            "目标服已存在的材料将跳过，不覆盖、不重复添加："
                            + "、".join(skipped_existing)
                        )
                for name in (row.name for row in compiled.rows):
                    found = connection.execute("SELECT 1 FROM StdItems WHERE Name=? LIMIT 1", (name,)).fetchone()
                    if mode == "create" and name in updating_names and not found:
                        blockers.append(f"目标服不存在，无法修改：{name}")
                    elif mode == "create" and found and name not in updating_names:
                        blockers.append(f"装备已存在：{name}")
                    elif mode == "repair_display" and not found:
                        blockers.append(f"装备不存在，无法补写 M2 显示：{name}")
            finally:
                connection.close()
        except sqlite3.Error as exc:
            blockers.append(f"无法只读检查 StdItems：{exc}")

        if mode == "create" and compiled.enforce_create_source:
            for row in compiled.rows:
                if row.name not in updating_names and "[图标来源]" not in row.equipment_text:
                    blockers.append(f"{row.name}：新装备必须填写来源编号")

        if mode == "update":
            has_resources = any(
                (dict(row.source_values).get("来源编号", "").strip()
                 or dict(row.source_values).get("SourceId", "").strip())
                for row in compiled.rows
            )
        else:
            has_resources = update_resources or mode in {"create", "material_create"} and any(
                "[图标来源]" in row.equipment_text for row in compiled.rows
            )
        if has_resources and client_data is None:
            label = "材料" if mode == "material_create" else "装备"
            blockers.append(f"源表包含图标资源{label}，必须选择客户端 data 目录")
        elif client_data is not None and not Path(client_data).is_dir():
            blockers.append(f"客户端 data 目录不存在：{client_data}")
        if needs_title_client:
            if client_data is None:
                blockers.append("称号卷必须选择客户端 data 目录，以同步 fenghao.dat")
            elif paths.fenghao_data is None or not paths.fenghao_data.is_file():
                blockers.append(f"称号卷需要客户端称号说明文件：{paths.fenghao_data}")

        client_library_names = (
            legacy_core.MATERIAL_ICON_LIBRARIES
            if mode == "material_create"
            else legacy_core.STATIC_ICON_LIBRARIES
        )
        client_libraries = tuple(
            paths.client_data / f"{library}.{suffix}"
            for library in client_library_names
            for suffix in ("wzl", "wzx")
        ) if paths.client_data is not None else ()
        if has_resources and paths.client_data is not None:
            for path in client_libraries:
                if not path.is_file():
                    label = "材料形态图库" if mode == "material_create" else "装备静态图库"
                    blockers.append(f"{label}缺失：{path}")
        client_resources_ready = not has_resources or (
            bool(client_libraries) and all(path.is_file() for path in client_libraries)
        )

        shared_paths = (paths.item_desc, paths.item_rule, paths.group_item)
        missing_shared = [path for path in shared_paths if not path.exists()]
        if missing_shared and mode in {"create", "update"}:
            warnings.append(
                "目标服缺少装备共享文件，确认生成时将安全创建（纳入事务与回滚）："
                + "、".join(path.name for path in missing_shared)
            )

        if (
            mode != "item_hint_sync"
            and
            not (has_resources and client_data is None)
            and not (needs_title_client and (client_data is None or paths.fenghao_data is None or not paths.fenghao_data.is_file()))
            and client_resources_ready
            and not (needs_qmanage and not paths.qmanage.is_file())
            and not (needs_attribute_panel and not paths.attribute_panel.is_file())
        ):
            previous_paths = legacy_core._PATHS
            try:
                with tempfile.TemporaryDirectory() as directory:
                    sandbox_root = Path(directory) / "server"
                    sandbox_client = Path(directory) / "client" if (has_resources or needs_title_client) else client_data
                    sandbox_paths = EquipmentPaths.for_target(self.platform_root, sandbox_root, sandbox_client)
                    server_copies = [(paths.db_path, sandbox_paths.db_path)]
                    if mode != "material_create":
                        server_copies.append((paths.qfunction, sandbox_paths.qfunction))
                    if needs_qmanage:
                        server_copies.append((paths.qmanage, sandbox_paths.qmanage))
                    if needs_attribute_panel:
                        server_copies.append((paths.attribute_panel, sandbox_paths.attribute_panel))
                    for source, destination in server_copies:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
                    if has_resources:
                        for source in client_libraries:
                            destination = sandbox_client / source.name
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, destination)
                    if needs_title_client and paths.fenghao_data is not None:
                        destination = sandbox_paths.fenghao_data
                        assert destination is not None
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(paths.fenghao_data, destination)
                    if mode != "material_create":
                        for source, destination in zip(shared_paths, (
                            sandbox_paths.item_desc, sandbox_paths.item_rule, sandbox_paths.group_item
                        )):
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            if source.exists():
                                shutil.copy2(source, destination)
                            else:
                                destination.write_bytes(b"")
                    legacy_core.configure_paths(sandbox_paths)
                    specs_dir = Path(directory) / "specs"
                    specs_dir.mkdir()
                    update_icon_cache: dict[int, int] = {}
                    for row in compiled.rows:
                        spec_path = specs_dir / f"{legacy_core.safe_filename(row.name)}.txt"
                        spec_path.write_text(row.equipment_text, encoding="utf-8")
                        try:
                            if mode == "create" and row.name not in updating_names:
                                legacy_core.check_equipment(spec_path)
                            elif mode == "material_create":
                                legacy_core.check_material(spec_path)
                            elif mode == "update" or (mode == "create" and row.name in updating_names):
                                from .update import update_equipment_row
                                update_equipment_row(
                                    dict(row.source_values),
                                    spec_path,
                                    icon_cache=update_icon_cache,
                                )
                            else:
                                selected_spec = legacy_core.parse_spec(spec_path)
                                legacy_core.validate_template_exists(selected_spec)
                                legacy_core.build_qfunction_text(
                                    selected_spec,
                                    legacy_core.load_script_props(),
                                    allow_existing_effect_branch=True,
                                )
                            if mode in {"create", "material_create"} and row.name not in updating_names:
                                selected_spec = legacy_core.parse_spec(spec_path)
                                legacy_core.validate_template_exists(selected_spec)
                                base_templates[row.name] = selected_spec.base_template_label or selected_spec.template
                        except Exception as exc:
                            error_text = str(exc)
                            if has_resources and paths.client_data is not None:
                                error_text = error_text.replace(
                                    str(sandbox_paths.client_data),
                                    str(paths.client_data),
                                )
                            message = f"{row.name}：{error_text}"
                            if message not in blockers:
                                blockers.append(message)
            finally:
                legacy_core.configure_paths(previous_paths)

        if hint_selections:
            hint_blockers, hint_warnings = preflight_item_hints(
                paths,
                hint_selections,
                descriptions_will_be_created=mode == "create",
            )
            blockers.extend(item for item in hint_blockers if item not in blockers)
            warnings.extend(item for item in hint_warnings if item not in warnings)

        if mode == "material_create":
            if compiled.rows:
                changes = [
                    EquipmentChange(
                        paths.db_path.relative_to(target.root).as_posix(),
                        "replace",
                        _hash(paths.db_path),
                    )
                ] + [
                    EquipmentChange(path.name, "replace", _hash(path), "client")
                    for path in client_libraries
                ]
            else:
                changes = []
                warnings.append("源表中的材料均已存在，本次没有需要生成的材料。")
            warnings.append(
                "材料固定写入 StdMode=46、OverLap=2、DuraMax=99999；"
                "只改 StdItems 与 Items 背包图库；材料不读取、不检查、不修改 DnItems 或 StateItem，"
                "不接入装备属性脚本。"
            )
        elif mode == "item_hint_sync":
            affected = (paths.item_desc, paths.effect_hint_items, paths.effect_hint_definitions)
            changes = [
                EquipmentChange(
                    path.relative_to(target.root).as_posix(),
                    "replace" if path.exists() else "create",
                    _hash(path),
                )
                for path in affected
            ]
            if paths.client_data is not None:
                for asset in item_hint_asset_paths(self.platform_root):
                    destination = paths.client_data / asset.name
                    if not destination.exists():
                        changes.append(EquipmentChange(asset.name, "create", None, "client"))
        else:
            affected = list((
                paths.db_path,
                paths.item_desc,
                paths.item_rule,
                paths.group_item,
                paths.qfunction,
            ) if mode in {"create", "update"} else (paths.qfunction,))
            if needs_qmanage:
                affected.append(paths.qmanage)
            if needs_attribute_panel:
                affected.append(paths.attribute_panel)
            changes = [
                EquipmentChange(
                    path.relative_to(target.root).as_posix(),
                    "replace" if path.exists() else "create",
                    _hash(path),
                )
                for path in affected
            ]
            if hint_selections:
                known = {(change.scope, change.relative_path) for change in changes}
                for path in (paths.effect_hint_items, paths.effect_hint_definitions):
                    relative = path.relative_to(target.root).as_posix()
                    if ("server", relative) not in known:
                        changes.append(EquipmentChange(
                            relative,
                            "replace" if path.exists() else "create",
                            _hash(path),
                        ))
                if paths.client_data is not None:
                    for asset in item_hint_asset_paths(self.platform_root):
                        destination = paths.client_data / asset.name
                        if not destination.exists():
                            changes.append(EquipmentChange(asset.name, "create", None, "client"))
            if needs_title_client and paths.fenghao_data is not None:
                known = {(change.scope, change.relative_path) for change in changes}
                if ("client", paths.fenghao_data.name) not in known:
                    changes.append(EquipmentChange(
                        paths.fenghao_data.name,
                        "replace",
                        _hash(paths.fenghao_data),
                        "client",
                    ))
            if mode in {"create", "update"}:
                if mode == "create" and has_resources:
                    warnings.append(
                        "新建装备直接复用来源编号作为 Looks；仍校验 Items/StateItem/DnItems "
                        "三套同号图片，但不复制、不修改客户端 WZL/WZX。"
                    )
                if update_resources:
                    warnings.append(
                        "修改装备直接复用来源编号作为 Looks；校验 Items/StateItem/DnItems "
                        "三套同号图片，但不复制、不修改客户端 WZL/WZX。"
                    )
                if _contains_slot(compiled, legacy_core.BACKPACK_ARTIFACT_SLOT):
                    warnings.append("背包神器按 StdMode=41 生成，只在背包持有时通过 CHECKITEM 计算脚本属性。")
                if needs_title_client:
                    warnings.append("称号卷将同时生成 StdMode=31 卷轴、StdMode=70 称号并同步 fenghao.dat。")
                if any(
                    not any(f"部位={slot}" in row.equipment_text for slot in legacy_core.SPECIAL_SCRIPT_SLOTS)
                    for row in compiled.rows
                ):
                    warnings.append(
                        "普通可穿戴装备持久固定写入 DuraMax=60000；源表中的旧持久列即使存在也会被忽略。"
                    )
        if mode == "create" and updating_names:
            warnings.append(f"同表处理：新增 {len(compiled.rows) - len(updating_names)} 件，修改 {len(updating_names)} 件；已有装备可编辑属性空白按最终快照清零，来源编号空白保留外观。")
            warnings.extend(f"{'修改' if row.name in updating_names else '新增'}：第{row.source_row}行 {row.name}" for row in compiled.rows)
        return EquipmentPlan(
            target=target,
            paths=paths,
            workbook_hash=compiled.workbook_hash,
            equipment_names=[row.name for row in compiled.rows],
            compiled=compiled,
            changes=changes,
            blockers=blockers,
            warnings=warnings,
            base_templates=base_templates,
            operation=mode,
            skipped_existing=tuple(skipped_existing),
        )
