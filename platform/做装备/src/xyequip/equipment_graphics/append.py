"""Independent, file-only append operation for unbound equipment resources."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from PIL import Image

from .action_wil import build_action_wil_wix
from .static_wzl import append_static_pair
from .transaction import TransactionError, apply_append_prepared, rollback_append_receipt, sha256
from . import scan_action_source


class EquipmentGraphicsAppendError(RuntimeError):
    pass


def _hash(path: Path) -> str:
    return sha256(path)


def _count(wzx: Path) -> int:
    data = wzx.read_bytes()
    if len(data) < 48:
        raise ValueError(f"WZX header is truncated: {wzx}")
    value = int.from_bytes(data[44:48], "little")
    if len(data) != 48 + value * 4:
        raise ValueError(f"WZX length/count mismatch: {wzx}")
    return value


def _wzl_count(wzl: Path) -> int:
    data = wzl.read_bytes()
    if len(data) < 48:
        raise ValueError(f"WZL header is truncated: {wzl}")
    return int.from_bytes(data[44:48], "little")


def _overlaps(left: Path, right: Path) -> bool:
    try:
        left.resolve().relative_to(right.resolve())
        return True
    except ValueError:
        try:
            right.resolve().relative_to(left.resolve())
            return True
        except ValueError:
            return False


def _source_hashes(config_path: Path, resources: list[dict], reserved_evidence: dict | None = None) -> dict[str, str]:
    sources = {config_path.resolve()}
    for resource in resources:
        sources.add(Path(str(resource["sources"]["bagImage"])).resolve())
        sources.add(Path(str(resource["sources"]["innerImage"])).resolve())
        action = resource["action"]
        root = Path(str(resource["sources"]["actionFrames"])).resolve()
        digits, frames = int(action.get("sourceFrameDigits", 6)), int(action["frameCount"])
        for index in range(frames):
            name = f"{index:0{digits}d}"
            image = root / f"{name}.png"
            if not image.is_file():
                image = root / f"{name}.PNG"
            sources.add(image.resolve())
            sources.add((root / "Placements" / f"{name}.txt").resolve())
    if reserved_evidence:
        sources.add(Path(str(reserved_evidence["path"])).resolve())
    return {str(path): _hash(path) for path in sorted(sources, key=str)}


def _find_applied_receipt(output_root: Path, config_hash: str) -> tuple[Path, dict] | None:
    transactions = output_root / "transactions"
    if not transactions.is_dir():
        return None
    for path in sorted(transactions.glob("*/receipt.json"), reverse=True):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if receipt.get("operation") == "equipment-graphics-append" and receipt.get("status") == "applied" and receipt.get("configHash") == config_hash:
            return path, receipt
    return None


def append_preflight(config_path: Path | str) -> dict[str, object]:
    """Read sources and candidate targets, but never create or modify files."""
    path = Path(config_path).resolve()
    blockers: list[str] = []
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"mode": "equipment-graphics-append-preflight", "blockers": [f"无法读取配置: {exc}"]}
    resources = config.get("resources") if isinstance(config.get("resources"), list) else []
    try:
        expected = int(config.get("expectedResourceCount"))
    except (TypeError, ValueError):
        expected = 0
    if config.get("schemaVersion") != 1: blockers.append("schemaVersion必须为1")
    if config.get("operation") != "equipment-graphics-append": blockers.append("operation必须为equipment-graphics-append")
    if expected < 1 or len(resources) != expected: blockers.append(f"expectedResourceCount必须为正整数且等于资源数量，当前为{len(resources)}")
    if not isinstance(config.get("startLooks"), int) or int(config.get("startLooks", -1)) < 0: blockers.append("startLooks必须为非负整数")
    output_root = Path(str(config.get("outputRoot", ""))).resolve()
    names = [str(item.get("name", "")).strip() for item in resources if isinstance(item, dict)]
    if len(names) != len(resources) or not all(names) or len(set(names)) != len(names): blockers.append("资源name必须是唯一非空资源名")
    source_hashes: dict[str, str] = {}
    action_libraries: set[str] = set()
    reserved_evidence = config.get("reservedShapesEvidence") if isinstance(config.get("reservedShapesEvidence"), dict) else None
    reserved_shapes: set[int] = set()
    try:
        reserved_shapes = {int(value) for value in config.get("reservedShapes", [])}
        if reserved_evidence:
            evidence_path = Path(str(reserved_evidence["path"])).resolve()
            if not evidence_path.is_file() or _hash(evidence_path) != str(reserved_evidence["sha256"]):
                raise ValueError("reservedShapesEvidence哈希不符")
    except (KeyError, TypeError, ValueError) as exc:
        blockers.append(f"reservedShapes清单无效: {exc}")
    if not blockers:
        try:
            for resource in resources:
                sources = resource["sources"]
                for key in ("bagImage", "innerImage"):
                    with Image.open(Path(str(sources[key]))) as opened: opened.verify()
                action = resource["action"]
                library = str(action["library"])
                kind = str(action["kind"])
                if (library, kind) not in {("Weapon", "weapon"), ("Human", "human")}:
                    raise ValueError(f"unsupported action library/kind: {library}/{kind}")
                scan_action_source(Path(str(sources["actionFrames"])), frame_count=int(action["frameCount"]), source_filename_digits=int(action.get("sourceFrameDigits", 6)), treat_one_by_one_as_empty=bool(action.get("treatOneByOneAsEmpty", True)))
                action_libraries.add(library)
            source_hashes = _source_hashes(path, resources, reserved_evidence)
        except (KeyError, OSError, ValueError, RuntimeError) as exc:
            blockers.append(f"资源源文件不完整: {exc}")
    target = config.get("target") if isinstance(config.get("target"), dict) else {}
    config_hash = _hash(path) if path.is_file() else ""
    existing = _find_applied_receipt(output_root, config_hash) if not blockers else None
    static_targets = target.get("staticTargets") if isinstance(target.get("staticTargets"), list) else []
    client_action_roots = target.get("clientActionRoots", target.get("actionRoots", {}))
    client_action_roots = client_action_roots if isinstance(client_action_roots, dict) else {}
    mirror_action_roots = target.get("actionMirrorRoots", {})
    mirror_action_roots = mirror_action_roots if isinstance(mirror_action_roots, dict) else {}
    target_hashes: dict[str, str | None] = {}
    if not static_targets: blockers.append("target.staticTargets不能为空")
    static_seen: set[str] = set()
    for entry in static_targets:
        try:
            wzl, wzx = Path(str(entry["wzl"])).resolve(), Path(str(entry["wzx"])).resolve()
            if str(entry["library"]) not in {"Items", "DnItems", "StateItem"}: raise ValueError("static library必须为Items/DnItems/StateItem")
            if _overlaps(output_root, wzl) or _overlaps(output_root, wzx): raise ValueError("outputRoot不得覆盖静态目标")
            if str(wzl) in static_seen or str(wzx) in static_seen: raise ValueError("静态目标重复")
            static_seen.update((str(wzl), str(wzx)))
            count = _count(wzx)
            expected_count = int(entry["expectedCount"])
            if expected_count != int(config["startLooks"]): raise ValueError("每个静态库expectedCount必须等于startLooks")
            if _wzl_count(wzl) != count: raise ValueError("WZL/WZX槽数不一致")
            if count != expected_count and not (existing and count == expected_count + len(resources)):
                raise ValueError(f"库长度{count}不等于期望{expected_count}")
            target_hashes[str(wzl)] = _hash(wzl); target_hashes[str(wzx)] = _hash(wzx)
        except (KeyError, OSError, ValueError) as exc:
            blockers.append(f"静态目标无效: {exc}")
    required_static = {(role, library) for role in ("client-static", "launcher-patch") for library in ("Items", "DnItems", "StateItem")}
    actual_static = {(str(item.get("role")), str(item.get("library"))) for item in static_targets if isinstance(item, dict)}
    if actual_static != required_static or len(static_targets) != len(actual_static):
        blockers.append("staticTargets必须唯一且完整包含客户端/补丁源的Items、DnItems、StateItem")
    used_shapes: dict[str, set[int]] = {library: set(reserved_shapes) for library in action_libraries}
    for library in action_libraries:
        client_roots, mirror_roots = client_action_roots.get(library, []), mirror_action_roots.get(library, [])
        if not isinstance(client_roots, list) or not isinstance(mirror_roots, list):
            blockers.append(f"动作目标目录必须为数组: {library}")
            continue
        roots = client_roots + mirror_roots
        if not roots or not all(isinstance(item, str) and item for item in roots):
            blockers.append(f"动作库缺少目标目录: {library}")
            continue
        seen_roots: set[str] = set()
        for raw in roots:
            root = Path(str(raw)).resolve()
            if str(root) in seen_roots:
                blockers.append(f"动作目标目录重复: {root}")
                continue
            seen_roots.add(str(root))
            if _overlaps(output_root, root) or not root.parent.is_dir():
                blockers.append(f"动作目标目录无效: {root}")
                continue
            for asset in root.iterdir() if root.is_dir() else []:
                if asset.is_file() and asset.suffix.lower() in {".wil", ".wix"} and asset.stem.isdigit():
                    used_shapes[library].add(int(asset.stem)); target_hashes[str(asset.resolve())] = _hash(asset)
    if existing:
        receipt_path, receipt = existing
        expected_files = receipt.get("expectedFiles") if isinstance(receipt.get("expectedFiles"), list) else []
        if receipt.get("sourceHashes") != source_hashes:
            blockers.append("已安装追加事务的来源发生漂移")
        for item in expected_files:
            live = Path(str(item.get("target", "")))
            if not live.is_file() or _hash(live) != item.get("after"):
                blockers.append(f"已安装追加目标漂移: {live}")
        return {"mode": "equipment-graphics-append-preflight", "blockers": blockers, "configHash": config_hash,
                "sourceHashes": source_hashes, "targetHashes": target_hashes, "resourceMap": receipt.get("resourceMap", []),
                "databaseAccess": [], "isNoop": not blockers, "receiptPath": str(receipt_path)}
    if blockers:
        return {"mode": "equipment-graphics-append-preflight", "blockers": blockers, "configHash": config_hash,
                "sourceHashes": source_hashes, "targetHashes": target_hashes, "resourceMap": [],
                "databaseAccess": [], "isNoop": False}
    next_asset_id = {library: int(config.get("shapeStart", 1400)) for library in action_libraries}
    resource_map = []
    for offset, resource in enumerate(resources):
        library = resource.get("action", {}).get("library")
        while next_asset_id[library] in used_shapes[library]: next_asset_id[library] += 1
        action_asset_id = next_asset_id[library]
        resource_map.append({"name": resource.get("name"), "looks": int(config.get("startLooks", 0)) + offset,
                             "actionAssetId": action_asset_id, "library": library})
        used_shapes[library].add(action_asset_id); next_asset_id[library] += 1
    # Freeze every exact numeric output path before construction.  These are
    # intentionally absent for a first append; a file that appears later is
    # an external change, never a new baseline to accept.
    for mapped in resource_map:
        library = str(mapped["library"])
        roots = list(client_action_roots.get(library, [])) + list(mirror_action_roots.get(library, []))
        for raw_root in roots:
            for suffix in (".wil", ".wix"):
                action_target = (Path(raw_root) / f"{mapped['actionAssetId']}{suffix}").resolve()
                target_hashes[str(action_target)] = _hash(action_target) if action_target.is_file() else None
    return {"mode": "equipment-graphics-append-preflight", "blockers": blockers, "configHash": config_hash,
            "sourceHashes": source_hashes, "targetHashes": target_hashes, "resourceMap": resource_map,
            "databaseAccess": [], "isNoop": False}


def append_apply(config_path: Path | str) -> dict[str, object]:
    plan = append_preflight(config_path)
    if plan.get("blockers"):
        raise EquipmentGraphicsAppendError("预检阻止追加: " + "; ".join(plan["blockers"]))
    if plan.get("isNoop"):
        return {"receiptPath": plan["receiptPath"], "status": "noop"}
    path = Path(config_path).resolve()
    config = json.loads(path.read_text(encoding="utf-8")); output_root = Path(config["outputRoot"]).resolve()
    resources, resource_map = config["resources"], plan["resourceMap"]
    prepared_root = output_root / "prepared" / uuid.uuid4().hex
    prepared_root.mkdir(parents=True, exist_ok=False)
    prepared: list[dict[str, object]] = []
    static_reports: list[dict[str, object]] = []
    for entry in config["target"]["staticTargets"]:
        wzl, wzx = Path(entry["wzl"]), Path(entry["wzx"])
        candidate_wzl, candidate_wzx = prepared_root / f"static_{len(static_reports):02d}.wzl", prepared_root / f"static_{len(static_reports):02d}.wzx"
        library = entry["library"]
        image_key, placement_key = ("innerImage", "innerPlacement") if library == "StateItem" else ("bagImage", "bagPlacement")
        appends = [{"image": resource["sources"][image_key], "placement": resource["static"].get(placement_key, [0, 0]), "alpha_cutoff": config["encoding"].get("alphaCutoff", 128)} for resource in resources]
        report = append_static_pair(wzl, wzx, appends, candidate_wzl, candidate_wzx, expected_count=int(entry["expectedCount"]))
        static_reports.append({"name": entry["name"], **report})
        for candidate, target in ((candidate_wzl, wzl), (candidate_wzx, wzx)):
            prepared.append({"candidate": str(candidate), "target": str(target), "candidateSha256": _hash(candidate), "targetSha256": plan["targetHashes"][str(target.resolve())], "role": entry["role"]})
    for resource, mapped in zip(resources, resource_map):
        action = resource["action"]; library = action["library"]
        candidate_wil, candidate_wix = prepared_root / f"{library}_{mapped['actionAssetId']}.wil", prepared_root / f"{library}_{mapped['actionAssetId']}.wix"
        build_action_wil_wix(kind=action["kind"], source_root=Path(resource["sources"]["actionFrames"]), output_wil=candidate_wil, output_wix=candidate_wix,
                             frame_count=int(action["frameCount"]), source_filename_digits=int(action.get("sourceFrameDigits", 6)),
                             alpha_cutoff=int(config["encoding"].get("alphaCutoff", 128)), treat_one_by_one_as_empty=bool(action.get("treatOneByOneAsEmpty", True)))
        for role, roots in (("client-action", config["target"].get("clientActionRoots", config["target"].get("actionRoots", {})).get(library, [])), ("action-mirror", config["target"].get("actionMirrorRoots", {}).get(library, []))):
            for root in roots:
                for candidate in (candidate_wil, candidate_wix):
                    target = Path(root) / f"{mapped['actionAssetId']}{candidate.suffix}"
                    prepared.append({"candidate": str(candidate), "target": str(target), "candidateSha256": _hash(candidate), "targetSha256": plan["targetHashes"][str(target.resolve())], "role": role})
    if _hash(path) != plan["configHash"] or _source_hashes(path, resources, config.get("reservedShapesEvidence")) != plan["sourceHashes"]:
        raise EquipmentGraphicsAppendError("构建期间配置或来源发生漂移")
    for target, digest in plan["targetHashes"].items():
        live = Path(target)
        if digest is None:
            if live.exists():
                raise EquipmentGraphicsAppendError(f"构建期间出现新目标: {target}")
        elif not live.is_file() or _hash(live) != digest:
            raise EquipmentGraphicsAppendError(f"构建期间目标发生漂移: {target}")
    grouped_payloads: dict[str, list[list[str]]] = {}
    for entry, report in zip(config["target"]["staticTargets"], static_reports):
        grouped_payloads.setdefault(entry["library"], []).append([item["payloadSha256"] for item in report["appended"]])
    for library, payload_sets in grouped_payloads.items():
        if any(payloads != payload_sets[0] for payloads in payload_sets[1:]):
            raise EquipmentGraphicsAppendError(f"两端新增静态payload不一致: {library}")
    try:
        return apply_append_prepared(output_root=output_root, config_hash=plan["configHash"], source_hashes=plan["sourceHashes"], resource_map=resource_map, prepared=prepared, static_reports=static_reports)
    except TransactionError as exc:
        raise EquipmentGraphicsAppendError(str(exc)) from exc


def append_rollback(receipt_path: Path | str) -> dict[str, object]:
    try:
        return rollback_append_receipt(Path(receipt_path))
    except TransactionError as exc:
        raise EquipmentGraphicsAppendError(str(exc)) from exc
