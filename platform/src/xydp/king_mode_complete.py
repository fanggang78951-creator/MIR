from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .encoding import TextDocument, encode_text_document, read_text_document
from .king_mode_flow import (
    FlowChange,
    FlowPlan,
    FlowReceipt,
    KingModeFlowError,
    _append_unique,
    _cfg,
    _ensure_break_after_login_call,
    _int,
    _merge_defaults,
    _merge_missing_config_keys,
    _parse_config,
)
from .sqlitepatch import SqlitePatchError, apply_sqlite_upsert
from .target import TargetInspector, is_executable_running
from .textpatch import (
    TextPatchError,
    ensure_event_label,
    install_event_hook,
    install_managed_anchor_hook,
    install_managed_block,
    scan_labels,
)


PACKAGE_ID = "xy.optional.king-mode.complete"
COMBAT_DEPENDENCIES = (
    "xy.combat.core",
    "xy.combat.runtime-refresh",
    "xy.combat.power",
    "xy.combat.blast",
)


def _sha256(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _encode_target(text: str, newline: str = "\r\n") -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", newline).encode("gb18030")


def _read_target_document(path: Path) -> TextDocument:
    if not path.exists():
        return TextDocument("", "gb18030", "\r\n")
    raw = path.read_bytes()
    document = read_text_document(path)
    if raw.isascii():
        return TextDocument(document.text, "gb18030", document.newline)
    return document


def _point(cfg: dict[str, dict[str, str]], section: str, key: str, fallback: str) -> tuple[int, int]:
    raw = _cfg(cfg, section, key, fallback)
    try:
        x_text, y_text = raw.split(",", 1)
        return int(x_text.strip()), int(y_text.strip())
    except (ValueError, TypeError) as exc:
        raise KingModeFlowError(f"坐标必须使用 X,Y：[{section}] {key}={raw}") from exc


def _safe_path(root: Path, relative: str) -> Path:
    candidate = (root / Path(relative.replace("/", os.sep))).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise KingModeFlowError(f"目标路径越界：{relative}") from exc
    return candidate


def _replace_exact(text: str, old: str, new: str, expected: int | None = None) -> str:
    count = text.count(old)
    if expected is not None and count != expected:
        raise KingModeFlowError(f"正式脚本结构已变化，拒绝猜测替换：{old!r}，期望{expected}处，实际{count}处")
    if expected is None and count == 0:
        raise KingModeFlowError(f"正式脚本缺少待渲染内容：{old!r}")
    return text.replace(old, new)


def _merge_map_line(
    text: str,
    logical: str,
    physical: str | None,
    display: str,
    required_flags: tuple[str, ...],
    newline: str,
) -> str:
    pattern = re.compile(
        rf"^\[{re.escape(logical)}(?P<header>[^\]]*)\](?P<tail>[^\r\n]*)(?P<eol>\r?\n|$)",
        re.MULTILINE | re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) > 1:
        lines = [text.count("\n", 0, match.start()) + 1 for match in matches]
        raise KingModeFlowError(f"MapInfo 地图号不唯一：{logical} {lines}")
    expected_map = logical if physical is None else f"{logical}|{physical}"
    header = f"[{expected_map} {display}]"
    if not matches:
        line = " ".join((header, *required_flags)).rstrip()
        prefix = "" if not text or text.endswith(("\n", "\r")) else newline
        return text + prefix + line + newline
    match = matches[0]
    current_header = match.group("header").strip()
    current_map = current_header.split(None, 1)[0] if current_header else ""
    if current_map.startswith("|"):
        current_physical = current_map[1:]
        if physical is None or current_physical.lower() != physical.lower():
            raise KingModeFlowError(
                f"MapInfo 物理地图冲突：{logical} 当前={current_physical}，成果={physical or logical}"
            )
    tail_tokens = match.group("tail").strip().split()
    seen = {token.upper() for token in tail_tokens}
    for flag in required_flags:
        if flag.upper() not in seen:
            tail_tokens.append(flag)
            seen.add(flag.upper())
    replacement = " ".join((header, *tail_tokens)).rstrip() + match.group("eol")
    return text[:match.start()] + replacement + text[match.end():]


def _remove_map_monsters(text: str, logical: str, newline: str) -> str:
    lines = text.splitlines()
    kept = [line for line in lines if not line.strip() or line.strip().split()[0].lower() != logical.lower()]
    suffix = newline if text.endswith(("\n", "\r")) else ""
    return newline.join(kept) + suffix


def _set_ini_names(text: str, values: dict[str, str], newline: str) -> str:
    lines = text.splitlines()
    section = None
    positions: dict[str, list[int]] = {key.lower(): [] for key in values}
    names_start = None
    names_end = len(lines)
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section == "names" and names_end == len(lines):
                names_end = index
            section = stripped[1:-1].strip().lower()
            if section == "names":
                names_start = index
            continue
        if section != "names" or "=" not in raw:
            continue
        key = raw.split("=", 1)[0].strip().lower()
        if key in positions:
            positions[key].append(index)
    duplicates = [key for key, indexes in positions.items() if len(indexes) > 1]
    if duplicates:
        raise KingModeFlowError("Nations.ini 国家名称键重复：" + "、".join(duplicates))
    if names_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        names_start = len(lines)
        lines.append("[Names]")
        names_end = len(lines)
    inserts: list[str] = []
    for key, value in values.items():
        indexes = positions[key.lower()]
        if indexes:
            lines[indexes[0]] = f"{key}={value}"
        else:
            inserts.append(f"{key}={value}")
    if inserts:
        lines[names_end:names_end] = inserts
    return newline.join(lines) + newline


def _strip_exact_legacy_block(text: str, begin: str, end: str, required_call: str) -> str:
    pattern = re.compile(
        rf"^; {re.escape(begin)}\r?\n(?P<body>.*?)^; {re.escape(end)}\r?\n?",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return text
    body = match.group("body")
    calls = [line.strip() for line in body.splitlines() if line.strip().startswith("#CALL")]
    if calls != [required_call]:
        raise KingModeFlowError(f"旧国王模式块含手工内容，拒绝自动迁移：{begin}")
    return text[:match.start()] + text[match.end():]


class KingModeCompleteService:
    """将已通过游戏验收的国王模式作为一个事务植入同引擎初始端。"""

    package_id = PACKAGE_ID

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.package_root = self.root / "packages" / "verified" / PACKAGE_ID
        self.payload = self.package_root / "payload"
        central_config = self.root / "所需材料表格汇总" / "14_国王模式配置.txt"
        self.default_config = central_config if central_config.is_file() else self.payload / "国王模式配置.txt"
        self.template = self.payload / "国王模式赛前流程模板.txt"
        self.scripts = self.payload / "scripts"

    def _values(self, cfg: dict[str, dict[str, str]]) -> dict[str, Any]:
        ax, ay = _point(cfg, "地图", "A方野区落点", "50,50")
        bx, by = _point(cfg, "地图", "B方野区落点", "50,50")
        abx, aby = _point(cfg, "地图", "A方对战复活点", "15,50")
        bbx, bby = _point(cfg, "地图", "B方对战复活点", "100,50")
        lx, ly = _point(cfg, "地图", "登录落点", "14,16")
        signup_x, signup_y = _point(cfg, "NPC", "报名官坐标", "12,16")
        return_x, return_y = _point(cfg, "NPC", "返回官坐标", "16,16")
        meditate_a_x, meditate_a_y = _point(cfg, "NPC", "打坐A坐标", "20,50")
        meditate_b_x, meditate_b_y = _point(cfg, "NPC", "打坐B坐标", "95,50")
        breakthrough_x, breakthrough_y = _point(cfg, "NPC", "破釜沉舟坐标", "58,50")
        demon_x, demon_y = _point(cfg, "NPC", "恶魔契约坐标", "58,55")
        total_waves = _int(cfg, "刷怪", "总波数", 5)
        uniform_count = _int(cfg, "刷怪", "每波普通怪数量", 10)
        waves = []
        for index in range(1, total_waves + 1):
            waves.append({
                "normal": _cfg(cfg, "刷怪", f"第{index}波普通怪", ""),
                "boss": _cfg(cfg, "刷怪", f"第{index}波Boss", ""),
                "normal_count": _int(cfg, "刷怪", f"第{index}波普通怪数量", uniform_count),
            })
        team_size = _int(cfg, "阵容", "每队人数", 5)
        return {
            "login_map": _cfg(cfg, "地图", "登录地图", "T218"),
            "login_physical": _cfg(cfg, "地图", "登录物理地图", "T218.map"),
            "a_wild_map": _cfg(cfg, "地图", "A方野区", "XYKWA"),
            "b_wild_map": _cfg(cfg, "地图", "B方野区", "XYKWB"),
            "battle_map": _cfg(cfg, "地图", "对战地图", "XYGDZY"),
            "login_x": lx,
            "login_y": ly,
            "a_wild_x": ax,
            "a_wild_y": ay,
            "b_wild_x": bx,
            "b_wild_y": by,
            "a_battle_x": abx,
            "a_battle_y": aby,
            "b_battle_x": bbx,
            "b_battle_y": bby,
            "team_size": team_size,
            "team_limit": team_size - 1,
            "king_size": _int(cfg, "阵容", "国王人数", 1),
            "commoner_size": _int(cfg, "阵容", "平民人数", 4),
            "countdown": _int(cfg, "阵容", "倒计时秒数", 10),
            "king_job": _cfg(cfg, "阵容", "国王职业", "战士"),
            "first_spawn_delay_seconds": _int(cfg, "刷怪", "首波延迟秒数", 30),
            "wave_duration_seconds": _int(cfg, "刷怪", "每波持续分钟", 10) * 60,
            "wave_gap_seconds": _int(cfg, "刷怪", "波次间隔秒数", 15),
            "final_entry_delay_seconds": _int(cfg, "刷怪", "第五波清场后入场延迟秒数", 15),
            "boss_count": _int(cfg, "刷怪", "每波Boss数量", 1),
            "total_waves": total_waves,
            "waves": waves,
            "npc_signup_name": _cfg(cfg, "NPC", "报名官名称", "国王模式报名官"),
            "npc_signup_x": signup_x,
            "npc_signup_y": signup_y,
            "npc_signup_appearance": _int(cfg, "NPC", "报名官外观", 24),
            "npc_return_name": _cfg(cfg, "NPC", "返回官名称", "裁判老秦"),
            "npc_return_x": return_x,
            "npc_return_y": return_y,
            "npc_return_appearance": _int(cfg, "NPC", "返回官外观", 24),
            "meditate_a_x": meditate_a_x,
            "meditate_a_y": meditate_a_y,
            "meditate_b_x": meditate_b_x,
            "meditate_b_y": meditate_b_y,
            "breakthrough_x": breakthrough_x,
            "breakthrough_y": breakthrough_y,
            "demon_x": demon_x,
            "demon_y": demon_y,
            "battle_npc_appearance": _int(cfg, "NPC", "角斗场NPC外观", 0),
            "a_nation_id": _int(cfg, "国家", "A方国家编号", 1),
            "a_nation_name": _cfg(cfg, "国家", "A方国家名称", "A国"),
            "b_nation_id": _int(cfg, "国家", "B方国家编号", 2),
            "b_nation_name": _cfg(cfg, "国家", "B方国家名称", "B国"),
            "title_name": _cfg(cfg, "国王属性", "称号名称", "国王"),
            "title_hp": _int(cfg, "国王属性", "最大生命", 2000),
            "title_element": _int(cfg, "国王属性", "全元素", 10),
            "king_max_deaths": _int(cfg, "国王属性", "国王最大死亡次数", 10),
            "normal_kill_reward": _int(cfg, "奖励", "普通击杀奖励", 100),
            "normal_death_loss": _int(cfg, "奖励", "普通死亡扣除", 25),
            "king_kill_reward": _int(cfg, "奖励", "国王击杀奖励", 500),
            "king_death_loss": _int(cfg, "奖励", "国王死亡扣除", 200),
            "normal_exp_rate": _int(cfg, "奖励", "普通击杀经验百分比", 10),
            "king_exp_rate": _int(cfg, "奖励", "国王击杀经验百分比", 50),
            "normal_reborn_percent": _int(cfg, "复活", "普通成员生命魔法百分比", 50),
            "king_reborn_percent": _int(cfg, "复活", "国王生命魔法百分比", 100),
            "break_streak": _int(cfg, "破釜沉舟", "连续死亡次数", 3),
            "break_total": _int(cfg, "破釜沉舟", "累计死亡次数", 6),
            "break_power": _int(cfg, "破釜沉舟", "神力增加百分比", 100),
            "demon_cost": _int(cfg, "恶魔契约", "消耗元宝", 100),
            "demon_add": _int(cfg, "恶魔契约", "三职业上下限增加", 1),
            "meditate_percent": _int(cfg, "打坐恢复", "每秒生命魔法百分比", 5),
            "example": _int(cfg, "状态", "示例配置", 0),
        }

    def _wave_script(self, values: dict[str, Any]) -> str:
        if values["total_waves"] != 5:
            raise KingModeFlowError("国王模式固定五波，[刷怪] 总波数必须为5")
        lines = [
            "#IF", "EQUAL G120 2", "#ACT", "INC G131 1",
            "#IF", "EQUAL G120 3", "#ACT", "DEC G132 1",
        ]

        def generate(wave_no: int) -> list[str]:
            wave = values["waves"][wave_no - 1]
            if not wave["normal"] or not wave["boss"]:
                raise KingModeFlowError(f"第{wave_no}波普通怪和Boss名称不能为空")
            if wave["normal_count"] <= 0:
                raise KingModeFlowError(f"第{wave_no}波普通怪数量必须大于0")
            # 当前服游戏验收通过的翎风语法：地图 X Y 名称 范围 数量。
            return [
                f"MonGenEx {values['a_wild_map']} {values['a_wild_x']} {values['a_wild_y']} {wave['normal']} 35 {wave['normal_count']}",
                f"MonGenEx {values['a_wild_map']} {values['a_wild_x']} {values['a_wild_y']} {wave['boss']} 35 {values['boss_count']}",
                f"MonGenEx {values['b_wild_map']} {values['b_wild_x']} {values['b_wild_y']} {wave['normal']} 35 {wave['normal_count']}",
                f"MonGenEx {values['b_wild_map']} {values['b_wild_x']} {values['b_wild_y']} {wave['boss']} 35 {values['boss_count']}",
            ]

        lines += [
            "#IF", "EQUAL G120 2", "EQUAL G127 0", f"EQUAL G131 {values['first_spawn_delay_seconds']}", "#ACT",
            *generate(1), "MOV G127 1", "MOV G131 0",
            f"SENDMSG 0 第1波：{values['waves'][0]['normal']}与{values['waves'][0]['boss']}已生成。",
        ]
        for wave_no in range(1, 6):
            delay = values["final_entry_delay_seconds"] if wave_no == 5 else values["wave_gap_seconds"]
            lines += [
                "#IF", "EQUAL G120 2", f"EQUAL G127 {wave_no}", f"EQUAL G131 {values['wave_duration_seconds']}", "#ACT",
                f"ClearMapMon {values['a_wild_map']}", f"ClearMapMon {values['b_wild_map']}",
                "MOV G120 3", f"MOV G132 {delay}",
            ]
            if wave_no < 5:
                next_wave = values["waves"][wave_no]
                lines += [
                    "#IF", "EQUAL G120 3", f"EQUAL G127 {wave_no}", "EQUAL G132 0", "#ACT",
                    *generate(wave_no + 1), f"MOV G127 {wave_no + 1}", "MOV G120 2", "MOV G131 0",
                    f"SENDMSG 0 第{wave_no + 1}波：{next_wave['normal']}与{next_wave['boss']}已生成。",
                ]
            else:
                lines += [
                    "#IF", "EQUAL G120 3", "EQUAL G127 5", "EQUAL G132 0", "#ACT",
                    "MOV G120 4", "MOV G133 0",
                    f"SENDMSG 0 第5波清场完成，{values['final_entry_delay_seconds']}秒后进入角斗场。",
                ]
        return "\n".join(lines)

    def _render_flow(self, values: dict[str, Any]) -> bytes:
        text = self.template.read_text(encoding="utf-8")
        text = text.replace("__WAVE_SCRIPT__", self._wave_script(values))
        for key, value in values.items():
            if isinstance(value, (str, int)):
                text = text.replace(f"__KMF_{key.upper()}__", str(value))
        missing = sorted(set(re.findall(r"__[A-Z0-9_]+__", text)))
        if missing:
            raise KingModeFlowError("国王模式模板存在未渲染参数：" + "、".join(missing))
        return _encode_target(text)

    def _add_change(
        self,
        changes: dict[tuple[str, str], FlowChange],
        scope: str,
        root: Path,
        relative: str,
        after: bytes,
        operation: str,
    ) -> None:
        path = _safe_path(root, relative)
        before = path.read_bytes() if path.exists() else None
        normalized = relative.replace("\\", "/")
        if before == after:
            return
        changes[(scope, normalized)] = FlowChange(
            scope, normalized, _sha256(before), _sha256(after) or "", operation, after, before
        )

    def _payload_script(self, name: str) -> bytes:
        path = self.scripts / name
        if not path.exists():
            raise KingModeFlowError(f"国王模式正式脚本缺失：{path}")
        return _encode_target(path.read_text(encoding="utf-8"))

    def _render_core(self, values: dict[str, Any]) -> bytes:
        text = (self.scripts / "国王模式核心.txt").read_text(encoding="utf-8")
        # 先替换带坐标的命令，再替换地图号，避免自定义地图名造成二次匹配。
        replacements = (
            ("MAPMOVE XYKWA 50 50", f"MAPMOVE {values['a_wild_map']} {values['a_wild_x']} {values['a_wild_y']}", 2),
            ("MAPMOVE XYKWB 50 50", f"MAPMOVE {values['b_wild_map']} {values['b_wild_x']} {values['b_wild_y']}", 2),
            ("MAPMOVE XYGDZY 15 50", f"MAPMOVE {values['battle_map']} {values['a_battle_x']} {values['a_battle_y']}", 3),
            ("MAPMOVE XYGDZY 100 50", f"MAPMOVE {values['battle_map']} {values['b_battle_x']} {values['b_battle_y']}", 3),
            ("MOV N$XY_KING_A_X 15", f"MOV N$XY_KING_A_X {values['a_battle_x']}", 1),
            ("MOV N$XY_KING_A_Y 50", f"MOV N$XY_KING_A_Y {values['a_battle_y']}", 1),
            ("MOV N$XY_KING_B_X 100", f"MOV N$XY_KING_B_X {values['b_battle_x']}", 1),
            ("MOV N$XY_KING_B_Y 50", f"MOV N$XY_KING_B_Y {values['b_battle_y']}", 1),
            ("MOV N$XY_KING_TEAM_CAP 5", f"MOV N$XY_KING_TEAM_CAP {values['team_size']}", 2),
        )
        for old, new, expected in replacements:
            text = _replace_exact(text, old, new, expected)
        text = _replace_exact(text, "CHECKMAPNAME XYKWA", f"CHECKMAPNAME {values['a_wild_map']}")
        text = _replace_exact(text, "CHECKMAPNAME XYKWB", f"CHECKMAPNAME {values['b_wild_map']}")
        text = _replace_exact(text, "CHECKMAPNAME XYGDZY", f"CHECKMAPNAME {values['battle_map']}")

        title = values["title_name"]
        for command, expected in (("CHECKFENGHAO 国王", 3), ("RECYCFENGHAO 国王", 2), ("GIVEFENGHAO 国王", 1)):
            text = _replace_exact(text, command, command.replace("国王", title), expected)
        title_pattern = re.compile(r"(?m)^SetNewFengHaoValue 国王 (\d+) = 10$")
        text, count = title_pattern.subn(
            lambda match: f"SetNewFengHaoValue {title} {match.group(1)} = {values['title_element']}", text
        )
        if count != 11:
            raise KingModeFlowError(f"国王称号元素模板应为11行，实际{count}行")
        text = _replace_exact(
            text,
            "SENDMSG 6 国王称号授予成功：最大生命+2000，全元素+10。",
            f"SENDMSG 6 {title}称号授予成功：最大生命+{values['title_hp']}，全元素+{values['title_element']}。",
            1,
        )

        max_threshold = values["king_max_deaths"] - 1
        for old in ("LARGE G136 9", "LARGE G137 9", "SMALL G136 9", "SMALL G137 9"):
            text = _replace_exact(text, old, old.rsplit(" ", 1)[0] + f" {max_threshold}", 1)

        text = _replace_exact(text, "MOV N$XY_KING_KILL_REWARD 500", f"MOV N$XY_KING_KILL_REWARD {values['king_kill_reward']}", 2)
        text = _replace_exact(text, "MOV N$XY_KING_EXP_RATE 50", f"MOV N$XY_KING_EXP_RATE {values['king_exp_rate']}", 2)
        text = _replace_exact(text, "MOV N$XY_KING_KILL_REWARD 100", f"MOV N$XY_KING_KILL_REWARD {values['normal_kill_reward']}", 3)
        text = _replace_exact(text, "MOV N$XY_KING_EXP_RATE 10", f"MOV N$XY_KING_EXP_RATE {values['normal_exp_rate']}", 3)

        for old, new, expected in (
            ("CHECKGAMEGOLD > 24", f"CHECKGAMEGOLD > {values['normal_death_loss'] - 1}", 1),
            ("GAMEGOLD - 25", f"GAMEGOLD - {values['normal_death_loss']}", 1),
            ("死亡扣除25元宝", f"死亡扣除{values['normal_death_loss']}元宝", 1),
            ("元宝不足25", f"元宝不足{values['normal_death_loss']}", 1),
            ("CHECKGAMEGOLD > 199", f"CHECKGAMEGOLD > {values['king_death_loss'] - 1}", 1),
            ("GAMEGOLD - 200", f"GAMEGOLD - {values['king_death_loss']}", 1),
            ("国王死亡扣除200元宝", f"国王死亡扣除{values['king_death_loss']}元宝", 1),
            ("元宝不足200", f"元宝不足{values['king_death_loss']}", 1),
            ("HumanHP = 50", f"HumanHP = {values['normal_reborn_percent']}", 4),
            ("HumanMP = 50", f"HumanMP = {values['normal_reborn_percent']}", 4),
            ("HumanHP = 100", f"HumanHP = {values['king_reborn_percent']}", 6),
            ("HumanMP = 100", f"HumanMP = {values['king_reborn_percent']}", 6),
        ):
            text = _replace_exact(text, old, new, expected)
        return _encode_target(text)

    def _render_title_visual_sync(self, values: dict[str, Any]) -> bytes:
        text = (self.scripts / "称号视觉同步模板.txt").read_text(encoding="utf-8")
        text = _replace_exact(text, "__KMF_TITLE_NAME__", values["title_name"], 1)
        missing = sorted(set(re.findall(r"__[A-Z0-9_]+__", text)))
        if missing:
            raise KingModeFlowError("称号视觉同步模板存在未渲染参数：" + "、".join(missing))
        return _encode_target(text)

    def _render_npc(self, name: str, values: dict[str, Any]) -> bytes:
        text = (self.scripts / name).read_text(encoding="utf-8")
        if name == "国王模式破釜沉舟.txt":
            for old, new, expected in (
                ("连续死亡3次", f"连续死亡{values['break_streak']}次", 1),
                ("累计死亡6次", f"累计死亡{values['break_total']}次", 1),
                ("增加100%", f"增加{values['break_power']}%", 5),
                ("LARGE G138 2", f"LARGE G138 {values['break_streak'] - 1}", 1),
                ("LARGE G139 2", f"LARGE G139 {values['break_streak'] - 1}", 1),
                ("LARGE G136 5", f"LARGE G136 {values['break_total'] - 1}", 1),
                ("LARGE G137 5", f"LARGE G137 {values['break_total'] - 1}", 1),
                ("CHECKMAPNAME XYGDZY", f"CHECKMAPNAME {values['battle_map']}", 4),
            ):
                text = _replace_exact(text, old, new, expected)
        elif name == "国王模式恶魔契约.txt":
            cost = values["demon_cost"]
            add = values["demon_add"]
            for old, new, expected in (
                ("消耗100元宝", f"消耗{cost}元宝", 1),
                ("CHECKGAMEGOLD > 99", f"CHECKGAMEGOLD > {cost - 1}", 1),
                ("GAMEGOLD - 100", f"GAMEGOLD - {cost}", 1),
                ("ChangeHumAbilityEX 5 + 1", f"ChangeHumAbilityEX 5 + {add}", 1),
                ("ChangeHumAbilityEX 6 + 1", f"ChangeHumAbilityEX 6 + {add}", 1),
                ("ChangeHumAbilityEX 7 + 1", f"ChangeHumAbilityEX 7 + {add}", 1),
                ("ChangeHumAbilityEX 8 + 1", f"ChangeHumAbilityEX 8 + {add}", 1),
                ("ChangeHumAbilityEX 9 + 1", f"ChangeHumAbilityEX 9 + {add}", 1),
                ("ChangeHumAbilityEX 10 + 1", f"ChangeHumAbilityEX 10 + {add}", 1),
                ("各增加1点", f"各增加{add}点", 1),
                ("各增加1-1", f"各增加{add}-{add}", 1),
                ("元宝不足100", f"元宝不足{cost}", 1),
            ):
                text = _replace_exact(text, old, new, expected)
        elif name in ("国王模式打坐恢复A.txt", "国王模式打坐恢复B.txt"):
            text = _replace_exact(text, "的5%", f"的{values['meditate_percent']}%", 1)
            text = _replace_exact(text, "魔法5%", f"魔法{values['meditate_percent']}%", 1)
        return _encode_target(text)

    def _apply_combat_dependencies(self, text: str, newline: str, break_power: int) -> str:
        for package_id in COMBAT_DEPENDENCIES:
            manifest_path = self.root / "packages" / "verified" / package_id / "manifest.json"
            if not manifest_path.exists():
                raise KingModeFlowError(f"国王模式常驻依赖缺失：{package_id}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for operation in manifest.get("operations", []):
                if operation.get("target") != "Mir200/Envir/Market_Def/QFunction-0.txt":
                    continue
                op_type = operation.get("type")
                if op_type == "ensure_event_label":
                    text = ensure_event_label(text, package_id, operation["label"], newline).text
                elif op_type == "managed_block":
                    labels = re.findall(r"(?m)^\[@([^\]]+)\]", operation["content"])
                    for label in labels:
                        if scan_labels(text).labels.get(label.lower()) and f"; XYDP-BEGIN {package_id} " not in text:
                            raise KingModeFlowError(f"常驻依赖标签已被非平台脚本占用：[@{label}]")
                    text = install_managed_block(text, package_id, operation["content"], newline).text
                elif op_type == "event_hook":
                    text = ensure_event_label(text, "xy.combat.core", operation["label"], newline).text
                    text = install_event_hook(text, package_id, operation["label"], operation["content"], newline).text
        text = install_managed_anchor_hook(
            text,
            "xy.optional.king-mode.breakthrough",
            "XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR",
            f"#IF\nEQUAL N$XY_KING_BREAK_ACTIVE 1\n#ACT\nINC N$XY_RT_Power {break_power}",
            newline,
        ).text
        text = install_managed_anchor_hook(
            text,
            "xy.optional.king-mode.breakthrough",
            "XY_EQUIP_MAKER_POWER_ANCHOR",
            f"#IF\nEQUAL N$XY_KING_BREAK_ACTIVE 1\n#ACT\nINC N$倍攻 {break_power}",
            newline,
        ).text
        return text

    def _apply_qfunction(self, path: Path, battle_map: str, break_power: int) -> bytes:
        doc = _read_target_document(path)
        text = doc.text
        duplicates = scan_labels(text).duplicates
        if duplicates:
            detail = "、".join(f"{name}:{lines}" for name, lines in duplicates.items())
            raise KingModeFlowError(f"QFunction 存在重复标签：{detail}")
        text = _strip_exact_legacy_block(
            text,
            "XY-KING-KILL-EXP-BEGIN",
            "XY-KING-KILL-EXP-END",
            "#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_KILL_EXP",
        )
        text = _strip_exact_legacy_block(
            text,
            "XY-KING-LETHAL-SETTLEMENT-BEGIN",
            "XY-KING-LETHAL-SETTLEMENT-END",
            "#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_ATTACK_LETHAL",
        )
        text = _strip_exact_legacy_block(
            text,
            "XY-KING-VICTIM-LETHAL-SETTLEMENT-BEGIN",
            "XY-KING-VICTIM-LETHAL-SETTLEMENT-END",
            "#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_STRUCK_LETHAL",
        )
        text = _strip_exact_legacy_block(
            text,
            "XY-KING-NATIVE-REVIVE-BEGIN",
            "XY-KING-NATIVE-REVIVE-END",
            "#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_REVIVAL",
        )
        text = self._apply_combat_dependencies(text, doc.newline, break_power)
        labels = (
            "PlayOffline", "PlayDie", "KillPlay", "PlayLogin", "AttackDamage",
            "HeroAttackDamage", "StruckDamage", "HeroStruckDamage", "Revival", "Run", "Walk",
            "ActiveTitle_2", "UnactiveTitle_2",
        )
        for label in labels:
            text = ensure_event_label(text, "xy.optional.king-mode.core", label, doc.newline).text
        meditate = (
            "#IF\nEQUAL N$XY_KING_MEDITATE 1\n#ACT\nMOV N$XY_KING_MEDITATE 0\n"
            "SETOFFTIMEREX 9\nSENDMSG 6 打坐恢复已停止。"
        )
        hooks = {
            ("xy.optional.king-mode.core", "PlayOffline"): meditate + (
                "\n#IF\nEQUAL N$XY_KING_BREAK_ACTIVE 1\n#ACT\nMOV N$XY_KING_BREAK_ACTIVE 0\n"
                "; 离线后由下次PlayLogin常驻重算恢复，禁止写死POWERRATE 100。\nSENDMSG 6 破釜沉舟效果已结束。"
            ),
            ("xy.optional.king-mode.core", "PlayDie"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_PLAY_DIE\n" + meditate +
                "\n#IF\nEQUAL N$XY_KING_BREAK_ACTIVE 1\n#ACT\nMOV N$XY_KING_BREAK_ACTIVE 0\n"
                "DELAYGOTO 1 @XYDP_RecalcPower\nSENDMSG 6 破釜沉舟效果已结束。"
            ),
            ("xy.optional.king-mode.complete.reward", "KillPlay"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_KILL_EXP"
            ),
            ("xy.optional.king-mode.core", "PlayLogin"): meditate + (
                "\n#IF\nEQUAL N$XY_KING_BREAK_ACTIVE 1\n#ACT\nMOV N$XY_KING_BREAK_ACTIVE 0\n"
                "; 本事件已有xy.combat.power延迟重算，禁止写死POWERRATE 100。\nSENDMSG 6 破釜沉舟效果已结束。"
            ),
            ("xy.optional.king-mode.core", "AttackDamage"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_ATTACK_GUARD\n" + meditate +
                "\n#IF\nCHECKMAPNAME " + battle_map + "\nCHECKCURRTARGETRACE = 0\n#ACT\n"
                "#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_ATTACK_LETHAL"
            ),
            ("xy.optional.king-mode.core", "HeroAttackDamage"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_ATTACK_GUARD\n" + meditate
            ),
            ("xy.optional.king-mode.core", "StruckDamage"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_ATTACK_GUARD\n" + meditate +
                "\n#IF\nCHECKMAPNAME " + battle_map + "\n#ACT\n"
                "#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_STRUCK_LETHAL"
            ),
            ("xy.optional.king-mode.core", "HeroStruckDamage"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_ATTACK_GUARD\n" + meditate
            ),
            ("xy.optional.king-mode.core", "Revival"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式\\国王模式核心.txt] @XY_KING_REVIVAL\n" + meditate +
                "\n#IF\nEQUAL N$XY_KING_BREAK_ACTIVE 1\n#ACT\nMOV N$XY_KING_BREAK_ACTIVE 0\n"
                "DELAYGOTO 1 @XYDP_RecalcPower\nSENDMSG 6 破釜沉舟效果已结束。"
            ),
            ("xy.optional.king-mode.core", "Run"): meditate,
            ("xy.optional.king-mode.core", "Walk"): meditate,
            ("xy.optional.king-mode.flow", "PlayOffline"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_OFFLINE"
            ),
            ("xy.optional.king-mode.flow", "PlayLogin"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_LOGIN"
            ),
            ("xy.optional.king-mode.title-visual", "ActiveTitle_2"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\称号视觉\\称号视觉同步.txt] @XY_TITLE_VISUAL_SYNC"
            ),
            ("xy.optional.king-mode.title-visual", "UnactiveTitle_2"): (
                "#IF\n#ACT\n#CALL [\\玄渊功能\\称号视觉\\称号视觉同步.txt] @XY_TITLE_VISUAL_SYNC"
            ),
        }
        for (package_id, label), content in hooks.items():
            text = install_event_hook(text, package_id, label, content, doc.newline).text
        return encode_text_document(doc, text)

    def _apply_qmanage(self, path: Path, meditate_percent: int) -> bytes:
        doc = _read_target_document(path)
        text = _ensure_break_after_login_call(doc.text, "xy.optional.king-mode.flow", doc.newline)
        for label in ("OnTimerEx8", "OnTimerEx9"):
            text = ensure_event_label(text, "xy.optional.king-mode.complete", label, doc.newline).text
        text = install_event_hook(
            text,
            "xy.optional.king-mode.core",
            "OnTimerEx9",
            f"#IF\nEQUAL N$XY_KING_MEDITATE 1\n#ACT\nHumanHP + {meditate_percent} 0 1 0 0 1\nHumanMP + {meditate_percent} 0 1 1\nBREAK",
            doc.newline,
        ).text
        text = install_event_hook(
            text,
            "xy.optional.king-mode.flow",
            "OnTimerEx8",
            "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_TICK",
            doc.newline,
        ).text
        return encode_text_document(doc, text)

    def _apply_login(self, path: Path) -> bytes:
        doc = _read_target_document(path)
        text = ensure_event_label(doc.text, "xy.optional.king-mode.complete", "登陆设置", doc.newline).text
        text = install_event_hook(
            text,
            "xy.optional.king-mode.core",
            "登陆设置",
            "#ACT\nMOV N$XY_KING_MEDITATE 0\nMOV N$XY_KING_BREAK_ACTIVE 0\nSETOFFTIMEREX 9",
            doc.newline,
        ).text
        text = install_event_hook(
            text,
            "xy.optional.king-mode.flow",
            "登陆设置",
            "#IF\n#ACT\n#CALL [\\玄渊功能\\国王模式赛前\\国王模式赛前流程.txt] @XY_KING_FLOW_LOGIN",
            doc.newline,
        ).text
        text = install_event_hook(
            text,
            "xy.optional.king-mode.title-visual",
            "登陆设置",
            "#IF\n#ACT\n#CALL [\\玄渊功能\\称号视觉\\称号视觉同步.txt] @XY_TITLE_VISUAL_SYNC",
            doc.newline,
        ).text
        return encode_text_document(doc, text)

    def preflight(self, server: Path, client: Path | None = None, operation: str = "king-mode-one-click") -> FlowPlan:
        target = TargetInspector.inspect(Path(server))
        client_root = Path(client).resolve() if client else None
        blockers: list[str] = []
        warnings: list[str] = []
        if client_root is None or not client_root.is_dir():
            blockers.append("国王模式完整安装必须选择客户端根目录")
        if not self.package_root.is_dir():
            blockers.append(f"国王模式正式成果包缺失：{self.package_root}")
        if is_executable_running(target.mir200 / "M2Server.exe"):
            warnings.append("M2Server.exe 正在运行；允许预检和安装，真实文件锁定时事务会完整失败并回滚")

        config_path = target.envir / "QuestDiary" / "玄渊配置" / "国王模式配置.txt"
        default_text = self.default_config.read_text(encoding="utf-8")
        config_doc = _read_target_document(config_path)
        merged_config = _merge_defaults(config_doc.text if config_path.exists() else None, default_text, config_doc.newline)
        if config_path.exists():
            merged_config = _merge_missing_config_keys(merged_config, default_text, config_doc.newline)
        cfg = _parse_config(merged_config)
        try:
            values = self._values(cfg)
        except KingModeFlowError as exc:
            values = {}
            blockers.append(str(exc))
        if values:
            if values["example"] != 0:
                blockers.append("[状态] 示例配置必须为0")
            if values["team_size"] != values["king_size"] + values["commoner_size"]:
                blockers.append("每队人数必须等于国王人数加平民人数")
            if values["team_size"] != 5 or values["king_size"] != 1 or values["commoner_size"] != 4:
                blockers.append("当前已验收国王模式固定为每队1国王+4平民")
            if values["a_nation_id"] == values["b_nation_id"]:
                blockers.append("A/B 两方国家编号不能相同")
            if values["boss_count"] != 1:
                blockers.append("当前已验收规则要求每波Boss数量=1")
            fixed_maps = {
                "login_map": "T218",
                "login_physical": "T218.map",
                "a_wild_map": "XYKWA",
                "b_wild_map": "XYKWB",
                "battle_map": "XYGDZY",
            }
            for key, expected in fixed_maps.items():
                if str(values[key]).lower() != expected.lower():
                    blockers.append(f"完整包地图资源固定为 {expected}，当前配置 {key}={values[key]}")
            positive_fields = {
                "国王最大死亡次数": values["king_max_deaths"],
                "普通死亡扣除": values["normal_death_loss"],
                "国王死亡扣除": values["king_death_loss"],
                "普通成员复活百分比": values["normal_reborn_percent"],
                "国王复活百分比": values["king_reborn_percent"],
                "破釜连续死亡次数": values["break_streak"],
                "破釜累计死亡次数": values["break_total"],
                "破釜神力增加百分比": values["break_power"],
                "恶魔契约消耗": values["demon_cost"],
                "恶魔契约属性增加": values["demon_add"],
                "打坐恢复百分比": values["meditate_percent"],
            }
            for label, number in positive_fields.items():
                if number <= 0:
                    blockers.append(f"{label}必须大于0")
            if not values["title_name"].strip():
                blockers.append("国王称号名称不能为空")
            elif "\r" in values["title_name"] or "\n" in values["title_name"]:
                blockers.append("国王称号名称不能包含换行")

        changes: dict[tuple[str, str], FlowChange] = {}
        self._add_change(
            changes,
            "server",
            target.root,
            "Mir200/Envir/QuestDiary/玄渊配置/国王模式配置.txt",
            encode_text_document(config_doc, merged_config),
            "config-merge",
        )

        if values:
            try:
                core = self._render_core(values)
                flow = self._render_flow(values)
                title_visual_sync = self._render_title_visual_sync(values)
                core_text = core.decode("gb18030")
                flow_text = flow.decode("gb18030")
                title_visual_sync_text = title_visual_sync.decode("gb18030")
                for label in (
                    "XY_KING_APPLY_TITLE", "XY_KING_CLEAR_TITLE", "XY_KING_KILL_EXP",
                    "XY_KING_ATTACK_LETHAL", "XY_KING_STRUCK_LETHAL", "XY_KING_REVIVAL",
                ):
                    if f"[@{label}]" not in core_text:
                        blockers.append(f"正式核心缺少标签：{label}")
                for token in (
                    f"GIVEFENGHAO {values['title_name']} 1",
                    f"SetNewFengHaoValue {values['title_name']} 10 = {values['title_element']}",
                    "CHANGEEXP +",
                ):
                    if token not in core_text:
                        blockers.append(f"正式核心缺少已验收命令：{token}")
                if flow_text.count("MonGenEx ") != 20 or flow_text.count("ClearMapMon ") != 10:
                    blockers.append("五波刷怪必须包含20条MonGenEx和10条ClearMapMon")
                if "ReadConfigFileItem" in flow_text:
                    blockers.append("正式流程禁止运行时读取配置TXT")
                if f"CheckActiveFengHao {values['title_name']}" not in title_visual_sync_text:
                    blockers.append("称号视觉同步缺少当前展示检测")
                if re.search(r"(?im)^\s*(CHECKFENGHAO|GIVEFENGHAO|SetActiveFengHao)\b", title_visual_sync_text):
                    blockers.append("称号视觉同步禁止按拥有判断或改变玩家当前称号")
                self._add_change(
                    changes, "server", target.root,
                    "Mir200/Envir/QuestDiary/玄渊功能/国王模式/国王模式核心.txt", core, "verified-script",
                )
                self._add_change(
                    changes, "server", target.root,
                    "Mir200/Envir/QuestDiary/玄渊功能/国王模式赛前/国王模式赛前流程.txt", flow, "config-render",
                )
                self._add_change(
                    changes, "server", target.root,
                    "Mir200/Envir/QuestDiary/玄渊功能/称号视觉/称号视觉同步.txt",
                    title_visual_sync, "active-title-visual-sync",
                )
                script_targets = {
                    f"Mir200/Envir/Market_Def/玄渊国王模式_赛前报名-{values['login_map']}.txt": "国王模式赛前报名.txt",
                    f"Mir200/Envir/Market_Def/玄渊国王模式_返回大厅-{values['login_map']}.txt": "国王模式返回大厅.txt",
                    f"Mir200/Envir/Market_Def/玄渊国王模式_打坐恢复A-{values['battle_map']}.txt": "国王模式打坐恢复A.txt",
                    f"Mir200/Envir/Market_Def/玄渊国王模式_打坐恢复B-{values['battle_map']}.txt": "国王模式打坐恢复B.txt",
                    f"Mir200/Envir/Market_Def/玄渊国王模式_破釜沉舟-{values['battle_map']}.txt": "国王模式破釜沉舟.txt",
                    f"Mir200/Envir/Market_Def/玄渊国王模式_恶魔契约-{values['battle_map']}.txt": "国王模式恶魔契约.txt",
                }
                for relative, source_name in script_targets.items():
                    self._add_change(
                        changes, "server", target.root, relative,
                        self._render_npc(source_name, values), "verified-npc+config-render",
                    )
            except (KingModeFlowError, UnicodeError, OSError) as exc:
                blockers.append(str(exc))

            try:
                mapinfo_path = target.envir / "MapInfo.txt"
                map_doc = _read_target_document(mapinfo_path)
                mapinfo = map_doc.text
                mapinfo = _merge_map_line(
                    mapinfo, values["login_map"], None, "死亡神殿",
                    ("SAFE", "NORECALL", "NORANDOMMOVE", "NODEARRECALL", "NOGUILDRECALL", "NOMasterRECALL", "NORECONNECT(0)", "DAY"),
                    map_doc.newline,
                )
                mapinfo = _merge_map_line(mapinfo, values["battle_map"], "vx605", "角斗场", (), map_doc.newline)
                wild_flags = ("FIGHT2", "NORECALL", "NOGUILDRECALL", "NODEARRECALL", "NOMasterRECALL", "NORANDOMMOVE")
                mapinfo = _merge_map_line(mapinfo, values["a_wild_map"], "xykwa", "角斗场A方野区", wild_flags, map_doc.newline)
                mapinfo = _merge_map_line(mapinfo, values["b_wild_map"], "xykwb", "角斗场B方野区", wild_flags, map_doc.newline)
                self._add_change(changes, "server", target.root, "Mir200/Envir/MapInfo.txt", encode_text_document(map_doc, mapinfo), "mapinfo")

                minimap_path = target.envir / "MiniMap.txt"
                mini_doc = _read_target_document(minimap_path)
                mini = mini_doc.text
                for line in ("vx605 10606", "xykwa 10606", "xykwb 10606"):
                    mini = _append_unique(mini, line, mini_doc.newline)
                self._add_change(changes, "server", target.root, "Mir200/Envir/MiniMap.txt", encode_text_document(mini_doc, mini), "minimap")

                merchant_path = target.envir / "MerChant.txt"
                merchant_doc = _read_target_document(merchant_path)
                merchant = merchant_doc.text
                merchant_lines = (
                    f"玄渊国王模式_赛前报名\t{values['login_map']}\t{values['npc_signup_x']}\t{values['npc_signup_y']}\t{values['npc_signup_name']}\t0\t{values['npc_signup_appearance']}\t0",
                    f"玄渊国王模式_返回大厅\t{values['login_map']}\t{values['npc_return_x']}\t{values['npc_return_y']}\t{values['npc_return_name']}\t0\t{values['npc_return_appearance']}\t0",
                    f"玄渊国王模式_打坐恢复A\t{values['battle_map']}\t{values['meditate_a_x']}\t{values['meditate_a_y']}\t打坐恢复\t0\t{values['battle_npc_appearance']}\t0",
                    f"玄渊国王模式_打坐恢复B\t{values['battle_map']}\t{values['meditate_b_x']}\t{values['meditate_b_y']}\t打坐恢复\t0\t{values['battle_npc_appearance']}\t0",
                    f"玄渊国王模式_破釜沉舟\t{values['battle_map']}\t{values['breakthrough_x']}\t{values['breakthrough_y']}\t破釜沉舟\t0\t{values['battle_npc_appearance']}\t0",
                    f"玄渊国王模式_恶魔契约\t{values['battle_map']}\t{values['demon_x']}\t{values['demon_y']}\t恶魔契约\t0\t{values['battle_npc_appearance']}\t0",
                )
                for line in merchant_lines:
                    merchant = _append_unique(merchant, line, merchant_doc.newline, (0, 1))
                self._add_change(changes, "server", target.root, "Mir200/Envir/MerChant.txt", encode_text_document(merchant_doc, merchant), "merchant")

                mon_path = target.envir / "MonGen.txt"
                if mon_path.exists():
                    mon_doc = _read_target_document(mon_path)
                    without_login_monsters = _remove_map_monsters(mon_doc.text, values["login_map"], mon_doc.newline)
                    self._add_change(changes, "server", target.root, "Mir200/Envir/MonGen.txt", encode_text_document(mon_doc, without_login_monsters), "safe-map-monster-clean")

                nations_path = target.envir / "Nations" / "Nations.ini"
                nations_doc = _read_target_document(nations_path)
                nations = _set_ini_names(
                    nations_doc.text,
                    {
                        f"NationalNames{values['a_nation_id']}": values["a_nation_name"],
                        f"NationalNames{values['b_nation_id']}": values["b_nation_name"],
                    },
                    nations_doc.newline,
                )
                self._add_change(changes, "server", target.root, "Mir200/Envir/Nations/Nations.ini", encode_text_document(nations_doc, nations), "nation-config")
            except (OSError, TextPatchError, KingModeFlowError) as exc:
                blockers.append(str(exc))

            try:
                qfunction_path = target.envir / "Market_Def" / "QFunction-0.txt"
                self._add_change(
                    changes, "server", target.root, "Mir200/Envir/Market_Def/QFunction-0.txt",
                    self._apply_qfunction(
                        qfunction_path, values["battle_map"], values["break_power"]
                    ), "event-hooks+combat-dependencies",
                )
                qmanage_path = target.envir / "MapQuest_Def" / "QManage.txt"
                self._add_change(
                    changes, "server", target.root, "Mir200/Envir/MapQuest_Def/QManage.txt",
                    self._apply_qmanage(qmanage_path, values["meditate_percent"]), "timer-hooks",
                )
                login_path = target.envir / "QuestDiary" / "游戏登陆" / "登陆脚本.txt"
                self._add_change(
                    changes, "server", target.root, "Mir200/Envir/QuestDiary/游戏登陆/登陆脚本.txt",
                    self._apply_login(login_path), "login-hook",
                )
            except (OSError, TextPatchError, KingModeFlowError, json.JSONDecodeError) as exc:
                blockers.append(str(exc))

            state_root = "Mir200/Envir/QuestDiary/玄渊数据/xy_king_mode"
            empty_names = (
                "A队名单.txt", "B队名单.txt", "A队国王名单.txt", "B队国王名单.txt",
                "A队平民名单.txt", "B队平民名单.txt", "活动控制者.txt",
            )
            for name in empty_names:
                destination = _safe_path(target.root, f"{state_root}/{name}")
                if not destination.exists():
                    self._add_change(changes, "server", target.root, f"{state_root}/{name}", b"", "blank-state-create")
            status_path = _safe_path(target.root, f"{state_root}/国王模式状态.txt")
            if not status_path.exists():
                status = (
                    "[状态]\r\n模式=报名\r\nA队人数=0\r\nB队人数=0\r\nA国王=无\r\nB国王=无\r\n"
                    "A国王死亡=0\r\nB国王死亡=0\r\nA国王连死=0\r\nB国王连死=0\r\n"
                ).encode("gb18030")
                self._add_change(changes, "server", target.root, f"{state_root}/国王模式状态.txt", status, "blank-state-create")

            db_relative = "Mud2/DB/ApexM2.DB"
            db_path = target.root / "Mud2" / "DB" / "ApexM2.DB"
            try:
                database = db_path.read_bytes() if db_path.exists() else None
                title_database = apply_sqlite_upsert(database, {
                    "type": "sqlite_upsert",
                    "table": "StdItems",
                    "unique_key": ["Name"],
                    "allocate": {"Idx": "max_plus_one"},
                    "on_conflict": "error",
                    "values": {
                        "Name": values["title_name"], "StdMode": 70, "Shape": 2, "Weight": 0, "Anicount": 1,
                        "Source": 0, "Reserved": 2, "Looks": 15, "DuraMax": 0,
                        "Ac": 0, "Ac2": 0, "Mac": 0, "Mac2": 0, "Dc": 0, "Dc2": 0,
                        "Mc": 0, "Mc2": 0, "Sc": 0, "Sc2": 0, "Need": 0, "NeedLevel": 0,
                        "Price": 0, "Stock": 0, "Color": 253, "OverLap": 0, "HP": values["title_hp"], "MP": 0,
                        "Light": 0, "Horse": 0,
                    },
                })
                self._add_change(changes, "server", target.root, db_relative, title_database, "king-title-sqlite-upsert")
            except (OSError, SqlitePatchError) as exc:
                blockers.append(f"国王称号数据库预检失败：{exc}")

            map_names = ("T218.map", "vx605.map", "xykwa.map", "xykwb.map")
            for name in map_names:
                source = self.payload / "maps" / name
                if not source.exists():
                    blockers.append(f"平台地图资源缺失：{name}")
                    continue
                asset = source.read_bytes()
                server_existing = target.root / "Mir200" / "Map" / name
                if server_existing.exists() and server_existing.read_bytes() != asset:
                    blockers.append(f"服务端地图冲突，拒绝覆盖：Mir200/Map/{name}")
                else:
                    self._add_change(changes, "server", target.root, f"Mir200/Map/{name}", asset, "map-copy")
                if client_root:
                    client_existing = client_root / "Map" / name
                    if client_existing.exists() and client_existing.read_bytes() != asset:
                        blockers.append(f"客户端地图冲突，拒绝覆盖：Map/{name}")
                    else:
                        self._add_change(changes, "client", client_root, f"Map/{name}", asset, "map-copy")

            if client_root:
                for required in ("data/npc.wzl", "data/npc.wzx", "data/Tiles.wzl", "data/Tiles.wzx", "data/Objects.wzl", "data/Objects.wzx"):
                    if not _safe_path(client_root, required).exists():
                        blockers.append(f"客户端基础资源缺失：{required}")
                client_data = self.payload / "client" / "data"
                for source in sorted(client_data.iterdir()) if client_data.is_dir() else []:
                    relative = f"data/{source.name}"
                    asset = source.read_bytes()
                    existing = _safe_path(client_root, relative)
                    if existing.exists() and existing.read_bytes() != asset:
                        blockers.append(f"客户端补丁冲突，拒绝覆盖：{relative}")
                    else:
                        self._add_change(changes, "client", client_root, relative, asset, "client-patch-copy")
                game_exe = self.root / "assets" / "king-mode" / "client-root" / "国王模式.exe"
                if not game_exe.exists():
                    blockers.append("平台缺少国王模式客户端入口程序")
                else:
                    asset = game_exe.read_bytes()
                    existing = client_root / "国王模式.exe"
                    if existing.exists() and existing.read_bytes() != asset:
                        blockers.append("客户端已有不同版本的 国王模式.exe，拒绝覆盖")
                    else:
                        self._add_change(changes, "client", client_root, "国王模式.exe", asset, "client-entry-copy")

        warnings.extend((
            "完整安装包含A/B国家、国王称号数据库行、神力倍攻和暴击伤害常驻重算链。",
            "安装后必须重启M2；客户端需退出后使用客户端根目录中的 国王模式.exe 重新进入。",
            "怪物数据库尚未包含配置中的怪物时，波次脚本会运行但对应怪物不会生成。",
        ))
        raw_config = config_path.read_bytes() if config_path.exists() else b""
        return FlowPlan(
            operation,
            str(target.root),
            str(client_root) if client_root else None,
            str(config_path),
            _sha256(raw_config) or "",
            list(changes.values()),
            blockers,
            warnings,
            {**values, "combat_dependencies": list(COMBAT_DEPENDENCIES)} if values else {},
        )

    def apply(self, plan: FlowPlan, yes: bool = False) -> FlowReceipt:
        if not yes:
            raise KingModeFlowError("必须显式确认安装")
        if plan.blockers:
            raise KingModeFlowError("预检存在阻止项：" + "；".join(plan.blockers))
        if not plan.changes:
            return FlowReceipt(
                "already-installed", plan.operation, plan.server, plan.client, plan.config_hash,
                [], "", time.strftime("%Y-%m-%d %H:%M:%S"), plan.warnings,
            )
        backup_root = self.root / "backups" / (time.strftime("%Y%m%d_%H%M%S") + "-king-mode-complete-" + uuid.uuid4().hex[:8])
        backup_files = backup_root / "files"
        backup_files.mkdir(parents=True, exist_ok=False)
        roots = {"server": Path(plan.server), "client": Path(plan.client) if plan.client else None}
        committed: list[FlowChange] = []
        receipt_path = Path(plan.server) / "Mir200" / "Envir" / ".xydp" / "king-mode-complete-receipt.json"
        previous_receipt = receipt_path.read_bytes() if receipt_path.exists() else None
        if previous_receipt is not None:
            (backup_root / "previous-receipt.json").write_bytes(previous_receipt)
        try:
            for change in plan.changes:
                root = roots.get(change.scope)
                if root is None:
                    raise KingModeFlowError(f"缺少{change.scope}根目录")
                destination = _safe_path(root, change.relative_path)
                current = destination.read_bytes() if destination.exists() else None
                if current != change.before:
                    raise KingModeFlowError(f"预检后目标发生变化：{change.scope}/{change.relative_path}")
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
                    raise KingModeFlowError(f"写入失败（文件可能被占用）：{destination}：{exc}") from exc
                if _sha256(destination.read_bytes()) != change.after_hash:
                    raise KingModeFlowError(f"写入后哈希校验失败：{destination}")
                committed.append(change)
            receipt = FlowReceipt(
                transaction_id=backup_root.name,
                operation=plan.operation,
                server=plan.server,
                client=plan.client,
                config_hash=plan.config_hash,
                changes=[
                    {
                        "scope": change.scope,
                        "path": change.relative_path,
                        "before_hash": change.before_hash,
                        "after_hash": change.after_hash,
                        "operation": change.operation,
                    }
                    for change in committed
                ],
                backup_root=str(backup_root),
                created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                warnings=plan.warnings,
            )
            receipt_data = json.dumps(asdict(receipt), ensure_ascii=False, indent=2).encode("utf-8")
            (backup_root / "receipt.json").write_bytes(receipt_data)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            temp_receipt = receipt_path.with_suffix(".tmp")
            temp_receipt.write_bytes(receipt_data)
            os.replace(temp_receipt, receipt_path)
            return receipt
        except Exception:
            for change in reversed(committed):
                root = roots.get(change.scope)
                if root is None:
                    continue
                destination = _safe_path(root, change.relative_path)
                if change.before is None:
                    destination.unlink(missing_ok=True)
                else:
                    backup = backup_files / change.scope / Path(change.relative_path.replace("/", os.sep))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temp = destination.with_name(destination.name + f".rollback-{uuid.uuid4().hex[:8]}.tmp")
                    temp.write_bytes(backup.read_bytes())
                    os.replace(temp, destination)
            raise

    def rollback(self, server: Path, yes: bool = False) -> str:
        if not yes:
            raise KingModeFlowError("回滚必须显式确认")
        server_root = Path(server).resolve()
        receipt_path = server_root / "Mir200" / "Envir" / ".xydp" / "king-mode-complete-receipt.json"
        if not receipt_path.exists():
            raise KingModeFlowError("目标服没有可回滚的国王模式一键安装收据")
        data = json.loads(receipt_path.read_text(encoding="utf-8"))
        if Path(data["server"]).resolve() != server_root:
            raise KingModeFlowError("安装收据与当前服务端不匹配")
        backup_root = Path(data["backup_root"])
        if not backup_root.is_dir():
            raise KingModeFlowError(f"平台备份不存在：{backup_root}")
        roots = {"server": server_root, "client": Path(data["client"]).resolve() if data.get("client") else None}
        for change in data["changes"]:
            root = roots.get(change["scope"])
            if root is None:
                raise KingModeFlowError(f"回滚缺少{change['scope']}根目录")
            destination = _safe_path(root, change["path"])
            current = destination.read_bytes() if destination.exists() else None
            if _sha256(current) != change["after_hash"]:
                raise KingModeFlowError(f"安装后内容已被修改，拒绝回滚：{change['scope']}/{change['path']}")
        for change in reversed(data["changes"]):
            root = roots[change["scope"]]
            destination = _safe_path(root, change["path"])
            if change["before_hash"] is None:
                destination.unlink(missing_ok=True)
            else:
                backup = backup_root / "files" / change["scope"] / Path(change["path"].replace("/", os.sep))
                if not backup.exists() or _sha256(backup.read_bytes()) != change["before_hash"]:
                    raise KingModeFlowError(f"回滚备份损坏：{backup}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                temp = destination.with_name(destination.name + f".rollback-{uuid.uuid4().hex[:8]}.tmp")
                temp.write_bytes(backup.read_bytes())
                os.replace(temp, destination)
        previous = backup_root / "previous-receipt.json"
        if previous.exists():
            receipt_path.write_bytes(previous.read_bytes())
        else:
            receipt_path.unlink(missing_ok=True)
        (backup_root / "rollback.json").write_text(
            json.dumps({"transaction_id": data["transaction_id"], "rolled_back_at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(data["transaction_id"])

    def config_apply(self, server: Path, client: Path | None = None) -> FlowPlan:
        return self.preflight(server, client, operation="king-mode-config-apply")
