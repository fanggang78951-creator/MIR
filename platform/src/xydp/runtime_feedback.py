from __future__ import annotations

"""读取 M2 运行日志，把真实失败反馈带回预检，而不是重复发布同一错误。"""

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Iterable


@dataclass(frozen=True)
class RuntimeIssue:
    kind: str
    severity: str
    message: str
    source: str = ""
    line: int | None = None
    command: str = ""
    log_file: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_SCRIPT_ERROR = re.compile(r"脚本错误:\s*(?P<command>.*?)\s*第[:：](?P<line>\d+)\s*行:\s*(?P<source>.+)$")
_NPC_COORDINATE = re.compile(r"添加Npc到地图坐标失败\.\.\.(?P<name>.+?)\s+(?P<map>\S+)\s*\((?P<x>\d+):(?P<y>\d+)\)")


def _decode_log(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "utf-16-le"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", errors="replace")


def parse_m2_log(text: str, log_file: Path | str = "") -> list[RuntimeIssue]:
    issues: list[RuntimeIssue] = []
    log_name = str(log_file)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _SCRIPT_ERROR.search(line)
        if match:
            command = match.group("command").strip()
            source = match.group("source").strip()
            if command.startswith("ReadConfigFileItem") and "Market_Def" in source:
                message = (
                    "M2 已确认该 NPC 脚本上下文不接受 ReadConfigFileItem；"
                    "配置读取必须放入 QFunction/QManage 核心入口，NPC 只保留稳定触发命令。"
                )
            else:
                message = f"M2 报告脚本错误：{command}"
            issues.append(RuntimeIssue("script-error", "block", message, source, int(match.group("line")), command, log_name))
            continue
        match = _NPC_COORDINATE.search(line)
        if match:
            issues.append(RuntimeIssue(
                "npc-coordinate", "warn",
                f"NPC“{match.group('name').strip()}”未能放置到 {match.group('map')}({match.group('x')},{match.group('y')})，请检查地图可通行坐标。",
                match.group("map"), None, "", log_name,
            ))
    return issues


def recent_m2_issues(server_root: Path, *, max_files: int = 5) -> list[RuntimeIssue]:
    log_root = Path(server_root) / "Mir200" / "Log"
    if not log_root.is_dir():
        return []
    paths = sorted(log_root.glob("*.txt"), key=lambda item: item.stat().st_mtime, reverse=True)[:max_files]
    issues: list[RuntimeIssue] = []
    for path in paths:
        try:
            issues.extend(parse_m2_log(_decode_log(path), path))
        except OSError:
            continue
    unique: list[RuntimeIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (issue.kind, issue.source, issue.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def unsafe_npc_commands(script_text: str) -> list[str]:
    """返回已有实服日志证明在 Market_Def NPC 上会报错的命令。"""
    commands = []
    if re.search(r"(?im)^\s*ReadConfigFileItem\b", script_text):
        commands.append("ReadConfigFileItem")
    return commands


def contract_gaps(changes: Iterable[object], required: dict[str, Iterable[str]]) -> list[str]:
    """检查计划中的共享文件是否真的含有活动运行入口标记。"""
    by_path = {str(getattr(change, "relative_path", "")): getattr(change, "after", b"") for change in changes}
    gaps: list[str] = []
    for path, markers in required.items():
        content = by_path.get(path, b"")
        if isinstance(content, bytes):
            content = content.decode("gb18030", errors="replace")
        for marker in markers:
            if marker not in content:
                gaps.append(f"{path} 缺少运行入口：{marker}")
    return gaps
