from __future__ import annotations

from pathlib import Path, PurePosixPath


DIRECTORY_NAME = "所需材料表格汇总"

DOCUMENTS = {
    "equipment_create": "09_装备批量生成.xlsx",
    "material_create": "11_材料批量生成.xlsx",
    "warrior_skill_upgrade": "12_战士技能强化.xlsx",
    "monster_execution_rules": "13_地图怪物处决规则.csv",
    "king_mode": "14_国王模式配置.txt",
    "first_pick": "15_首爆奖励配置.txt",
    "revive_icon": "16_复活图标装备名单.txt",
    "recycle_config": "19_装备回收配置.xlsx",
    "material_recycle": "19B_材料回收配置.xlsx",
    "monster_create": "20_怪物批量生成.xlsx",
    "seal_base": "21_神印基础属性.xlsx",
    "title_advance": "22_称号晋升.xlsx",
    "nmgf_sword": "23_宁姆格福_圣律之剑.xlsx",
    "nmgf_relic": "24_宁姆格福_黄金圣物.xlsx",
    "equipment_collection": "33_装备收集图鉴.xlsx",
    "item_synthesis": "34_通用物品合成.xlsx",
    "item_synthesis_npcs": "35_合成NPC与配方分配.txt",
    "mingge_system": "37_命格系统.xlsx",
}


def documents_root(platform_root: Path) -> Path:
    return Path(platform_root).resolve() / DIRECTORY_NAME


def preferred_document(platform_root: Path, name: str, fallback: Path | None = None) -> Path:
    """Return the centralized user document, with an old-path compatibility fallback."""
    preferred = documents_root(platform_root) / name
    if preferred.is_file() or fallback is None:
        return preferred
    return Path(fallback)


def package_operation_source(
    platform_root: Path,
    package_source: Path,
    user_document: str | None,
) -> Path:
    """Resolve an optional centralized package input without weakening package fallback safety."""
    if not user_document:
        return package_source
    relative = PurePosixPath(user_document)
    if relative.is_absolute() or len(relative.parts) != 1 or relative.name in {"", ".", ".."}:
        raise ValueError(f"填写文档路径无效: {user_document}")
    root = documents_root(platform_root).resolve()
    candidate = (root / relative.name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"填写文档路径越界: {user_document}") from exc
    return candidate if candidate.is_file() else package_source
