from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .encoding import TextDocument, encode_text_document, read_text_document
from .target import TargetInspector, is_executable_running
from .textpatch import TextPatchError, ensure_event_label, install_event_hook


class KingModeFlowError(RuntimeError):
    pass


def _sha256(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _read_text(path: Path, default_encoding: str = "gb18030") -> TextDocument:
    if not path.exists():
        return TextDocument("", default_encoding, "\r\n")
    return read_text_document(path)


def _encode(doc: TextDocument, text: str) -> bytes:
    return encode_text_document(doc, text)


def _parse_config(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    section = "默认"
    sections[section] = {}
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            sections.setdefault(section, {})
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            sections.setdefault(section, {})[key.strip()] = value.strip()
    return sections


def _cfg(cfg: dict[str, dict[str, str]], section: str, key: str, default: str = "") -> str:
    return cfg.get(section, {}).get(key, default)


def _int(cfg: dict[str, dict[str, str]], section: str, key: str, default: int) -> int:
    raw = _cfg(cfg, section, key, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise KingModeFlowError(f"配置必须是整数: [{section}] {key}={raw}") from exc


def _append_unique(text: str, line: str, newline: str, key: tuple[int, ...] = (0,)) -> str:
    wanted = line.rstrip("\r\n")
    fields = wanted.split("\t")
    wanted_key = tuple(fields[i] for i in key)
    for existing in text.splitlines():
        parts = existing.split("\t")
        if len(parts) <= max(key, default=-1):
            continue
        if tuple(parts[i] for i in key) == wanted_key:
            if existing == wanted:
                return text
            raise KingModeFlowError(f"受管唯一行冲突: {wanted_key}")
    prefix = "" if not text or text.endswith(("\r", "\n")) else newline
    return text + prefix + wanted + newline


def _ensure_break_after_login_call(text: str, package_id: str, newline: str) -> str:
    """Prevent QManage @MAIN1 from falling through into its default map.

    The current service calls the real login script from ``[@MAIN1]`` and then
    immediately falls through to ``[@MAIN]``, whose legacy ``map 0159`` would
    overwrite the activity's login destination.  Insert a small managed BREAK
    immediately after that exact call, with strict uniqueness/hash checks.
    """
    call_line = r"#CALL [\游戏登陆\登陆脚本.txt] @登陆设置"
    marker = f"{package_id} LoginFallthrough"
    begin_re = re.compile(
        rf"^; XYDP-HOOK-BEGIN {re.escape(marker)} SHA256=([0-9a-f]{{64}})\r?$",
        re.MULTILINE | re.IGNORECASE,
    )
    begin = begin_re.search(text)
    if begin:
        end_re = re.compile(
            rf"^; XYDP-HOOK-END {re.escape(marker)}\r?$",
            re.MULTILINE | re.IGNORECASE,
        )
        end = end_re.search(text, begin.end())
        if not end:
            raise KingModeFlowError("QManage 登录调用后的受管 BREAK 缺少结束标记")
        current = text[begin.end() + (1 if text[begin.end():begin.end() + 1] == "\n" else 0):end.start()].rstrip("\r\n")
        if hashlib.sha256(current.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest() != begin.group(1):
            raise KingModeFlowError("QManage 登录调用后的受管 BREAK 被手工修改")
        return text
    line_re = re.compile(rf"^[ \t]*{re.escape(call_line)}[ \t]*\r?$", re.MULTILINE)
    matches = list(line_re.finditer(text))
    if len(matches) != 1:
        raise KingModeFlowError(f"QManage 登录脚本调用不唯一，无法安全阻止回落: {len(matches)}")
    body = "BREAK"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    block = (
        f"; XYDP-HOOK-BEGIN {marker} SHA256={digest}{newline}"
        f"{body}{newline}; XYDP-HOOK-END {marker}{newline}"
    )
    insert_at = matches[0].end()
    if text[insert_at:insert_at + 1] == "\n":
        insert_at += 1
    return text[:insert_at] + block + text[insert_at:]


def _replace_map_display(text: str, logical_map: str, display_name: str, newline: str, fallback_line: str) -> str:
    """Replace one MapInfo header without changing its existing flags.

    MapInfo lines are not a normal key/value table: the external name lives in
    the bracket header while the flags follow it.  Replacing the whole line
    would silently drop existing safety/combat flags, so only the header is
    changed.  Duplicate logical map definitions are rejected because the
    engine would otherwise make the result ambiguous.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    matches = [i for i, line in enumerate(lines) if line.startswith(f"[{logical_map}|") or line.startswith(f"[{logical_map}]")]
    if len(matches) > 1:
        raise KingModeFlowError(f"MapInfo 地图代码重复，无法安全改名: {logical_map}")
    if not matches:
        return _append_unique(text, fallback_line, newline, (0,))
    index = matches[0]
    line = lines[index]
    close = line.find("]")
    suffix = line[close + 1:] if close >= 0 else ""
    right = line[line.find("|") + 1:close] if "|" in line and close >= 0 else ""
    fallback_right = fallback_line[fallback_line.find("|") + 1:fallback_line.find("]")] if "|" in fallback_line and "]" in fallback_line else ""
    # 翎风 MapInfo 的右侧首词是物理地图别名（例如 vx605/xykwa），
    # 后面的文字才是外显名。首词不能因为改名而丢失。
    existing_parts = right.strip().split(None, 1)
    fallback_parts = fallback_right.strip().split(None, 1)
    alias = existing_parts[0] if len(existing_parts) > 1 else (fallback_parts[0] if fallback_parts else "")
    rendered_right = f"{alias} {display_name}" if alias else display_name
    lines[index] = f"[{logical_map}|{rendered_right}]" + suffix
    return newline.join(lines)


def _merge_defaults(current: str | None, defaults: str, newline: str) -> str:
    if not current:
        return defaults.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    current_lines = current.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    existing_sections: set[str] = set()
    for line in current_lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            existing_sections.add(stripped[1:-1].strip())
    additions: list[str] = []
    default_lines = defaults.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    active = ""
    for line in default_lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            active = stripped[1:-1].strip()
            if active in existing_sections:
                continue
            if additions and additions[-1] != "":
                additions.append("")
            additions.append(line)
            continue
        if active and active not in existing_sections:
            additions.append(line)
    base = current.rstrip("\r\n")
    if additions:
        base += newline + newline.join(additions).rstrip("\r\n")
    return base + newline


def _merge_missing_config_keys(current: str, defaults: str, newline: str) -> str:
    """Add keys from the platform mother table into existing sections.

    Older target servers already have a ``[刷怪]`` section.  Appending only a
    missing section would leave the old values active, so missing keys are
    inserted into the existing section while every user value is preserved.
    """
    lines = current.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    default_lines = defaults.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[tuple[str, list[str]]] = []
    active = ""
    body: list[str] = []
    for raw in default_lines:
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if active:
                blocks.append((active, body))
            active = stripped[1:-1].strip()
            body = []
        elif active:
            body.append(raw)
    if active:
        blocks.append((active, body))

    def section_bounds(name: str) -> tuple[int, int] | None:
        starts = [i for i, line in enumerate(lines) if line.strip() == f"[{name}]"]
        if len(starts) > 1:
            raise KingModeFlowError(f"配置区段重复，无法安全合并: [{name}]")
        if not starts:
            return None
        start = starts[0]
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[") and lines[i].strip().endswith("]")), len(lines))
        return start, end

    for name, body in blocks:
        bounds = section_bounds(name)
        if bounds is None:
            additions = [f"[{name}]"] + body
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(additions)
            continue
        start, end = bounds
        existing_keys = {
            line.split("=", 1)[0].strip()
            for line in lines[start + 1:end]
            if "=" in line and not line.strip().startswith((";", "#"))
        }
        missing = [line for line in body if "=" in line and line.split("=", 1)[0].strip() not in existing_keys]
        if missing:
            lines[end:end] = missing
    return newline.join(lines) + newline


@dataclass(frozen=True)
class FlowChange:
    scope: str
    relative_path: str
    before_hash: str | None
    after_hash: str
    operation: str
    after: bytes = field(repr=False)
    before: bytes | None = field(default=None, repr=False)


@dataclass
class FlowPlan:
    operation: str
    server: str
    client: str | None
    config_path: str
    config_hash: str
    changes: list[FlowChange]
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowReceipt:
    transaction_id: str
    operation: str
    server: str
    client: str | None
    config_hash: str
    changes: list[dict[str, Any]]
    backup_root: str
    created_at: str
    warnings: list[str] = field(default_factory=list)


class KingModeFlowService:
    """国王模式赛前流程的专用事务服务。

    该服务只处理声明式文本/二进制资源，不执行包内 Python、批处理或脚本。
    配置 TXT 是母表；运行链拿到的是平台渲染后的固定脚本，因此不会在 M2
    运行时调用 ReadConfigFileItem。
    """

    package_id = "xy.optional.king-mode.flow"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.package_root = self.root / "packages" / "candidate" / self.package_id
        self.payload = self.package_root / "payload"
        central_config = self.root / "所需材料表格汇总" / "14_国王模式配置.txt"
        self.default_config = central_config if central_config.is_file() else self.payload / "国王模式配置.txt"
        self.template = self.payload / "国王模式赛前流程模板.txt"
        self.signup_template = self.payload / "国王模式赛前报名模板.txt"
        self.return_template = self.payload / "国王模式返回大厅模板.txt"

    def _default_values(self, cfg: dict[str, dict[str, str]]) -> dict[str, Any]:
        def point(section: str, key: str, fallback: str) -> tuple[int, int]:
            raw = _cfg(cfg, section, key, fallback)
            try:
                x, y = (int(item.strip()) for item in raw.split(",", 1))
                return x, y
            except (ValueError, TypeError) as exc:
                raise KingModeFlowError(f"坐标格式必须为 X,Y: [{section}] {key}={raw}") from exc

        ax, ay = point("地图", "A方野区落点", "50,50")
        bx, by = point("地图", "B方野区落点", "50,50")
        a_bx, a_by = point("地图", "A方对战复活点", "15,50")
        b_bx, b_by = point("地图", "B方对战复活点", "100,50")
        def npc_point(key: str, key_y: str, fallback: str) -> tuple[int, int]:
            raw = _cfg(cfg, "NPC", key, fallback)
            if "," in raw:
                return point("NPC", key, fallback)
            try:
                return int(raw), _int(cfg, "NPC", key_y, int(fallback.split(",", 1)[1]))
            except ValueError as exc:
                raise KingModeFlowError(f"NPC坐标格式必须为 X,Y 或配套 X/Y: {raw}") from exc
        signup_x, signup_y = npc_point("报名官坐标", "报名官坐标Y", "29,26")
        return_x, return_y = npc_point("返回官坐标", "返回官坐标Y", "32,26")
        total_waves = _int(cfg, "刷怪", "总波数", 5)
        wave_names: list[dict[str, str]] = []
        legacy_normal = _cfg(cfg, "刷怪", "普通怪名称", "蝴蝶仙子")
        legacy_boss = _cfg(cfg, "刷怪", "Boss名称", "精灵王")
        for index in range(1, total_waves + 1):
            wave_names.append({
                "normal": _cfg(cfg, "刷怪", f"第{index}波普通怪", legacy_normal if index == 1 else ""),
                "boss": _cfg(cfg, "刷怪", f"第{index}波Boss", legacy_boss if index == 1 else ""),
            })
        wave_duration_min = _int(cfg, "刷怪", "每波持续分钟", _int(cfg, "刷怪", "刷新间隔分钟", 10))
        wave_gap_seconds = _int(cfg, "刷怪", "波次间隔秒数", 15)
        first_spawn_delay = _int(cfg, "刷怪", "首波延迟秒数", 30)
        final_entry_delay = _int(cfg, "刷怪", "第五波清场后入场延迟秒数", 15)
        return {
            "login_map": _cfg(cfg, "地图", "登录地图", "chushidi"),
            "a_wild_map": _cfg(cfg, "地图", "A方野区", "XYKWA"),
            "b_wild_map": _cfg(cfg, "地图", "B方野区", "XYKWB"),
            "battle_map": _cfg(cfg, "地图", "对战地图", "XYGDZY"),
            "login_x": point("地图", "登录落点", "29,30")[0],
            "login_y": point("地图", "登录落点", "29,30")[1],
            "a_wild_x": ax,
            "a_wild_y": ay,
            "b_wild_x": bx,
            "b_wild_y": by,
            "a_battle_x": a_bx,
            "a_battle_y": a_by,
            "b_battle_x": b_bx,
            "b_battle_y": b_by,
            "team_size": _int(cfg, "阵容", "每队人数", 5),
            "king_size": _int(cfg, "阵容", "国王人数", 1),
            "commoner_size": _int(cfg, "阵容", "平民人数", 4),
            "countdown": _int(cfg, "阵容", "倒计时秒数", 10),
            "king_job": _cfg(cfg, "阵容", "国王职业", "战士"),
            "normal_monster": legacy_normal,
            "boss_monster": legacy_boss,
            "normal_count": _int(cfg, "刷怪", "每波普通怪数量", 10),
            "boss_count": _int(cfg, "刷怪", "每波Boss数量", 1),
            "total_waves": total_waves,
            "first_spawn_delay_seconds": first_spawn_delay,
            "wave_duration_seconds": wave_duration_min * 60,
            "wave_gap_seconds": wave_gap_seconds,
            "final_entry_delay_seconds": final_entry_delay,
            "wave_names": wave_names,
            "npc_signup_name": _cfg(cfg, "NPC", "报名官名称", "国王模式报名官"),
            "npc_signup_x": signup_x,
            "npc_signup_y": signup_y,
            "npc_signup_appearance": _int(cfg, "NPC", "报名官外观", 24),
            "npc_return_name": _cfg(cfg, "NPC", "返回官名称", "国王模式返回官"),
            "npc_return_x": return_x,
            "npc_return_y": return_y,
            "npc_return_appearance": _int(cfg, "NPC", "返回官外观", 24),
            "example": _int(cfg, "状态", "示例配置", 1),
        }

    def _wave_script(self, values: dict[str, Any]) -> str:
        """Render the fixed five-wave wild-area state machine.

        Counters are global and only the activity controller advances them.
        The first wave waits 30 seconds; later waves are spawned immediately
        after the 15-second clear interval.  ClearMapMon is intentionally used
        instead of killing monsters so no death reward/drop path can run.
        """
        if values["total_waves"] != 5:
            raise KingModeFlowError("国王模式五波流程要求 [刷怪] 总波数=5")
        lines: list[str] = [
            "; ---- XY-KING-FLOW-WILD-5-WAVE-BEGIN ----",
            "#IF",
            "Check [1500] 2",
            "CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\活动控制者.txt <$USERNAME>",
            "#ACT",
            "INC G1511 1",
        ]
        names = values["wave_names"]
        def gen(wave_no: int) -> list[str]:
            item = names[wave_no - 1]
            normal = item["normal"]
            boss = item["boss"]
            if not normal or not boss:
                raise KingModeFlowError(f"第{wave_no}波普通怪和Boss名称不能为空")
            return [
                # 目标服已验证的语法是：地图 X Y 怪物 数量 范围；
                # 多写一个参数会让 M2 整个流程文件拒绝加载。
                f"MonGenEx {values['a_wild_map']} {values['a_wild_x']} {values['a_wild_y']} {normal} {values['normal_count']} 35",
                f"MonGenEx {values['a_wild_map']} {values['a_wild_x']} {values['a_wild_y']} {boss} {values['boss_count']} 35",
                f"MonGenEx {values['b_wild_map']} {values['b_wild_x']} {values['b_wild_y']} {normal} {values['normal_count']} 35",
                f"MonGenEx {values['b_wild_map']} {values['b_wild_x']} {values['b_wild_y']} {boss} {values['boss_count']} 35",
            ]
        # 首波：进入野区后计时达到 30 秒才生成。
        lines += [
            "#IF", "Check [1500] 2", "Check [1507] 0", f"Check [1511] {values['first_spawn_delay_seconds']}", "#ACT",
            *gen(1), "SET [1507] 1", "SET [1511] 0",
            f"SENDMSG 0 第1波：{names[0]['normal']}与{names[0]['boss']}已生成。",
        ]
        # 清理间隔倒计时只由控制者递减，避免十名玩家同时重复推进状态。
        lines += [
            "#IF", "Check [1500] 3",
            "CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\活动控制者.txt <$USERNAME>",
            "#ACT", "DEC G1512 1",
        ]
        for wave_no in range(1, 6):
            # 每波 600 秒到达后清理两张野区，并进入统一的 15 秒间隔。
            lines += [
                "#IF", "Check [1500] 2", f"Check [1507] {wave_no}", f"Check [1511] {values['wave_duration_seconds']}", "#ACT",
                f"; XY-KING-FLOW-CLEAR-NO-DROP WAVE-{wave_no}",
                f"ClearMapMon {values['a_wild_map']}",
                f"ClearMapMon {values['b_wild_map']}",
                "SET [1500] 3",
                f"SET [1512] {values['final_entry_delay_seconds'] if wave_no == 5 else values['wave_gap_seconds']}",
                f"SENDMSG 0 第{wave_no}波野怪已清场，{values['final_entry_delay_seconds'] if wave_no == 5 else values['wave_gap_seconds']}秒后进入下一阶段。",
            ]
            if wave_no < 5:
                # 最后一秒由控制者直接生成下一波，避免再额外等待 600 秒。
                lines += [
                    "#IF", "Check [1500] 3", f"Check [1507] {wave_no}", "Check [1512] 0", "#ACT",
                    *gen(wave_no + 1), f"SET [1507] {wave_no + 1}", "SET [1500] 2", "SET [1511] 0",
                    f"SENDMSG 0 第{wave_no + 1}波：{names[wave_no]['normal']}与{names[wave_no]['boss']}已生成。",
                ]
            else:
                lines += [
                    "#IF", "Check [1500] 3", "Check [1507] 5", "Check [1512] 0", "#ACT",
                    "SET [1500] 4", "SET [1513] 0",
                    f"SENDMSG 0 第5波清场完成，{values['final_entry_delay_seconds']}秒后进入角斗场。",
                ]
        lines.append("; ---- XY-KING-FLOW-WILD-5-WAVE-END ----")
        return "\n".join(lines)

    def _render(self, source: Path, values: dict[str, Any]) -> bytes:
        text = source.read_text(encoding="utf-8")
        if source.resolve() == self.template.resolve():
            text = text.replace("__WAVE_SCRIPT__", self._wave_script(values))
        for key, value in values.items():
            text = text.replace(f"__KMF_{key.upper()}__", str(value))
            text = text.replace(f"__{key.upper()}__", str(value))
        if "__KMF_" in text:
            missing = sorted(set(re.findall(r"__KMF_[A-Z0-9_]+__", text)))
            raise KingModeFlowError(f"流程模板存在未渲染参数: {missing}")
        return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n").encode("gb18030")

    def _add_change(self, changes: dict[tuple[str, str], FlowChange], scope: str, root: Path, relative: str, after: bytes, operation: str) -> None:
        path = root / Path(relative.replace("/", os.sep))
        before = path.read_bytes() if path.exists() else None
        key = (scope, relative.replace("\\", "/"))
        if before == after:
            return
        changes[key] = FlowChange(scope, key[1], _sha256(before), _sha256(after) or "", operation, after, before)

    def _text_after_append(self, path: Path, lines: list[str]) -> bytes:
        doc = _read_text(path)
        text = doc.text
        for line, key in lines:
            text = _append_unique(text, line, doc.newline, key)
        return _encode(doc, text)

    def preflight(self, server: Path, client: Path | None = None, operation: str = "king-mode-flow") -> FlowPlan:
        target = TargetInspector.inspect(Path(server))
        client_root = Path(client).resolve() if client else None
        blockers: list[str] = []
        warnings: list[str] = []
        if client_root is None or not client_root.is_dir():
            blockers.append("地图流程需要客户端根目录")
        if is_executable_running(target.mir200 / "M2Server.exe"):
            warnings.append("M2Server.exe 正在运行；本流程允许继续，但文件被真实锁定时事务会完整失败")
        config_path = target.envir / "QuestDiary" / "玄渊配置" / "国王模式配置.txt"
        config_doc = _read_text(config_path)
        if not config_path.exists():
            config_doc = _read_text(self.default_config, "utf-8")
        defaults = self.default_config.read_text(encoding="utf-8")
        merged_config = _merge_defaults(config_doc.text if config_path.exists() else None, defaults, config_doc.newline)
        if config_path.exists():
            merged_config = _merge_missing_config_keys(merged_config, defaults, config_doc.newline)
        cfg = _parse_config(merged_config)
        values = self._default_values(cfg)
        if values["example"] != 0:
            blockers.append("[状态] 示例配置=1；请修改配置并设置为0后再应用")
        if values["team_size"] != values["king_size"] + values["commoner_size"]:
            blockers.append("每队人数必须等于国王人数+平民人数")
        if values["team_size"] <= 0 or values["countdown"] <= 0 or values["total_waves"] <= 0:
            blockers.append("队伍人数、倒计时和总波数必须大于0")
        if values["total_waves"] != 5:
            blockers.append("国王模式流程固定要求总波数=5")
        if values["first_spawn_delay_seconds"] <= 0 or values["wave_duration_seconds"] <= 0 or values["wave_gap_seconds"] <= 0 or values["final_entry_delay_seconds"] <= 0:
            blockers.append("首波延迟、每波持续时间、波次间隔和入场延迟必须大于0")
        if values["normal_count"] <= 0 or values["boss_count"] <= 0:
            blockers.append("每波普通怪数量和Boss数量必须大于0")
        seen_monsters: set[str] = set()
        for index, item in enumerate(values["wave_names"], 1):
            if not item["normal"] or not item["boss"]:
                blockers.append(f"第{index}波普通怪和Boss名称不能为空")
            for key in ("normal", "boss"):
                name = item[key]
                if name and name in seen_monsters:
                    blockers.append(f"怪物名称重复，无法区分波次: {name}")
                if name:
                    seen_monsters.add(name)
        roots = {"server": target.root, "client": client_root}
        changes: dict[tuple[str, str], FlowChange] = {}
        config_rel = "Mir200/Envir/QuestDiary/玄渊配置/国王模式配置.txt"
        if config_path.exists():
            self._add_change(changes, "server", target.root, config_rel, _encode(config_doc, merged_config), "config-merge")
        else:
            self._add_change(changes, "server", target.root, config_rel, merged_config.encode("gb18030"), "config-create")

        flow_rel = "Mir200/Envir/QuestDiary/玄渊功能/国王模式赛前/国王模式赛前流程.txt"
        signup_rel = "Mir200/Envir/Market_Def/玄渊国王模式_赛前报名-chushidi.txt"
        return_rel = "Mir200/Envir/Market_Def/玄渊国王模式_返回大厅-chushidi.txt"
        flow_bytes: bytes | None = None
        try:
            flow_bytes = self._render(self.template, values)
            flow_text = flow_bytes.decode("gb18030")
            if flow_text.count("MonGenEx ") != values["total_waves"] * 4:
                blockers.append("五波流程的 MonGenEx 数量不符合 A/B 两图各普通怪+Boss 契约")
            if flow_text.count("ClearMapMon ") != values["total_waves"] * 2:
                blockers.append("五波流程必须每波清理 XYKWA 和 XYKWB")
            if any(token in flow_text for token in ("KillMon ", "GAMEDIAMOND", "GAMEDROP", "DROPITEM")):
                blockers.append("刷怪清场块发现击杀/奖励/掉落调用，已阻止安装")
            if "ReadConfigFileItem" in flow_text:
                blockers.append("赛前流程禁止运行时读取配置 TXT")
            if "SETONTIMEREX 10" in flow_text or "SETOFFTIMEREX 10" in flow_text:
                blockers.append("国王模式不能使用目标引擎不支持的10号定时器")
            if re.search(r"(?:INC|DEC) \\[15(?:0\\d|1\\d)\\]", flow_text):
                blockers.append("赛前流程的 G1500-G1515 计数器不能使用方括号变量")
            if not all(token in flow_text for token in (
                "XY_KING_FLOW_SINGLE_TEST_REQUEST",
                "XY_KING_FLOW_SINGLE_TEST_RESET_REQUEST",
                "XY_KING_FLOW_SINGLE_TEST_START",
                "XY_KING_FLOW_CANCEL",
            )):
                blockers.append("国王模式扩展标签不完整")
            # NPC 入口标签必须与外部流程实现标签分离。翎风在同名
            # #CALL 返回时会把控制流跳回 NPC 自身，形成 GOTO 死循环。
            for public_label in (
                "JOIN_A_KING", "JOIN_A_COMMONER", "JOIN_B_KING", "JOIN_B_COMMONER",
                "START", "SINGLE_TEST_REQUEST", "SINGLE_TEST_RESET_REQUEST", "CANCEL",
            ):
                if f"[@XY_KING_FLOW_{public_label}_IMPL]" not in flow_text:
                    blockers.append(f"流程缺少 NPC 转发实现标签: XY_KING_FLOW_{public_label}_IMPL")
            signup_text = self._render(self.signup_template, values).decode("gb18030")
            for public_label in (
                "JOIN_A_KING", "JOIN_A_COMMONER", "JOIN_B_KING", "JOIN_B_COMMONER",
                "START", "SINGLE_TEST_REQUEST", "SINGLE_TEST_RESET_REQUEST", "CANCEL",
            ):
                expected = f"#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_{public_label}_IMPL"
                if expected not in signup_text:
                    blockers.append(f"NPC 转发未指向独立实现标签: XY_KING_FLOW_{public_label}")
            for item in values["wave_names"]:
                if item["normal"] and flow_text.count(item["normal"]) < 2:
                    blockers.append(f"流程未完整渲染普通怪名称: {item['normal']}")
                if item["boss"] and flow_text.count(item["boss"]) < 2:
                    blockers.append(f"流程未完整渲染Boss名称: {item['boss']}")
        except KingModeFlowError as exc:
            blockers.append(str(exc))
        if flow_bytes is not None:
            self._add_change(changes, "server", target.root, flow_rel, flow_bytes, "render-flow")
        self._add_change(changes, "server", target.root, signup_rel, self._render(self.signup_template, values), "render-npc")
        self._add_change(changes, "server", target.root, return_rel, self._render(self.return_template, values), "render-npc")

        mapinfo_path = target.envir / "MapInfo.txt"
        mapinfo_doc = _read_text(mapinfo_path)
        mapinfo = mapinfo_doc.text
        try:
            mapinfo = _replace_map_display(
                mapinfo, "chushidi", "真彩459 初始之地", mapinfo_doc.newline,
                "[chushidi|真彩459 初始之地] SAFE NORANDOMMOVE NORECALL NOGUILDRECALL NODEARRECALL NOMasterRECALL",
            )
            mapinfo = _replace_map_display(
                mapinfo, "XYKWA", "角斗场A方野区", mapinfo_doc.newline,
                "[XYKWA|xykwa 角斗场A方野区] FIGHT2 NORECALL NOGUILDRECALL NODEARRECALL NOMasterRECALL NORANDOMMOVE",
            )
            mapinfo = _replace_map_display(
                mapinfo, "XYKWB", "角斗场B方野区", mapinfo_doc.newline,
                "[XYKWB|xykwb 角斗场B方野区] FIGHT2 NORECALL NOGUILDRECALL NODEARRECALL NOMasterRECALL NORANDOMMOVE",
            )
            mapinfo = _replace_map_display(
                mapinfo, "XYGDZY", "角斗场", mapinfo_doc.newline,
                "[XYGDZY|vx605 角斗场] FIGHT2 NORECALL NOGUILDRECALL NODEARRECALL NOMasterRECALL NORANDOMMOVE",
            )
        except KingModeFlowError as exc:
            blockers.append(str(exc))
        self._add_change(changes, "server", target.root, "Mir200/Envir/MapInfo.txt", _encode(mapinfo_doc, mapinfo), "mapinfo")

        minimap_path = target.envir / "MiniMap.txt"
        minimap_doc = _read_text(minimap_path)
        minimap = minimap_doc.text
        minimap = _append_unique(minimap, "真彩459 3786", minimap_doc.newline)
        minimap = _append_unique(minimap, "xykwa 10606", minimap_doc.newline)
        minimap = _append_unique(minimap, "xykwb 10606", minimap_doc.newline)
        self._add_change(changes, "server", target.root, "Mir200/Envir/MiniMap.txt", _encode(minimap_doc, minimap), "minimap")

        merchant_path = target.envir / "MerChant.txt"
        merchant_doc = _read_text(merchant_path)
        merchant = merchant_doc.text
        merchant = _append_unique(merchant, f"玄渊国王模式_赛前报名\tchushidi\t{values['npc_signup_x']}\t{values['npc_signup_y']}\t{values['npc_signup_name']}\t0\t{values['npc_signup_appearance']}\t0", merchant_doc.newline, (0, 1))
        merchant = _append_unique(merchant, f"玄渊国王模式_返回大厅\tchushidi\t{values['npc_return_x']}\t{values['npc_return_y']}\t{values['npc_return_name']}\t0\t{values['npc_return_appearance']}\t0", merchant_doc.newline, (0, 1))
        self._add_change(changes, "server", target.root, "Mir200/Envir/MerChant.txt", _encode(merchant_doc, merchant), "merchant")

        qfunction_path = target.envir / "Market_Def" / "QFunction-0.txt"
        qdoc = _read_text(qfunction_path)
        qtext = qdoc.text
        hooks = {
            "PlayLogin": f"#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_LOGIN",
            "PlayOffline": f"#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_OFFLINE",
        }
        for label, content in hooks.items():
            try:
                qtext = install_event_hook(qtext, self.package_id, label, content, qdoc.newline).text
            except TextPatchError as exc:
                blockers.append(f"QFunction {label} 受管钩子无法安全插入: {exc}")
        self._add_change(changes, "server", target.root, "Mir200/Envir/Market_Def/QFunction-0.txt", _encode(qdoc, qtext), "qfunction-hook")

        # 当前翎风服真实登录链是 QManage [@Login] ->
        # QuestDiary\\游戏登陆\\登陆脚本.txt [@登陆设置]，不能只依赖
        # QFunction 的自建 [@PlayLogin] 事件。保留 PlayLogin 兼容入口，
        # 同时把活动登录流程挂到真实入口，确保玩家登录后进入大厅。
        login_script_path = target.envir / "QuestDiary" / "游戏登陆" / "登陆脚本.txt"
        login_doc = _read_text(login_script_path)
        login_text = login_doc.text
        login_hook = "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_LOGIN"
        try:
            login_text = install_event_hook(
                login_text,
                self.package_id,
                "登陆设置",
                login_hook,
                login_doc.newline,
            ).text
        except TextPatchError as exc:
            blockers.append(f"登陆脚本 登陆设置 受管钩子无法安全插入: {exc}")
        self._add_change(
            changes,
            "server",
            target.root,
            "Mir200/Envir/QuestDiary/游戏登陆/登陆脚本.txt",
            _encode(login_doc, login_text),
            "login-script-hook",
        )

        qmanage_path = target.envir / "MapQuest_Def" / "QManage.txt"
        mdoc = _read_text(qmanage_path)
        mtext = mdoc.text
        try:
            mtext = _ensure_break_after_login_call(mtext, self.package_id, mdoc.newline)
        except KingModeFlowError as exc:
            blockers.append(str(exc))
        tick = "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_TICK"
        try:
            mtext = ensure_event_label(mtext, self.package_id, "OnTimerEx8", mdoc.newline).text
            mtext = install_event_hook(mtext, self.package_id, "OnTimerEx8", tick, mdoc.newline).text
        except TextPatchError as exc:
            blockers.append(f"QManage OnTimerEx8 受管钩子无法安全插入: {exc}")
        self._add_change(changes, "server", target.root, "Mir200/Envir/MapQuest_Def/QManage.txt", _encode(mdoc, mtext), "qmanage-hook")

        state_root = target.envir / "QuestDiary" / "玄渊数据" / "xy_king_mode"
        for state_name in ("A队国王名单.txt", "B队国王名单.txt", "A队平民名单.txt", "B队平民名单.txt", "活动控制者.txt"):
            state_path = state_root / state_name
            if not state_path.exists():
                self._add_change(
                    changes,
                    "server",
                    target.root,
                    f"Mir200/Envir/QuestDiary/玄渊数据/xy_king_mode/{state_name}",
                    b"",
                    "state-file-create",
                )

        if client_root:
            for name in ("真彩459.map", "xykwa.map", "xykwb.map"):
                if not (self.payload / "maps" / name).exists():
                    blockers.append(f"平台地图资源缺失: {name}")
                else:
                    asset = (self.payload / "maps" / name).read_bytes()
                    existing = client_root / "Map" / name
                    if existing.exists() and existing.read_bytes() != asset:
                        blockers.append(f"客户端地图资源冲突，拒绝覆盖: Map/{name}")
                    else:
                        self._add_change(changes, "client", client_root, f"Map/{name}", asset, "map-copy")
            # vx605 已验收资源使用 150；初始大厅沿用客户端现有 Objects13 WZL/WZX。
            for resource in ("Tiles150.Pak", "Objects150.Pak", "mmap10.Pak", "Objects13.wzl", "Objects13.wzx", "npc.wzl", "npc.wzx"):
                if not (client_root / "data" / resource).exists():
                    blockers.append(f"客户端资源缺失: data/{resource}")
            for name in ("真彩459.map", "xykwa.map", "xykwb.map"):
                asset = (self.payload / "maps" / name).read_bytes()
                existing = target.root / "Mir200" / "Map" / name
                if existing.exists() and existing.read_bytes() != asset:
                    blockers.append(f"服务端地图资源冲突，拒绝覆盖: Mir200/Map/{name}")
                else:
                    self._add_change(changes, "server", target.root, f"Mir200/Map/{name}", asset, "map-copy")

        return FlowPlan(operation, str(target.root), str(client_root) if client_root else None, str(config_path), _sha256(config_doc.text.encode(config_doc.encoding)) or "", list(changes.values()), blockers, warnings, values)

    def apply(self, plan: FlowPlan, yes: bool = False) -> FlowReceipt:
        if not yes:
            raise KingModeFlowError("必须显式提供 --yes")
        if plan.blockers:
            raise KingModeFlowError("预检存在阻止项: " + "；".join(plan.blockers))
        if not plan.changes:
            raise KingModeFlowError("没有需要应用的变更")
        backup_root = self.root / "backups" / (time.strftime("%Y%m%d_%H%M%S") + "-king-mode-flow-" + uuid.uuid4().hex[:8])
        backup_files = backup_root / "files"
        backup_files.mkdir(parents=True, exist_ok=False)
        roots = {"server": Path(plan.server), "client": Path(plan.client) if plan.client else None}
        committed: list[FlowChange] = []
        try:
            for change in plan.changes:
                root = roots.get(change.scope)
                if root is None:
                    raise KingModeFlowError(f"缺少 {change.scope} 根目录")
                destination = root / Path(change.relative_path.replace("/", os.sep))
                current = destination.read_bytes() if destination.exists() else None
                if current != change.before:
                    raise KingModeFlowError(f"预检后目标发生变化: {change.scope}/{change.relative_path}")
                if current is not None:
                    backup = backup_files / change.scope / Path(change.relative_path.replace("/", os.sep))
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    backup.write_bytes(current)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temp = destination.with_name(destination.name + f".xydp-{uuid.uuid4().hex[:8]}.tmp")
                try:
                    temp.write_bytes(change.after)
                    os.replace(temp, destination)
                except OSError as exc:
                    temp.unlink(missing_ok=True)
                    raise KingModeFlowError(f"写入失败（可能被M2/客户端锁定）: {destination}: {exc}") from exc
                committed.append(change)
            receipt = FlowReceipt(
                transaction_id=backup_root.name,
                operation=plan.operation,
                server=plan.server,
                client=plan.client,
                config_hash=plan.config_hash,
                changes=[{"scope": c.scope, "path": c.relative_path, "before_hash": c.before_hash, "after_hash": c.after_hash, "operation": c.operation} for c in committed],
                backup_root=str(backup_root),
                created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                warnings=plan.warnings,
            )
            receipt_path = Path(plan.server) / "Mir200" / "Envir" / ".xydp" / "king-mode-flow-receipt.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(asdict(receipt), ensure_ascii=False, indent=2), encoding="utf-8")
            return receipt
        except Exception:
            for change in reversed(committed):
                root = roots.get(change.scope)
                if root is None:
                    continue
                destination = root / Path(change.relative_path.replace("/", os.sep))
                if change.before is None:
                    destination.unlink(missing_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(change.before)
            raise

    def config_apply(self, server: Path, client: Path | None = None) -> FlowPlan:
        return self.preflight(server, client, operation="king-mode-config-apply")
