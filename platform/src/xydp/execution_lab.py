from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .installer import InstallError, InstallPlan, InstallReceipt, Installer, PlannedChange
from .execution_map_rules import augment_package, load_map_rules, render_rule_rows
from .repository import PackageRepository
from .target import TargetInspector, is_executable_running


PACKAGE_ID = "xy.lab.execution"
OPERATION_TYPE = "execution-lab"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


class _ExecutionLabInstaller(Installer):
    """Keep experimental receipts out of the normal platform install state."""

    @staticmethod
    def state_root(target_root: Path) -> Path:
        return Path(target_root) / ".xydp" / "execution-lab"

    def _write_receipts(self, target_root: Path, receipt: InstallReceipt) -> None:
        data = asdict(receipt)
        _atomic_json(Path(receipt.backup_root) / "receipt.json", data)

        state = self.state_root(target_root)
        transaction_path = state / "transactions" / f"{receipt.transaction_id}.json"
        installed = state / "installed.json"
        installed_before = installed.read_bytes() if installed.exists() else None
        try:
            _atomic_json(transaction_path, data)
            installed_data = (
                json.loads(installed_before.decode("utf-8"))
                if installed_before is not None
                else {"packages": {}, "transactions": []}
            )
            installed_data["packages"].update(receipt.packages)
            if receipt.transaction_id not in installed_data["transactions"]:
                installed_data["transactions"].append(receipt.transaction_id)
            _atomic_json(installed, installed_data)
        except Exception:
            transaction_path.unlink(missing_ok=True)
            if installed_before is None:
                installed.unlink(missing_ok=True)
            else:
                _atomic_bytes(installed, installed_before)
            transactions = state / "transactions"
            if transactions.exists() and not any(transactions.iterdir()):
                transactions.rmdir()
            if state.exists() and not any(state.iterdir()):
                state.rmdir()
            raise

    def _remove_transaction_from_state(self, target_root: Path, transaction_id: str) -> None:
        state_root = self.state_root(target_root)
        state_path = state_root / "installed.json"
        if not state_path.exists():
            return
        state = json.loads(state_path.read_text(encoding="utf-8"))
        remaining = [item for item in state.get("transactions", []) if item != transaction_id]
        if not remaining:
            for path in sorted(state_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            state_root.rmdir()
            xydp_root = state_root.parent
            if xydp_root.exists() and not any(xydp_root.iterdir()):
                xydp_root.rmdir()
            return

        packages: dict[str, str] = {}
        valid_transactions: list[str] = []
        for item in remaining:
            receipt_path = self.backups_root / item / "receipt.json"
            if not receipt_path.exists():
                continue
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("rolled_back_at"):
                continue
            if receipt.get("operation_type") != OPERATION_TYPE:
                continue
            packages.update(receipt.get("packages", {}))
            valid_transactions.append(item)
        _atomic_json(
            state_path,
            {"packages": packages, "transactions": valid_transactions},
        )


class ExecutionLabService:
    """Isolated transaction entry for execution scripts and the registered map table."""

    def __init__(self, platform_root: Path):
        self.platform_root = Path(platform_root).resolve()
        self.lab_root = self.platform_root / "labs" / "execution"
        self.repository = PackageRepository(self.lab_root / "packages")
        self.rules_path = self.platform_root / "所需材料表格汇总" / "13_地图怪物处决规则.csv"
        self.installer = _ExecutionLabInstaller(
            self.repository,
            self.lab_root / "backups",
        )

    @property
    def state_folder_name(self) -> str:
        return "execution-lab"

    def preflight(self, server_root: Path) -> InstallPlan:
        self.repository.refresh()
        if set(self.repository.packages) != {PACKAGE_ID}:
            raise InstallError("处决实验室包库必须且只能包含处决测试包")
        rules, rules_sha256 = load_map_rules(self.rules_path)
        parameters = {
            "map_rules_sha256": rules_sha256,
            "map_rule_count": len(rules),
            "map_rule_ids": [item.map_id for item in rules],
            "map_rules_file": str(self.rules_path),
        }
        target = TargetInspector.inspect(Path(server_root))
        qfunction = target.envir / "Market_Def" / "QFunction-0.txt"
        if qfunction.is_file() and b"XYDP-LAB-BEGIN xy.lab.execution.monster-map0" in qfunction.read_bytes():
            return self._preflight_legacy_map_table(target.root, qfunction, rules, parameters)
        self.repository.packages[PACKAGE_ID] = augment_package(
            self.repository.packages[PACKAGE_ID], rules
        )
        plan = self.installer.preflight(
            Path(server_root),
            [PACKAGE_ID],
            parameters,
            operation_type=OPERATION_TYPE,
        )
        if plan.package_ids != [PACKAGE_ID]:
            raise InstallError("处决测试计划混入了其他成果包，已阻止导入")
        return plan

    def _preflight_legacy_map_table(
        self,
        server_root: Path,
        qfunction: Path,
        rules,
        parameters: dict[str, Any],
    ) -> InstallPlan:
        if is_executable_running(server_root / "Mir200" / "M2Server.exe"):
            raise InstallError("目标服务端 M2Server.exe 正在运行，请先手动停止")
        before = qfunction.read_bytes()
        try:
            text = before.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise InstallError("旧地图处决脚本不是GB18030编码，禁止接管") from exc
        begin = "; XY_EXECUTION_MONSTER_MAP_RULES_BEGIN"
        end = "; XY_EXECUTION_MONSTER_MAP_RULES_END"
        if text.count(begin) != 1 or text.count(end) != 1:
            raise InstallError("旧地图处决规则块缺失或重复，禁止自动接管")
        newline = "\r\n" if "\r\n" in text else "\n"
        rendered = render_rule_rows(list(rules)).replace("\n", newline)
        after_text, count = re.subn(
            re.escape(begin) + r".*?" + re.escape(end),
            lambda _: rendered,
            text,
            count=1,
            flags=re.S,
        )
        if count != 1:
            raise InstallError("旧地图处决规则块无法唯一替换")
        after = after_text.encode("gb18030")
        package = self.repository.packages[PACKAGE_ID]
        changes = [] if before == after else [
            PlannedChange(
                "Mir200/Envir/Market_Def/QFunction-0.txt",
                before,
                after,
                "map_rule_table",
                PACKAGE_ID,
            )
        ]
        return InstallPlan(
            target_root=str(server_root),
            client_root=None,
            package_ids=[PACKAGE_ID],
            package_versions={PACKAGE_ID: package.version},
            parameters=parameters,
            changes=changes,
            warnings=["已识别并安全接管2026-07旧地图处决试点；仅更新表格生成区，不覆盖其余已验收脚本。"],
            operation_type=OPERATION_TYPE,
            candidate_packages=[PACKAGE_ID] if package.status == "candidate" else [],
        )

    def install(self, plan: InstallPlan, *, confirmed_test_server: bool) -> InstallReceipt:
        if not confirmed_test_server:
            raise InstallError("必须确认目标是独立测试服，才能导入处决测试脚本")
        if plan.operation_type != OPERATION_TYPE or plan.package_ids != [PACKAGE_ID]:
            raise InstallError("当前计划不是独立处决测试计划")
        if not plan.changes:
            raise InstallError("没有需要导入的变更，目标已是当前处决测试版本")
        return self.installer.install(plan)

    def latest_transaction(self, server_root: Path) -> str:
        state_path = (
            Path(server_root)
            / ".xydp"
            / self.state_folder_name
            / "installed.json"
        )
        if not state_path.exists():
            raise InstallError("目标服没有处决测试导入记录")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for transaction_id in reversed(state.get("transactions", [])):
            receipt_path = self.installer.backups_root / transaction_id / "receipt.json"
            if not receipt_path.exists():
                continue
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("rolled_back_at"):
                continue
            if receipt.get("operation_type") == OPERATION_TYPE:
                return str(transaction_id)
        raise InstallError("目标服没有可回滚的处决测试事务")

    def rollback_latest(self, server_root: Path) -> str:
        target = TargetInspector.inspect(Path(server_root))
        if is_executable_running(target.mir200 / "M2Server.exe"):
            raise InstallError("目标服务端 M2Server.exe 正在运行，请先手动停止再回滚")
        transaction_id = self.latest_transaction(server_root)
        receipt_path = self.installer.backups_root / transaction_id / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("operation_type") != OPERATION_TYPE:
            raise InstallError("最近事务不是处决测试事务，已阻止回滚")
        self.installer.rollback(target.root, transaction_id)
        return transaction_id
