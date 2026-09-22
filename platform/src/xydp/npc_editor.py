from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .encoding import TextDocument, encode_text_document, read_text_document
from .installer import InstallPlan, Installer, PlannedChange
from .runtime_feedback import contract_gaps, recent_m2_issues, unsafe_npc_commands
from .target import TargetInspector, is_executable_running
from .textpatch import TextPatchError, add_unique_line, ensure_event_label, install_event_hook


class NpcEditorError(ValueError):
    """NPC 草稿或成果包生成错误。"""


@dataclass
class NpcDraft:
    package_id: str = "xy.npc.new-npc"
    display_name: str = "新NPC"
    script_path: str = "玄渊NPC/新NPC"
    map_code: str = "0"
    x: int = 34
    y: int = 30
    visible_name: str = "新NPC"
    appearance: int = 0
    patch_library: str = "Npc"
    patch_index: int = 0
    patch_source: str = ""
    patch_status: str = "manual-required"
    script_text: str = "[@Main]\n#SAY\n欢迎来到新NPC。\\\n<关闭/@exit>\n"


@dataclass
class NpcDirectPlan:
    target: Path
    draft: NpcDraft
    changes: list[PlannedChange] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    operation: str = "npc-direct-import"
    drafts: list[NpcDraft] = field(default_factory=list)


@dataclass(frozen=True)
class ActivityEntryContract:
    """非常驻活动的公共入口契约。

    活动不能只投放一个脚本文件；它至少要声明自己依赖的事件文件，
    并把登录、QFunction、QManage 等入口和 NPC 注册纳入同一预检/事务。
    后续活动只需复用这个契约，不再靠人工记忆补注册行。
    """

    package_id: str
    required_files: tuple[str, ...] = ()
    login_hooks: dict[str, str] = field(default_factory=dict)
    qfunction_hooks: dict[str, str] = field(default_factory=dict)
    qmanage_hooks: dict[str, str] = field(default_factory=dict)


def _activity_path(plan: NpcDirectPlan, relative_path: str) -> Path:
    return plan.target.root / Path(relative_path.replace("/", "\\"))


def add_activity_entry_contract(plan: NpcDirectPlan, contract: ActivityEntryContract) -> None:
    """把活动入口依赖加入直接导入计划。

    文件不存在是阻止项；文件存在时所有钩子都走受管块/受管事件桩，
    因此重复预检幂等，目标文件被手工改动时会安全停止。
    """
    for relative_path in contract.required_files:
        path = _activity_path(plan, relative_path)
        if not path.is_file():
            plan.blockers.append(f"活动依赖文件不存在：{relative_path}")
    if contract.login_hooks and _activity_path(plan, "Mir200/Envir/QuestDiary/游戏登陆/登陆脚本.txt").is_file():
        add_managed_event_hooks(
            plan,
            "Mir200/Envir/QuestDiary/游戏登陆/登陆脚本.txt",
            contract.package_id,
            contract.login_hooks,
        )
    if contract.qfunction_hooks and _activity_path(plan, "Mir200/Envir/Market_Def/QFunction-0.txt").is_file():
        add_managed_event_hooks(
            plan,
            "Mir200/Envir/Market_Def/QFunction-0.txt",
            contract.package_id,
            contract.qfunction_hooks,
        )
    if contract.qmanage_hooks and _activity_path(plan, "Mir200/Envir/MapQuest_Def/QManage.txt").is_file():
        add_managed_event_hooks(
            plan,
            "Mir200/Envir/MapQuest_Def/QManage.txt",
            contract.package_id,
            contract.qmanage_hooks,
        )


def _server_relative_script(draft: NpcDraft) -> str:
    return f"Mir200/Envir/Market_Def/{draft.script_path}-{draft.map_code}.txt"


def _new_document(text: str, encoding: str = "gb18030", newline: str = "\r\n") -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    return encode_text_document(TextDocument("", encoding, newline), normalized)


def _platform_owns_change(server_root: Path, package_id: str, relative_path: str, before: bytes) -> bool:
    """仅当当前字节仍等于平台上一笔收据的 after_hash 时允许受管升级。"""
    state_path = Path(server_root) / ".xydp" / "installed.json"
    if not state_path.is_file():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if package_id not in state.get("packages", {}):
            return False
        expected = hashlib.sha256(before).hexdigest()
        for transaction_id in reversed(state.get("transactions", [])):
            receipt_path = state_path.parent / "transactions" / f"{transaction_id}.json"
            if not receipt_path.is_file():
                continue
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            for change in receipt.get("changes", []):
                if (str(change.get("path", "")).replace("\\", "/") == relative_path.replace("\\", "/")
                        and str(change.get("after_hash", "")).lower() == expected
                        and package_id in receipt.get("packages", {})):
                    return True
    except (OSError, ValueError, TypeError):
        return False
    return False


def direct_preflight_many(drafts: list[NpcDraft], server_root: Path) -> NpcDirectPlan:
    if not drafts:
        raise NpcEditorError("至少需要一个 NPC 草稿")
    checked_drafts = [validate_draft(item) for item in drafts]
    target = TargetInspector.inspect(Path(server_root))
    plan = NpcDirectPlan(
        target=target,
        draft=checked_drafts[0],
        operation="npc-direct-batch-import" if len(checked_drafts) > 1 else "npc-direct-import",
        drafts=checked_drafts,
    )
    if is_executable_running(target.mir200 / "M2Server.exe"):
        plan.warnings.append("M2Server.exe 正在运行；文件若被锁定，提交会安全失败且不留下半成品。")
    # 把上一轮 M2 的真实报错反馈带回本轮预检；只看最新日志，避免旧日志永久阻塞新版本。
    latest_issues = recent_m2_issues(target.root, max_files=1)
    draft_names = {Path(item.script_path).name for item in checked_drafts}
    seen_runtime_keys: set[tuple[str, str, str]] = set()
    for issue in latest_issues:
        runtime_key = (issue.kind, issue.source, issue.message)
        if runtime_key in seen_runtime_keys:
            continue
        seen_runtime_keys.add(runtime_key)
        if issue.source and any(name in issue.source for name in draft_names):
            matching = next((item for item in checked_drafts if Path(item.script_path).name in issue.source), None)
            command_name = issue.command.split(" ", 1)[0] if issue.command else ""
            if matching is not None and command_name and command_name not in matching.script_text:
                plan.warnings.append(f"上一轮 M2 的错误命令已从本次 NPC 模板移除：{command_name}（{issue.source}:{issue.line}）")
            else:
                plan.blockers.append(f"上一轮 M2 已记录同一 NPC 的运行错误：{issue.message}（{issue.source}:{issue.line}）")
        else:
            plan.warnings.append(f"最新 M2 日志反馈：{issue.message}")
    map_info = target.envir / "MapInfo.txt"
    if not map_info.is_file():
        plan.blockers.append("活动依赖文件不存在：Mir200/Envir/MapInfo.txt")
        map_doc = TextDocument("", "gb18030", "\r\n")
    else:
        map_doc = read_text_document(map_info)
    seen_scripts: set[str] = set()
    for checked in checked_drafts:
        if checked.map_code.casefold() not in map_doc.text.casefold():
            message = f"MapInfo.txt 中找不到地图代码：{checked.map_code}"
            if message not in plan.blockers:
                plan.blockers.append(message)
        script_relative = _server_relative_script(checked)
        if script_relative in seen_scripts:
            plan.blockers.append(f"批量 NPC 使用了重复脚本路径：{script_relative}")
            continue
        seen_scripts.add(script_relative)
        script_path = target.root / Path(script_relative.replace("/", "\\"))
        script_after = _new_document(checked.script_text)
        if script_path.exists():
            try:
                current = read_text_document(script_path)
                desired = checked.script_text.replace("\n", current.newline)
                if current.text.replace("\r\n", "\n").replace("\r", "\n").rstrip() != desired.replace("\r\n", "\n").replace("\r", "\n").rstrip():
                    package_id = f"npc-direct:{checked.package_id}"
                    old_unsafe = unsafe_npc_commands(current.text)
                    if old_unsafe and not unsafe_npc_commands(checked.script_text) and _platform_owns_change(target.root, package_id, script_relative, script_path.read_bytes()):
                        plan.warnings.append(f"识别为平台已登记的失败 NPC 修复升级，将在事务备份后替换：{script_relative}")
                    else:
                        plan.blockers.append(f"NPC脚本已存在且内容不同，禁止覆盖：{script_relative}")
                else:
                    script_after = script_path.read_bytes()
            except UnicodeError as exc:
                plan.blockers.append(f"NPC脚本编码无法识别：{script_relative} ({exc})")
        plan.changes.append(PlannedChange(script_relative, script_path.read_bytes() if script_path.exists() else None, script_after, "npc-script-direct", f"npc-direct:{checked.package_id}"))

    merchant_relative = "Mir200/Envir/MerChant.txt"
    merchant_path = target.root / Path(merchant_relative.replace("/", "\\"))
    if merchant_path.exists():
        merchant_doc = read_text_document(merchant_path)
    else:
        merchant_doc = TextDocument("", "gb18030", "\r\n")
    merchant_text = merchant_doc.text
    try:
        for checked in checked_drafts:
            merchant_line = f"{checked.script_path}\t{checked.map_code}\t{checked.x}\t{checked.y}\t{checked.visible_name}\t0\t{checked.appearance}\t0"
            merchant_text = add_unique_line(merchant_text, merchant_line, [0, 1], merchant_doc.newline).text
        merchant_after = encode_text_document(merchant_doc, merchant_text)
    except TextPatchError as exc:
        plan.blockers.append(f"MerChant 唯一键冲突：{exc}")
        merchant_after = merchant_path.read_bytes() if merchant_path.exists() else _new_document(merchant_doc.text)
    plan.changes.append(PlannedChange(merchant_relative, merchant_path.read_bytes() if merchant_path.exists() else None, merchant_after, "npc-register-direct", f"npc-direct:{checked_drafts[0].package_id}"))
    return plan


def direct_preflight(draft: NpcDraft, server_root: Path) -> NpcDirectPlan:
    return direct_preflight_many([draft], server_root)


def direct_install(plan: NpcDirectPlan, installer: Installer):
    if plan.blockers:
        raise NpcEditorError("直接导入被阻止：\n" + "\n".join(plan.blockers))
    drafts = plan.drafts or [plan.draft]
    package_ids: list[str] = []
    for item in drafts:
        package_id = f"npc-direct:{item.package_id}"
        if package_id not in package_ids:
            package_ids.append(package_id)
    for change in plan.changes:
        if change.package_id not in package_ids:
            package_ids.append(change.package_id)
    install_plan = InstallPlan(
        target_root=str(plan.target.root),
        client_root=None,
        package_ids=package_ids,
        package_versions={item: "1.0.0" for item in package_ids},
        parameters=asdict(drafts[0]) if len(drafts) == 1 else {"npcs": [asdict(item) for item in drafts]},
        changes=[change for change in plan.changes if change.before != change.after],
        warnings=plan.warnings,
        operation_type=plan.operation,
        candidate_packages=[],
    )
    return installer.install(install_plan)


def add_managed_event_hooks(plan: NpcDirectPlan, relative_path: str, package_id: str, hooks: dict[str, str]) -> None:
    """在直接导入计划中加入受管事件标签和钩子，预检阶段不写目标服。"""
    path = plan.target.root / Path(relative_path.replace("/", "\\"))
    if not path.exists():
        plan.blockers.append(f"事件文件不存在：{relative_path}")
        return
    try:
        document = read_text_document(path)
        text = document.text
        for label, content in hooks.items():
            text = ensure_event_label(text, package_id, label, document.newline).text
            text = install_event_hook(text, package_id, label, content, document.newline).text
        after = encode_text_document(document, text)
        plan.changes.append(PlannedChange(relative_path, path.read_bytes(), after, "npc-runtime-hook", package_id))
    except (OSError, UnicodeError, TextPatchError) as exc:
        plan.blockers.append(f"事件钩子无法安全合并：{relative_path} ({exc})")


@dataclass
class KingModeNpcConfig:
    map_code: str = "XYGDZY"
    a_spawn_x: int = 15
    a_spawn_y: int = 50
    b_spawn_x: int = 100
    b_spawn_y: int = 50
    a_recovery_x: int = 20
    a_recovery_y: int = 50
    b_recovery_x: int = 95
    b_recovery_y: int = 50
    breakthrough_x: int = 58
    breakthrough_y: int = 50
    demon_x: int = 58
    demon_y: int = 55
    appearance_recovery_a: int = 0
    appearance_recovery_b: int = 0
    appearance_breakthrough: int = 0
    appearance_demon: int = 0


def validate_king_mode_config(config: KingModeNpcConfig) -> KingModeNpcConfig:
    map_code = config.map_code.strip()
    if not map_code:
        raise NpcEditorError("国王模式地图代码不能为空")
    values = asdict(config)
    for key, value in values.items():
        if key == "map_code":
            continue
        values[key] = _safe_int(value, key)
    values["map_code"] = map_code
    return KingModeNpcConfig(**values)


def _king_recovery_script() -> str:
    return """[@Main]
#SAY
打坐恢复：每秒恢复最大生命和魔法的5%。受到攻击或移动后自动停止。\\
<开始打坐/@XY_KING_MEDITATE_START>\\
<停止打坐/@XY_KING_MEDITATE_STOP>\\
<关闭/@exit>

[@XY_KING_MEDITATE_START]
#ACT
MOV N$XY_KING_MEDITATE 1
SETONTIMEREX 9 1000
SENDMSG 6 已开始打坐，每秒恢复最大生命和魔法5%。
BREAK

[@XY_KING_MEDITATE_STOP]
#ACT
MOV N$XY_KING_MEDITATE 0
SETOFFTIMEREX 9
SENDMSG 6 打坐恢复已停止。
BREAK
"""


def _king_breakthrough_script() -> str:
    return """[@Main]
#SAY
破釜沉舟：仅国王可用。连续被击杀3次，或累计被击杀6次后，攻击力翻倍。\\
<发动破釜沉舟/@XY_KING_BREAKTHROUGH>\\
<关闭/@exit>

[@XY_KING_BREAKTHROUGH]
#IF
EQUAL N$XY_KING_BREAK_ACTIVE 1
#ACT
SENDMSG 5 破釜沉舟已经发动。
BREAK

#IF
EQUAL N$XY_KING_MODE 1
EQUAL S$XY_KING_A_KING <$USERNAME>
LARGE N$XY_KING_A_STREAK 2
#ACT
POWERRATE 200 0 0 1 0
MOV N$XY_KING_BREAK_ACTIVE 1
SENDMSG 0 A队国王发动破釜沉舟，攻击翻倍。
BREAK

#IF
EQUAL N$XY_KING_MODE 1
EQUAL S$XY_KING_A_KING <$USERNAME>
LARGE N$XY_KING_A_DEATHS 5
#ACT
POWERRATE 200 0 0 1 0
MOV N$XY_KING_BREAK_ACTIVE 1
SENDMSG 0 A队国王发动破釜沉舟，攻击翻倍。
BREAK

#IF
EQUAL N$XY_KING_MODE 1
EQUAL S$XY_KING_B_KING <$USERNAME>
LARGE N$XY_KING_B_STREAK 2
#ACT
POWERRATE 200 0 0 1 0
MOV N$XY_KING_BREAK_ACTIVE 1
SENDMSG 0 B队国王发动破釜沉舟，攻击翻倍。
BREAK

#IF
EQUAL N$XY_KING_MODE 1
EQUAL S$XY_KING_B_KING <$USERNAME>
LARGE N$XY_KING_B_DEATHS 5
#ACT
POWERRATE 200 0 0 1 0
MOV N$XY_KING_BREAK_ACTIVE 1
SENDMSG 0 B队国王发动破釜沉舟，攻击翻倍。
BREAK

#ACT
SENDMSG 5 你当前不是国王，或尚未达到破釜沉舟条件。
BREAK
"""


def _king_demon_script() -> str:
    return """[@Main]
#SAY
恶魔契约：消耗100元宝，攻击、魔法、道术下限和上限各增加1点。\\
<签订恶魔契约/@XY_KING_DEMON_CONTRACT>\\
<关闭/@exit>

[@XY_KING_DEMON_CONTRACT]
#IF
CHECKGAMEDIAMOND 100
#ACT
GAMEDIAMOND - 100
ChangeHumAbilityEX 5 + 1
ChangeHumAbilityEX 6 + 1
ChangeHumAbilityEX 7 + 1
ChangeHumAbilityEX 8 + 1
ChangeHumAbilityEX 9 + 1
ChangeHumAbilityEX 10 + 1
SENDMSG 0 恶魔契约生效：攻击、魔法、道术各增加1-1。
BREAK

#ACT
SENDMSG 5 元宝不足100，无法签订恶魔契约。
BREAK
"""


def build_king_mode_npcs(config: KingModeNpcConfig) -> list[NpcDraft]:
    checked = validate_king_mode_config(config)
    common = {"map_code": checked.map_code, "patch_library": "Npc", "patch_status": "manual-required"}
    return [
        NpcDraft(package_id="xy.npc.king-mode-meditate-a", display_name="国王模式-打坐恢复A", script_path="玄渊国王模式_打坐恢复A", x=checked.a_recovery_x, y=checked.a_recovery_y, visible_name="打坐恢复", appearance=checked.appearance_recovery_a, script_text=_king_recovery_script(), **common),
        NpcDraft(package_id="xy.npc.king-mode-meditate-b", display_name="国王模式-打坐恢复B", script_path="玄渊国王模式_打坐恢复B", x=checked.b_recovery_x, y=checked.b_recovery_y, visible_name="打坐恢复", appearance=checked.appearance_recovery_b, script_text=_king_recovery_script(), **common),
        NpcDraft(package_id="xy.npc.king-mode-breakthrough", display_name="国王模式-破釜沉舟", script_path="玄渊国王模式_破釜沉舟", x=checked.breakthrough_x, y=checked.breakthrough_y, visible_name="破釜沉舟", appearance=checked.appearance_breakthrough, script_text=_king_breakthrough_script(), **common),
        NpcDraft(package_id="xy.npc.king-mode-demon-contract", display_name="国王模式-恶魔契约", script_path="玄渊国王模式_恶魔契约", x=checked.demon_x, y=checked.demon_y, visible_name="恶魔契约", appearance=checked.appearance_demon, script_text=_king_demon_script(), **common),
    ]


def _king_mode_config_text(config: KingModeNpcConfig) -> str:
    """按预设窗口的参数生成活动配置，不把坐标藏在核心脚本里。"""
    checked = validate_king_mode_config(config)
    return f"""[基础]
功能开关=1
总人数=10
每队人数=5
活动地图={checked.map_code}
报名状态=1
战斗状态=0

[A队复活点]
地图={checked.map_code}
X={checked.a_spawn_x}
Y={checked.a_spawn_y}
方向=0

[B队复活点]
地图={checked.map_code}
X={checked.b_spawn_x}
Y={checked.b_spawn_y}
方向=4

[国王属性]
称号名称=国王模式国王
最大生命=2000
全元素=10
国王最大死亡次数=10

[奖励]
普通击杀奖励=100
普通死亡扣除=25
国王击杀奖励=500
国王死亡扣除=500

[运行时]
状态文件=..\\QuestDiary\\玄渊数据\\xy_king_mode\\国王模式状态.txt
A队名单=..\\QuestDiary\\玄渊数据\\xy_king_mode\\A队名单.txt
B队名单=..\\QuestDiary\\玄渊数据\\xy_king_mode\\B队名单.txt
全元素命令=待在目标服实测后填写
"""


def _queue_activity_file(
    plan: NpcDirectPlan,
    relative_path: str,
    after: bytes,
    package_id: str,
    *,
    preserve_existing: bool = False,
    allow_managed_upgrade: bool = False,
) -> None:
    """把活动母文件加入计划；已有母文件不同则阻止覆盖，状态文件例外只初始化一次。"""
    path = _activity_path(plan, relative_path)
    if path.exists() and not path.is_file():
        plan.blockers.append(f"活动目标路径不是文件：{relative_path}")
        return
    before = path.read_bytes() if path.is_file() else None
    if before is not None:
        if preserve_existing:
            plan.warnings.append(f"保留已存在活动状态文件：{relative_path}")
            return
        if before != after:
            if allow_managed_upgrade and _platform_owns_change(plan.target.root, package_id, relative_path, before):
                plan.warnings.append(f"识别为平台已登记的活动核心升级，将在事务备份后替换：{relative_path}")
                plan.changes.append(PlannedChange(relative_path, before, after, "activity-upgrade", package_id))
            else:
                plan.blockers.append(f"活动母文件已存在且内容不同，禁止覆盖：{relative_path}")
        return
        return
    plan.changes.append(PlannedChange(relative_path, None, after, "activity-seed-file", package_id))


def _seed_king_mode_files(plan: NpcDirectPlan, config: KingModeNpcConfig) -> None:
    # 源码运行时从 src/xydp 回到平台根目录；PyInstaller 单文件运行时，
    # __file__ 位于 Windows 临时解包目录，必须改用 EXE 所在目录回溯。
    platform_root = (
        Path(sys.executable).resolve().parent.parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2]
    )
    payload_root = platform_root / "packages" / "candidate" / "xy.optional.king-mode.core" / "payload"
    package_id = "xy.optional.king-mode.core"
    for filename, relative_path in (
        ("国王模式核心.txt", "Mir200/Envir/QuestDiary/玄渊功能/国王模式/国王模式核心.txt"),
    ):
        source = payload_root / filename
        if not source.is_file():
            plan.blockers.append(f"平台核心成果缺失：{source}")
            continue
        _queue_activity_file(
            plan,
            relative_path,
            _new_document(source.read_text(encoding="utf-8")),
            package_id,
            allow_managed_upgrade=True,
        )
    config_bytes = _new_document(_king_mode_config_text(config))
    _queue_activity_file(
        plan,
        "Mir200/Envir/QuestDiary/玄渊配置/国王模式配置.txt",
        config_bytes,
        package_id,
    )
    state_files = {
        "Mir200/Envir/QuestDiary/玄渊数据/xy_king_mode/国王模式状态.txt": "[状态]\n模式=报名\nA队人数=0\nB队人数=0\nA国王死亡=0\nB国王死亡=0\nA国王连死=0\nB国王连死=0\n",
        "Mir200/Envir/QuestDiary/玄渊数据/xy_king_mode/A队名单.txt": "",
        "Mir200/Envir/QuestDiary/玄渊数据/xy_king_mode/B队名单.txt": "",
    }
    for relative_path, text in state_files.items():
        _queue_activity_file(plan, relative_path, _new_document(text), package_id, preserve_existing=True)


def king_mode_preflight(config: KingModeNpcConfig, server_root: Path) -> NpcDirectPlan:
    checked = validate_king_mode_config(config)
    plan = direct_preflight_many(build_king_mode_npcs(checked), server_root)
    plan.operation = "king-mode-npc-direct-import"
    plan.warnings.append("完整活动契约：核心脚本、配置/状态文件、MerChant注册、登录入口、QFunction和QManage均纳入同一事务。")
    plan.warnings.append("复活点和活动地图写入国王模式配置；打坐/功能 NPC 坐标可在预设窗口修改。")
    _seed_king_mode_files(plan, checked)
    meditation_cancel_hook = """#IF
EQUAL N$XY_KING_MEDITATE 1
#ACT
MOV N$XY_KING_MEDITATE 0
SETOFFTIMEREX 9
SENDMSG 6 打坐恢复已停止。"""
    lifecycle_reset_hook = """#IF
EQUAL N$XY_KING_MEDITATE 1
#ACT
MOV N$XY_KING_MEDITATE 0
SETOFFTIMEREX 9
SENDMSG 6 打坐恢复已停止。

#IF
EQUAL N$XY_KING_BREAK_ACTIVE 1
#ACT
MOV N$XY_KING_BREAK_ACTIVE 0
POWERRATE 100 0 0 1 0
SENDMSG 6 破釜沉舟效果已结束。"""
    core_file = r"\玄渊功能\国王模式\国王模式核心.txt"

    def core_call(label: str) -> str:
        return f"#IF\n#ACT\n#CALL [{core_file}] @{label}"

    qfunction_hooks = {
        "Run": meditation_cancel_hook,
        "Walk": meditation_cancel_hook,
        "AttackDamage": core_call("XY_KING_ATTACK_GUARD") + "\n" + meditation_cancel_hook,
        "HeroAttackDamage": core_call("XY_KING_ATTACK_GUARD") + "\n" + meditation_cancel_hook,
        "StruckDamage": core_call("XY_KING_ATTACK_GUARD") + "\n" + meditation_cancel_hook,
        "HeroStruckDamage": core_call("XY_KING_ATTACK_GUARD") + "\n" + meditation_cancel_hook,
        "PlayDie": core_call("XY_KING_PLAY_DIE") + "\n" + lifecycle_reset_hook,
        "Revival": core_call("XY_KING_REVIVAL") + "\n" + lifecycle_reset_hook,
        "PlayOffline": lifecycle_reset_hook,
        "PlayLogin": lifecycle_reset_hook,
    }
    activity_contract = ActivityEntryContract(
        package_id="xy.optional.king-mode.core",
        required_files=(
            "Mir200/Envir/MapInfo.txt",
            "Mir200/Envir/Market_Def/QFunction-0.txt",
            "Mir200/Envir/MapQuest_Def/QManage.txt",
            "Mir200/Envir/QuestDiary/游戏登陆/登陆脚本.txt",
        ),
        login_hooks={"登陆设置": """#ACT
MOV N$XY_KING_MEDITATE 0
MOV N$XY_KING_BREAK_ACTIVE 0
SETOFFTIMEREX 9"""},
        qfunction_hooks=qfunction_hooks,
        qmanage_hooks={"OnTimerEx9": """#IF
EQUAL N$XY_KING_MEDITATE 1
#ACT
HumanHP + 5 0 1 0 0 1
HumanMP + 5 0 1 1
BREAK"""},
    )
    add_activity_entry_contract(plan, activity_contract)
    for gap in contract_gaps(
        plan.changes,
        {
            "Mir200/Envir/Market_Def/QFunction-0.txt": (
                "@XY_KING_ATTACK_GUARD",
                "@XY_KING_PLAY_DIE",
                "@XY_KING_REVIVAL",
            ),
            "Mir200/Envir/QuestDiary/游戏登陆/登陆脚本.txt": ("XY_KING_MEDITATE", "XY_KING_BREAK_ACTIVE"),
            "Mir200/Envir/MapQuest_Def/QManage.txt": ("HumanHP + 5", "HumanMP + 5"),
        },
    ):
        plan.blockers.append(f"活动运行契约不完整：{gap}")
    return plan


def _safe_package_id(value: str) -> str:
    text = value.strip().lower().replace("_", "-")
    if not text.startswith("xy.npc."):
        text = "xy.npc." + text
    text = re.sub(r"[^a-z0-9.-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip(".-")
    if text == "xy.npc":
        text = "xy.npc.new-npc"
    return text


def _safe_script_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise NpcEditorError("NPC脚本路径必须是相对路径，且不能包含 ..")
    if any(not part or part in {".", ".."} for part in path.parts):
        raise NpcEditorError("NPC脚本路径存在非法目录名")
    return "/".join(path.parts)


def _safe_int(value: Any, field: str, minimum: int = 0) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise NpcEditorError(f"{field}必须是整数") from exc
    if number < minimum:
        raise NpcEditorError(f"{field}不能小于 {minimum}")
    return number


def validate_draft(draft: NpcDraft) -> NpcDraft:
    package_id = _safe_package_id(draft.package_id)
    script_path = _safe_script_path(draft.script_path)
    map_code = draft.map_code.strip()
    if not map_code:
        raise NpcEditorError("地图代码不能为空")
    if not draft.display_name.strip() or not draft.visible_name.strip():
        raise NpcEditorError("NPC显示名称不能为空")
    if re.search(r"[:*?\"<>|]", script_path):
        raise NpcEditorError("NPC脚本路径包含 Windows 不允许的字符")
    if "[@Main]" not in draft.script_text:
        raise NpcEditorError("对话文本必须包含 [@Main] 标签")
    if "#SAY" not in draft.script_text.upper():
        raise NpcEditorError("对话文本必须包含 #SAY")
    unsafe = unsafe_npc_commands(draft.script_text)
    if unsafe:
        raise NpcEditorError(
            "NPC 对话脚本不能直接读取配置文件（已由目标 M2 日志确认会报错）："
            + ", ".join(unsafe)
            + "；请把配置读取放入 QFunction/QManage 运行入口，NPC 只保留触发命令。"
        )
    patch_status = draft.patch_status.strip() or "manual-required"
    if patch_status not in {"reuse-installed", "source-selected", "manual-required"}:
        raise NpcEditorError("客户端补丁状态无效")
    return NpcDraft(
        package_id=package_id,
        display_name=draft.display_name.strip(),
        script_path=script_path,
        map_code=map_code,
        x=_safe_int(draft.x, "X坐标"),
        y=_safe_int(draft.y, "Y坐标"),
        visible_name=draft.visible_name.strip(),
        appearance=_safe_int(draft.appearance, "NPC外观编号"),
        patch_library=draft.patch_library.strip() or "Npc",
        patch_index=_safe_int(draft.patch_index, "补丁图片编号"),
        patch_source=draft.patch_source.strip(),
        patch_status=patch_status,
        script_text=draft.script_text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n",
    )


def scan_npc_appearances(client_data: Path) -> list[dict[str, Any]]:
    """只读扫描 Npc*.wzx 的索引表，供 GUI 选择外观编号。

    WZX 的 48 字节头和索引表是稳定的；WZL 头部计数不作为阻止条件，
    这样可以显示旧客户端中 WZL/WZX 计数不一致但 WZX 仍可选的资源。
    """
    root = Path(client_data)
    if not str(client_data).strip():
        raise NpcEditorError("请先选择客户端 data 目录")
    if not root.is_dir():
        raise NpcEditorError(f"客户端 data 目录不存在：{root}")
    results: list[dict[str, Any]] = []
    for wzx in sorted(root.glob("Npc*.wzx"), key=lambda p: p.name.lower()):
        raw = wzx.read_bytes()
        if len(raw) < 48 or (len(raw) - 48) % 4:
            continue
        table_count = (len(raw) - 48) // 4
        declared = int.from_bytes(raw[44:48], "little")
        count = min(table_count, declared) if declared else table_count
        library = wzx.stem
        for index in range(count):
            offset = int.from_bytes(raw[48 + index * 4:52 + index * 4], "little")
            results.append({
                "library": library,
                "index": index,
                "appearance": index,
                "empty": offset == 0,
                "wzx": str(wzx),
                "wzl": str(wzx.with_suffix(".wzl")),
                "declared_count": declared,
                "table_count": table_count,
            })
    return results


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_draft(draft: NpcDraft, output: Path) -> Path:
    checked = validate_draft(draft)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(checked), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def load_draft(path: Path) -> NpcDraft:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return validate_draft(NpcDraft(**data))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise NpcEditorError(f"NPC草稿读取失败：{path}") from exc


def create_package(draft: NpcDraft, platform_root: Path) -> Path:
    """将 NPC 编辑结果落为 candidate 成果包，不直接修改目标服务端。"""
    checked = validate_draft(draft)
    root = Path(platform_root).resolve() / "packages" / "candidate" / checked.package_id
    if root.exists():
        raise NpcEditorError(f"成果包已存在，请换一个包ID：{checked.package_id}")
    payload = root / "payload"
    payload.mkdir(parents=True, exist_ok=False)
    script_name = "npc_dialogue.txt"
    (payload / script_name).write_text(checked.script_text, encoding="utf-8", newline="\n")
    patch_file = Path(checked.patch_source) if checked.patch_source else None
    patch_metadata = {
        "library": checked.patch_library,
        "index": checked.patch_index,
        "source": checked.patch_source,
        "status": checked.patch_status,
        "wzx_sha256": _sha256(patch_file) if patch_file and patch_file.suffix.lower() == ".wzx" else None,
        "wzl_sha256": _sha256(patch_file.with_suffix(".wzl")) if patch_file and patch_file.suffix.lower() == ".wzx" else None,
        "note": "客户端补丁只记录来源与复用状态；未知补丁不得直接覆盖目标 data。",
    }
    (payload / "client_patch.json").write_text(json.dumps(patch_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    params = {
        "npc_script_path": {"type": "string", "required": True, "default": checked.script_path},
        "npc_map": {"type": "string", "required": True, "default": checked.map_code},
        "npc_x": {"type": "integer", "required": True, "default": checked.x},
        "npc_y": {"type": "integer", "required": True, "default": checked.y},
        "npc_name": {"type": "string", "required": True, "default": checked.visible_name},
        "npc_appearance": {"type": "integer", "required": True, "default": checked.appearance},
    }
    manifest = {
        "schema_version": 1,
        "id": checked.package_id,
        "version": "1.0.0-candidate.1",
        "display_name": checked.display_name,
        "status": "candidate",
        "engine": "LFM2",
        "residency": "optional",
        "bundle": "npc",
        "dependencies": [],
        "parameters": params,
        "claims": {"labels": [], "variables": [], "maps": [], "npcs": [checked.script_path]},
        "operations": [
            {
                "type": "render",
                "source": f"payload/{script_name}",
                "target": "Mir200/Envir/Market_Def/{npc_script_path}-{npc_map}.txt",
                "source_encoding": "utf-8",
                "target_encoding": "gb18030",
            },
            {
                "type": "unique_line",
                "target": "Mir200/Envir/MerChant.txt",
                "line": "{npc_script_path}\t{npc_map}\t{npc_x}\t{npc_y}\t{npc_name}\t0\t{npc_appearance}\t0",
                "key_fields": [0, 1],
            },
        ],
        "preflight_checks": [
            {"type": "file_exists", "path": "Mir200/Envir/MapInfo.txt"},
        ],
        "post_checks": [
            {"type": "file_exists", "path": "Mir200/Envir/Market_Def/{npc_script_path}-{npc_map}.txt"},
        ],
        "evidence": [
            "npc-editor:v1",
            f"client-patch:{checked.patch_status}",
            "game-validation:required",
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "使用说明.txt").write_text(
        f"{checked.display_name}\n\n"
        f"脚本注册路径：{checked.script_path}\n地图：{checked.map_code} 坐标：{checked.x},{checked.y}\n"
        f"显示名称：{checked.visible_name}\n外观库：{checked.patch_library} 图片：{checked.patch_index}\n"
        f"客户端补丁状态：{checked.patch_status}\n\n"
        "安装前请确认目标客户端存在对应 Npc*.wzl/.wzx；未知补丁不得直接覆盖。\n"
        "安装后需重启/重载 M2，并进游戏确认头顶名称、外观和对话。\n",
        encoding="utf-8",
    )
    return root
