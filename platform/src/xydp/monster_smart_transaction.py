from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .monster_engine import RESOURCE_KEYS, EngineDependency, parse_effect_image_list, rewrite_smartmonster_ini


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return _sha256_bytes(path.read_bytes())


@dataclass(frozen=True)
class SmartGeneratedFile:
    target_path: str
    content: bytes
    after_hash: str
    kind: str = ""
    companion_hash: str | None = None
    pak_password: str | None = None


@dataclass(frozen=True)
class SmartMonsterBatchPlan:
    effect_list_after: bytes
    generated_files: tuple[SmartGeneratedFile, ...]
    resource_mappings: tuple[dict[str, object], ...]
    blockers: tuple[str, ...]
    effect_list_path: str = ""
    effect_list_before_hash: str = ""

    def assert_effect_list_unchanged(self) -> None:
        """Reject a candidate once its zero-based allocation input has drifted."""
        current = _sha256_file(Path(self.effect_list_path))
        if current != self.effect_list_before_hash:
            raise RuntimeError(f"EffectImageList预检后发生漂移：{self.effect_list_path}")


def target_resource_entry(monster_id: int, ordinal: int, source: EngineDependency) -> str:
    suffix = Path(source.entry).suffix.lower()
    return f"XY_MonV3_{int(monster_id)}_{int(ordinal)}_{source.source_hash[:8]}{suffix}"


def _inside(root: Path, candidate: Path) -> Path | None:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _resource_paths(client_data: Path, entry: str, dependency: EngineDependency) -> tuple[Path, ...] | None:
    primary = _inside(client_data, client_data / entry)
    if primary is None:
        return None
    if dependency.kind == "wzl_wzx":
        if primary.suffix.casefold() != ".wzl":
            return None
        return primary, primary.with_suffix(".wzx")
    if dependency.kind == "pak":
        if primary.suffix.casefold() != ".pak":
            return None
        return (primary,)
    return None


def _source_payloads(dependency: EngineDependency) -> tuple[bytes, ...]:
    primary = Path(dependency.source_path)
    payloads = [primary.read_bytes()]
    if _sha256_bytes(payloads[0]) != dependency.source_hash:
        raise RuntimeError(f"供体资源哈希漂移：{primary}")
    if dependency.kind == "wzl_wzx":
        if not dependency.companion_path or not dependency.companion_hash:
            raise RuntimeError(f"WZL缺少WZX伴随资源：{primary}")
        companion = Path(dependency.companion_path)
        payload = companion.read_bytes()
        if _sha256_bytes(payload) != dependency.companion_hash:
            raise RuntimeError(f"供体伴随资源哈希漂移：{companion}")
        payloads.append(payload)
    return tuple(payloads)


def _dependency_key(dependency: EngineDependency) -> tuple[str, str, str | None, str | None]:
    return dependency.kind, dependency.source_hash, dependency.companion_hash, dependency.pak_password


def _dependency_order_key(dependency: EngineDependency) -> tuple[int, str, str, str, str, str]:
    return (
        int(dependency.source_index),
        dependency.kind,
        dependency.entry.casefold(),
        dependency.source_hash,
        dependency.companion_hash or "",
        dependency.pak_password or "",
    )


def _dependency_items(
    records: Sequence[object], dependencies: Mapping[int, Iterable[EngineDependency]], blockers: list[str]
) -> list[tuple[object, int, EngineDependency]]:
    items: list[tuple[object, int, EngineDependency]] = []
    for record in records:
        monster_id = int(getattr(record, "monster_id"))
        source = list(dependencies.get(monster_id, ()))
        if not source:
            blockers.append(f"{getattr(record, 'monster_name')}：缺少SmartMonster资源依赖")
            continue
        has_stable_ordinals = all(getattr(dependency, "ordinal", None) is not None for dependency in source)
        if has_stable_ordinals:
            ordered = sorted(source, key=lambda dependency: (int(dependency.ordinal), _dependency_order_key(dependency)))
        else:
            ordered = sorted(source, key=_dependency_order_key)
        for fallback_ordinal, dependency in enumerate(ordered):
            ordinal = int(dependency.ordinal) if has_stable_ordinals else fallback_ordinal
            items.append((record, ordinal, dependency))
    return items


def _append_effect_entries(raw: bytes, encoding: str, bom: bytes, newline: str, entries: Sequence[str]) -> bytes:
    if not entries:
        return raw
    newline_bytes = newline.encode(encoding)
    prefix = raw
    if prefix != bom and prefix and not (prefix.endswith(b"\r") or prefix.endswith(b"\n")):
        prefix += newline_bytes
    return prefix + newline.join(entries).encode(encoding) + newline_bytes


def _existing_matching_index(
    lines: Sequence[str], client_data: Path, dependency: EngineDependency
) -> int | None:
    expected = (dependency.source_hash, dependency.companion_hash)
    for index, entry in enumerate(lines):
        paths = _resource_paths(client_data, entry.strip(), dependency)
        if paths is None or not all(path.is_file() for path in paths):
            continue
        hashes = tuple(_sha256_file(path) for path in paths)
        if hashes == expected[:len(hashes)]:
            return index
    return None


def _registered_resource_blockers(lines: Sequence[str], client_data: Path) -> list[str]:
    blockers: list[str] = []
    for entry in lines:
        name = entry.strip()
        if not name:
            continue
        path = _inside(client_data, client_data / name)
        if path is None:
            blockers.append(f"{name}：EffectImageList登记资源路径越界")
            continue
        suffix = path.suffix.casefold()
        if suffix == ".wzl":
            files = (path, path.with_suffix(".wzx"))
        elif suffix == ".wzx":
            files = (path.with_suffix(".wzl"), path)
        elif suffix == ".pak":
            files = (path,)
        else:
            continue
        exists = tuple(file.is_file() for file in files)
        if not any(exists):
            blockers.append(f"{name}：EffectImageList已登记但目标资源缺失")
        elif not all(exists):
            blockers.append(f"{name}：目标资源对不完整")
    return blockers


_RESOURCE_REFERENCE = re.compile(
    r"^\s*(?P<key>" + "|".join(re.escape(key) for key in RESOURCE_KEYS) + r")\s*=\s*(?P<value>-?\d+)"
)


def _resource_references(ini_bytes: bytes) -> list[tuple[str, int]]:
    body = ini_bytes[3:] if ini_bytes.startswith(b"\xef\xbb\xbf") else ini_bytes
    for encoding in ("utf-8", "gb18030"):
        try:
            text = body.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("SmartMonster INI文本编码无法识别")
    references: list[tuple[str, int]] = []
    for line in text.splitlines():
        match = _RESOURCE_REFERENCE.match(line)
        if match is not None:
            references.append((match.group("key"), int(match.group("value"))))
    return references


def _validate_rewritten_references(before: bytes, after: bytes, source_to_target: Mapping[int, int]) -> None:
    before_refs = _resource_references(before)
    after_refs = _resource_references(after)
    if len(before_refs) != len(after_refs):
        raise RuntimeError("SmartMonster INI资源引用数量变化")
    for (before_key, source_index), (after_key, target_index) in zip(before_refs, after_refs):
        if before_key != after_key:
            raise RuntimeError("SmartMonster INI资源引用键变化")
        expected = source_index if source_index < 0 else source_to_target.get(source_index)
        if expected is None:
            raise RuntimeError(f"资源引用缺少目标映射：{source_index}")
        if target_index != expected:
            raise RuntimeError(f"SmartMonster INI资源引用未正确重写：{before_key}={source_index}")


def build_smartmonster_batch(
    records: Iterable[object],
    dependencies: Mapping[int, Iterable[EngineDependency]],
    server_root: Path,
    client_data: Path,
) -> SmartMonsterBatchPlan:
    """Build deterministic SmartMonster candidate bytes without writing any endpoint."""
    server_root = Path(server_root).resolve()
    client_data = Path(client_data).resolve()
    effect_path = server_root / "Mir200" / "Envir" / "EffectImageList.txt"
    smart_root = server_root / "Mir200" / "Envir" / "SmartMonster"
    blockers: list[str] = []
    if not server_root.is_dir():
        blockers.append(f"目标服务端不存在：{server_root}")
    if not client_data.is_dir():
        blockers.append(f"目标客户端data不存在：{client_data}")
    if not effect_path.is_file():
        blockers.append(f"目标服缺少EffectImageList：{effect_path}")
    if not smart_root.is_dir():
        blockers.append(f"目标服缺少SmartMonster目录：{smart_root}")
    if blockers:
        return SmartMonsterBatchPlan(b"", (), (), tuple(blockers), str(effect_path), "")

    document = parse_effect_image_list(effect_path)
    before_hash = _sha256_bytes(document.raw)
    blockers.extend(_registered_resource_blockers(document.lines, client_data))
    ordered_records = tuple(sorted(
        records,
        key=lambda record: (int(getattr(record, "monster_id")), str(getattr(record, "monster_name")).casefold()),
    ))
    for record in ordered_records:
        if getattr(record, "engine_mode", "smartmonster") != "smartmonster":
            blockers.append(f"{getattr(record, 'monster_name')}：不是SmartMonster闭包")
        if getattr(record, "closure_status", "ready_verified") not in {"ready_verified", "ready_opaque"}:
            blockers.append(f"{getattr(record, 'monster_name')}：闭包状态不可候选")
        name = str(getattr(record, "monster_name"))
        target_ini = _inside(smart_root, smart_root / f"{name}.ini")
        if target_ini is None:
            blockers.append(f"{name}：目标INI路径越界")
    items = _dependency_items(ordered_records, dependencies, blockers)
    if blockers:
        return SmartMonsterBatchPlan(document.raw, (), (), tuple(blockers), str(effect_path), before_hash)

    units: dict[tuple[str, str, str | None, str | None], tuple[object, int, EngineDependency]] = {}
    for record, ordinal, dependency in items:
        units.setdefault(_dependency_key(dependency), (record, ordinal, dependency))

    generated: list[SmartGeneratedFile] = []
    resource_indices: dict[tuple[str, str, str | None, str | None], int] = {}
    resource_entries: dict[tuple[str, str, str | None, str | None], str] = {}
    additions: list[str] = []
    line_indices: dict[str, int] = {}
    for index, entry in enumerate(document.lines):
        line_indices.setdefault(entry.strip().casefold(), index)

    for key, (record, ordinal, dependency) in units.items():
        if dependency.kind == "pak" and not dependency.pak_password:
            blockers.append(f"{dependency.entry}：PAK缺少唯一密码规则")
            continue
        entry = target_resource_entry(int(getattr(record, "monster_id")), ordinal, dependency)
        paths = _resource_paths(client_data, entry, dependency)
        if paths is None:
            blockers.append(f"{entry}：目标资源路径或类型无效")
            continue
        existing = tuple(path.is_file() for path in paths)
        line_index = line_indices.get(entry.casefold())
        if any(existing) and not all(existing):
            blockers.append(f"{entry}：目标资源对不完整")
            continue
        if line_index is not None and not all(existing):
            blockers.append(f"{entry}：EffectImageList已登记但目标资源不完整")
            continue
        if all(existing):
            expected = (dependency.source_hash, dependency.companion_hash)
            actual = tuple(_sha256_file(path) for path in paths)
            if actual != expected[:len(actual)]:
                blockers.append(f"{entry}：同名异内容，禁止覆盖")
                continue
            index = line_index if line_index is not None else len(document.lines) + len(additions)
            if line_index is None:
                additions.append(entry)
            resource_indices[key] = index
            resource_entries[key] = entry
            continue
        reused = _existing_matching_index(document.lines, client_data, dependency)
        if reused is not None:
            resource_indices[key] = reused
            resource_entries[key] = document.lines[reused].strip()
            continue
        try:
            payloads = _source_payloads(dependency)
        except (OSError, RuntimeError) as exc:
            blockers.append(str(exc))
            continue
        index = len(document.lines) + len(additions)
        additions.append(entry)
        resource_indices[key] = index
        resource_entries[key] = entry
        for path, payload in zip(paths, payloads):
            generated.append(SmartGeneratedFile(
                str(path), payload, _sha256_bytes(payload), dependency.kind,
                dependency.companion_hash, dependency.pak_password,
            ))

    if blockers:
        return SmartMonsterBatchPlan(document.raw, (), (), tuple(blockers), str(effect_path), before_hash)

    mappings: list[dict[str, object]] = []
    generated_inis: list[SmartGeneratedFile] = []
    for record in ordered_records:
        monster_id = int(getattr(record, "monster_id"))
        name = str(getattr(record, "monster_name"))
        source_ini = Path(str(getattr(record, "smart_ini_path", "")))
        try:
            ini_bytes = source_ini.read_bytes()
            expected_ini_hash = getattr(record, "smart_ini_hash", None)
            if expected_ini_hash and _sha256_bytes(ini_bytes) != expected_ini_hash:
                raise RuntimeError(f"供体INI哈希漂移：{source_ini}")
            source_to_target: dict[int, int] = {}
            for item_record, ordinal, dependency in items:
                if int(getattr(item_record, "monster_id")) != monster_id:
                    continue
                key = _dependency_key(dependency)
                target_index = resource_indices[key]
                prior = source_to_target.setdefault(int(dependency.source_index), target_index)
                if prior != target_index:
                    raise RuntimeError(f"{name}：同一供体资源号映射冲突：{dependency.source_index}")
                mappings.append({
                    "monster_id": monster_id,
                    "ordinal": ordinal,
                    "source_index": int(dependency.source_index),
                    "target_index": target_index,
                    "target_entry": resource_entries[key],
                    "source_hash": dependency.source_hash,
                    "kind": dependency.kind,
                    "companion_hash": dependency.companion_hash,
                    "pak_password": dependency.pak_password,
                })
            rewritten = rewrite_smartmonster_ini(ini_bytes, source_to_target)
            target_ini = _inside(smart_root, smart_root / f"{name}.ini")
            if target_ini is None:
                raise RuntimeError(f"{name}：目标INI路径越界")
            _validate_rewritten_references(ini_bytes, rewritten, source_to_target)
            if target_ini.is_file():
                if _sha256_file(target_ini) != _sha256_bytes(rewritten):
                    raise RuntimeError(f"{name}：同名INI异内容，禁止覆盖")
            else:
                generated_inis.append(SmartGeneratedFile(str(target_ini), rewritten, _sha256_bytes(rewritten)))
        except (OSError, RuntimeError) as exc:
            blockers.append(str(exc))

    if blockers:
        return SmartMonsterBatchPlan(document.raw, (), (), tuple(blockers), str(effect_path), before_hash)
    effect_after = _append_effect_entries(document.raw, document.encoding, document.bom, document.newline, additions)
    generated.sort(key=lambda item: item.target_path.casefold())
    generated.extend(sorted(generated_inis, key=lambda item: item.target_path.casefold()))
    mappings.sort(key=lambda item: (int(item["monster_id"]), int(item["ordinal"]), int(item["source_index"])))
    return SmartMonsterBatchPlan(
        effect_after,
        tuple(generated),
        tuple(mappings),
        (),
        str(effect_path),
        before_hash,
    )
