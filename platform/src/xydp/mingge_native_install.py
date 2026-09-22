"""命格38号候选的P1隔离测试安装链。

只允许当前已实测的灵玉位置17、属性行17、绑定1、防御+5黄金组合。
该模块不修改数据库、客户端或旧37号命格目录。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .mingge_native import (
    NativeCandidate,
    NativeCandidateError,
    compile_native_candidate,
    read_native_candidate_workbook,
)
from .mingge_native_p2_install import _transaction_lock as _shared_script_transaction_lock


COMMAND_NAME = "命格平台验收"
COMMAND_NUMBER = 97
MANAGED_BEGIN = "; XY-MG-NATIVE-P1-BEGIN"
MANAGED_END = "; XY-MG-NATIVE-P1-END"
TEST_SCRIPT_RELATIVE = "Mir200/Envir/QuestDiary/玄渊验收/命格平台单件验收.txt"
USERCMD_RELATIVE = "Mir200/Envir/UserCmd.txt"
QFUNCTION_RELATIVE = "Mir200/Envir/Market_Def/QFunction-0.txt"


class NativeTestInstallError(ValueError):
    """P1隔离测试安装契约不满足。"""


@dataclass(frozen=True)
class NativeTestPlannedFile:
    relative_path: str
    path: Path
    existed_before: bool
    before_sha256: str | None
    after_sha256: str
    after: bytes


@dataclass(frozen=True)
class NativeTestInstallPlan:
    plan_id: str
    candidate_id: str
    workbook: Path
    workbook_sha256: str
    server_root: Path
    files: tuple[NativeTestPlannedFile, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class NativeTestInstallReceipt:
    transaction_id: str
    status: str
    candidate_id: str
    receipt_path: Path
    files: tuple[str, ...]


@dataclass(frozen=True)
class NativeTestRollbackReceipt:
    transaction_id: str
    status: str
    receipt_path: Path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _planned_file(server_root: Path, relative_path: str, after: bytes) -> NativeTestPlannedFile:
    path = server_root / Path(relative_path)
    before = _read(path)
    return NativeTestPlannedFile(
        relative_path=relative_path,
        path=path,
        existed_before=before is not None,
        before_sha256=_sha256_bytes(before) if before is not None else None,
        after_sha256=_sha256_bytes(after),
        after=after,
    )


def _candidate_blockers(candidate: NativeCandidate) -> list[str]:
    blockers: list[str] = []
    if candidate.equip_slot != 17:
        blockers.append("P1只允许当前已实测的灵玉位置17")
    if candidate.target_item_name != "鞭尸灵玉":
        blockers.append("P1只允许可回收测试装备鞭尸灵玉")
    if len(candidate.properties) != 1:
        blockers.append("P1只允许单条真实属性，禁止多属性或09号脚本属性")
        return blockers
    item = candidate.properties[0]
    if not (
        item.display_name in {"防御", "自身防御"}
        and item.property_row == 17
        and item.position == 17
        and item.binding == 1
        and item.color == 250
        and item.type3 == 0
        and item.type4 == 9
        and item.value_command == "value_ex"
        and item.value == 5
        and item.value2 == 0
        and item.value3 == 0
        and item.dependency is None
    ):
        blockers.append("P1候选必须精确为属性行17、绑定1、直接防御+5黄金组合")
    return blockers


def _decode_script(data: bytes, label: str) -> str:
    try:
        return data.decode("gb18030")
    except UnicodeDecodeError as exc:
        raise NativeTestInstallError(f"{label}不是GB18030/GBK可读文本") from exc


def _encode_script(text: str) -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return (normalized.rstrip("\n") + "\n").replace("\n", "\r\n").encode("gb18030")


def _render_test_script(candidate: NativeCandidate) -> bytes:
    compiled = compile_native_candidate(candidate)
    command_lines = compiled.script.rstrip("\r\n").split("\r\n")
    item = candidate.properties[0]
    body = [
        "[@XY_MG_NATIVE_P1_MAIN]",
        "{",
        "#IF",
        "ISADMIN",
        f"CHECKUSEITEM {candidate.equip_slot}",
        "#ACT",
        "GOTO @XY_MG_NATIVE_P1_CHECK_NAME",
        "BREAK",
        "#ELSEACT",
        "MESSAGEBOX 仅允许管理员在灵玉位置执行平台隔离验收，未写入。",
        "BREAK",
        "",
        "[@XY_MG_NATIVE_P1_CHECK_NAME]",
        "#IF",
        f"EQUAL <$JADE> {candidate.target_item_name}",
        "#ACT",
        "GOTO @XY_MG_NATIVE_P1_READ",
        "BREAK",
        "#ELSEACT",
        f"MESSAGEBOX 当前灵玉不是“{candidate.target_item_name}”，已阻止。",
        "BREAK",
        "",
        "[@XY_MG_NATIVE_P1_READ]",
        "#IF",
        "#ACT",
        f"GetCustomItemText {candidate.equip_slot} <$STR(S1)>",
        f"GetCustomItemTextColor {candidate.equip_slot} <$STR(N1)>",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 0 N$XY_MG_P1_COLOR",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 1 N$XY_MG_P1_BIND",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 2 N$XY_MG_P1_POS",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 3 N$XY_MG_P1_MODE",
        f"GetCustomItemValueEx {candidate.equip_slot} {item.property_row} N$XY_MG_P1_PCT N$XY_MG_P1_V1 N$XY_MG_P1_V2 N$XY_MG_P1_V3",
        "GOTO @XY_MG_NATIVE_P1_DECIDE",
        "BREAK",
        "",
        "[@XY_MG_NATIVE_P1_DECIDE]",
        "#IF",
        "EQUAL N$XY_MG_P1_COLOR 250",
        "EQUAL N$XY_MG_P1_BIND 1",
        "EQUAL N$XY_MG_P1_POS 17",
        "EQUAL N$XY_MG_P1_MODE 0",
        "EQUAL N$XY_MG_P1_PCT 0",
        "EQUAL N$XY_MG_P1_V1 5",
        "EQUAL N$XY_MG_P1_V2 0",
        "EQUAL N$XY_MG_P1_V3 0",
        "#ACT",
        "GOTO @XY_MG_NATIVE_P1_READY",
        "BREAK",
        "#ELSEACT",
        "GOTO @XY_MG_NATIVE_P1_BLOCKED",
        "BREAK",
        "",
        "[@XY_MG_NATIVE_P1_READY]",
        "#SAY",
        f"平台候选：{candidate.candidate_id}\\",
        "当前文字：<$STR(S1)>，默认颜色：<$STR(N1)>。\\",
        "真实属性行17已精确读回为250/1/17/0/0/5/0/0。\\",
        "本次会以38号候选整体替换显示文字，并重写相同的防御+5；不扣费、不抽取、不改数据库。\\",
        "<写入平台隔离候选/@XY_MG_NATIVE_P1_PREWRITE>  <退出/@EXIT>",
        "",
        "[@XY_MG_NATIVE_P1_BLOCKED]",
        "#SAY",
        "已阻止平台候选写入：真实属性行17不是黄金样本250/1/17/0/0/5/0/0。\\",
        "当前值：颜色=<$STR(N$XY_MG_P1_COLOR)> 绑定=<$STR(N$XY_MG_P1_BIND)> 位置=<$STR(N$XY_MG_P1_POS)> 模式=<$STR(N$XY_MG_P1_MODE)>\\",
        "百分比=<$STR(N$XY_MG_P1_PCT)> 值1=<$STR(N$XY_MG_P1_V1)> 值2=<$STR(N$XY_MG_P1_V2)> 值3=<$STR(N$XY_MG_P1_V3)>。\\",
        "<退出/@EXIT>",
        "",
        "[@XY_MG_NATIVE_P1_PREWRITE]",
        "#IF",
        "ISADMIN",
        f"CHECKUSEITEM {candidate.equip_slot}",
        f"EQUAL <$JADE> {candidate.target_item_name}",
        "#ACT",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 0 N$XY_MG_P1_COLOR",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 1 N$XY_MG_P1_BIND",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 2 N$XY_MG_P1_POS",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 3 N$XY_MG_P1_MODE",
        f"GetCustomItemValueEx {candidate.equip_slot} {item.property_row} N$XY_MG_P1_PCT N$XY_MG_P1_V1 N$XY_MG_P1_V2 N$XY_MG_P1_V3",
        "GOTO @XY_MG_NATIVE_P1_PREWRITE_DECIDE",
        "BREAK",
        "#ELSEACT",
        "MESSAGEBOX 管理员、位置或装备名称门禁已变化，未写入。",
        "BREAK",
        "",
        "[@XY_MG_NATIVE_P1_PREWRITE_DECIDE]",
        "#IF",
        "EQUAL N$XY_MG_P1_COLOR 250",
        "EQUAL N$XY_MG_P1_BIND 1",
        "EQUAL N$XY_MG_P1_POS 17",
        "EQUAL N$XY_MG_P1_MODE 0",
        "EQUAL N$XY_MG_P1_PCT 0",
        "EQUAL N$XY_MG_P1_V1 5",
        "EQUAL N$XY_MG_P1_V2 0",
        "EQUAL N$XY_MG_P1_V3 0",
        "#ACT",
        "GOTO @XY_MG_NATIVE_P1_APPLY",
        "BREAK",
        "#ELSEACT",
        "MESSAGEBOX 点击后属性行17已变化，未写入；请重新输入@命格平台验收。",
        "BREAK",
        "",
        "[@XY_MG_NATIVE_P1_APPLY]",
        "#IF",
        "ISADMIN",
        f"CHECKUSEITEM {candidate.equip_slot}",
        f"EQUAL <$JADE> {candidate.target_item_name}",
        "EQUAL N$XY_MG_P1_COLOR 250",
        "EQUAL N$XY_MG_P1_BIND 1",
        "EQUAL N$XY_MG_P1_POS 17",
        "EQUAL N$XY_MG_P1_MODE 0",
        "EQUAL N$XY_MG_P1_PCT 0",
        "EQUAL N$XY_MG_P1_V1 5",
        "EQUAL N$XY_MG_P1_V2 0",
        "EQUAL N$XY_MG_P1_V3 0",
        "#ACT",
        *command_lines,
        "GOTO @XY_MG_NATIVE_P1_READ_AFTER",
        "BREAK",
        "#ELSEACT",
        "MESSAGEBOX 最终门禁未通过，未写入；请重新输入@命格平台验收。",
        "BREAK",
        "",
        "[@XY_MG_NATIVE_P1_READ_AFTER]",
        "#IF",
        "#ACT",
        f"GetCustomItemText {candidate.equip_slot} <$STR(S1)>",
        f"GetCustomItemTextColor {candidate.equip_slot} <$STR(N1)>",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 0 N$XY_MG_P1_COLOR",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 1 N$XY_MG_P1_BIND",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 2 N$XY_MG_P1_POS",
        f"GetCustomItemAbil {candidate.equip_slot} {item.property_row} 3 N$XY_MG_P1_MODE",
        f"GetCustomItemValueEx {candidate.equip_slot} {item.property_row} N$XY_MG_P1_PCT N$XY_MG_P1_V1 N$XY_MG_P1_V2 N$XY_MG_P1_V3",
        "GOTO @XY_MG_NATIVE_P1_AFTER",
        "BREAK",
        "",
        "[@XY_MG_NATIVE_P1_AFTER]",
        "#SAY",
        "平台候选写后读回：<$STR(S1)>，默认颜色=<$STR(N1)>。\\",
        "真实属性行17应继续为250/1/17/0/0/5/0/0。\\",
        "请截图本面板，再悬浮灵玉确认命格名称、颜色、防御+5均可见。\\",
        "<退出/@EXIT>",
        "}",
    ]
    return _encode_script("\n".join(body))


def _render_usercmd(current: bytes) -> tuple[bytes, list[str]]:
    text = _decode_script(current, "UserCmd.txt")
    blockers: list[str] = []
    exact = f"{COMMAND_NAME}\t{COMMAND_NUMBER}"
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line in lines:
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        if parts[0] == COMMAND_NAME and parts[1] != str(COMMAND_NUMBER):
            blockers.append(f"UserCmd命令名{COMMAND_NAME}已占用其他编号")
        if parts[1] == str(COMMAND_NUMBER) and parts[0] != COMMAND_NAME:
            blockers.append(f"UserCmd编号{COMMAND_NUMBER}已被{parts[0]}占用")
    if exact not in lines:
        lines = [line for line in lines if line] + [exact]
    return _encode_script("\n".join(lines)), blockers


def _qfunction_block() -> str:
    return "\n".join((
        MANAGED_BEGIN,
        f"[@UserCmd{COMMAND_NUMBER}]",
        "#IF",
        "ISADMIN",
        "#ACT",
        "#CALL [\\玄渊验收\\命格平台单件验收.txt] @XY_MG_NATIVE_P1_MAIN",
        "BREAK",
        "#ELSEACT",
        "SENDMSG 6 [命格平台验收] 仅管理员测试角色可使用。",
        "BREAK",
        MANAGED_END,
    ))


def _render_qfunction(current: bytes) -> tuple[bytes, list[str]]:
    text = _decode_script(current, "QFunction-0.txt")
    blockers: list[str] = []
    block = _qfunction_block()
    if MANAGED_BEGIN in text or MANAGED_END in text:
        if block.replace("\n", "\r\n") not in text and block not in text:
            blockers.append("QFunction已存在不匹配的P1受管块")
        return current, blockers
    if f"[@UserCmd{COMMAND_NUMBER}]" in text:
        blockers.append(f"QFunction的@UserCmd{COMMAND_NUMBER}已被其他逻辑占用")
        return current, blockers
    rendered = text.rstrip("\r\n") + "\r\n\r\n" + block.replace("\n", "\r\n") + "\r\n"
    return rendered.encode("gb18030"), blockers


def plan_native_test_install(
    workbook_path: Path, candidate_id: str, server_root: Path
) -> NativeTestInstallPlan:
    """只读预检P1隔离候选，生成精确三文件计划。"""
    book = read_native_candidate_workbook(Path(workbook_path))
    matches = [item for item in book.candidates if item.candidate_id == candidate_id]
    if len(matches) != 1:
        raise NativeTestInstallError(f"启用候选必须唯一存在：{candidate_id}")
    candidate = matches[0]
    server = Path(server_root).resolve()
    blockers = _candidate_blockers(candidate)
    usercmd_path = server / Path(USERCMD_RELATIVE)
    qfunction_path = server / Path(QFUNCTION_RELATIVE)
    if not usercmd_path.is_file():
        blockers.append(f"UserCmd不存在：{usercmd_path}")
        usercmd_after = b""
    else:
        usercmd_after, found = _render_usercmd(usercmd_path.read_bytes())
        blockers.extend(found)
    if not qfunction_path.is_file():
        blockers.append(f"QFunction不存在：{qfunction_path}")
        qfunction_after = b""
    else:
        qfunction_after, found = _render_qfunction(qfunction_path.read_bytes())
        blockers.extend(found)
    test_script = _render_test_script(candidate)
    test_path = server / Path(TEST_SCRIPT_RELATIVE)
    existing_test = _read(test_path)
    if existing_test is not None and existing_test != test_script:
        blockers.append("隔离测试脚本已存在且内容不匹配，禁止覆盖")
    files = (
        _planned_file(server, USERCMD_RELATIVE, usercmd_after),
        _planned_file(server, QFUNCTION_RELATIVE, qfunction_after),
        _planned_file(server, TEST_SCRIPT_RELATIVE, test_script),
    )
    workbook_hash = _sha256_bytes(book.source.read_bytes())
    identity = "|".join((
        candidate_id,
        workbook_hash,
        *(f"{item.relative_path}:{item.before_sha256}:{item.after_sha256}" for item in files),
    ))
    return NativeTestInstallPlan(
        plan_id=hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
        candidate_id=candidate_id,
        workbook=book.source,
        workbook_sha256=workbook_hash,
        server_root=server,
        files=files,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=("旧37号命格路线保持原样；P1只增加独立管理员验收入口",),
    )


def _current_hash(path: Path) -> str | None:
    data = _read(path)
    return _sha256_bytes(data) if data is not None else None


def _assert_plan_is_current(plan: NativeTestInstallPlan) -> None:
    if plan.blockers:
        raise NativeTestInstallError("安装计划存在阻断：" + "；".join(plan.blockers))
    if _sha256_bytes(plan.workbook.read_bytes()) != plan.workbook_sha256:
        raise NativeTestInstallError("38号候选表在预检后发生变化，请重新预检")
    for item in plan.files:
        if _current_hash(item.path) != item.before_sha256:
            raise NativeTestInstallError(f"目标文件在预检后发生变化，请重新预检：{item.path}")


def _transaction_root(platform_root: Path, transaction_id: str) -> Path:
    root = Path(platform_root).resolve()
    transaction = root / "backups" / "mingge-native-test" / transaction_id
    if not transaction.resolve(strict=False).is_relative_to(root):
        raise NativeTestInstallError("命格P1事务目录越界")
    return transaction


def _install_native_test_candidate_unlocked(
    plan: NativeTestInstallPlan, platform_root: Path
) -> NativeTestInstallReceipt:
    """按已验证计划写入三个隔离测试文件，并保存逐字节回滚收据。"""
    _assert_plan_is_current(plan)
    transaction_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    transaction = _transaction_root(platform_root, transaction_id)
    if transaction.exists():
        raise NativeTestInstallError(f"事务目录已存在：{transaction}")
    files_dir = transaction / "files"
    files_dir.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    written: list[NativeTestPlannedFile] = []
    try:
        for index, item in enumerate(plan.files):
            before = _read(item.path)
            backup = files_dir / f"{index:02d}.bin"
            if before is not None:
                _atomic_write(backup, before)
            entries.append({
                "relative_path": item.relative_path,
                "path": str(item.path),
                "existed_before": before is not None,
                "before_sha256": item.before_sha256,
                "after_sha256": item.after_sha256,
                "backup": str(backup) if before is not None else None,
            })
            _atomic_write(item.path, item.after)
            written.append(item)
        for item in plan.files:
            if _current_hash(item.path) != item.after_sha256:
                raise NativeTestInstallError(f"安装后哈希不匹配：{item.path}")
    except BaseException:
        for index, item in reversed(list(enumerate(written))):
            entry = entries[index]
            backup_value = entry["backup"]
            if backup_value:
                _atomic_write(item.path, Path(str(backup_value)).read_bytes())
            else:
                item.path.unlink(missing_ok=True)
        raise
    receipt_data = {
        "schema_version": 1,
        "operation": "mingge-native-p1-test",
        "status": "installed-test-candidate",
        "transaction_id": transaction_id,
        "candidate_id": plan.candidate_id,
        "plan_id": plan.plan_id,
        "server_root": str(plan.server_root),
        "workbook": str(plan.workbook),
        "workbook_sha256": plan.workbook_sha256,
        "files": entries,
        "writes_server": True,
        "writes_client": False,
        "writes_database": False,
        "old_mingge_route_untouched": True,
    }
    receipt_path = transaction / "receipt.json"
    _atomic_write(
        receipt_path,
        (json.dumps(receipt_data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return NativeTestInstallReceipt(
        transaction_id=transaction_id,
        status="installed-test-candidate",
        candidate_id=plan.candidate_id,
        receipt_path=receipt_path,
        files=tuple(item.relative_path for item in plan.files),
    )


def install_native_test_candidate(
    plan: NativeTestInstallPlan, platform_root: Path
) -> NativeTestInstallReceipt:
    """在共享脚本事务锁内安装P1，避免与P2交叉覆盖共享入口。"""
    with _shared_script_transaction_lock(platform_root, plan.server_root):
        return _install_native_test_candidate_unlocked(plan, platform_root)


def _rollback_native_test_install_unlocked(
    platform_root: Path, transaction_id: str, server_root: Path
) -> NativeTestRollbackReceipt:
    """仅当三个已安装文件都未漂移时，逐字节恢复P1事务。"""
    transaction = _transaction_root(platform_root, transaction_id)
    receipt_path = transaction / "receipt.json"
    if not receipt_path.is_file():
        raise NativeTestInstallError(f"命格P1事务收据不存在：{transaction_id}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("operation") != "mingge-native-p1-test":
        raise NativeTestInstallError("事务收据不属于命格P1隔离安装")
    expected_server = Path(str(receipt.get("server_root", ""))).resolve()
    actual_server = Path(server_root).resolve()
    if expected_server != actual_server:
        raise NativeTestInstallError("回滚目标服务端与事务收据不一致")
    entries = list(receipt.get("files", []))
    for entry in entries:
        path = Path(str(entry["path"]))
        if not path.resolve(strict=False).is_relative_to(actual_server):
            raise NativeTestInstallError(f"回滚文件越出服务端目录：{path}")
        if _current_hash(path) != entry.get("after_sha256"):
            raise NativeTestInstallError(f"安装后文件已漂移，拒绝覆盖：{path}")
    for entry in entries:
        path = Path(str(entry["path"]))
        backup_value = entry.get("backup")
        if entry.get("existed_before"):
            backup = Path(str(backup_value))
            if not backup.is_file() or _sha256_bytes(backup.read_bytes()) != entry.get("before_sha256"):
                raise NativeTestInstallError(f"回滚备份缺失或哈希不匹配：{path}")
            _atomic_write(path, backup.read_bytes())
        else:
            path.unlink(missing_ok=True)
    rollback_path = transaction / "rollback-receipt.json"
    _atomic_write(
        rollback_path,
        (json.dumps({
            "schema_version": 1,
            "operation": "mingge-native-p1-test-rollback",
            "status": "rolled-back",
            "transaction_id": transaction_id,
            "server_root": str(actual_server),
        }, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return NativeTestRollbackReceipt(
        transaction_id=transaction_id,
        status="rolled-back",
        receipt_path=rollback_path,
    )


def rollback_native_test_install(
    platform_root: Path, transaction_id: str, server_root: Path
) -> NativeTestRollbackReceipt:
    """在共享脚本事务锁内回滚P1，避免与P2并发写UserCmd/QFunction。"""
    with _shared_script_transaction_lock(platform_root, server_root):
        return _rollback_native_test_install_unlocked(platform_root, transaction_id, server_root)
