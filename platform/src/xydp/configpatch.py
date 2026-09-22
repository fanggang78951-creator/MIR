from __future__ import annotations

from dataclasses import dataclass
import re


class ConfigPatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Section:
    name: str
    keys: tuple[tuple[str, str], ...]


def _parse(text: str) -> tuple[_Section, ...]:
    sections: list[_Section] = []
    section_names: set[str] = set()
    current_name: str | None = None
    current_keys: list[tuple[str, str]] = []
    key_names: set[str] = set()

    def finish() -> None:
        nonlocal current_name, current_keys, key_names
        if current_name is not None:
            sections.append(_Section(current_name, tuple(current_keys)))
        current_name = None
        current_keys = []
        key_names = set()

    for line_number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            name = stripped[1:-1].strip()
            if not name:
                raise ConfigPatchError(f"空节名: 第{line_number}行")
            lowered = name.casefold()
            if lowered in section_names:
                raise ConfigPatchError(f"重复节: {name}")
            finish()
            current_name = name
            section_names.add(lowered)
            continue
        if current_name is None:
            raise ConfigPatchError(f"配置键出现在节之前: 第{line_number}行")
        if "=" not in raw:
            raise ConfigPatchError(f"配置行缺少等号: 第{line_number}行")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigPatchError(f"空配置键: 第{line_number}行")
        lowered = key.casefold()
        if lowered in key_names:
            raise ConfigPatchError(f"重复键: [{current_name}] {key}")
        key_names.add(lowered)
        current_keys.append((key, value))
    finish()
    return tuple(sections)


def _newline_text(text: str, newline: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return newline.join(lines) + newline


def merge_config_text(current: str | None, defaults: str, newline: str) -> str:
    """Preserve current values and append only missing sections and keys from defaults."""
    default_sections = _parse(defaults)
    if current is None or current == "":
        return _newline_text(defaults, newline)

    current_sections = _parse(current)
    existing = {
        section.name.casefold(): {key.casefold() for key, _ in section.keys}
        for section in current_sections
    }
    missing_sections = [section for section in default_sections if section.name.casefold() not in existing]
    missing_keys = {
        section.name.casefold(): [(key, value) for key, value in section.keys if key.casefold() not in existing.get(section.name.casefold(), set())]
        for section in default_sections
        if section.name.casefold() in existing
    }
    if not missing_sections and not any(missing_keys.values()):
        return current

    lines = current.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    trailing_newline = bool(lines and lines[-1] == "")
    if trailing_newline:
        lines.pop()

    for section in default_sections:
        wanted = missing_keys.get(section.name.casefold(), [])
        if not wanted:
            continue
        start = next(
            index for index, line in enumerate(lines)
            if line.strip().startswith("[")
            and line.strip().endswith("]")
            and line.strip()[1:-1].strip().casefold() == section.name.casefold()
        )
        end = len(lines)
        for index in range(start + 1, len(lines)):
            stripped = lines[index].strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                end = index
                break
        lines[end:end] = [f"{key}={value}" for key, value in wanted]

    for section in missing_sections:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{section.name}]")
        lines.extend(f"{key}={value}" for key, value in section.keys)

    result = newline.join(lines)
    if trailing_newline or missing_sections or any(missing_keys.values()):
        result += newline
    return result


def set_flat_config_values(current: str, values: dict[str, str], newline: str) -> str:
    """Set selected key=value entries while preserving every unrelated line."""
    if not values:
        raise ConfigPatchError("配置设置不能为空")
    wanted = {str(key).casefold(): (str(key), str(value)) for key, value in values.items()}
    found = {key: 0 for key in wanted}
    lines = current.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    trailing_newline = bool(lines and lines[-1] == "")
    if trailing_newline:
        lines.pop()

    pattern = re.compile(r"^(\s*([^;#=][^=]*?)\s*=\s*)(.*)$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        key = match.group(2).strip().casefold()
        if key not in wanted:
            continue
        found[key] += 1
        if found[key] > 1:
            raise ConfigPatchError(f"重复键: {wanted[key][0]}")
        lines[index] = match.group(1) + wanted[key][1]

    for lowered, (key, value) in wanted.items():
        if found[lowered] == 0:
            lines.append(f"{key}={value}")

    result = newline.join(lines)
    if trailing_newline or values:
        result += newline
    return result
