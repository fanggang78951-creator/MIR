from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class AttributePanelError(ValueError):
    pass


MAX_ATTRIBUTE_ITEMS = 12
MAX_EQUIPMENT_ADDITIONS = 32
MAX_TITLE_ADDITIONS = 32
_VARIABLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$\u4e00-\u9fff]*$")
_NAMESPACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,15}$")
_FORBIDDEN_TEXT = set("\\#<>{}\r\n\t")


@dataclass(frozen=True)
class CompiledAttributePanel:
    normalized: dict[str, Any]
    setup: str
    tooltip: str
    variables: tuple[str, ...]


def _integer(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise AttributePanelError(f"{field} 必须是整数")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AttributePanelError(f"{field} 必须是整数") from exc
    if number < minimum or number > maximum:
        raise AttributePanelError(f"{field} 必须在 {minimum} 到 {maximum} 之间")
    return number


def _display_text(value: Any, field: str, *, maximum: int, allow_empty: bool = False) -> str:
    text = str(value)
    if not text and allow_empty:
        return text
    if not text:
        raise AttributePanelError(f"{field} 不能为空")
    if len(text) > maximum:
        raise AttributePanelError(f"{field} 最多 {maximum} 个字符")
    if any(char.isspace() or char in _FORBIDDEN_TEXT for char in text):
        raise AttributePanelError(f"{field} 含空格或脚本保留字符")
    return text


def compile_attribute_panel(value: Any) -> CompiledAttributePanel:
    if not isinstance(value, dict):
        raise AttributePanelError("属性面板参数必须是JSON对象")
    unknown_panel = set(value) - {"title", "title_color", "namespace", "items"}
    if unknown_panel:
        raise AttributePanelError(f"属性面板存在未知字段: {', '.join(sorted(unknown_panel))}")

    title = _display_text(value.get("title", "玄渊属性"), "面板标题", maximum=20)
    title_color = _integer(value.get("title_color", 250), "标题颜色", minimum=0, maximum=255)
    namespace = str(value.get("namespace", ""))
    if namespace and not _NAMESPACE_RE.fullmatch(namespace):
        raise AttributePanelError("面板变量命名空间只能使用英文字母、数字和下划线，且必须以字母开头")
    items = value.get("items")
    if not isinstance(items, list) or not items:
        raise AttributePanelError("属性面板至少需要1个显示项")
    if len(items) > MAX_ATTRIBUTE_ITEMS:
        raise AttributePanelError(f"属性面板最多支持{MAX_ATTRIBUTE_ITEMS}个显示项")

    normalized_items: list[dict[str, Any]] = []
    setup_lines: list[str] = []
    tooltip_lines = [f"{title_color}#{title}"]
    variables: list[str] = []
    for index, raw_item in enumerate(items, 1):
        if not isinstance(raw_item, dict):
            raise AttributePanelError(f"第{index}个显示项必须是JSON对象")
        unknown_item = set(raw_item) - {
            "label", "source", "bind_type", "read_mode", "equipment_additions", "title_additions",
            "offset", "divisor", "prefix", "suffix", "color", "clamp_min"
        }
        if unknown_item:
            raise AttributePanelError(
                f"第{index}个显示项存在未知字段: {', '.join(sorted(unknown_item))}"
            )

        label = _display_text(raw_item.get("label", ""), f"第{index}项名称", maximum=20)
        source = str(raw_item.get("source", ""))
        if not _VARIABLE_RE.fullmatch(source):
            raise AttributePanelError(f"第{index}项来源变量格式无效: {source}")
        bind_raw = raw_item.get("bind_type")
        bind_type = None if bind_raw is None else _integer(
            bind_raw, f"第{index}项装备显示属性位", minimum=0, maximum=255
        )
        read_mode = str(raw_item.get("read_mode", "auto")).lower()
        if read_mode not in {"auto", "source", "bind", "zero"}:
            raise AttributePanelError(
                f"第{index}项读取模式必须是 auto、source、bind 或 zero"
            )
        if read_mode == "auto":
            read_mode = "bind" if bind_type is not None else "source"
        if read_mode == "bind" and bind_type is None:
            raise AttributePanelError(f"第{index}项bind读取模式必须提供bind_type")

        additions_raw = raw_item.get("equipment_additions", [])
        if not isinstance(additions_raw, list):
            raise AttributePanelError(f"第{index}项装备加成规则必须是JSON数组")
        if len(additions_raw) > MAX_EQUIPMENT_ADDITIONS:
            raise AttributePanelError(
                f"第{index}项最多支持{MAX_EQUIPMENT_ADDITIONS}条装备加成规则"
            )
        additions: list[dict[str, Any]] = []
        for addition_index, raw_addition in enumerate(additions_raw, 1):
            if not isinstance(raw_addition, dict):
                raise AttributePanelError(
                    f"第{index}项第{addition_index}条装备加成必须是JSON对象"
                )
            unknown_addition = set(raw_addition) - {"name", "amount", "count"}
            if unknown_addition:
                raise AttributePanelError(
                    f"第{index}项第{addition_index}条装备加成存在未知字段: "
                    f"{', '.join(sorted(unknown_addition))}"
                )
            equipment_name = _display_text(
                raw_addition.get("name", ""),
                f"第{index}项第{addition_index}条装备名称",
                maximum=40,
            )
            amount = _integer(
                raw_addition.get("amount"),
                f"第{index}项第{addition_index}条加成数值",
                minimum=-1_000_000_000,
                maximum=1_000_000_000,
            )
            count = _integer(
                raw_addition.get("count", 1),
                f"第{index}项第{addition_index}条装备数量",
                minimum=1,
                maximum=99,
            )
            additions.append({"name": equipment_name, "amount": amount, "count": count})
        title_additions_raw = raw_item.get("title_additions", [])
        if not isinstance(title_additions_raw, list):
            raise AttributePanelError(f"第{index}项称号加成规则必须是JSON数组")
        if len(title_additions_raw) > MAX_TITLE_ADDITIONS:
            raise AttributePanelError(
                f"第{index}项最多支持{MAX_TITLE_ADDITIONS}条称号加成规则"
            )
        title_additions: list[dict[str, Any]] = []
        title_names: set[str] = set()
        for addition_index, raw_addition in enumerate(title_additions_raw, 1):
            if not isinstance(raw_addition, dict):
                raise AttributePanelError(
                    f"第{index}项第{addition_index}条称号加成必须是JSON对象"
                )
            unknown_addition = set(raw_addition) - {"name", "amount"}
            if unknown_addition:
                raise AttributePanelError(
                    f"第{index}项第{addition_index}条称号加成存在未知字段: "
                    f"{', '.join(sorted(unknown_addition))}"
                )
            title_name = _display_text(
                raw_addition.get("name", ""),
                f"第{index}项第{addition_index}条称号名称",
                maximum=40,
            )
            if title_name in title_names:
                raise AttributePanelError(f"第{index}项称号加成名称重复: {title_name}")
            title_names.add(title_name)
            amount = _integer(
                raw_addition.get("amount"),
                f"第{index}项第{addition_index}条称号加成数值",
                minimum=-1_000_000_000,
                maximum=1_000_000_000,
            )
            title_additions.append({"name": title_name, "amount": amount})
        offset = _integer(
            raw_item.get("offset", 0), f"第{index}项基准偏移", minimum=-1_000_000_000, maximum=1_000_000_000
        )
        divisor = _integer(
            raw_item.get("divisor", 1), f"第{index}项显示除数", minimum=1, maximum=1_000_000_000
        )
        prefix = _display_text(
            raw_item.get("prefix", ""), f"第{index}项前缀", maximum=8, allow_empty=True
        )
        suffix = _display_text(
            raw_item.get("suffix", ""), f"第{index}项后缀", maximum=8, allow_empty=True
        )
        color = _integer(raw_item.get("color", 251), f"第{index}项颜色", minimum=0, maximum=255)
        clamp_raw = raw_item.get("clamp_min")
        clamp_min = None if clamp_raw is None else _integer(
            clamp_raw, f"第{index}项最小显示值", minimum=-1_000_000_000, maximum=1_000_000_000
        )

        mirror = (
            f"N$XY_UI_{namespace}_Value{index:02d}"
            if namespace
            else f"N$XY_UI_Value{index:02d}"
        )
        variables.append(mirror)
        # 每一项必须开启自己的无条件动作块。上一项的 clamp 会留下一个
        # 条件 #ACT；若直接接 MOV，后续项会被错误包进上一项的负数分支。
        setup_lines.extend(("#IF", "#ACT"))
        if read_mode == "source":
            if divisor == 1 or additions or title_additions:
                setup_lines.append(f"MOV {mirror} <$STR({source})>")
            else:
                setup_lines.append(f"FORMULATION <$STR({source})>/{divisor} {mirror}")
        elif read_mode == "bind":
            bind_point = f"{mirror}_BindPoint"
            bind_rate = f"{mirror}_BindRate"
            setup_lines.extend((
                f"MOV {bind_point} 0",
                f"MOV {bind_rate} 0",
                f"GetAllCustomItemValue {bind_type} {bind_point} {bind_rate}",
                f"MOV {mirror} <$STR({bind_point})>",
                f"INC {mirror} <$STR({bind_rate})>",
            ))
        else:
            setup_lines.append(f"MOV {mirror} 0")
        for addition in additions:
            setup_lines.extend((
                "#IF",
                f"CHECKITEMW {addition['name']} {addition['count']}",
                "#ACT",
            ))
            amount = addition["amount"]
            if amount >= 0:
                setup_lines.append(f"INC {mirror} {amount}")
            else:
                setup_lines.append(f"DEC {mirror} {-amount}")
        for addition in title_additions:
            setup_lines.extend((
                "#IF",
                f"CHECKFENGHAO {addition['name']}",
                "#ACT",
            ))
            amount = addition["amount"]
            if amount >= 0:
                setup_lines.append(f"INC {mirror} {amount}")
            else:
                setup_lines.append(f"DEC {mirror} {-amount}")
        if divisor != 1 and (read_mode != "source" or additions or title_additions):
            setup_lines.append(f"FORMULATION <$STR({mirror})>/{divisor} {mirror}")
        if offset > 0:
            setup_lines.append(f"DEC {mirror} {offset}")
        elif offset < 0:
            setup_lines.append(f"INC {mirror} {-offset}")
        if clamp_min is not None:
            setup_lines.extend(("#IF", f"SMALL {mirror} {clamp_min}", "#ACT", f"MOV {mirror} {clamp_min}"))
        tooltip_lines.append(f"{color}#{label}:{prefix}<$STR({mirror})>{suffix}")
        normalized_items.append({
            "label": label,
            "source": source,
            "bind_type": bind_type,
            "read_mode": read_mode,
            "equipment_additions": additions,
            "title_additions": title_additions,
            "offset": offset,
            "divisor": divisor,
            "prefix": prefix,
            "suffix": suffix,
            "color": color,
            "clamp_min": clamp_min,
        })

    return CompiledAttributePanel(
        normalized={
            "title": title,
            "title_color": title_color,
            "namespace": namespace,
            "items": normalized_items,
        },
        setup="\n".join(setup_lines),
        tooltip="\\".join(tooltip_lines),
        variables=tuple(variables),
    )
