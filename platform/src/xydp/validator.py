from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

from .manifest import ManifestError, PackageManifest
from .sqlitepatch import (
    SqlitePatchError,
    validate_sqlite_magic_skill_update_operation,
    validate_sqlite_upsert_operation,
)


class PackageValidationError(RuntimeError):
    pass


ALLOWED_OPERATIONS = {"managed_block", "ensure_event_label", "ensure_callable_label", "event_hook", "remove_event_hook", "managed_anchor_hook", "unique_line", "exclusive_unique_line", "indexed_text_line", "mapinfo_flag", "mapinfo_title", "render", "config_merge", "config_set", "copy", "binary_copy", "copy_tree", "transcode_copy", "sqlite_upsert", "sqlite_magic_skill_update"}
ALLOWED_CHECKS = {"file_exists", "file_missing", "sha256", "encoding", "text_contains", "text_not_contains", "reference_exists", "label_exists", "label_available", "indexed_text_line_equals", "tree_token_available"}
FORBIDDEN_SUFFIXES = {".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".py", ".pyw"}


def _relative(value: str, label: str) -> None:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise PackageValidationError(f"{label}路径越界: {value}")


def _validate_event_hook(operation: dict) -> None:
    label = str(operation.get("label", "")).strip()
    if not label:
        raise PackageValidationError("event_hook 缺少 label")
    content = str(operation.get("content", ""))
    if not content.strip():
        raise PackageValidationError(f"event_hook 内容为空: {label}")

    section = ""
    for line_number, raw_line in enumerate(content.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("#"):
            section = line.split(maxsplit=1)[0].upper()
            continue
        if line.upper().startswith("DELAYGOTO ") and section not in {"#ACT", "#ELSEACT"}:
            raise PackageValidationError(
                f"event_hook 的 DELAYGOTO 必须位于 #ACT/#ELSEACT: {label} 第{line_number}行"
            )


def validate_package(package_dir: Path) -> PackageManifest:
    package_dir = Path(package_dir).resolve()
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.is_file():
        raise PackageValidationError("缺少 manifest.json")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = PackageManifest.from_dict(data, manifest_path)
    except (json.JSONDecodeError, ManifestError) as exc:
        raise PackageValidationError(str(exc)) from exc
    for path in package_dir.rglob("*"):
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        if path.is_symlink() or os.path.islink(path) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise PackageValidationError(f"成果包禁止路径链接: {path.name}")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise PackageValidationError(f"成果包禁止携带可执行文件: {path.name}")
    for operation in manifest.operations:
        operation_type = operation.get("type")
        if operation_type not in ALLOWED_OPERATIONS:
            raise PackageValidationError(f"不支持的操作类型: {operation_type}")
        if "target" not in operation:
            raise PackageValidationError(f"操作缺少 target: {operation_type}")
        _relative(str(operation["target"]), "目标")
        if operation.get("scope", "server") not in {"server", "client"}:
            raise PackageValidationError(f"操作 scope 无效: {operation.get('scope')}")
        if "preserve_existing" in operation:
            if operation_type not in {"render", "copy", "binary_copy", "copy_tree"}:
                raise PackageValidationError(f"{operation_type} 不支持 preserve_existing")
            if not isinstance(operation["preserve_existing"], bool):
                raise PackageValidationError("preserve_existing 必须是布尔值")
        if "strict_existing" in operation:
            if operation_type != "transcode_copy":
                raise PackageValidationError(f"{operation_type} 不支持 strict_existing")
            if not isinstance(operation["strict_existing"], bool):
                raise PackageValidationError("strict_existing 必须是布尔值")
        if operation_type in {"render", "config_merge", "copy", "binary_copy", "copy_tree", "transcode_copy"}:
            source = str(operation.get("source", ""))
            _relative(source, "源")
            source_path = package_dir.joinpath(*PurePosixPath(source).parts)
            if not source_path.exists():
                raise PackageValidationError(f"源文件不存在: {source}")
        if "user_document" in operation:
            if operation_type not in {"render", "config_merge", "copy", "binary_copy", "transcode_copy"}:
                raise PackageValidationError(f"{operation_type} 不支持 user_document")
            user_document = PurePosixPath(str(operation["user_document"]))
            if user_document.is_absolute() or len(user_document.parts) != 1 or user_document.name in {"", ".", ".."}:
                raise PackageValidationError("user_document 必须是汇总目录中的单个文件名")
        if operation_type == "sqlite_upsert":
            try:
                validate_sqlite_upsert_operation(operation)
            except SqlitePatchError as exc:
                raise PackageValidationError(str(exc)) from exc
        if operation_type == "sqlite_magic_skill_update":
            try:
                validate_sqlite_magic_skill_update_operation(operation)
            except SqlitePatchError as exc:
                raise PackageValidationError(str(exc)) from exc
        if operation_type == "managed_anchor_hook":
            if not str(operation.get("anchor", "")).strip():
                raise PackageValidationError("managed_anchor_hook 缺少 anchor")
            if "content" not in operation:
                raise PackageValidationError("managed_anchor_hook 缺少 content")
        if operation_type == "indexed_text_line":
            line_number = operation.get("line_number")
            if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number < 1:
                raise PackageValidationError("indexed_text_line line_number 必须是正整数")
            if not str(operation.get("content", "")).strip():
                raise PackageValidationError("indexed_text_line 缺少 content")
        if "accepted_current_hashes" in operation:
            if operation_type not in {"managed_block", "remove_event_hook"}:
                raise PackageValidationError(
                    "accepted_current_hashes 仅允许用于 managed_block、remove_event_hook"
                )
            accepted = operation["accepted_current_hashes"]
            if not isinstance(accepted, list) or not accepted or len(accepted) > 8:
                raise PackageValidationError("accepted_current_hashes 必须是1至8个哈希的数组")
            if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value) for value in accepted):
                raise PackageValidationError("accepted_current_hashes 包含无效SHA256")
            if len({value.lower() for value in accepted}) != len(accepted):
                raise PackageValidationError("accepted_current_hashes 不得重复")
        if "legacy_package_ids" in operation:
            if operation_type not in {"managed_block", "event_hook", "managed_anchor_hook"}:
                raise PackageValidationError(
                    "legacy_package_ids 仅允许用于 managed_block、event_hook、managed_anchor_hook"
                )
            legacy_ids = operation["legacy_package_ids"]
            if not isinstance(legacy_ids, list) or not legacy_ids or len(legacy_ids) > 8:
                raise PackageValidationError("legacy_package_ids 必须是1至8个包ID的数组")
            if any(not isinstance(value, str) or not value.startswith("xy.") for value in legacy_ids):
                raise PackageValidationError("legacy_package_ids 包含无效包ID")
            if len(set(legacy_ids)) != len(legacy_ids):
                raise PackageValidationError("legacy_package_ids 不得重复")
            if manifest.id in legacy_ids:
                raise PackageValidationError("legacy_package_ids 不得包含当前包ID")
        if "retired_equipment_anchors" in operation:
            if operation_type != "managed_block":
                raise PackageValidationError(
                    "retired_equipment_anchors 仅允许用于 managed_block"
                )
            retired_anchors = operation["retired_equipment_anchors"]
            if not isinstance(retired_anchors, list) or not retired_anchors or len(retired_anchors) > 8:
                raise PackageValidationError(
                    "retired_equipment_anchors 必须是1至8个锚点名的数组"
                )
            if any(
                not isinstance(value, str)
                or not re.fullmatch(r"XY_EQUIP_MAKER_[A-Za-z0-9_]+_ANCHOR", value)
                for value in retired_anchors
            ):
                raise PackageValidationError("retired_equipment_anchors 包含无效锚点")
            if len(set(retired_anchors)) != len(retired_anchors):
                raise PackageValidationError("retired_equipment_anchors 不得重复")
        if operation_type == "event_hook":
            _validate_event_hook(operation)
        if operation_type == "remove_event_hook":
            label = str(operation.get("label", "")).strip()
            if not label:
                raise PackageValidationError("remove_event_hook 缺少 label")
            if "content" in operation:
                raise PackageValidationError("remove_event_hook 不允许 content")
            owner_package_id = str(operation.get("owner_package_id", manifest.id))
            if not owner_package_id.startswith("xy."):
                raise PackageValidationError("remove_event_hook owner_package_id 无效")
            if "accepted_current_hashes" not in operation:
                raise PackageValidationError("remove_event_hook 必须声明 accepted_current_hashes")
        if operation_type == "mapinfo_flag":
            map_id = str(operation.get("map_id", "")).strip()
            flag = str(operation.get("flag", "")).strip()
            if not map_id or not flag:
                raise PackageValidationError("mapinfo_flag 缺少 map_id 或 flag")
            if operation.get("target") != "Mir200/Envir/MapInfo.txt":
                raise PackageValidationError("mapinfo_flag 仅允许修改 Mir200/Envir/MapInfo.txt")
        if operation_type == "mapinfo_title":
            map_id = str(operation.get("map_id", "")).strip()
            display_name = str(operation.get("display_name", "")).strip()
            if not map_id or not display_name:
                raise PackageValidationError("mapinfo_title 缺少 map_id 或 display_name")
            if len(display_name) > 80 or any(char in display_name for char in "[]\r\n\t"):
                raise PackageValidationError("mapinfo_title display_name 无效")
            if operation.get("target") != "Mir200/Envir/MapInfo.txt":
                raise PackageValidationError("mapinfo_title 仅允许修改 Mir200/Envir/MapInfo.txt")
        if operation_type == "config_set":
            values = operation.get("values")
            if not isinstance(values, dict) or not values:
                raise PackageValidationError("config_set values 必须是非空对象")
            for key, value in values.items():
                if not isinstance(key, str) or not key.strip() or "=" in key:
                    raise PackageValidationError("config_set 配置键无效")
                if not isinstance(value, (str, int, float, bool)):
                    raise PackageValidationError(f"config_set 配置值无效: {key}")
    for check in (*manifest.preflight_checks, *manifest.post_checks):
        if check.get("type") not in ALLOWED_CHECKS:
            raise PackageValidationError(f"不支持的检查类型: {check.get('type')}")
        _relative(str(check.get("path", "")), "检查")
        if check.get("type") == "indexed_text_line_equals":
            line_number = check.get("line_number")
            if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number < 1:
                raise PackageValidationError("indexed_text_line_equals line_number 必须是正整数")
            if not str(check.get("text", "")).strip():
                raise PackageValidationError("indexed_text_line_equals 缺少 text")
        if check.get("type") == "tree_token_available":
            if not str(check.get("token", "")).strip():
                raise PackageValidationError("tree_token_available 缺少 token")
            allowed_paths = check.get("allowed_paths", [])
            if not isinstance(allowed_paths, list):
                raise PackageValidationError("tree_token_available allowed_paths 必须是数组")
            for allowed_path in allowed_paths:
                _relative(str(allowed_path), "允许路径")
    if manifest.status == "verified" and not manifest.evidence:
        raise PackageValidationError("verified 成果包必须声明 evidence")
    return manifest
