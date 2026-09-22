from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .installer import InstallError, InstallPlan, InstallReceipt, Installer
from .repository import PackageRepository


@dataclass(frozen=True)
class OptionalPreset:
    id: str
    display_name: str
    package_ids: tuple[str, ...]

    @property
    def operation_type(self) -> str:
        return f"optional-preset:{self.id}"


PRESETS: dict[str, OptionalPreset] = {
    "rage": OptionalPreset(
        id="rage",
        display_name="狂暴系统",
        package_ids=("xy.optional.rage.core",),
    ),
    "donate": OptionalPreset(
        id="donate",
        display_name="沙城捐献",
        package_ids=("xy.optional.donate.core",),
    ),
}


class OptionalPresetService:
    """Install one canonical optional feature and its declared dependencies as one transaction."""

    def __init__(self, platform_root: Path, backups_root: Path | None = None):
        self.platform_root = Path(platform_root).resolve()
        self.repository = PackageRepository(self.platform_root / "packages")
        self.installer = Installer(
            self.repository,
            Path(backups_root) if backups_root is not None else self.platform_root / "backups",
        )

    def definition(self, preset_id: str) -> OptionalPreset:
        try:
            return PRESETS[preset_id]
        except KeyError as exc:
            raise InstallError(f"未知非常驻一键预设: {preset_id}") from exc

    def preflight(
        self,
        preset_id: str,
        server_root: Path,
        params: dict[str, Any] | None = None,
    ) -> InstallPlan:
        definition = self.definition(preset_id)
        self.repository.refresh()
        return self.installer.preflight(
            Path(server_root),
            list(definition.package_ids),
            params or {},
            operation_type=definition.operation_type,
        )

    def install(self, preset_id: str, plan: InstallPlan) -> InstallReceipt:
        definition = self.definition(preset_id)
        if plan.operation_type != definition.operation_type:
            raise InstallError("当前计划与非常驻一键预设不匹配")
        if tuple(package for package in plan.package_ids if package in definition.package_ids) != definition.package_ids:
            raise InstallError("当前计划缺少非常驻一键预设包")
        return self.installer.install(plan)

    def latest_transaction(self, preset_id: str, server_root: Path) -> str:
        definition = self.definition(preset_id)
        state_path = Path(server_root) / ".xydp" / "installed.json"
        if not state_path.exists():
            raise InstallError(f"目标服没有{definition.display_name}安装记录")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for transaction_id in reversed(state.get("transactions", [])):
            receipt_path = self.installer.backups_root / transaction_id / "receipt.json"
            if not receipt_path.exists():
                continue
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("rolled_back_at"):
                continue
            if receipt.get("operation_type") == definition.operation_type:
                return str(transaction_id)
        raise InstallError(f"目标服没有可回滚的{definition.display_name}一键安装事务")

    def rollback_latest(self, preset_id: str, server_root: Path) -> str:
        transaction_id = self.latest_transaction(preset_id, server_root)
        self.installer.rollback(Path(server_root), transaction_id)
        return transaction_id
