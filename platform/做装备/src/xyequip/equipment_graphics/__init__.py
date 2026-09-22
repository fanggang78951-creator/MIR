"""Manifest-driven equipment graphics import candidate.

This package is deliberately isolated in the integration mirror.  It performs
no target writes during preflight.
"""

from __future__ import annotations

import json
import hashlib
import struct
from pathlib import Path
import sqlite3
from contextlib import closing
from uuid import uuid4

from PIL import Image


class EquipmentGraphicsError(RuntimeError):
    """The manifest or its reviewed target state is not safe to apply."""


def _sha_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_image(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size
    except Exception as exc:
        raise EquipmentGraphicsError(f"影像不可读取: {path}: {exc}") from exc


def _valid_auto_shape(manifest: dict, config_hash: str, idx: int, current_shape: int, output_root: Path) -> int | None:
    """Reuse only a completed receipt whose config and current Shape agree."""
    transaction_root = output_root / "transactions"
    if not transaction_root.is_dir():
        return None
    for receipt_path in sorted(transaction_root.glob("*/receipt.json"), reverse=True):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if receipt.get("status") != "applied" or receipt.get("configHash") != config_hash:
            continue
        for update in receipt.get("shapeUpdates", []):
            if update.get("idx") != idx:
                continue
            try:
                old_shape, new_shape = int(update["oldShape"]), int(update["newShape"])
            except (KeyError, TypeError, ValueError):
                continue
            if current_shape == new_shape and new_shape != old_shape:
                return new_shape
            if current_shape != old_shape:
                return None
    return None


def _wzx_count(path: Path) -> int | None:
    try:
        data = path.read_bytes()
        if len(data) < 48:
            return None
        count = struct.unpack_from("<I", data, 44)[0]
        return count if len(data) == 48 + count * 4 else None
    except OSError:
        return None


def scan_action_source(
    source_root: Path | str,
    *,
    frame_count: int,
    source_filename_digits: int,
    treat_one_by_one_as_empty: bool,
) -> dict[str, int]:
    """Read frame/placement completeness and declared empty slots without writes."""
    root = Path(source_root)
    visible = 0
    empty = 0
    for index in range(frame_count):
        name = f"{index:0{source_filename_digits}d}"
        image_path = root / f"{name}.png"
        if not image_path.is_file():
            image_path = root / f"{name}.PNG"
        placement = root / "Placements" / f"{name}.txt"
        if not image_path.is_file() or not placement.is_file():
            raise EquipmentGraphicsError(f"动作帧或Placement缺失: {name}")
        lines = placement.read_text(encoding="utf-8").splitlines()
        if len(lines) != 2:
            raise EquipmentGraphicsError(f"Placement必须为两行坐标: {placement}")
        try:
            int(lines[0]); int(lines[1])
        except ValueError as exc:
            raise EquipmentGraphicsError(f"Placement不是整数坐标: {placement}") from exc
        with Image.open(image_path) as image:
            is_empty = treat_one_by_one_as_empty and image.size == (1, 1)
        if is_empty:
            empty += 1
        else:
            visible += 1
    return {"frameCount": frame_count, "visibleFrames": visible, "emptyFrames": empty}


def preflight(config_path: Path | str) -> dict[str, object]:
    """Fully validate sources and target state without creating or writing anything."""
    try:
        operation = json.loads(Path(config_path).read_text(encoding="utf-8")).get("operation")
    except (OSError, ValueError):
        operation = None
    if operation == "equipment-graphics-append":
        from .append import append_preflight
        return append_preflight(config_path)
    manifest_path = Path(config_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    blockers: list[str] = []
    if manifest.get("schemaVersion") != 1:
        blockers.append("schemaVersion 必须为 1")
    if manifest.get("operation") != "equipment-graphics-import":
        blockers.append("operation 必须为 equipment-graphics-import")
    items = manifest.get("items")
    if not isinstance(items, list):
        blockers.append("items 必须为数组")
        items = []
    elif not items:
        blockers.append("items 不能为空")
    resolved_items: list[dict[str, object]] = []
    shape_updates: list[dict[str, object]] = []
    source_hashes: dict[str, str] = {}
    target_hashes: dict[str, str | None] = {}
    seen_names: set[str] = set()
    reserved_shapes: set[int] = set()
    encoding = manifest.get("encoding") if isinstance(manifest.get("encoding"), dict) else {}
    try:
        frame_count = int(encoding.get("actionFrameCount", 0))
        frame_digits = int(encoding.get("sourceFrameDigits", 6))
        alpha_cutoff = int(encoding.get("alphaCutoff", 128))
    except (TypeError, ValueError):
        frame_count = frame_digits = 0; alpha_cutoff = -1
    if frame_count <= 0: blockers.append("encoding.actionFrameCount 必须为正整数")
    if frame_digits <= 0: blockers.append("动作帧编号位数必须为正整数")
    if not 0 <= alpha_cutoff <= 255: blockers.append("encoding.alphaCutoff 必须在0..255")
    if encoding.get("staticType") not in (None, "type6-bgr24-bottom-up"):
        blockers.append("encoding.staticType必须为type6-bgr24-bottom-up")
    target = manifest.get("target")
    if not isinstance(target, dict):
        blockers.append("target.database 必须为数据库路径")
        target = {}
    database = Path(target.get("database", ""))
    if not isinstance(target.get("database"), str) or not database.is_file():
        if isinstance(target.get("database"), str):
            blockers.append(f"数据库不存在: {database}")
    db_hash_before = _sha_path(database) if isinstance(target.get("database"), str) and database.is_file() else None
    if db_hash_before:
        target_hashes[str(database.resolve())] = db_hash_before
    client_data = Path(target.get("clientData", "")) if isinstance(target.get("clientData"), str) else None
    patch_data = Path(target.get("launcherPatchData", "")) if isinstance(target.get("launcherPatchData"), str) else None
    if client_data and patch_data:
        for library in ("Items", "DnItems", "StateItem"):
            left, right = client_data / f"{library}.wzl", patch_data / f"{library}.wzl"
            left_x, right_x = client_data / f"{library}.wzx", patch_data / f"{library}.wzx"
            all_present = all(path.is_file() for path in (left, right, left_x, right_x))
            if all_present and (_sha_path(left) != _sha_path(right) or _sha_path(left_x) != _sha_path(right_x)):
                blockers.append(f"客户端与登录器补丁源不一致，拒绝静默覆盖: {library}")
            elif (left.is_file() or left_x.is_file()) and not all_present:
                blockers.append(f"客户端/登录器补丁源文件不完整: {library}")
            for path in (left, right, left_x, right_x):
                if path.is_file(): target_hashes[str(path.resolve())] = _sha_path(path)
    output_root = Path(manifest.get("outputRoot", "")) if isinstance(manifest.get("outputRoot"), str) else Path()
    output_root_valid = isinstance(manifest.get("outputRoot"), str) and bool(str(manifest.get("outputRoot")).strip())
    if not output_root_valid:
        blockers.append("outputRoot必须为非空候选目录")
    elif output_root.resolve() == manifest_path.parent.resolve():
        blockers.append("outputRoot不得覆盖配置文件所在目录")
    selected_indices: set[int] = set()
    if database.is_file() and items:
        try:
            uri = f"file:{database.resolve().as_posix()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(StdItems)")}
                required_columns = {"Idx", "Name", "StdMode", "Looks", "Shape"}
                if not required_columns <= columns:
                    blockers.append("StdItems缺少Idx/Name/StdMode/Looks/Shape字段")
                all_rows = connection.execute("SELECT Idx, Name, StdMode, Looks, Shape FROM StdItems").fetchall()
                for item in items:
                    if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
                        blockers.append("items[].name 必须为非空装备名称"); continue
                    name = item["name"].strip()
                    if name in seen_names:
                        blockers.append(f"装备名称重复: {name}")
                    seen_names.add(name)
                    kind = item.get("kind")
                    if kind not in ("weapon", "armor"):
                        blockers.append(f"装备类型必须为 weapon 或 armor: {name}"); continue
                    rows = connection.execute("SELECT Idx, Name, StdMode, Looks, Shape FROM StdItems WHERE Name=?", (name,)).fetchall()
                    if len(rows) != 1:
                        blockers.append(f"装备名称必须唯一且存在: {name} (匹配 {len(rows)} 行)"); continue
                    idx, db_name, std_mode, looks, shape = rows[0]
                    selected_indices.add(int(idx))
                    expected_modes = {"weapon": {5}, "armor": {10}}[kind]
                    if int(std_mode) not in expected_modes:
                        blockers.append(f"kind与StdMode不匹配: {name} ({kind}, StdMode={std_mode})")
                    if "stdMode" in item and int(item["stdMode"]) != int(std_mode):
                        blockers.append(f"装备 StdMode 不符: {name}")
                    sources = item.get("sources")
                    static = item.get("static")
                    action = item.get("action")
                    if not isinstance(sources, dict) or not isinstance(static, dict) or not isinstance(action, dict):
                        blockers.append(f"{name} 缺少sources/static/action声明"); continue
                    expected_library = "Weapon" if kind == "weapon" else "Human"
                    if action.get("library") != expected_library:
                        blockers.append(f"{name} action.library必须为{expected_library}")
                    action_root = Path(sources.get("actionFrames", ""))
                    if output_root_valid:
                        roots_to_check = [action_root, Path(sources.get("bagImage", "")), Path(sources.get("innerImage", ""))]
                        roots_to_check += [client_data, patch_data]
                        graphics = target.get("graphicsRoots") if isinstance(target.get("graphicsRoots"), dict) else {}
                        roots_to_check += [Path(value) for value in graphics.values() if isinstance(value, str) and value]
                        for protected in roots_to_check:
                            if protected and (output_root.resolve() == protected.resolve() or output_root.resolve().is_relative_to(protected.resolve()) or protected.resolve().is_relative_to(output_root.resolve())):
                                blockers.append(f"outputRoot与源/目标目录重叠: {output_root} ↔ {protected}")
                    try:
                        item_frame_digits = int(action.get("sourceFrameDigits", frame_digits))
                    except (TypeError, ValueError):
                        item_frame_digits = 0
                        blockers.append(f"{name} sourceFrameDigits必须为正整数")
                    for key in ("bagImage", "innerImage"):
                        image = Path(sources.get(key, ""))
                        if not image.is_file(): blockers.append(f"素材不存在: {name} {key}: {image}")
                        else:
                            _read_image(image); source_hashes[str(image.resolve())] = _sha_path(image)
                    if action_root.is_dir() and frame_count > 0:
                        try:
                            stats = scan_action_source(action_root, frame_count=frame_count, source_filename_digits=item_frame_digits, treat_one_by_one_as_empty=bool(action.get("treatOneByOneAsEmpty", True)))
                            for frame in range(frame_count):
                                stem = f"{frame:0{item_frame_digits}d}"
                                image_path = action_root / f"{stem}.png"
                                if not image_path.is_file(): image_path = action_root / f"{stem}.PNG"
                                placement_path = action_root / "Placements" / f"{stem}.txt"
                                source_hashes[str(image_path.resolve())] = _sha_path(image_path)
                                source_hashes[str(placement_path.resolve())] = _sha_path(placement_path)
                            expected_visible = encoding.get("actionVisibleFrames")
                            expected_empty = encoding.get("actionEmptyFrames")
                            if expected_visible is not None and stats["visibleFrames"] != int(expected_visible): blockers.append(f"{name} 可见帧数不符: {stats['visibleFrames']}")
                            if expected_empty is not None and stats["emptyFrames"] != int(expected_empty): blockers.append(f"{name} 空帧数不符: {stats['emptyFrames']}")
                        except (EquipmentGraphicsError, TypeError, ValueError) as exc: blockers.append(str(exc))
                    else: blockers.append(f"动作帧目录不存在: {name}: {action_root}")
                    for placement_key in ("bagPlacement", "innerPlacement"):
                        placement = static.get(placement_key)
                        if not isinstance(placement, (list, tuple)) or len(placement) != 2:
                            blockers.append(f"{name} {placement_key}必须为[x,y]")
                        else:
                            try:
                                px, py = int(placement[0]), int(placement[1])
                                if not (-32768 <= px <= 32767 and -32768 <= py <= 32767):
                                    blockers.append(f"{name} {placement_key}超出int16范围")
                            except (TypeError, ValueError): blockers.append(f"{name} {placement_key}坐标必须为整数")
                    libraries = static.get("libraries")
                    if not isinstance(libraries, list) or not libraries: blockers.append(f"{name} static.libraries不能为空")
                    elif any(lib not in {"Items", "DnItems", "StateItem"} for lib in libraries): blockers.append(f"{name} static.libraries包含未知图库")
                    if client_data and isinstance(libraries, list):
                        for lib in libraries:
                            for suffix in (".wzl", ".wzx"):
                                path = client_data / f"{lib}{suffix}"
                                if not path.is_file():
                                    blockers.append(f"客户端静态库缺失: {path}")
                                elif suffix == ".wzx" and _wzx_count(path) is None:
                                    blockers.append(f"客户端WZX长度/count无效: {path}")
                    if looks is not None:
                        if int(looks) < 0:
                            blockers.append(f"Looks超出有效范围: {name}={looks}")
                        if client_data:
                            for library in ("Items", "DnItems", "StateItem"):
                                count = _wzx_count(client_data / f"{library}.wzx")
                                if count is not None and int(looks) >= count:
                                    blockers.append(f"Looks超出{library}槽位范围: {name}={looks}/{count}")
                        owners = [row for row in all_rows if row[3] == looks and int(row[0]) != int(idx)]
                        if owners: blockers.append(f"Looks={looks}被其它装备共用，拒绝覆盖: {name}")
                    resolved_items.append({"idx": int(idx), "name": db_name, "stdMode": int(std_mode), "looks": int(looks), "shape": int(shape), "kind": kind})
                    if item.get("autoShape") is not True:
                        blockers.append(f"{name} 必须显式启用autoShape=true以保护Shape占用")
                    else:
                        roots = target.get("graphicsRoots") if isinstance(target.get("graphicsRoots"), dict) else {}
                        library = expected_library
                        graphics_root_value = roots.get(library)
                        if not isinstance(graphics_root_value, str) or not graphics_root_value.strip():
                            blockers.append(f"autoShape缺少独立图库路径: {library}"); continue
                        graphics_root = Path(graphics_root_value)
                        if graphics_root.exists() and not graphics_root.is_dir():
                            blockers.append(f"autoShape独立图库路径不是目录: {library}"); continue
                        reused = _valid_auto_shape(manifest, config_hash, int(idx), int(shape), output_root)
                        if reused is not None: new_shape = reused
                        else:
                            used = {int(row[4]) for row in all_rows if row[4] is not None}
                            existing = {int(path.stem) for path in graphics_root.glob("*.wil") if path.stem.isdigit()}
                            candidate = int(manifest.get("autoShapeStart", 1000))
                            while candidate in used or candidate in existing or candidate in reserved_shapes: candidate += 1
                            new_shape = candidate
                        reserved_shapes.add(new_shape)
                        if int(new_shape) != int(shape):
                            shape_updates.append({"idx": int(idx), "oldShape": int(shape), "newShape": int(new_shape), "library": library, "oldRow": [int(idx), db_name, int(std_mode), int(looks), int(shape)]})
                        resolved_items[-1]["targetShape"] = int(new_shape)
                        for suffix in (".wil", ".wix"):
                            path = graphics_root / f"{new_shape}{suffix}"; target_hashes[str(path.resolve())] = _sha_path(path) if path.is_file() else None
        except sqlite3.Error as exc:
            blockers.append(f"无法只读查询 StdItems: {exc}")
    elif items:
        blockers.append("无法读取目标数据库，未执行装备解析")
    if db_hash_before and _sha_path(database) != db_hash_before:
        blockers.append("预检期间数据库发生漂移")
    return {
        "mode": "preflight", "manifestPath": str(manifest_path), "blockers": blockers,
        "resolvedItems": resolved_items, "shapeUpdates": shape_updates, "configHash": config_hash,
        "dbHash": target_hashes.get(str(database.resolve())) if database.is_file() else None,
        "sourceHashes": source_hashes, "targetHashes": target_hashes,
    }


def apply(config_path: Path | str) -> dict[str, object]:
    """Apply only after an all-read-only preflight is clear.

    The candidate intentionally stops before creating a workspace when the
    manifest is incomplete or refers to an unsafe target.  Target write and
    resource-build stages are added only after their frame and static writer
    contracts have corresponding tests.
    """
    try:
        operation = json.loads(Path(config_path).read_text(encoding="utf-8")).get("operation")
    except (OSError, ValueError):
        operation = None
    if operation == "equipment-graphics-append":
        from .append import append_apply
        return append_apply(config_path)
    result = preflight(config_path)
    if result["blockers"]:
        raise EquipmentGraphicsError("预检阻止安装: " + "; ".join(result["blockers"]))
    source_manifest_path = Path(config_path).resolve()
    if hashlib.sha256(source_manifest_path.read_bytes()).hexdigest() != result.get("configHash"):
        raise EquipmentGraphicsError("配置在预检后发生漂移，拒绝应用")
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    # User manifests declare sources only; candidates are always rebuilt here.
    manifest.pop("preparedFiles", None)
    from .builder import build_prepared_files
    manifest["preparedFiles"] = build_prepared_files(manifest, result)
    if hashlib.sha256(source_manifest_path.read_bytes()).hexdigest() != result.get("configHash"):
        raise EquipmentGraphicsError("配置在构建后发生漂移，拒绝应用")
    manifest_path = Path(manifest["outputRoot"]) / "apply-manifests" / f"{uuid4().hex}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    from .transaction import apply_prepared, TransactionError
    try:
        return apply_prepared(manifest_path=manifest_path, preflight=result)
    except TransactionError as exc:
        raise EquipmentGraphicsError(str(exc)) from exc


def rollback(receipt_path: Path | str) -> dict[str, object]:
    """Reserved public API; refusing unknown receipts protects external changes."""
    try:
        operation = json.loads(Path(receipt_path).read_text(encoding="utf-8")).get("operation")
    except (OSError, ValueError):
        operation = None
    if operation == "equipment-graphics-append":
        from .append import append_rollback
        return append_rollback(receipt_path)
    from .transaction import rollback_receipt, TransactionError
    try:
        return rollback_receipt(Path(receipt_path))
    except TransactionError as exc:
        raise EquipmentGraphicsError(str(exc)) from exc


def verify_launcher(receipt_path: Path | str) -> dict[str, object]:
    """Verify every declared client/patch target; absence never passes."""
    from .transaction import sha256
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    expected = receipt.get("expectedFiles") or receipt.get("files") or []
    blockers: list[str] = []
    verified = 0
    roles = {str(item.get("role")) for item in expected if isinstance(item, dict)}
    if not expected: blockers.append("收据缺少expectedFiles/files，拒绝空文件假通过")
    if "client-static" not in roles and "client-action" not in roles: blockers.append("收据缺少实际客户端资源role")
    if "launcher-patch" not in roles and "launcher-action" not in roles: blockers.append("收据缺少登录器补丁资源role")
    for item in expected:
        if not isinstance(item, dict) or item.get("role") not in {"client-static", "client-action", "launcher-patch", "launcher-action", "action-mirror"}:
            blockers.append(f"资源role无效: {item.get('target') if isinstance(item, dict) else item}"); continue
        target = Path(str(item.get("target", ""))); after = item.get("after") or item.get("afterSha256")
        if not target.is_file(): blockers.append(f"资源不存在: {target}")
        elif not after or sha256(target) != after: blockers.append(f"资源哈希不符: {target}")
        else: verified += 1
    return {"receiptPath": str(Path(receipt_path)), "expectedFiles": len(expected), "verifiedFiles": verified, "success": not blockers, "status": "verified" if not blockers else "failed", "blockers": blockers, "manualGeneration": "用户使用官方登录器生成器后，再调用此接口核对客户端与补丁资源；本核验不检测用户是否实际生成EXE。"}


__all__ = ["EquipmentGraphicsError", "apply", "preflight", "rollback", "scan_action_source", "verify_launcher"]
