from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


class TextPatchError(ValueError):
    pass


@dataclass(frozen=True)
class LabelScan:
    labels: dict[str, list[int]]

    @property
    def duplicates(self) -> dict[str, list[int]]:
        return {name: lines for name, lines in self.labels.items() if len(lines) > 1}


@dataclass(frozen=True)
class PatchResult:
    text: str
    changed: bool
    content_hash: str


LABEL_RE = re.compile(r"^\s*\[@([^\]]+)\]\s*$", re.MULTILINE | re.IGNORECASE)


def scan_labels(text: str) -> LabelScan:
    labels: dict[str, list[int]] = {}
    for match in LABEL_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        labels.setdefault(match.group(1).strip().lower(), []).append(line)
    return LabelScan(labels)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


EXTENSION_RE = re.compile(
    r"^; XYDP-EXTENSION-BEGIN ([A-Za-z0-9_.-]+)\r?\n.*?^; XYDP-EXTENSION-END \1\r?$",
    re.MULTILINE | re.DOTALL,
)

ANCHOR_HOOK_RE = re.compile(
    r"^; XYDP-ANCHOR-HOOK-BEGIN ([A-Za-z0-9_.-]+) ([A-Za-z0-9_.-]+) SHA256=[0-9a-f]{64}\r?\n"
    r".*?^; XYDP-ANCHOR-HOOK-END \1 \2\r?\n?",
    re.MULTILINE | re.DOTALL,
)

# 装备工具写入统一出口的固定五行块。它与 extension/anchor-hook 一样属于
# 平台生成的可变内容；只认可严格结构，普通手工脚本仍参与父块哈希校验。
EQUIPMENT_BLOCK_RE = re.compile(
    r"(?:^[ \t]*\r?\n)?"
    r"^; XY-EQUIP-MAKER [^\r\n]+\r?\n"
    r"^#IF\r?\n"
    r"^CHECKITEMW [^\r\n]+ 1\r?\n"
    r"^#ACT\r?\n"
    r"^(?:(?:INC|ChangeDamageValue|MOV) [^\r\n]+|HumanHP \+ [^\r\n]+)\r?\n?",
    re.MULTILINE,
)

EQUIPMENT_ANCHOR_RE = re.compile(
    r"^[ \t]*;[ \t]*(XY_EQUIP_MAKER_[A-Za-z0-9_]+_ANCHOR)[ \t]*\r?$",
    re.MULTILINE,
)


def _managed_hash(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    canonical = EXTENSION_RE.sub(lambda match: f"; XYDP-EXTENSION-BEGIN {match.group(1)}\n; XYDP-EXTENSION-END {match.group(1)}", normalized)
    canonical = ANCHOR_HOOK_RE.sub("", canonical)
    canonical = EQUIPMENT_BLOCK_RE.sub("", canonical)
    return _hash(canonical)


def _merge_extension_zones(template: str, current: str) -> str:
    current_zones = {match.group(1): match.group(0) for match in EXTENSION_RE.finditer(current)}
    return EXTENSION_RE.sub(lambda match: current_zones.get(match.group(1), match.group(0)), template)


def _merge_anchor_hook_zones(template: str, current: str) -> str:
    merged = template
    for match in ANCHOR_HOOK_RE.finditer(current):
        package_id, anchor = match.group(1), match.group(2)
        marker = f"; XYDP-ANCHOR-HOOK-BEGIN {package_id} {anchor} "
        if marker in merged:
            continue
        anchor_re = re.compile(rf"^[ \t]*;[ \t]*{re.escape(anchor)}[ \t]*\r?$", re.MULTILINE)
        anchors = list(anchor_re.finditer(merged))
        if len(anchors) != 1:
            raise TextPatchError(f"升级父受管块时无法唯一恢复锚点钩子: {package_id}/{anchor}")
        insert_at = anchors[0].end() + (1 if merged[anchors[0].end():anchors[0].end() + 1] == "\n" else 0)
        while merged.startswith("; XYDP-ANCHOR-HOOK-BEGIN ", insert_at):
            end_line = re.search(r"^; XYDP-ANCHOR-HOOK-END .+?\r?$", merged[insert_at:], re.MULTILINE)
            if not end_line:
                raise TextPatchError(f"升级父受管块时发现损坏的锚点钩子: {anchor}")
            insert_at += end_line.end()
            if merged[insert_at:insert_at + 1] == "\n":
                insert_at += 1
        merged = merged[:insert_at] + match.group(0) + merged[insert_at:]
    return merged


def _merge_equipment_blocks(
    template: str,
    current: str,
    retired_anchors: tuple[str, ...] = (),
) -> str:
    """按最近的装备锚点恢复平台装备工具生成的五行属性块。"""
    merged = template
    newline = "\r\n" if "\r\n" in template else "\n"
    blocks_by_anchor: dict[str, list[str]] = {}
    for match in EQUIPMENT_BLOCK_RE.finditer(current):
        # 保留装备模板有意放在属性块前的空行，只移除块尾换行。
        block = match.group(0).rstrip("\r\n")
        if block in merged:
            continue
        anchors = list(EQUIPMENT_ANCHOR_RE.finditer(current, 0, match.start()))
        if not anchors:
            raise TextPatchError("升级父受管块时发现装备属性块缺少所属锚点")
        anchor = anchors[-1].group(1)
        if anchor in retired_anchors:
            continue
        blocks_by_anchor.setdefault(anchor, []).append(block)

    # 同一锚点下的多个装备块必须一次性按当前顺序插回。若逐块都插在
    # 锚点后面，第二次预检会把顺序反转，造成永远不幂等的伪变化。
    for anchor, blocks in blocks_by_anchor.items():
        anchor_re = re.compile(rf"^[ \t]*;[ \t]*{re.escape(anchor)}[ \t]*\r?$", re.MULTILINE)
        target_anchors = list(anchor_re.finditer(merged))
        if len(target_anchors) != 1:
            raise TextPatchError(f"升级父受管块时无法唯一恢复装备属性块: {anchor}")
        insert_at = target_anchors[0].end()
        if merged[insert_at:insert_at + 1] == "\n":
            insert_at += 1
        restored = newline.join(blocks) + newline
        merged = merged[:insert_at] + restored + merged[insert_at:]
    return merged


def install_managed_block(
    text: str,
    package_id: str,
    content: str,
    newline: str,
    expected_hash: str | None = None,
    accepted_current_hashes: tuple[str, ...] = (),
    legacy_package_ids: tuple[str, ...] = (),
    retired_equipment_anchors: tuple[str, ...] = (),
) -> PatchResult:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline).strip("\r\n")
    new_hash = _managed_hash(normalized)
    candidates: list[tuple[str, re.Match[str]]] = []
    for candidate_id in (package_id, *legacy_package_ids):
        begin_pattern = re.compile(
            rf"^; XYDP-BEGIN {re.escape(candidate_id)} SHA256=([0-9a-f]{{64}})\r?$",
            re.MULTILINE,
        )
        match = begin_pattern.search(text)
        if match:
            candidates.append((candidate_id, match))
    if len(candidates) > 1:
        found = ", ".join(candidate_id for candidate_id, _ in candidates)
        raise TextPatchError(f"新旧受管块同时存在，禁止自动接管: {found}")
    current_package_id, begin = candidates[0] if candidates else (package_id, None)
    if begin:
        end_pattern = re.compile(rf"^; XYDP-END {re.escape(current_package_id)}\r?$", re.MULTILINE)
        end = end_pattern.search(text, begin.end())
        if not end:
            raise TextPatchError(f"受管块缺少结束标记: {current_package_id}")
        content_start = begin.end()
        if text[content_start:content_start + 1] == "\n":
            content_start += 1
        current = text[content_start:end.start()].rstrip("\r\n")
        marker_hash = begin.group(1)
        current_hash = _managed_hash(current)
        if current_hash != marker_hash and current_hash not in accepted_current_hashes:
            raise TextPatchError(f"受管块被手工修改: {current_package_id}")
        if expected_hash and marker_hash != expected_hash:
            raise TextPatchError(f"受管块版本哈希不匹配: {current_package_id}")
        block_end = end.end() + (1 if text[end.end():end.end() + 1] == "\n" else 0)
        merged = _merge_equipment_blocks(
            _merge_anchor_hook_zones(_merge_extension_zones(normalized, current), current),
            current,
            retired_equipment_anchors,
        )
        replacement = f"; XYDP-BEGIN {package_id} SHA256={new_hash}{newline}{merged}{newline}; XYDP-END {package_id}{newline}"
        old = text[begin.start():block_end]
        return PatchResult(text=text[:begin.start()] + replacement + text[block_end:], changed=old != replacement, content_hash=new_hash)
    block = f"; XYDP-BEGIN {package_id} SHA256={new_hash}{newline}{normalized}{newline}; XYDP-END {package_id}"
    separator = "" if not text else ("" if text.endswith(newline) else newline) + newline
    return PatchResult(text=text + separator + block + newline, changed=True, content_hash=new_hash)


def add_unique_line(text: str, line: str, key_fields: list[int], newline: str) -> PatchResult:
    wanted = line.rstrip("\r\n")
    wanted_fields = wanted.split("\t")
    wanted_key = tuple(wanted_fields[index] for index in key_fields)
    for existing in text.splitlines():
        fields = existing.split("\t")
        if len(fields) <= max(key_fields, default=-1):
            continue
        if tuple(fields[index] for index in key_fields) == wanted_key:
            if existing == wanted:
                return PatchResult(text=text, changed=False, content_hash=_hash(wanted))
            raise TextPatchError(f"唯一键冲突: {wanted_key}")
    prefix = "" if not text or text.endswith(("\n", "\r")) else newline
    return PatchResult(text=text + prefix + wanted + newline, changed=True, content_hash=_hash(wanted))


def set_indexed_text_line(
    text: str,
    line_number: int,
    content: str,
    newline: str,
) -> PatchResult:
    """Set one 1-based TextVar-style row without shifting any existing row."""
    if line_number < 1:
        raise TextPatchError(f"索引文本行号必须大于0: {line_number}")
    wanted = content.rstrip("\r\n")
    if "\r" in wanted or "\n" in wanted:
        raise TextPatchError("索引文本行内容不得包含换行")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    trailing_newline = normalized.endswith("\n")
    rows = normalized.split("\n")
    if trailing_newline:
        rows.pop()
    if len(rows) == 1 and rows[0] == "" and not text:
        rows = []
    while len(rows) < line_number:
        rows.append("")

    current = rows[line_number - 1]
    if current == wanted:
        return PatchResult(text=text, changed=False, content_hash=_hash(wanted))
    if current.strip():
        raise TextPatchError(f"第{line_number}行已被其他内容占用: {current}")
    rows[line_number - 1] = wanted
    result = newline.join(rows) + (newline if trailing_newline else "")
    return PatchResult(text=result, changed=result != text, content_hash=_hash(wanted))


def set_exclusive_unique_line(text: str, line: str, key_fields: list[int], newline: str) -> PatchResult:
    """Replace every line sharing the declared key with exactly one managed line."""
    wanted = line.rstrip("\r\n")
    wanted_fields = wanted.split("\t")
    if not key_fields:
        raise TextPatchError("独占唯一行缺少 key_fields")
    if min(key_fields) < 0 or max(key_fields) >= len(wanted_fields):
        raise TextPatchError(f"独占唯一行 key_fields 越界: {key_fields}")
    wanted_key = tuple(wanted_fields[index] for index in key_fields)
    lines = text.splitlines()
    matching_indexes: list[int] = []
    for index, existing in enumerate(lines):
        fields = existing.split("\t")
        if len(fields) <= max(key_fields):
            continue
        if tuple(fields[field] for field in key_fields) == wanted_key:
            matching_indexes.append(index)

    if len(matching_indexes) == 1 and lines[matching_indexes[0]] == wanted:
        return PatchResult(text=text, changed=False, content_hash=_hash(wanted))

    if matching_indexes:
        first_match = matching_indexes[0]
        matching_set = set(matching_indexes)
        retained = [existing for index, existing in enumerate(lines) if index not in matching_set]
        insert_at = sum(1 for index in range(first_match) if index not in matching_set)
        retained.insert(insert_at, wanted)
    else:
        retained = [*lines, wanted]
    result = newline.join(retained) + newline
    return PatchResult(text=result, changed=result != text, content_hash=_hash(wanted))


def ensure_mapinfo_flag(text: str, map_id: str, flag: str) -> PatchResult:
    """Append one whole-map flag to exactly one MapInfo definition.

    The definition header and every existing flag are preserved byte-for-byte at
    text level.  Only the requested token is appended before the original line
    ending.  ``SAFE(10,10,5)`` is intentionally different from the whole-map
    ``SAFE`` token.
    """
    wanted_map = map_id.strip()
    wanted_flag = flag.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", wanted_map):
        raise TextPatchError(f"MapInfo 地图代码无效: {map_id}")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\([^()\r\n]*\))?", wanted_flag):
        raise TextPatchError(f"MapInfo 标记无效: {flag}")

    lines = text.splitlines(keepends=True)
    matching_indexes: list[int] = []
    for index, raw in enumerate(lines):
        content = raw.rstrip("\r\n")
        match = re.match(r"^\s*\[([^\]]+)]", content)
        if not match:
            continue
        inside = match.group(1).strip()
        logical = inside.split("|", 1)[0].strip() if "|" in inside else inside.split(maxsplit=1)[0]
        if logical.casefold() == wanted_map.casefold():
            matching_indexes.append(index)

    if not matching_indexes:
        raise TextPatchError(f"MapInfo 找不到地图代码: {wanted_map}")
    if len(matching_indexes) > 1:
        raise TextPatchError(f"MapInfo 地图代码不唯一: {wanted_map}")

    index = matching_indexes[0]
    raw = lines[index]
    content = raw.rstrip("\r\n")
    line_ending = raw[len(content):]
    header_end = content.find("]")
    tail = content[header_end + 1:]
    if re.search(rf"(?<!\S){re.escape(wanted_flag)}(?!\S)", tail, re.IGNORECASE):
        return PatchResult(text=text, changed=False, content_hash=_hash(f"{wanted_map}:{wanted_flag}"))

    stripped = content.rstrip(" \t")
    trailing_space = content[len(stripped):]
    lines[index] = f"{stripped} {wanted_flag}{trailing_space}{line_ending}"
    result = "".join(lines)
    return PatchResult(text=result, changed=True, content_hash=_hash(f"{wanted_map}:{wanted_flag}"))


def set_mapinfo_display_name(text: str, map_id: str, display_name: str) -> PatchResult:
    """Replace only the display title in one MapInfo registration header.

    Logical map id, physical MAP alias, flags, whitespace outside the title and
    the original line ending are preserved.  A missing or duplicate map id is a
    hard error so a batch cannot silently rename the wrong registration.
    """
    wanted_map = map_id.strip()
    wanted_title = display_name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", wanted_map):
        raise TextPatchError(f"MapInfo 地图代码无效: {map_id}")
    if not wanted_title or len(wanted_title) > 80 or any(char in wanted_title for char in "[]\r\n\t"):
        raise TextPatchError(f"MapInfo 外显名称无效: {display_name}")

    lines = text.splitlines(keepends=True)
    matches: list[tuple[int, re.Match[str]]] = []
    header_pattern = re.compile(r"^(?P<lead>\s*\[)(?P<header>[^\]]+)(?P<close>\])(?P<tail>.*)$")
    for index, raw in enumerate(lines):
        content = raw.rstrip("\r\n")
        match = header_pattern.match(content)
        if not match:
            continue
        header = match.group("header")
        logical = header.split("|", 1)[0].strip().split(maxsplit=1)[0]
        if logical.casefold() == wanted_map.casefold():
            matches.append((index, match))

    if not matches:
        raise TextPatchError(f"MapInfo 找不到地图代码: {wanted_map}")
    if len(matches) > 1:
        raise TextPatchError(f"MapInfo 地图代码不唯一: {wanted_map}")

    index, match = matches[0]
    raw = lines[index]
    content = raw.rstrip("\r\n")
    line_ending = raw[len(content):]
    header = match.group("header")
    identity_match = re.match(r"^(?P<identity>\s*[^\s|]+(?:\|[^\s]+)?)(?P<spacing>\s*)(?P<title>.*)$", header)
    if not identity_match:
        raise TextPatchError(f"MapInfo 注册行格式无法识别: {wanted_map}")
    spacing = identity_match.group("spacing") or " "
    replacement_header = f"{identity_match.group('identity')}{spacing}{wanted_title}"
    replacement = (
        f"{match.group('lead')}{replacement_header}{match.group('close')}"
        f"{match.group('tail')}{line_ending}"
    )
    if replacement == raw:
        return PatchResult(text=text, changed=False, content_hash=_hash(f"{wanted_map}:{wanted_title}"))
    lines[index] = replacement
    return PatchResult(
        text="".join(lines),
        changed=True,
        content_hash=_hash(f"{wanted_map}:{wanted_title}"),
    )


def ensure_event_label(text: str, package_id: str, label: str, newline: str) -> PatchResult:
    """在事件缺失时创建最小受管事件桩；已有目标事件绝不改写。"""
    body = f"[@{label}]{newline}#IF{newline}#ACT{newline}BREAK"
    content_hash = _managed_hash(body)
    labels = scan_labels(text).labels.get(label.lower(), [])
    if len(labels) > 1:
        raise TextPatchError(f"事件标签不唯一: [@{label}] {labels}")
    begin_re = re.compile(
        rf"^; XYDP-EVENT-STUB-BEGIN {re.escape(package_id)} {re.escape(label)} SHA256=([0-9a-f]{{64}})\r?$",
        re.MULTILINE | re.IGNORECASE,
    )
    begin = begin_re.search(text)
    if begin:
        end_re = re.compile(
            rf"^; XYDP-EVENT-STUB-END {re.escape(package_id)} {re.escape(label)}\r?$",
            re.MULTILINE | re.IGNORECASE,
        )
        end = end_re.search(text, begin.end())
        if not end or len(labels) != 1:
            raise TextPatchError(f"基础事件桩损坏: {package_id}/{label}")
        start = begin.end() + (1 if text[begin.end():begin.end() + 1] == "\n" else 0)
        current = text[start:end.start()].rstrip("\r\n")
        # 事件钩子必须紧随标签插入；校验基础事件桩时排除这些各自受管的钩子。
        without_hooks = re.sub(
            r"^; XYDP-HOOK-BEGIN [^\r\n]+\r?\n.*?^; XYDP-HOOK-END [^\r\n]+\r?\n?",
            "",
            current,
            flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
        ).rstrip("\r\n")
        if _managed_hash(without_hooks) != begin.group(1):
            raise TextPatchError(f"基础事件桩被手工修改: {package_id}/{label}")
        if begin.group(1) != content_hash:
            raise TextPatchError(f"基础事件桩版本哈希不匹配: {package_id}/{label}")
        return PatchResult(text=text, changed=False, content_hash=content_hash)
    if labels:
        return PatchResult(text=text, changed=False, content_hash=content_hash)
    block = (
        f"; XYDP-EVENT-STUB-BEGIN {package_id} {label} SHA256={content_hash}{newline}"
        f"{body}{newline}; XYDP-EVENT-STUB-END {package_id} {label}"
    )
    separator = "" if not text else ("" if text.endswith(newline) else newline) + newline
    return PatchResult(text=text + separator + block + newline, changed=True, content_hash=content_hash)


def ensure_callable_label(text: str, package_id: str, label: str, newline: str) -> PatchResult:
    """确保 ``#CALL [file] @label`` 的目标是带花括号的可调用子程序。

    普通 QFunction 事件不能强行加花括号，因此该能力与
    :func:`ensure_event_label` 分离。已有无括号标签只在正文确认为平台的
    最小 ``#IF/#ACT/BREAK`` 空桩时迁移，避免猜测包裹用户脚本。
    """
    body = f"[@{label}]{newline}{{{newline}#IF{newline}#ACT{newline}BREAK{newline}}}"
    content_hash = _managed_hash(body)
    labels = scan_labels(text).labels.get(label.lower(), [])
    if len(labels) > 1:
        raise TextPatchError(f"可调用标签不唯一: [@{label}] {labels}")

    begin_re = re.compile(
        rf"^; XYDP-CALLABLE-STUB-BEGIN {re.escape(package_id)} {re.escape(label)} SHA256=([0-9a-f]{{64}})\r?$",
        re.MULTILINE | re.IGNORECASE,
    )
    begin = begin_re.search(text)
    if begin:
        end_re = re.compile(
            rf"^; XYDP-CALLABLE-STUB-END {re.escape(package_id)} {re.escape(label)}\r?$",
            re.MULTILINE | re.IGNORECASE,
        )
        end = end_re.search(text, begin.end())
        if not end or len(labels) != 1:
            raise TextPatchError(f"可调用空桩损坏: {package_id}/{label}")
        start = begin.end() + (1 if text[begin.end():begin.end() + 1] == "\n" else 0)
        current = text[start:end.start()].rstrip("\r\n")
        without_hooks = re.sub(
            r"^; XYDP-HOOK-BEGIN [^\r\n]+\r?\n.*?^; XYDP-HOOK-END [^\r\n]+\r?\n?",
            "",
            current,
            flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
        ).rstrip("\r\n")
        if _managed_hash(without_hooks) != begin.group(1):
            raise TextPatchError(f"可调用空桩被手工修改: {package_id}/{label}")
        if begin.group(1) != content_hash:
            raise TextPatchError(f"可调用空桩版本哈希不匹配: {package_id}/{label}")
        return PatchResult(text=text, changed=False, content_hash=content_hash)

    if labels:
        label_re = re.compile(rf"^[ \t]*\[@{re.escape(label)}\][ \t]*\r?$", re.MULTILINE | re.IGNORECASE)
        match = label_re.search(text)
        assert match is not None
        section_start = match.end() + (1 if text[match.end():match.end() + 1] == "\n" else 0)
        next_label = LABEL_RE.search(text, section_start)
        section_end = next_label.start() if next_label else len(text)
        section = text[section_start:section_end]
        significant = [line.strip() for line in section.splitlines() if line.strip()]
        if significant and significant[0] == "{":
            if significant[-1] != "}":
                raise TextPatchError(f"可调用标签缺少结束花括号: [@{label}]")
            return PatchResult(text=text, changed=False, content_hash=content_hash)

        without_hooks = re.sub(
            r"^; XYDP-HOOK-BEGIN [^\r\n]+\r?\n.*?^; XYDP-HOOK-END [^\r\n]+\r?\n?",
            "",
            section,
            flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        effective = [
            line.strip()
            for line in without_hooks.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line.strip() and not line.lstrip().startswith(";")
        ]
        if effective != ["#IF", "#ACT", "BREAK"]:
            raise TextPatchError(f"无法安全迁移为可调用标签: [@{label}]")
        inner = section.strip("\r\n")
        replacement = f"{{{newline}{inner}{newline}}}{newline}"
        return PatchResult(
            text=text[:section_start] + replacement + text[section_end:],
            changed=True,
            content_hash=content_hash,
        )

    block = (
        f"; XYDP-CALLABLE-STUB-BEGIN {package_id} {label} SHA256={content_hash}{newline}"
        f"{body}{newline}; XYDP-CALLABLE-STUB-END {package_id} {label}"
    )
    separator = "" if not text else ("" if text.endswith(newline) else newline) + newline
    return PatchResult(text=text + separator + block + newline, changed=True, content_hash=content_hash)


def install_event_hook(
    text: str,
    package_id: str,
    label: str,
    content: str,
    newline: str,
    legacy_package_ids: tuple[str, ...] = (),
) -> PatchResult:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline).strip("\r\n")
    content_hash = _managed_hash(normalized)
    candidates: list[tuple[str, re.Match[str]]] = []
    for candidate_id in (package_id, *legacy_package_ids):
        begin_re = re.compile(
            rf"^; XYDP-HOOK-BEGIN {re.escape(candidate_id)} {re.escape(label)} SHA256=([0-9a-f]{{64}})\r?$",
            re.MULTILINE | re.IGNORECASE,
        )
        begin = begin_re.search(text)
        if begin:
            candidates.append((candidate_id, begin))
    if len(candidates) > 1:
        found = ", ".join(candidate_id for candidate_id, _ in candidates)
        raise TextPatchError(f"新旧事件钩子同时存在，禁止自动接管: {found}/{label}")
    current_package_id, begin = candidates[0] if candidates else (package_id, None)
    if begin:
        end_re = re.compile(
            rf"^; XYDP-HOOK-END {re.escape(current_package_id)} {re.escape(label)}\r?$",
            re.MULTILINE | re.IGNORECASE,
        )
        end = end_re.search(text, begin.end())
        if not end:
            raise TextPatchError(f"事件钩子缺少结束标记: {current_package_id}/{label}")
        start = begin.end() + (1 if text[begin.end():begin.end() + 1] == "\n" else 0)
        current = text[start:end.start()].rstrip("\r\n")
        if _managed_hash(current) != begin.group(1):
            raise TextPatchError(f"事件钩子被手工修改: {current_package_id}/{label}")
        block_end = end.end() + (1 if text[end.end():end.end() + 1] == "\n" else 0)
        merged = _merge_equipment_blocks(
            _merge_anchor_hook_zones(_merge_extension_zones(normalized, current), current),
            current,
        )
        replacement = (
            f"; XYDP-HOOK-BEGIN {package_id} {label} SHA256={content_hash}{newline}"
            f"{merged}{newline}; XYDP-HOOK-END {package_id} {label}{newline}"
        )
        old = text[begin.start():block_end]
        return PatchResult(text[:begin.start()] + replacement + text[block_end:], old != replacement, content_hash)
    label_re = re.compile(rf"^[ \t]*\[@{re.escape(label)}\][ \t]*\r?$", re.MULTILINE | re.IGNORECASE)
    matches = list(label_re.finditer(text))
    if not matches:
        raise TextPatchError(f"找不到事件标签: [@{label}]")
    if len(matches) != 1:
        lines = [text.count("\n", 0, item.start()) + 1 for item in matches]
        raise TextPatchError(f"事件标签不唯一: [@{label}] {lines}")
    insert_at = matches[0].end() + (1 if text[matches[0].end():matches[0].end() + 1] == "\n" else 0)
    callable_open = re.match(r"[ \t]*\{[ \t]*(?:\r?\n|$)", text[insert_at:])
    if callable_open:
        insert_at += callable_open.end()
    while text.startswith("; XYDP-HOOK-BEGIN ", insert_at):
        end_line = re.search(r"^; XYDP-HOOK-END .+?\r?$", text[insert_at:], re.MULTILINE)
        if not end_line:
            raise TextPatchError(f"事件标签 [@{label}] 下存在损坏的受管钩子")
        insert_at += end_line.end()
        if text[insert_at:insert_at + 1] == "\n":
            insert_at += 1
    block = (
        f"; XYDP-HOOK-BEGIN {package_id} {label} SHA256={content_hash}{newline}"
        f"{normalized}{newline}; XYDP-HOOK-END {package_id} {label}{newline}"
    )
    return PatchResult(text[:insert_at] + block + text[insert_at:], True, content_hash)


def remove_event_hook(
    text: str,
    owner_package_id: str,
    label: str,
    newline: str,
    accepted_current_hashes: tuple[str, ...],
) -> PatchResult:
    """按已知正文哈希安全移除一个旧事件钩子；不存在时保持幂等。"""
    begin_re = re.compile(
        rf"^; XYDP-HOOK-BEGIN {re.escape(owner_package_id)} {re.escape(label)} SHA256=([0-9a-f]{{64}})\r?$",
        re.MULTILINE | re.IGNORECASE,
    )
    begins = list(begin_re.finditer(text))
    identity_hash = _hash(f"{owner_package_id}:{label}")
    if not begins:
        return PatchResult(text=text, changed=False, content_hash=identity_hash)
    if len(begins) > 1:
        raise TextPatchError(f"事件钩子标记不唯一: {owner_package_id}/{label}")
    begin = begins[0]
    marker_hash = begin.group(1).lower()
    if marker_hash not in accepted_current_hashes:
        raise TextPatchError(f"旧事件钩子版本不在允许移除范围: {owner_package_id}/{label}")
    end_re = re.compile(
        rf"^; XYDP-HOOK-END {re.escape(owner_package_id)} {re.escape(label)}\r?$",
        re.MULTILINE | re.IGNORECASE,
    )
    end = end_re.search(text, begin.end())
    if not end:
        raise TextPatchError(f"事件钩子缺少结束标记: {owner_package_id}/{label}")
    start = begin.end() + (1 if text[begin.end():begin.end() + 1] == "\n" else 0)
    current = text[start:end.start()].rstrip("\r\n")
    if _managed_hash(current) != begin.group(1):
        raise TextPatchError(f"事件钩子被手工修改，禁止移除: {owner_package_id}/{label}")
    block_end = end.end() + (1 if text[end.end():end.end() + 1] == "\n" else 0)
    return PatchResult(
        text=text[:begin.start()] + text[block_end:],
        changed=True,
        content_hash=identity_hash,
    )


def install_managed_anchor_hook(
    text: str,
    package_id: str,
    anchor: str,
    content: str,
    newline: str,
    legacy_package_ids: tuple[str, ...] = (),
    canonical_before_existing_hooks: bool = False,
) -> PatchResult:
    """在唯一的注释锚点后安装可校验、可升级的受管脚本片段。"""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline).strip("\r\n")
    content_hash = _managed_hash(normalized)
    anchor_re = re.compile(rf"^[ \t]*;[ \t]*{re.escape(anchor)}[ \t]*\r?$", re.MULTILINE)
    anchors = list(anchor_re.finditer(text))
    if not anchors:
        raise TextPatchError(f"找不到受管锚点: {anchor}")
    if len(anchors) != 1:
        lines = [text.count("\n", 0, match.start()) + 1 for match in anchors]
        raise TextPatchError(f"受管锚点不唯一: {anchor} {lines}")

    candidates: list[tuple[str, re.Match[str]]] = []
    for candidate_id in (package_id, *legacy_package_ids):
        begin_re = re.compile(
            rf"^; XYDP-ANCHOR-HOOK-BEGIN {re.escape(candidate_id)} {re.escape(anchor)} SHA256=([0-9a-f]{{64}})\r?$",
            re.MULTILINE,
        )
        begin = begin_re.search(text)
        if begin:
            candidates.append((candidate_id, begin))
    if len(candidates) > 1:
        found = ", ".join(candidate_id for candidate_id, _ in candidates)
        raise TextPatchError(f"新旧锚点钩子同时存在，禁止自动接管: {found}/{anchor}")
    current_package_id, begin = candidates[0] if candidates else (package_id, None)
    if begin:
        end_re = re.compile(
            rf"^; XYDP-ANCHOR-HOOK-END {re.escape(current_package_id)} {re.escape(anchor)}\r?$",
            re.MULTILINE,
        )
        end = end_re.search(text, begin.end())
        if not end:
            raise TextPatchError(f"锚点钩子缺少结束标记: {current_package_id}/{anchor}")
        start = begin.end() + (1 if text[begin.end():begin.end() + 1] == "\n" else 0)
        current = text[start:end.start()].rstrip("\r\n")
        if _managed_hash(current) != begin.group(1):
            raise TextPatchError(f"锚点钩子被手工修改: {current_package_id}/{anchor}")
        block_end = end.end() + (1 if text[end.end():end.end() + 1] == "\n" else 0)
        replacement = (
            f"; XYDP-ANCHOR-HOOK-BEGIN {package_id} {anchor} SHA256={content_hash}{newline}"
            f"{normalized}{newline}; XYDP-ANCHOR-HOOK-END {package_id} {anchor}{newline}"
        )
        old = text[begin.start():block_end]
        if canonical_before_existing_hooks:
            without_current = text[:begin.start()] + text[block_end:]
            anchor_without = anchor_re.search(without_current)
            assert anchor_without is not None
            other_begin_re = re.compile(
                rf"^; XYDP-ANCHOR-HOOK-BEGIN \S+ {re.escape(anchor)} SHA256=[0-9a-f]{{64}}\r?$",
                re.MULTILINE,
            )
            other = other_begin_re.search(without_current, anchor_without.end())
            if other:
                rebuilt = without_current[:other.start()] + replacement + without_current[other.start():]
                return PatchResult(rebuilt, rebuilt != text, content_hash)
        return PatchResult(text[:begin.start()] + replacement + text[block_end:], old != replacement, content_hash)

    if canonical_before_existing_hooks:
        other_begin_re = re.compile(
            rf"^; XYDP-ANCHOR-HOOK-BEGIN \S+ {re.escape(anchor)} SHA256=[0-9a-f]{{64}}\r?$",
            re.MULTILINE,
        )
        other = other_begin_re.search(text, anchors[0].end())
        if other:
            block = (
                f"; XYDP-ANCHOR-HOOK-BEGIN {package_id} {anchor} SHA256={content_hash}{newline}"
                f"{normalized}{newline}; XYDP-ANCHOR-HOOK-END {package_id} {anchor}{newline}"
            )
            return PatchResult(text[:other.start()] + block + text[other.start():], True, content_hash)

    insert_at = anchors[0].end() + (1 if text[anchors[0].end():anchors[0].end() + 1] == "\n" else 0)
    while text.startswith("; XYDP-ANCHOR-HOOK-BEGIN ", insert_at):
        end_line = re.search(r"^; XYDP-ANCHOR-HOOK-END .+?\r?$", text[insert_at:], re.MULTILINE)
        if not end_line:
            raise TextPatchError(f"锚点 {anchor} 下存在损坏的受管钩子")
        insert_at += end_line.end()
        if text[insert_at:insert_at + 1] == "\n":
            insert_at += 1
    block = (
        f"; XYDP-ANCHOR-HOOK-BEGIN {package_id} {anchor} SHA256={content_hash}{newline}"
        f"{normalized}{newline}; XYDP-ANCHOR-HOOK-END {package_id} {anchor}{newline}"
    )
    return PatchResult(text[:insert_at] + block + text[insert_at:], True, content_hash)


def remove_managed_anchor_hook(
    text: str,
    package_id: str,
    anchor: str,
    legacy_package_ids: tuple[str, ...] = (),
) -> PatchResult:
    """安全移除当前包或旧包拥有的单个受管锚点钩子。"""
    candidates: list[tuple[str, re.Match[str]]] = []
    for candidate_id in (package_id, *legacy_package_ids):
        begin_re = re.compile(
            rf"^; XYDP-ANCHOR-HOOK-BEGIN {re.escape(candidate_id)} "
            rf"{re.escape(anchor)} SHA256=([0-9a-f]{{64}})\r?$",
            re.MULTILINE,
        )
        begin = begin_re.search(text)
        if begin:
            candidates.append((candidate_id, begin))
    if len(candidates) > 1:
        found = ", ".join(candidate_id for candidate_id, _ in candidates)
        raise TextPatchError(f"新旧锚点钩子同时存在，禁止自动移除: {found}/{anchor}")
    if not candidates:
        return PatchResult(text, False, _managed_hash(""))

    current_package_id, begin = candidates[0]
    end_re = re.compile(
        rf"^; XYDP-ANCHOR-HOOK-END {re.escape(current_package_id)} {re.escape(anchor)}\r?$",
        re.MULTILINE,
    )
    end = end_re.search(text, begin.end())
    if not end:
        raise TextPatchError(f"锚点钩子缺少结束标记: {current_package_id}/{anchor}")
    start = begin.end() + (1 if text[begin.end():begin.end() + 1] == "\n" else 0)
    current = text[start:end.start()].rstrip("\r\n")
    if _managed_hash(current) != begin.group(1):
        raise TextPatchError(f"锚点钩子被手工修改，禁止移除: {current_package_id}/{anchor}")
    block_end = end.end() + (1 if text[end.end():end.end() + 1] == "\n" else 0)
    return PatchResult(
        text=text[:begin.start()] + text[block_end:],
        changed=True,
        content_hash=begin.group(1),
    )
