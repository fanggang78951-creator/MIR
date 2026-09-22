from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .attribute_panel import AttributePanelError, compile_attribute_panel
from .configpatch import ConfigPatchError, merge_config_text, set_flat_config_values
from .encoding import TextDocument, encode_text_document, read_text_document
from .manifest import PackageManifest
from .repository import PackageRepository
from .sqlitepatch import SqlitePatchError, apply_sqlite_magic_skill_update, apply_sqlite_upsert
from .target import TargetInfo, TargetInspector, is_executable_running
from .user_documents import package_operation_source
from .textpatch import (
    TextPatchError,
    add_unique_line,
    ensure_event_label,
    ensure_callable_label,
    ensure_mapinfo_flag,
    install_event_hook,
    install_managed_anchor_hook,
    install_managed_block,
    remove_event_hook,
    scan_labels,
    set_indexed_text_line,
    set_exclusive_unique_line,
    set_mapinfo_display_name,
)


class InstallError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_target(root: Path, relative: str) -> Path:
    candidate = (root / Path(relative.replace("/", os.sep))).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise InstallError(f"目标路径越界: {relative}") from exc
    return candidate


class _StrictFormat(dict):
    def __missing__(self, key: str):
        raise InstallError(f"缺少参数: {key}")


def _render(value: str, params: dict[str, Any]) -> str:
    return value.format_map(_StrictFormat(params))


@dataclass
class PlannedChange:
    relative_path: str
    before: bytes | None
    after: bytes
    operation: str
    package_id: str
    scope: str = "server"


@dataclass
class InstallPlan:
    target_root: str
    client_root: str | None
    package_ids: list[str]
    package_versions: dict[str, str]
    parameters: dict[str, Any]
    changes: list[PlannedChange]
    warnings: list[str] = field(default_factory=list)
    operation_type: str = "package-install"
    candidate_packages: list[str] = field(default_factory=list)
    superseded_package_ids: list[str] = field(default_factory=list)
    launcher_root: str | None = None


@dataclass
class InstallReceipt:
    transaction_id: str
    target_root: str
    client_root: str | None
    packages: dict[str, str]
    parameters: dict[str, Any]
    changes: list[dict[str, Any]]
    backup_root: str
    created_at: str
    operation_type: str = "package-install"
    candidate_packages: list[str] = field(default_factory=list)
    superseded_package_ids: list[str] = field(default_factory=list)
    launcher_root: str | None = None


class Installer:
    def __init__(self, repository: PackageRepository, backups_root: Path):
        self.repository = repository
        self.backups_root = Path(backups_root)

    def _effective_parameters(self, packages: list[PackageManifest], params: dict[str, Any]) -> dict[str, Any]:
        effective: dict[str, Any] = {}
        specs: dict[str, dict[str, Any]] = {}
        for package in packages:
            for name, spec in package.parameters.items():
                if name in specs and specs[name].get("default") != spec.get("default"):
                    raise InstallError(f"成果包参数默认值冲突: {name}")
                specs[name] = spec
                if "default" in spec:
                    effective[name] = spec["default"]
        effective.update(params)
        for name, spec in specs.items():
            if spec.get("required") and (name not in effective or effective[name] in (None, "")):
                    raise InstallError(f"缺少必填参数: {name}")
            if name not in effective:
                continue
            value = effective[name]
            expected = spec.get("type", "string")
            if expected == "integer":
                try:
                    effective[name] = int(value)
                except (TypeError, ValueError) as exc:
                    raise InstallError(f"参数必须是整数: {name}") from exc
            elif expected == "boolean" and not isinstance(value, bool):
                if str(value).lower() in {"true", "1", "yes"}: effective[name] = True
                elif str(value).lower() in {"false", "0", "no"}: effective[name] = False
                else: raise InstallError(f"参数必须是布尔值: {name}")
            elif expected == "string":
                effective[name] = str(value)
            elif expected == "attribute_panel":
                try:
                    effective[name] = compile_attribute_panel(value).normalized
                except AttributePanelError as exc:
                    raise InstallError(f"属性面板参数无效: {name}: {exc}") from exc
            choices = spec.get("choices")
            if choices and effective[name] not in choices:
                raise InstallError(f"参数不在允许范围: {name}")
        return effective

    def _render_parameters(
        self, packages: list[PackageManifest], effective: dict[str, Any]
    ) -> dict[str, Any]:
        rendered = dict(effective)
        for package in packages:
            for name, spec in package.parameters.items():
                if spec.get("type") != "attribute_panel" or name not in effective:
                    continue
                compiled = compile_attribute_panel(effective[name])
                rendered[f"{name}_setup"] = compiled.setup
                rendered[f"{name}_tooltip"] = compiled.tooltip
        return rendered

    def preflight(
        self,
        target_root: Path,
        requested: list[str],
        params: dict[str, Any],
        client_root: Path | None = None,
        operation_type: str = "package-install",
    ) -> InstallPlan:
        if "xy.optional.equipment-wash-opening" in requested:
            raise InstallError("装备洗练使用统一equipment-wash-import核心；请在脚本配置同步选择洗练属性.txt，禁止普通包回写旧payload")
        target = TargetInspector.inspect(target_root)
        client = Path(client_root).absolute() if client_root else None
        if client is not None and not client.is_dir():
            raise InstallError(f"客户端根目录不存在: {client}")
        roots = {"server": target.root, "client": client}
        if is_executable_running(target.mir200 / "M2Server.exe"):
            raise InstallError("目标服务端 M2Server.exe 正在运行，请先手动停止")
        packages = self.repository.resolve(requested)
        specialized = [package for package in packages if package.install_route != "generic"]
        if specialized:
            routes = "、".join(
                f"{package.display_name}→{package.install_route}"
                for package in specialized
            )
            raise InstallError(f"配置型成果包必须使用对应专项页面安装：{routes}")
        effective_params = self._effective_parameters(packages, params)
        render_params = self._render_parameters(packages, effective_params)
        qfunction = target.envir / "Market_Def" / "QFunction-0.txt"
        qfunction_text = ""
        if qfunction.exists():
            qfunction_text = read_text_document(qfunction).text
            duplicates = scan_labels(qfunction_text).duplicates
            if duplicates:
                detail = ", ".join(f"{name}:{lines}" for name, lines in duplicates.items())
                raise InstallError(f"目标脚本存在重复标签，禁止安装: {detail}")
        self._check_claims(packages, qfunction_text)
        for package in packages:
            self._run_checks(roots, package.preflight_checks, render_params, {})
        staged: dict[tuple[str, str], bytes | None] = {}
        changes: dict[tuple[str, str], PlannedChange] = {}
        for package in packages:
            if package.status == "deprecated":
                raise InstallError(f"成果包已弃用: {package.id}")
            for operation in package.operations:
                scope = str(operation.get("scope", "server"))
                scope_root = roots.get(scope)
                if scope not in roots:
                    raise InstallError(f"操作作用域无效: {scope}")
                if scope_root is None:
                    raise InstallError(f"成果包 {package.id} 需要客户端根目录")
                target_prefix = _render(str(operation["target"]), render_params).replace("\\", "/").rstrip("/")
                expanded = self._expand_operation(package, operation, target_prefix)
                for relative, concrete_operation in expanded:
                    key = (scope, relative)
                    path = _safe_target(scope_root, relative)
                    before = staged.get(key, path.read_bytes() if path.exists() else None)
                    after = self._apply_operation(package, concrete_operation, before, render_params)
                    staged[key] = after
                    original = changes[key].before if key in changes else (path.read_bytes() if path.exists() else None)
                    changes[key] = PlannedChange(relative, original, after, str(operation["type"]), package.id, scope)
        for package in packages:
            self._run_checks(roots, package.post_checks, render_params, staged)
        real_changes = [change for change in changes.values() if change.before != change.after]
        superseded_package_ids = list(dict.fromkeys(
            str(legacy_id)
            for package in packages
            for operation in package.operations
            for legacy_id in operation.get("legacy_package_ids", [])
        ))
        return InstallPlan(
            target_root=str(target.root),
            client_root=str(client) if client else None,
            package_ids=[package.id for package in packages],
            package_versions={package.id: package.version for package in packages},
            parameters=effective_params,
            changes=real_changes,
            operation_type=operation_type,
            candidate_packages=[package.id for package in packages if package.status == "candidate"],
            superseded_package_ids=superseded_package_ids,
        )

    def _expand_operation(
        self,
        package: PackageManifest,
        operation: dict[str, Any],
        target_prefix: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        if operation["type"] != "copy_tree":
            return [(target_prefix, operation)]
        source_root = (package.root / operation["source"]).resolve()
        try:
            source_root.relative_to(package.root.resolve())
        except ValueError as exc:
            raise InstallError(f"包内源路径越界: {source_root}") from exc
        if not source_root.is_dir():
            raise InstallError(f"包内源目录不存在: {source_root}")
        result = []
        for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
            relative_source = source.relative_to(package.root.resolve()).as_posix()
            suffix = source.relative_to(source_root).as_posix()
            target = f"{target_prefix}/{suffix}" if target_prefix else suffix
            concrete = dict(operation)
            concrete["type"] = "copy"
            concrete["source"] = relative_source
            result.append((target, concrete))
        return result

    def _check_claims(self, packages: list[PackageManifest], qfunction_text: str) -> None:
        owners: dict[tuple[str, str], str] = {}
        labels = scan_labels(qfunction_text).labels
        for package in packages:
            recognized_package_ids = [package.id]
            recognized_package_ids.extend(
                str(legacy_id)
                for operation in package.operations
                for legacy_id in operation.get("legacy_package_ids", [])
            )
            owned_marker = any(
                re.search(
                    rf"^; XYDP-(?:HOOK-|ANCHOR-HOOK-)?BEGIN {re.escape(package_id)}(?:\s|$)",
                    qfunction_text,
                    re.MULTILINE,
                )
                for package_id in dict.fromkeys(recognized_package_ids)
            )
            for kind in ("labels", "variables", "maps", "npcs"):
                for raw in package.claims.get(kind, []):
                    claim = str(raw)
                    key = (kind, claim.lower())
                    if key in owners and owners[key] != package.id:
                        raise InstallError(f"成果包占用冲突: {kind}/{claim} ({owners[key]} 与 {package.id})")
                    owners[key] = package.id
                    if owned_marker:
                        continue
                    if kind == "labels" and claim.lower().removeprefix("@") in labels:
                        raise InstallError(f"标签占用冲突: {claim}")
                    if kind == "variables" and re.search(rf"(?<![\w$]){re.escape(claim)}(?![\w$])", qfunction_text, re.IGNORECASE):
                        raise InstallError(f"变量占用冲突: {claim}")

    def _run_checks(
        self,
        roots: dict[str, Path | None],
        checks: tuple[dict[str, Any], ...],
        params: dict[str, Any],
        staged: dict[tuple[str, str], bytes | None],
    ) -> None:
        for check in checks:
            check_type = check["type"]
            scope = str(check.get("scope", "server"))
            target_root = roots.get(scope)
            if target_root is None:
                raise InstallError(f"检查需要客户端根目录: {check.get('path', '')}")
            relative = _render(str(check["path"]), params).replace("\\", "/")
            path = _safe_target(target_root, relative)
            if check_type == "tree_token_available":
                if not path.is_dir():
                    raise InstallError(f"检查失败，目录不存在: {relative}")
                token = _render(str(check["token"]), params)
                pattern = re.compile(
                    rf"(?<![\w$]){re.escape(token)}(?![\w$])",
                    re.IGNORECASE,
                )
                allowed = {
                    _render(str(value), params).replace("\\", "/").lower()
                    for value in check.get("allowed_paths", [])
                }
                for candidate in sorted(path.rglob("*.txt")):
                    candidate_relative = (
                        Path(relative) / candidate.relative_to(path)
                    ).as_posix()
                    if candidate_relative.lower() in allowed:
                        continue
                    try:
                        document = read_text_document(candidate)
                    except (OSError, UnicodeError, ValueError) as exc:
                        raise InstallError(
                            f"检查失败，无法判定脚本编码: {candidate_relative}"
                        ) from exc
                    if pattern.search(document.text):
                        raise InstallError(
                            f"检查失败，资源 {token} 已被占用: {candidate_relative}"
                        )
                continue
            data = staged.get((scope, relative), path.read_bytes() if path.exists() else None)
            if check_type == "file_exists" and data is None:
                raise InstallError(f"检查失败，文件不存在: {relative}")
            if check_type == "file_missing" and data is not None:
                raise InstallError(f"检查失败，文件已存在: {relative}")
            if check_type == "sha256" and (data is None or _sha256(data) != str(check["value"]).lower()):
                raise InstallError(f"检查失败，哈希不匹配: {relative}")
            if check_type in {
                "text_contains", "text_not_contains", "reference_exists", "encoding",
                "label_exists", "label_available", "indexed_text_line_equals",
            }:
                if data is None:
                    if check_type == "label_available":
                        continue
                    raise InstallError(f"检查失败，文件不存在: {relative}")
                with tempfile.NamedTemporaryFile(delete=False) as handle:
                    temp = Path(handle.name); handle.write(data)
                try:
                    document = read_text_document(temp)
                finally:
                    temp.unlink(missing_ok=True)
                if check_type in {"text_contains", "reference_exists"} and _render(str(check["text"]), params) not in document.text:
                    raise InstallError(f"检查失败，引用不存在: {relative}")
                if check_type == "text_not_contains" and _render(str(check["text"]), params) in document.text:
                    raise InstallError(f"检查失败，发现禁止文本: {relative}")
                if check_type == "encoding" and document.encoding.lower() != str(check["value"]).lower():
                    raise InstallError(f"检查失败，编码不是 {check['value']}: {relative}")
                if check_type == "label_exists" and str(check["label"]).lower().removeprefix("@") not in scan_labels(document.text).labels:
                    raise InstallError(f"检查失败，标签不存在: {check['label']}")
                if check_type == "label_available":
                    label = _render(str(check["label"]), params).lower().removeprefix("@")
                    positions = scan_labels(document.text).labels.get(label, [])
                    if len(positions) > 1:
                        raise InstallError(f"检查失败，事件标签重复: {check['label']}")
                    if positions:
                        owner = _render(str(check.get("owner_package_id", "")), params).strip()
                        owned = False
                        if owner:
                            block_pattern = re.compile(
                                rf"^; XYDP-BEGIN {re.escape(owner)}(?:\s+SHA256=[0-9a-f]+)?\s*$"
                                rf"(?P<body>.*?)"
                                rf"^; XYDP-END {re.escape(owner)}\s*$",
                                re.IGNORECASE | re.MULTILINE | re.DOTALL,
                            )
                            owned = any(
                                label in scan_labels(match.group("body")).labels
                                for match in block_pattern.finditer(document.text)
                            )
                        if not owned:
                            raise InstallError(f"标签占用冲突: {check['label']}")
                if check_type == "indexed_text_line_equals":
                    line_number = int(check["line_number"])
                    rows = document.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                    expected = str(check["text"])
                    if line_number < 1 or len(rows) < line_number or rows[line_number - 1] != expected:
                        raise InstallError(f"检查失败，第{line_number}行内容不匹配: {relative}")
            if check_type not in {
                "file_exists", "file_missing", "sha256", "text_contains", "text_not_contains",
                "reference_exists", "encoding", "label_exists", "label_available",
                "indexed_text_line_equals", "tree_token_available",
            }:
                raise InstallError(f"不支持的检查类型: {check_type}")

    def _apply_operation(
        self,
        package: PackageManifest,
        operation: dict[str, Any],
        before: bytes | None,
        params: dict[str, Any],
    ) -> bytes:
        op_type = operation["type"]
        if operation.get("preserve_existing") is True and before is not None:
            return before
        if op_type == "sqlite_upsert":
            rendered = dict(operation)
            rendered["values"] = {
                key: _render(value, params) if isinstance(value, str) else value
                for key, value in operation["values"].items()
            }
            try:
                return apply_sqlite_upsert(before, rendered)
            except SqlitePatchError as exc:
                raise InstallError(f"{package.id}: {exc}") from exc
        if op_type == "sqlite_magic_skill_update":
            rendered = dict(operation)
            rendered["match"] = {
                key: _render(value, params) if isinstance(value, str) else value
                for key, value in operation["match"].items()
            }
            rendered["values"] = {
                key: _render(value, params) if isinstance(value, str) else value
                for key, value in operation["values"].items()
            }
            try:
                return apply_sqlite_magic_skill_update(before, rendered)
            except SqlitePatchError as exc:
                raise InstallError(f"{package.id}: {exc}") from exc
        if op_type in {"managed_block", "event_hook", "remove_event_hook", "managed_anchor_hook", "unique_line", "exclusive_unique_line", "indexed_text_line", "ensure_event_label", "ensure_callable_label", "mapinfo_flag", "mapinfo_title"}:
            if before is None:
                document = TextDocument("", operation.get("target_encoding", "gb18030"), "\r\n")
            else:
                with tempfile.NamedTemporaryFile(delete=False) as handle:
                    temp = Path(handle.name)
                    handle.write(before)
                try:
                    document = read_text_document(temp)
                finally:
                    temp.unlink(missing_ok=True)
                explicit_encoding = operation.get("target_encoding", "gb18030")
                if before.isascii():
                    document = TextDocument(
                        document.text,
                        str(explicit_encoding),
                        document.newline,
                        document.bom,
                    )
            try:
                if op_type == "managed_block":
                    content = _render(str(operation["content"]), params)
                    accepted_current_hashes = tuple(
                        str(value).lower()
                        for value in operation.get("accepted_current_hashes", [])
                    )
                    legacy_package_ids = tuple(
                        str(value)
                        for value in operation.get("legacy_package_ids", [])
                    )
                    retired_equipment_anchors = tuple(
                        str(value)
                        for value in operation.get("retired_equipment_anchors", [])
                    )
                    result = install_managed_block(
                        document.text,
                        package.id,
                        content,
                        document.newline,
                        accepted_current_hashes=accepted_current_hashes,
                        legacy_package_ids=legacy_package_ids,
                        retired_equipment_anchors=retired_equipment_anchors,
                    )
                elif op_type == "ensure_event_label":
                    label = _render(str(operation["label"]), params)
                    result = ensure_event_label(document.text, package.id, label, document.newline)
                elif op_type == "ensure_callable_label":
                    label = _render(str(operation["label"]), params)
                    result = ensure_callable_label(document.text, package.id, label, document.newline)
                elif op_type == "event_hook":
                    content = _render(str(operation["content"]), params)
                    label = _render(str(operation["label"]), params)
                    legacy_package_ids = tuple(
                        str(value) for value in operation.get("legacy_package_ids", [])
                    )
                    result = install_event_hook(
                        document.text,
                        package.id,
                        label,
                        content,
                        document.newline,
                        legacy_package_ids=legacy_package_ids,
                    )
                elif op_type == "remove_event_hook":
                    label = _render(str(operation["label"]), params)
                    owner_package_id = str(operation.get("owner_package_id", package.id))
                    accepted_current_hashes = tuple(
                        str(value).lower() for value in operation["accepted_current_hashes"]
                    )
                    result = remove_event_hook(
                        document.text,
                        owner_package_id,
                        label,
                        document.newline,
                        accepted_current_hashes,
                    )
                elif op_type == "managed_anchor_hook":
                    content = _render(str(operation["content"]), params)
                    anchor = _render(str(operation["anchor"]), params)
                    legacy_package_ids = tuple(
                        str(value) for value in operation.get("legacy_package_ids", [])
                    )
                    result = install_managed_anchor_hook(
                        document.text,
                        package.id,
                        anchor,
                        content,
                        document.newline,
                        legacy_package_ids=legacy_package_ids,
                    )
                elif op_type == "unique_line":
                    line = _render(str(operation["line"]), params)
                    result = add_unique_line(document.text, line, list(operation["key_fields"]), document.newline)
                elif op_type == "exclusive_unique_line":
                    line = _render(str(operation["line"]), params)
                    result = set_exclusive_unique_line(document.text, line, list(operation["key_fields"]), document.newline)
                elif op_type == "indexed_text_line":
                    content = str(operation["content"])
                    result = set_indexed_text_line(
                        document.text,
                        int(operation["line_number"]),
                        content,
                        document.newline,
                    )
                elif op_type == "mapinfo_flag":
                    map_id = _render(str(operation["map_id"]), params)
                    flag = _render(str(operation["flag"]), params)
                    result = ensure_mapinfo_flag(document.text, map_id, flag)
                else:
                    map_id = _render(str(operation["map_id"]), params)
                    display_name = _render(str(operation["display_name"]), params)
                    result = set_mapinfo_display_name(document.text, map_id, display_name)
            except TextPatchError as exc:
                raise InstallError(f"{package.id}: {exc}") from exc
            return encode_text_document(document, result.text)
        if op_type == "render":
            package_source = (package.root / operation["source"]).resolve()
            try:
                package_source.relative_to(package.root.resolve())
            except ValueError as exc:
                raise InstallError(f"包内源路径越界: {package_source}") from exc
            try:
                source = package_operation_source(
                    self.repository.root.parent,
                    package_source,
                    operation.get("user_document"),
                )
            except ValueError as exc:
                raise InstallError(f"{package.id}: {exc}") from exc
            text = _render(source.read_text(encoding=operation.get("source_encoding", "utf-8")), params)
            newline = operation.get("newline", "\r\n")
            text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
            return text.encode(operation.get("target_encoding", "gb18030"))
        if op_type == "config_merge":
            package_source = (package.root / operation["source"]).resolve()
            try:
                package_source.relative_to(package.root.resolve())
            except ValueError as exc:
                raise InstallError(f"包内源路径越界: {package_source}") from exc
            try:
                source = package_operation_source(
                    self.repository.root.parent,
                    package_source,
                    operation.get("user_document"),
                )
            except ValueError as exc:
                raise InstallError(f"{package.id}: {exc}") from exc
            if not source.is_file():
                raise InstallError(f"源配置文件不存在: {source}")
            defaults = source.read_text(encoding=operation.get("source_encoding", "utf-8"))
            if before is None:
                document = TextDocument(
                    "",
                    operation.get("target_encoding", "gb18030"),
                    operation.get("newline", "\r\n"),
                )
                current = None
            else:
                with tempfile.NamedTemporaryFile(delete=False) as handle:
                    temp = Path(handle.name)
                    handle.write(before)
                try:
                    document = read_text_document(temp)
                finally:
                    temp.unlink(missing_ok=True)
                current = document.text
            try:
                merged = merge_config_text(current, defaults, document.newline)
            except ConfigPatchError as exc:
                raise InstallError(f"{package.id}: {exc}") from exc
            return encode_text_document(document, merged)
        if op_type == "config_set":
            if before is None:
                raise InstallError(f"{package.id}: config_set 目标文件不存在")
            with tempfile.NamedTemporaryFile(delete=False) as handle:
                temp = Path(handle.name)
                handle.write(before)
            try:
                document = read_text_document(temp)
            finally:
                temp.unlink(missing_ok=True)
            try:
                values = {
                    str(key): _render(str(value), params)
                    for key, value in operation["values"].items()
                }
                merged = set_flat_config_values(document.text, values, document.newline)
            except ConfigPatchError as exc:
                raise InstallError(f"{package.id}: {exc}") from exc
            return encode_text_document(document, merged)
        if op_type == "transcode_copy":
            package_source = (package.root / operation["source"]).resolve()
            try:
                package_source.relative_to(package.root.resolve())
            except ValueError as exc:
                raise InstallError(f"包内源路径越界: {package_source}") from exc
            try:
                source = package_operation_source(
                    self.repository.root.parent,
                    package_source,
                    operation.get("user_document"),
                )
            except ValueError as exc:
                raise InstallError(f"{package.id}: {exc}") from exc
            if not source.is_file():
                raise InstallError(f"源文件不存在: {source}")
            try:
                text = source.read_text(encoding=operation.get("source_encoding", "utf-8"))
                newline = operation.get("newline")
                if newline:
                    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
                output = text.encode(operation.get("target_encoding", "gb18030"))
                if operation.get("strict_existing") is True and before is not None and before != output:
                    raise InstallError(
                        f"{package.id}: 目标文件已存在且内容不同，已阻止覆盖: {operation['target']}"
                    )
                return output
            except (UnicodeError, LookupError) as exc:
                raise InstallError(f"{package.id}: 文本转码失败: {source}") from exc
        if op_type in {"copy", "binary_copy"}:
            package_source = (package.root / operation["source"]).resolve()
            try:
                package_source.relative_to(package.root.resolve())
            except ValueError as exc:
                raise InstallError(f"包内源路径越界: {package_source}") from exc
            try:
                source = package_operation_source(
                    self.repository.root.parent,
                    package_source,
                    operation.get("user_document"),
                )
            except ValueError as exc:
                raise InstallError(f"{package.id}: {exc}") from exc
            if not source.is_file():
                raise InstallError(f"源文件不存在: {source}")
            return source.read_bytes()
        raise InstallError(f"不支持的操作类型: {op_type}")

    def install(self, plan: InstallPlan) -> InstallReceipt:
        from .target_lock import target_lock
        with target_lock(Path(plan.target_root)):
            return self._install_locked(plan)

    def _install_locked(self, plan: InstallPlan) -> InstallReceipt:
        if not plan.changes:
            raise InstallError("没有需要应用的变更，目标已处于所选版本")
        if "xy.optional.equipment-wash-opening" in plan.package_ids:
            raise InstallError("洗练旧普通包计划已失效，请通过equipment-wash-import重新预检")
        target = TargetInspector.inspect(Path(plan.target_root))
        client = Path(plan.client_root).absolute() if plan.client_root else None
        launcher = Path(plan.launcher_root).absolute() if plan.launcher_root else None
        roots = {"server": target.root, "client": client, "launcher": launcher}
        transaction_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        backup_root = self.backups_root / transaction_id
        backup_files = backup_root / "files"
        backup_files.mkdir(parents=True, exist_ok=False)
        receipt_changes: list[dict[str, Any]] = []
        committed: list[PlannedChange] = []
        try:
            for change in plan.changes:
                scope_root = roots.get(change.scope)
                if scope_root is None:
                    raise InstallError(f"安装计划缺少 {change.scope} 根目录")
                destination = _safe_target(scope_root, change.relative_path)
                current = destination.read_bytes() if destination.exists() else None
                if current != change.before:
                    raise InstallError(f"预检后目标发生变化: {change.relative_path}")
                if change.before is not None:
                    backup = backup_files / change.scope / Path(change.relative_path.replace("/", os.sep))
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    backup.write_bytes(change.before)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temp = destination.with_name(destination.name + f".xydp-{transaction_id}.tmp")
                temp.write_bytes(change.after)
                os.replace(temp, destination)
                committed.append(change)
                receipt_changes.append({
                    "path": change.relative_path,
                    "scope": change.scope,
                    "before_hash": _sha256(change.before) if change.before is not None else None,
                    "after_hash": _sha256(change.after),
                    "created": change.before is None,
                    "package_id": change.package_id,
                    "operation": change.operation,
                })
            receipt = InstallReceipt(
                transaction_id=transaction_id,
                target_root=str(target.root),
                client_root=str(client) if client else None,
                packages=plan.package_versions,
                parameters=plan.parameters,
                changes=receipt_changes,
                backup_root=str(backup_root),
                created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                operation_type=plan.operation_type,
                candidate_packages=plan.candidate_packages,
                superseded_package_ids=plan.superseded_package_ids,
                launcher_root=str(launcher) if launcher else None,
            )
            self._write_receipts(target.root, receipt)
            return receipt
        except Exception:
            self._restore_changes(roots, backup_root, committed)
            shutil.rmtree(backup_root, ignore_errors=True)
            raise

    def _write_receipts(self, target_root: Path, receipt: InstallReceipt) -> None:
        data = asdict(receipt)
        backup_receipt = Path(receipt.backup_root) / "receipt.json"
        backup_receipt.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        state = target_root / ".xydp"
        (state / "transactions").mkdir(parents=True, exist_ok=True)
        (state / "transactions" / f"{receipt.transaction_id}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        installed = state / "installed.json"
        installed_data = json.loads(installed.read_text(encoding="utf-8")) if installed.exists() else {"packages": {}, "transactions": []}
        for package_id in receipt.superseded_package_ids:
            installed_data["packages"].pop(package_id, None)
        installed_data["packages"].update(receipt.packages)
        installed_data["transactions"].append(receipt.transaction_id)
        installed.write_text(json.dumps(installed_data, ensure_ascii=False, indent=2), encoding="utf-8")

    def rollback(self, target_root: Path, transaction_id: str) -> None:
        from .target_lock import target_lock
        with target_lock(target_root):
            return self._rollback_locked(target_root, transaction_id)

    def _rollback_locked(self, target_root: Path, transaction_id: str) -> None:
        target = TargetInspector.inspect(target_root)
        receipt_path = self.backups_root / transaction_id / "receipt.json"
        if not receipt_path.exists():
            raise InstallError(f"找不到事务收据: {transaction_id}")
        data = json.loads(receipt_path.read_text(encoding="utf-8"))
        if Path(data["target_root"]).resolve() != target.root.resolve():
            raise InstallError("事务目标与当前服务端不一致")
        client = Path(data["client_root"]).absolute() if data.get("client_root") else None
        launcher = Path(data["launcher_root"]).absolute() if data.get("launcher_root") else None
        roots = {"server": target.root, "client": client, "launcher": launcher}
        for item in data["changes"]:
            scope_root = roots.get(item.get("scope", "server"))
            if scope_root is None:
                raise InstallError("事务缺少客户端根目录")
            path = _safe_target(scope_root, item["path"])
            current = path.read_bytes() if path.exists() else None
            if current is None or _sha256(current) != item["after_hash"]:
                raise InstallError(f"文件已在安装后被修改，禁止回滚: {item['path']}")
        for item in reversed(data["changes"]):
            scope = item.get("scope", "server")
            scope_root = roots.get(scope)
            if scope_root is None:
                raise InstallError("事务缺少客户端根目录")
            path = _safe_target(scope_root, item["path"])
            if item["created"]:
                path.unlink(missing_ok=True)
            else:
                backup = Path(data["backup_root"]) / "files" / scope / Path(item["path"].replace("/", os.sep))
                temp = path.with_name(path.name + f".rollback-{transaction_id}.tmp")
                temp.write_bytes(backup.read_bytes())
                os.replace(temp, path)
        self._remove_transaction_from_state(target.root, transaction_id)
        data["rolled_back_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        receipt_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def uninstall(self, target_root: Path, package_id: str) -> None:
        target = TargetInspector.inspect(target_root)
        state_path = target.root / ".xydp" / "installed.json"
        if not state_path.exists():
            raise InstallError("目标服没有平台安装状态")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        transactions = state.get("transactions", [])
        if package_id not in state.get("packages", {}):
            raise InstallError(f"成果包未安装: {package_id}")
        if not transactions:
            raise InstallError("安装状态缺少事务记录")
        latest = transactions[-1]
        receipt_path = self.backups_root / latest / "receipt.json"
        if not receipt_path.exists():
            raise InstallError(f"缺少最近事务备份: {latest}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if package_id not in receipt.get("packages", {}):
            raise InstallError("该包不是最近安装事务，需先回滚后续事务")
        self.rollback(target.root, latest)

    def _remove_transaction_from_state(self, target_root: Path, transaction_id: str) -> None:
        state_path = target_root / ".xydp" / "installed.json"
        if not state_path.exists():
            return
        state = json.loads(state_path.read_text(encoding="utf-8"))
        remaining = [item for item in state.get("transactions", []) if item != transaction_id]
        packages: dict[str, str] = {}
        valid_transactions: list[str] = []
        for item in remaining:
            receipt_path = self.backups_root / item / "receipt.json"
            if not receipt_path.exists():
                continue
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("rolled_back_at"):
                continue
            for package_id in receipt.get("superseded_package_ids", []):
                packages.pop(package_id, None)
            packages.update(receipt.get("packages", {}))
            valid_transactions.append(item)
        state_path.write_text(
            json.dumps({"packages": packages, "transactions": valid_transactions}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _restore_changes(self, roots: dict[str, Path | None], backup_root: Path, changes: list[PlannedChange]) -> None:
        for change in reversed(changes):
            scope_root = roots.get(change.scope)
            if scope_root is None:
                continue
            path = _safe_target(scope_root, change.relative_path)
            if change.before is None:
                path.unlink(missing_ok=True)
            else:
                backup = backup_root / "files" / change.scope / Path(change.relative_path.replace("/", os.sep))
                if backup.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(backup.read_bytes())
