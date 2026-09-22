from __future__ import annotations

from pathlib import Path
from typing import Any

from .installer import InstallError, InstallPlan, InstallReceipt, Installer
from .repository import PackageRepository


class ResidentService:
    """Collect and install every package explicitly marked as resident."""

    def __init__(self, repository: PackageRepository, backups_root: Path):
        self.repository = repository
        self.installer = Installer(repository, backups_root)

    def package_ids(self) -> list[str]:
        return sorted(
            item.id
            for item in self.repository.packages.values()
            if item.residency == "resident" and item.status != "deprecated"
        )

    def preflight(
        self,
        server_root: Path,
        params: dict[str, Any] | None = None,
        client_root: Path | None = None,
    ) -> InstallPlan:
        self.repository.refresh()
        package_ids = self.package_ids()
        if not package_ids:
            raise InstallError("平台没有登记常驻成果包")
        return self.installer.preflight(
            server_root,
            package_ids,
            params or {},
            client_root=client_root,
            operation_type="resident-base",
        )

    def install(self, plan: InstallPlan) -> InstallReceipt:
        if plan.operation_type != "resident-base":
            raise InstallError("当前计划不是常驻基础预检计划")
        return self.installer.install(plan)
