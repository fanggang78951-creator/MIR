from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def preferred_user_document(platform_root: Path, name: str, fallback: Path) -> Path:
    """Use the Chinese central workbook while retaining the historical path as fallback."""
    preferred = Path(platform_root).resolve() / "所需材料表格汇总" / name
    return preferred if preferred.is_file() else Path(fallback)


@dataclass(frozen=True)
class EquipmentPaths:
    """Every mutable target path and every immutable platform asset in one context."""

    platform_root: Path
    server_root: Path = Path(r"D:\MirServer")
    client_data: Path | None = None

    @classmethod
    def default(cls, platform_root: Path) -> "EquipmentPaths":
        return cls(Path(platform_root).resolve(), Path(r"D:\MirServer"), None)

    @classmethod
    def for_target(
        cls,
        platform_root: Path,
        server_root: Path,
        client_data: Path | None = None,
    ) -> "EquipmentPaths":
        return cls(
            Path(platform_root).resolve(),
            Path(server_root).resolve(),
            Path(client_data).resolve() if client_data is not None else None,
        )

    @property
    def equipment_root(self) -> Path:
        return self.platform_root / "做装备"

    @property
    def db_path(self) -> Path:
        return self.server_root / "Mud2" / "DB" / "ApexM2.DB"

    @property
    def envir(self) -> Path:
        return self.server_root / "Mir200" / "Envir"

    @property
    def item_desc(self) -> Path:
        return self.envir / "ItemDescList.txt"

    @property
    def item_rule(self) -> Path:
        return self.envir / "ItemRuleList.txt"

    @property
    def group_item(self) -> Path:
        return self.envir / "GroupItemList.txt"

    @property
    def effect_image_list(self) -> Path:
        return self.envir / "EffectImageList.txt"

    @property
    def effect_hint_definitions(self) -> Path:
        return self.envir / "EffectHintBG.txt"

    @property
    def effect_hint_items(self) -> Path:
        return self.envir / "EffectHintBGItems.txt"

    @property
    def qfunction(self) -> Path:
        return self.envir / "Market_Def" / "QFunction-0.txt"

    @property
    def qmanage(self) -> Path:
        return self.envir / "MapQuest_Def" / "QManage.txt"

    @property
    def attribute_panel(self) -> Path:
        return self.envir / "QuestDiary" / "玄渊功能" / "非常驻" / "属性总览" / "玄渊三属性按钮.txt"

    @property
    def fenghao_data(self) -> Path | None:
        """Client-side title description table used by generated title scrolls."""
        return self.client_data / "fenghao.dat" if self.client_data is not None else None

    @property
    def script_properties(self) -> Path:
        return self.equipment_root / "profiles" / "script_properties.json"

    @property
    def resource_map(self) -> Path:
        return self.equipment_root / "profiles" / "装备资源映射表.csv"

    @property
    def static_icon_importer(self) -> Path:
        return self.equipment_root / "src" / "xyequip" / "resources" / "static_icon_from_wzl.py"

    @property
    def raw_clone_importer(self) -> Path:
        return self.equipment_root / "src" / "xyequip" / "resources" / "clone_wzl_frame_raw.py"

    @property
    def backup_root(self) -> Path:
        return self.equipment_root / "backups"

    @property
    def output_root(self) -> Path:
        return self.equipment_root / "outputs"

    @property
    def master_workbook(self) -> Path:
        return preferred_user_document(
            self.platform_root,
            "09_装备批量生成.xlsx",
            self.equipment_root / "templates" / "XuanYuanItems.xlsx",
        )
