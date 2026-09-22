from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xyequip.batch import BatchEquipmentService, WorkbookInspection
from xyequip.installer import EquipmentInstaller, EquipmentReceipt
from xyequip.paths import preferred_user_document
from xyequip.planner import EquipmentPlan, EquipmentPlanner
from xyequip.item_hint import export_hint_workbook
from xyequip.paths import EquipmentPaths
from xyequip.target import inspect_target


@dataclass
class EquipmentUiState:
    server_root: str = r"D:\MirServer"
    client_data: str = ""
    workbook: str = ""


class EquipmentBridge:
    def __init__(self, platform_root: Path):
        self.platform_root = Path(platform_root).resolve()
        self.default_workbook = preferred_user_document(
            self.platform_root,
            "09_装备批量生成.xlsx",
            self.platform_root / "做装备" / "templates" / "XuanYuanItems.xlsx",
        )
        self.default_material_workbook = preferred_user_document(
            self.platform_root,
            "11_材料批量生成.xlsx",
            self.platform_root / "做装备" / "templates" / "XuanYuanMaterials.xlsx",
        )
        # 生成与修改共用唯一正式母表。保留该属性只为兼容旧调用方。
        self.default_update_workbook = self.default_workbook
        self.default_hint_workbook = preferred_user_document(
            self.platform_root,
            "17_装备悬浮分类.xlsx",
            self.platform_root / "做装备" / "templates" / "XuanYuanItemHints.xlsx",
        )
        self.service = BatchEquipmentService(self.platform_root)
        self.planner = EquipmentPlanner(self.platform_root)
        self.installer = EquipmentInstaller(self.platform_root)

    def inspect_workbook(self, workbook: Path) -> WorkbookInspection:
        return self.service.inspect(workbook)

    def preflight(self, workbook: Path, server: Path, client_data: Path | None = None) -> EquipmentPlan:
        compiled = self.service.compile_mixed(workbook, server)
        return self.planner.preflight(server, compiled, client_data)

    def material_preflight(self, workbook: Path, server: Path, client_data: Path) -> EquipmentPlan:
        compiled = self.service.compile_materials(workbook)
        return self.planner.preflight(server, compiled, client_data, mode="material_create")

    def repair_display_preflight(self, workbook: Path, server: Path) -> EquipmentPlan:
        compiled = self.service.compile(workbook)
        return self.planner.preflight(server, compiled, mode="repair_display")

    def update_preflight(
        self,
        workbook: Path,
        server: Path,
        client_data: Path | None = None,
    ) -> EquipmentPlan:
        return self.planner.preflight(
            server,
            self.service.compile_update(workbook),
            client_data,
            mode="update",
        )

    def hint_preflight(self, workbook: Path, server: Path, client_data: Path) -> EquipmentPlan:
        return self.planner.preflight(
            server,
            self.service.compile_hints(workbook),
            client_data,
            mode="item_hint_sync",
        )

    def export_hint_workbook(self, server: Path, output: Path) -> None:
        target = inspect_target(server)
        export_hint_workbook(
            EquipmentPaths.for_target(self.platform_root, target.root),
            output,
        )

    def export_update_workbook(self, server: Path, output: Path) -> None:
        self.service.export_update_workbook(server, output)

    def search_equipment(self, server: Path, keyword: str) -> list[dict[str, int | str]]:
        return self.service.search_equipment(server, keyword)

    def install(self, plan: EquipmentPlan) -> EquipmentReceipt:
        return self.installer.install(plan)

    def rollback(self, server: Path, transaction_id: str) -> None:
        self.installer.rollback(server, transaction_id)

    # 装备素材替换接线：核心模块由做装备/src/xyequip/equipment_graphics 提供。
    # 延迟导入保持现有平台启动路径兼容，配置文件由调用方选择。
    @staticmethod
    def _graphics_core():
        from xyequip import equipment_graphics
        return equipment_graphics

    def graphics_preflight(self, config_path: Path) -> dict[str, object]:
        return self._graphics_core().preflight(Path(config_path))

    def graphics_apply(self, config_path: Path) -> dict[str, object]:
        return self._graphics_core().apply(Path(config_path))

    def graphics_rollback(self, receipt_path: Path) -> dict[str, object]:
        return self._graphics_core().rollback(Path(receipt_path))

    def graphics_verify_launcher(self, receipt_path: Path) -> dict[str, object]:
        return self._graphics_core().verify_launcher(Path(receipt_path))
