from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .artifact_library import ArtifactLibrary, ReviewDecision
from .importer import PackageImporter
from .installer import Installer
from .migration import MigrationRegistry
from .optional_scripts import OptionalScriptLibrary
from .optional_presets import OptionalPresetService
from .repository import PackageRepository
from .resident import ResidentService
from .runtime import platform_root
from .runtime_feedback import recent_m2_issues
from .target import TargetInspector
from .validator import validate_package
from .equipment_bridge import EquipmentBridge


def _graphics_result_failed(result):
    """Apply the core result contract consistently at the CLI boundary."""
    if not isinstance(result, dict):
        return True
    if result.get("success") is False:
        return True
    status = str(result.get("status", "")).strip().lower()
    if status.startswith(("failed", "error", "blocked")) or status in {"aborted", "rollback_failed"}:
        return True
    return bool(result.get("blockers"))
from .king_mode_flow import KingModeFlowError
from .king_mode_complete import KingModeCompleteService
from .execution_lab import ExecutionLabService
from .initial_camp import InitialCampService
from .seal_title import SealTitleService
from .config_sync import ConfigSyncService
from .monster_library import MonsterLibraryService, default_generator_login_dir
from .monster_login_integration import verify_custom_monster_login
from .monster_workbook import MonsterWorkbookService
from .recycle_config import RecycleConfigService
from .equipment_aura import EquipmentAuraService
from .mingge_native import generate_native_candidates
from .mingge_native_install import (
    install_native_test_candidate,
    plan_native_test_install,
    rollback_native_test_install,
)
from .mingge_native_p2_install import (
    install_native_p2_test_candidate,
    inspect_native_p2_test_transaction,
    plan_native_p2_test_install,
    recover_native_p2_test_transaction,
    rollback_native_p2_test_install,
)
from .mingge_native_p3_color_install import (
    install_native_p3_color_test,
    plan_native_p3_color_test_install,
    rollback_native_p3_color_test,
)


def _params(values: list[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"参数必须使用 key=value: {value}")
        key, item = value.split("=", 1)
        stripped = item.strip()
        if stripped.startswith(("{", "[")):
            try:
                result[key] = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"参数JSON格式错误: {key}: {exc}") from exc
        else:
            result[key] = item
    return result


def _config_sync_change_summary(item: object) -> dict[str, str]:
    relative_path = getattr(item, "relative_path", None)
    path = relative_path if relative_path not in (None, "") else getattr(item, "path", "")
    return {
        "scope": str(getattr(item, "scope", "server")),
        "path": str(path),
        "operation": str(getattr(item, "operation", "")),
        "package": str(getattr(item, "package_id", "")),
    }


def _config_sync_receipt_summary(receipt: object) -> dict[str, object]:
    def normalize(value: object) -> object:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        return value

    return normalize(asdict(receipt))  # type: ignore[return-value]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xydp", description="玄渊翎风成果植入平台")
    parser.add_argument("--root", type=Path, default=platform_root())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-packages")
    build_info = sub.add_parser("project-build-info", help="只读返回实际执行模块指纹")
    build_info.add_argument("--module", action="append", required=True)
    project_list = sub.add_parser("project-list", help="只读查询平台功能使用卡")
    project_list.add_argument("--query", default="")
    project_card = sub.add_parser("project-card", help="查看当前功能卡及验收边界")
    project_card.add_argument("--id", required=True)
    project_task = sub.add_parser("project-task", help="输出绑定输入指纹的任务单，不执行安装")
    project_task.add_argument("--id", required=True)
    project_task.add_argument("--server", type=Path, required=True)
    project_task.add_argument("--client", type=Path)
    project_task.add_argument("--validation", action="store_true")
    project_task.add_argument("--task-id", help="总控任务编号；续做必须复用原编号")
    script_register = sub.add_parser("script-folder-register")
    script_register.add_argument("--source", type=Path, required=True)
    sub.add_parser("script-folder-list")
    script_show = sub.add_parser("script-folder-show")
    script_show.add_argument("--id", required=True)
    script_link = sub.add_parser("script-folder-link")
    script_link.add_argument("--id", required=True)
    script_link.add_argument("--package", required=True)
    for name in ("resident-preflight", "resident-install"):
        item = sub.add_parser(name)
        item.add_argument("--server", type=Path, required=True)
        item.add_argument("--client", type=Path)
        item.add_argument("--param", action="append", default=[])
        if name == "resident-install":
            item.add_argument("--yes", action="store_true")
    for name in (
        "rage-preflight", "rage-install", "rage-rollback",
        "donate-preflight", "donate-install", "donate-rollback",
    ):
        item = sub.add_parser(name, help="狂暴/捐献唯一脚本包的预检、安装和回滚")
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        if not name.endswith("-rollback"):
            item.add_argument("--param", action="append", default=[])
        if not name.endswith("-preflight"):
            item.add_argument("--yes", action="store_true")
    inspect = sub.add_parser("inspect-target"); inspect.add_argument("--server", type=Path, required=True)
    diagnose = sub.add_parser("runtime-diagnose", help="读取目标服最新 M2 日志并生成运行反馈")
    diagnose.add_argument("--server", type=Path, required=True)
    for name in ("preflight", "install"):
        item = sub.add_parser(name); item.add_argument("--server", type=Path, required=True)
        item.add_argument("--client", type=Path)
        item.add_argument("--package", action="append", required=True); item.add_argument("--param", action="append", default=[])
        if name == "install": item.add_argument("--yes", action="store_true")
    rollback = sub.add_parser("rollback"); rollback.add_argument("--server", type=Path, required=True); rollback.add_argument("--transaction", required=True); rollback.add_argument("--yes", action="store_true")
    uninstall = sub.add_parser("uninstall"); uninstall.add_argument("--server", type=Path, required=True); uninstall.add_argument("--package", required=True); uninstall.add_argument("--yes", action="store_true")
    imp = sub.add_parser("import-package"); imp.add_argument("archive", type=Path)
    mig = sub.add_parser("register-migration"); mig.add_argument("source", type=Path); mig.add_argument("--package", required=True); mig.add_argument("--status", choices=["candidate", "verified", "archived"], default="candidate")
    validate = sub.add_parser("validate-package"); validate.add_argument("package_dir", type=Path)
    extract = sub.add_parser("extract-library")
    extract.add_argument("--codex", type=Path, required=True)
    extract.add_argument("--legacy", type=Path, required=True)
    extract.add_argument("--deepseek", type=Path, required=True)
    extract.add_argument("--decisions", type=Path)
    extract.add_argument("--yes", action="store_true")
    equipment_inspect = sub.add_parser("equipment-inspect")
    equipment_inspect.add_argument("--input", type=Path, required=True)
    shared_equipment_workbook = Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\09_装备批量生成.xlsx")
    for name in ("equipment-preflight", "equipment-apply"):
        item = sub.add_parser(name)
        item.add_argument("--input", type=Path, default=shared_equipment_workbook)
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        item.add_argument("--client-data", type=Path)
        if name == "equipment-apply":
            item.add_argument("--yes", action="store_true")
    for name in ("equipment-material-preflight", "equipment-material-apply"):
        item = sub.add_parser(name)
        item.add_argument("--input", type=Path, required=True)
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        item.add_argument("--client-data", type=Path, required=True)
        if name == "equipment-material-apply":
            item.add_argument("--yes", action="store_true")
    for name in ("equipment-update-preflight", "equipment-update-apply"):
        item = sub.add_parser(name)
        item.add_argument("--input", type=Path, default=shared_equipment_workbook)
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        item.add_argument("--client-data", type=Path)
        if name == "equipment-update-apply":
            item.add_argument("--yes", action="store_true")
    equipment_update_export = sub.add_parser("equipment-update-export")
    equipment_update_export.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    equipment_update_export.add_argument("--output", type=Path, required=True)
    for name in ("equipment-hint-preflight", "equipment-hint-apply"):
        item = sub.add_parser(name)
        item.add_argument("--input", type=Path, required=True)
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        item.add_argument("--client-data", type=Path, required=True)
        if name == "equipment-hint-apply":
            item.add_argument("--yes", action="store_true")
    equipment_hint_export = sub.add_parser("equipment-hint-export")
    equipment_hint_export.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    equipment_hint_export.add_argument("--output", type=Path, required=True)
    equipment_rollback = sub.add_parser("equipment-rollback")
    equipment_rollback.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    equipment_rollback.add_argument("--transaction", required=True)
    equipment_rollback.add_argument("--yes", action="store_true")
    graphics_preflight = sub.add_parser("equipment-graphics-preflight", help="装备素材替换配置预检")
    graphics_preflight.add_argument("--config", type=Path, required=True)
    for name in ("equipment-graphics-apply",):
        item = sub.add_parser(name, help="按装备素材替换配置执行事务")
        item.add_argument("--config", type=Path, required=True)
    graphics_rollback = sub.add_parser("equipment-graphics-rollback", help="按收据回滚装备素材替换")
    graphics_rollback.add_argument("--receipt", type=Path, required=True)
    graphics_verify = sub.add_parser("equipment-graphics-verify-launcher", help="登录器生成后核验装备素材")
    graphics_verify.add_argument("--receipt", type=Path, required=True)
    for name in ("recycle-config-preflight", "recycle-config-apply"):
        item = sub.add_parser(name, help="按装备回收XLSX生成动态分类、自动回收和多奖励脚本")
        item.add_argument(
            "--input", type=Path,
            default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\19_装备回收配置.xlsx"),
        )
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        if name.endswith("-apply"):
            item.add_argument("--yes", action="store_true")
    recycle_search = sub.add_parser("recycle-config-search", help="搜索回收配置中的分类或装备")
    recycle_search.add_argument(
        "--input", type=Path,
        default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\19_装备回收配置.xlsx"),
    )
    recycle_search.add_argument("--keyword", default="")
    recycle_rollback = sub.add_parser("recycle-config-rollback", help="逐字节回滚装备回收配置事务")
    recycle_rollback.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    recycle_rollback.add_argument("--transaction", required=True)
    recycle_rollback.add_argument("--yes", action="store_true")
    monster_scan = sub.add_parser("monster-library-scan", help="扫描明月Monster资料并按正确Mon号本地化完整动作补丁")
    monster_scan.add_argument("--donor-db", type=Path, required=True)
    monster_scan.add_argument("--donor-wzl-data", type=Path, required=True)
    monster_scan.add_argument("--donor-pak-data", type=Path, required=True)
    monster_scan.add_argument("--donor-pak-rules", type=Path, required=True)
    monster_scan.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    monster_scan.add_argument("--client-data", type=Path, default=Path(r"E:\11周年\data"))
    monster_scan.add_argument("--donor-server-root", type=Path)
    monster_scan.add_argument("--no-materialize", action="store_true")
    monster_login = sub.add_parser("monster-login-verify", help="只读核验自定义怪物DAT与登录器集成状态")
    monster_login.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    monster_login.add_argument("--client", type=Path, default=Path(r"E:\11周年"))
    monster_login.add_argument("--generator-login-dir", type=Path)
    monster_login.add_argument("--dependency", type=Path, action="append", default=[])
    monster_list = sub.add_parser("monster-library-list", help="列出本地怪物资料和补丁状态")
    monster_list.add_argument("--status", choices=("all", "ready", "existing", "skipped"), default="ready")
    monster_list.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    monster_sidecar = sub.add_parser("monster-library-sidecar-import", help="导入施工台PAK桥接sidecar缩略图")
    monster_sidecar.add_argument("--source", type=Path, required=True)
    for name in ("monster-library-preflight", "monster-library-apply"):
        item = sub.add_parser(name, help="按怪物库编号预检或一键植入Monster资料与完整动作补丁")
        item.add_argument("--monster-id", type=int, action="append", required=True)
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        item.add_argument("--client-data", type=Path, default=Path(r"E:\11周年\data"))
        item.add_argument("--generator-login-dir", type=Path)
        if name.endswith("-apply"):
            item.add_argument("--yes", action="store_true")
    monster_rollback = sub.add_parser("monster-library-rollback", help="逐字节回滚怪物资料与补丁植入事务")
    monster_rollback.add_argument("--transaction", required=True)
    monster_rollback.add_argument("--yes", action="store_true")
    monster_workbook_inspect = sub.add_parser("monster-workbook-inspect", help="检查怪物批量生成XLSX")
    monster_workbook_inspect.add_argument(
        "--input", type=Path,
        default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\20_怪物批量生成.xlsx"),
    )
    for name in ("monster-workbook-preflight", "monster-workbook-apply"):
        item = sub.add_parser(name, help="按XLSX属性生成Monster资料并从默认怪物库选择完整模型")
        item.add_argument(
            "--input", type=Path,
            default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\20_怪物批量生成.xlsx"),
        )
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        item.add_argument("--client-data", type=Path, default=Path(r"E:\11周年\data"))
        item.add_argument("--generator-login-dir", type=Path)
        if name.endswith("-apply"):
            item.add_argument("--yes", action="store_true")
    for name in ("king-mode-flow-preflight", "king-mode-flow-apply", "king-mode-config-apply", "king-mode-one-click"):
        item = sub.add_parser(name, help="国王模式完整一键安装/配置渲染")
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        item.add_argument("--client", type=Path, default=Path(r"E:\11周年"))
        if name != "king-mode-flow-preflight":
            item.add_argument("--yes", action="store_true")
    king_rollback = sub.add_parser("king-mode-rollback", help="逐字节回滚最近一次国王模式完整安装")
    king_rollback.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    king_rollback.add_argument("--yes", action="store_true")
    execution_preflight = sub.add_parser("execution-preflight", help="处决实验室预检；不写目标服")
    execution_preflight.add_argument("--server", type=Path, required=True)
    execution_install = sub.add_parser("execution-install", help="处决实验室独立备份后导入测试服")
    execution_install.add_argument("--server", type=Path, required=True)
    execution_install.add_argument("--yes", action="store_true")
    execution_install.add_argument("--confirm-test-server", action="store_true")
    execution_rollback = sub.add_parser("execution-rollback", help="逐字节回滚最近一次处决测试导入")
    execution_rollback.add_argument("--server", type=Path, required=True)
    execution_rollback.add_argument("--yes", action="store_true")
    for name in ("initial-camp-preflight", "initial-camp-install", "initial-camp-rollback"):
        item = sub.add_parser(name, help="初始之地七NPC材料表预检、事务安装和回滚")
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        if name != "initial-camp-rollback":
            item.add_argument("--materials", type=Path, default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总"))
            item.add_argument("--client", type=Path, default=Path(r"E:\11周年"))
        if name != "initial-camp-preflight":
            item.add_argument("--yes", action="store_true")
    for name in ("seal-title-preflight", "seal-title-install", "seal-title-rollback"):
        item = sub.add_parser(name, help="神印基础属性与称号晋升双NPC候选预检、事务安装和回滚")
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        if name != "seal-title-rollback":
            item.add_argument(
                "--materials", type=Path,
                default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总"),
            )
            item.add_argument("--client", type=Path)
        if name != "seal-title-preflight":
            item.add_argument("--yes", action="store_true")
    for name in ("config-sync-preflight", "config-sync-install"):
        item = sub.add_parser(name, help="主动选择已登记的XLSX/TXT/CSV配置文件进行预检或事务植入")
        item.add_argument("--server", type=Path, required=True)
        item.add_argument("--client", type=Path)
        item.add_argument("--file", type=Path, action="append", required=True)
        if name == "config-sync-install":
            item.add_argument("--yes", action="store_true")
    config_rollback = sub.add_parser("config-sync-rollback", help="回滚脚本配置同步事务")
    config_rollback.add_argument("--server", type=Path, required=True)
    config_rollback.add_argument("--transaction", required=True)
    config_rollback.add_argument("--route", choices=("initial-camp-selected", "package-documents", "king-mode-config", "recycle-config", "growth-stage", "equipment-collection", "item-synthesis", "mingge-system", "mingge-npc", "mingge-content", "weapon-enchant", "attack-speed-breakthrough", "equipment-wash-import", "npc-bundle"), required=True)
    config_rollback.add_argument("--yes", action="store_true")
    for name in ("config-sync-bundle-preflight", "config-sync-bundle-install"):
        item = sub.add_parser(name, help="艾尔登法环全NPC ZIP/目录统一预检或事务安装")
        item.add_argument("--source", type=Path, required=True)
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        item.add_argument("--client", type=Path, default=Path(r"E:\11周年"))
        item.add_argument("--launcher", type=Path, default=Path(r"D:\素材文件夹\LFM2[20260707]\登录器"))
        if name.endswith("-install"):
            item.add_argument("--yes", action="store_true")
    bundle_rollback = sub.add_parser("config-sync-bundle-rollback", help="逐字节回滚艾尔登法环全NPC批量事务")
    bundle_rollback.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    bundle_rollback.add_argument("--transaction", required=True)
    bundle_rollback.add_argument("--yes", action="store_true")
    sub.add_parser("equipment-aura-list-styles", help="列出10套三格装备光环样式")
    aura_workbook = Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\36_装备范围光环.xlsx")
    for name in ("equipment-aura-preflight", "equipment-aura-install"):
        item = sub.add_parser(name, help="装备光环预检或事务部署")
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        item.add_argument("--client", type=Path, default=Path(r"E:\11周年"))
        item.add_argument("--login", type=Path, default=Path(r"D:\素材文件夹\LFM2[20260707]\登录器"))
        item.add_argument("--input", type=Path, default=aura_workbook)
        if name.endswith("-install"):
            item.add_argument("--yes", action="store_true")
    aura_rollback = sub.add_parser("equipment-aura-rollback", help="逐字节回滚装备光环事务")
    aura_rollback.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    aura_rollback.add_argument("--transaction", required=True)
    aura_rollback.add_argument("--yes", action="store_true")
    mingge_native = sub.add_parser(
        "mingge-native-candidate",
        help="按V1两表、V2中文五表或V3颜色六表生成离线候选，不写服务端、客户端或数据库",
    )
    mingge_native.add_argument(
        "--input",
        type=Path,
        default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\38_命格原生多色候选.xlsx"),
    )
    mingge_native.add_argument("--output", type=Path, required=True)
    for name in ("mingge-native-test-preflight", "mingge-native-test-install"):
        item = sub.add_parser(name, help="38号命格单件黄金样本的隔离预检或事务安装")
        item.add_argument(
            "--input", type=Path,
            default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\38_命格原生多色候选.xlsx"),
        )
        item.add_argument("--candidate", required=True)
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        if name.endswith("-install"):
            item.add_argument("--yes", action="store_true")
    mingge_native_rollback = sub.add_parser(
        "mingge-native-test-rollback", help="逐字节回滚38号命格P1隔离安装事务"
    )
    mingge_native_rollback.add_argument("--transaction", required=True)
    mingge_native_rollback.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    mingge_native_rollback.add_argument("--yes", action="store_true")
    for name in ("mingge-native-p2-test-preflight", "mingge-native-p2-test-install"):
        item = sub.add_parser(name, help="38号命格固定三属性P2候选的隔离预检或事务安装")
        item.add_argument(
            "--input", type=Path,
            default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\38_命格原生多色候选.xlsx"),
        )
        item.add_argument("--candidate", default="tiebi-vitality-p2")
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        if name.endswith("-install"):
            item.add_argument("--yes", action="store_true")
    mingge_native_p2_rollback = sub.add_parser(
        "mingge-native-p2-test-rollback", help="逐字节回滚38号命格P2三属性隔离安装事务"
    )
    mingge_native_p2_rollback.add_argument("--transaction", required=True)
    mingge_native_p2_rollback.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    mingge_native_p2_rollback.add_argument("--yes", action="store_true")
    mingge_native_p2_recover_preflight = sub.add_parser(
        "mingge-native-p2-test-recover-preflight", help="只读检查P2中断事务的封印、日志与三目标状态"
    )
    mingge_native_p2_recover_preflight.add_argument("--transaction", required=True)
    mingge_native_p2_recover_preflight.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    mingge_native_p2_recover = sub.add_parser(
        "mingge-native-p2-test-recover", help="显式恢复P2中断事务"
    )
    mingge_native_p2_recover.add_argument("--transaction", required=True)
    mingge_native_p2_recover.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    mingge_native_p2_recover.add_argument("--strategy", choices=("rollback", "finalize-install"), required=True)
    mingge_native_p2_recover.add_argument("--yes", action="store_true")
    for name in ("mingge-native-p3-color-test-preflight", "mingge-native-p3-color-test-install"):
        item = sub.add_parser(name, help="39号表四种颜色P3受限测试的只读预检或单脚本事务安装")
        item.add_argument(
            "--input", type=Path,
            default=Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\39_命格P3颜色导入测试.xlsx"),
        )
        item.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
        if name.endswith("-install"):
            item.add_argument("--yes", action="store_true")
    mingge_native_p3_rollback = sub.add_parser(
        "mingge-native-p3-color-test-rollback", help="逐字节恢复P2脚本并关闭P3自己的活动协调状态"
    )
    mingge_native_p3_rollback.add_argument("--transaction", required=True)
    mingge_native_p3_rollback.add_argument("--server", type=Path, default=Path(r"D:\MirServer"))
    mingge_native_p3_rollback.add_argument("--yes", action="store_true")
    return parser


def _review_decisions(path: Path | None) -> dict[str, ReviewDecision]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(relative).replace("\\", "/"): ReviewDecision(
            status=str(value["status"]),
            reason=str(value["reason"]),
            evidence=tuple(str(item) for item in value.get("evidence", [])),
        )
        for relative, value in raw.items()
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "project-build-info":
        from .release_identity import runtime_identity
        print(json.dumps(runtime_identity(args.module), sort_keys=True)); return 0
    if args.command in {"project-list", "project-card", "project-task"}:
        from .project_overview import ProjectOverview
        service = ProjectOverview(args.root)
        try:
            if args.command == "project-list": result = service.search(args.query)
            elif args.command == "project-card": result = service.get(args.id)
            else: result = service.task_order(args.id, args.server, args.client, args.validation, args.task_id)
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        except (ValueError, OSError, KeyError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False)); return 1
    if args.command == "monster-login-verify":
        status = verify_custom_monster_login(
            args.generator_login_dir or default_generator_login_dir(args.server),
            args.server / "Mir200" / "自定义怪物.dat",
            args.client / "传奇登陆器.exe",
            args.dependency,
        )
        print(json.dumps(asdict(status), ensure_ascii=False, indent=2)); return 0
    if args.command == "mingge-native-candidate":
        receipt = generate_native_candidates(
            args.input,
            args.output,
            allowed_output_root=platform_root() / "outputs",
        )
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    root = args.root.resolve()
    if args.command.startswith("mingge-native-p3-color-test-"):
        if args.command == "mingge-native-p3-color-test-rollback":
            if not args.yes:
                raise SystemExit("mingge-native-p3-color-test-rollback 必须显式提供 --yes")
            receipt = rollback_native_p3_color_test(root, args.transaction, args.server)
            print(json.dumps({
                "operation": "mingge-native-p3-color-test-rollback",
                "status": receipt.status,
                "transaction_id": receipt.transaction_id,
                "receipt": str(receipt.receipt_path),
                "restores_p2_script_byte_exact": True,
                "p2_stack_order": "P3先回滚，之后才可回滚P2",
            }, ensure_ascii=False, indent=2)); return 0
        plan = plan_native_p3_color_test_install(args.input, args.server, root)
        summary = {
            "operation": "mingge-native-p3-color-test",
            "plan_id": plan.plan_id,
            "workbook": str(plan.workbook),
            "workbook_sha256": plan.workbook_sha256,
            "candidate_spec_sha256": plan.candidate_spec_sha256,
            "candidate_ids": list(plan.candidate_ids),
            "server": str(plan.server_root),
            "blockers": list(plan.blockers),
            "warnings": list(plan.warnings),
            "changes": [{
                "path": str(item.path),
                "relative_path": item.relative_path,
                "before_sha256": item.before_sha256,
                "after_sha256": item.after_sha256,
            } for item in plan.files],
            "writes_server": args.command == "mingge-native-p3-color-test-install",
            "writes_usercmd": False,
            "writes_qfunction": True,
            "writes_client": False,
            "writes_database": False,
            "writes_real_property": True,
            "game_validation_status": "pending",
        }
        if args.command == "mingge-native-p3-color-test-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("mingge-native-p3-color-test-install 必须显式提供 --yes")
        if plan.blockers:
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1
        receipt = install_native_p3_color_test(plan, root)
        print(json.dumps({
            **summary,
            "status": receipt.status,
            "transaction_id": receipt.transaction_id,
            "receipt": str(receipt.receipt_path),
        }, ensure_ascii=False, indent=2)); return 0
    if args.command.startswith("mingge-native-p2-test-"):
        if args.command == "mingge-native-p2-test-recover-preflight":
            result = inspect_native_p2_test_transaction(root, args.transaction, args.server)
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        if args.command == "mingge-native-p2-test-recover":
            if not args.yes:
                raise SystemExit("mingge-native-p2-test-recover 必须显式提供 --yes")
            receipt = recover_native_p2_test_transaction(root, args.transaction, args.server, args.strategy)
            print(json.dumps({
                "operation": "mingge-native-p2-test-recover", "strategy": args.strategy,
                "status": receipt.status, "transaction_id": receipt.transaction_id,
                "receipt": str(receipt.receipt_path), "runtime_item_instance_restored": False,
            }, ensure_ascii=False, indent=2)); return 0
        if args.command == "mingge-native-p2-test-rollback":
            if not args.yes:
                raise SystemExit("mingge-native-p2-test-rollback 必须显式提供 --yes")
            receipt = rollback_native_p2_test_install(root, args.transaction, args.server)
            print(json.dumps({
                "operation": "mingge-native-p2-test-rollback", "status": receipt.status,
                "transaction_id": receipt.transaction_id, "receipt": str(receipt.receipt_path),
                "runtime_item_instance_restored": False,
            }, ensure_ascii=False, indent=2)); return 0
        plan = plan_native_p2_test_install(args.input, args.candidate, args.server)
        summary = {
            "operation": "mingge-native-p2-test", "plan_id": plan.plan_id,
            "candidate_id": plan.candidate_id, "candidate_spec_sha256": plan.candidate_spec_sha256,
            "compiled_script_sha256": plan.compiled_script_sha256,
            "workbook": str(plan.workbook), "workbook_sha256": plan.workbook_sha256,
            "server": str(plan.server_root),
            "engine_version": plan.engine_version, "engine_sha256": plan.engine_sha256,
            "blockers": list(plan.blockers), "warnings": list(plan.warnings),
            "evidence_status": list(plan.evidence_status),
            "evidence": [asdict(item) for item in plan.evidence],
            "changes": [{
                "path": str(item.path), "relative_path": item.relative_path,
                "before_sha256": item.before_sha256, "after_sha256": item.after_sha256,
            } for item in plan.files],
            "writes_server": args.command == "mingge-native-p2-test-install",
            "writes_client": False, "writes_database_directly": False,
            "runtime_item_instance_may_change_after_player_command": True,
            "game_validation_status": "pending",
        }
        if args.command == "mingge-native-p2-test-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("mingge-native-p2-test-install 必须显式提供 --yes")
        if plan.blockers:
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1
        receipt = install_native_p2_test_candidate(plan, root)
        print(json.dumps({
            **summary, "status": receipt.status, "transaction_id": receipt.transaction_id,
            "receipt": str(receipt.receipt_path),
        }, ensure_ascii=False, indent=2)); return 0
    if args.command.startswith("mingge-native-test-"):
        if args.command == "mingge-native-test-rollback":
            if not args.yes:
                raise SystemExit("mingge-native-test-rollback 必须显式提供 --yes")
            receipt = rollback_native_test_install(root, args.transaction, args.server)
            print(json.dumps({
                "operation": "mingge-native-p1-test-rollback",
                "status": receipt.status,
                "transaction_id": receipt.transaction_id,
                "receipt": str(receipt.receipt_path),
            }, ensure_ascii=False, indent=2)); return 0
        plan = plan_native_test_install(args.input, args.candidate, args.server)
        summary = {
            "operation": "mingge-native-p1-test",
            "plan_id": plan.plan_id,
            "candidate_id": plan.candidate_id,
            "workbook": str(plan.workbook),
            "workbook_sha256": plan.workbook_sha256,
            "server": str(plan.server_root),
            "blockers": list(plan.blockers),
            "warnings": list(plan.warnings),
            "changes": [
                {
                    "path": str(item.path),
                    "relative_path": item.relative_path,
                    "before_sha256": item.before_sha256,
                    "after_sha256": item.after_sha256,
                }
                for item in plan.files
            ],
            "writes_server": args.command == "mingge-native-test-install",
            "writes_client": False,
            "writes_database": False,
        }
        if args.command == "mingge-native-test-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("mingge-native-test-install 必须显式提供 --yes")
        if plan.blockers:
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1
        receipt = install_native_test_candidate(plan, root)
        print(json.dumps({
            **summary,
            "status": receipt.status,
            "transaction_id": receipt.transaction_id,
            "receipt": str(receipt.receipt_path),
        }, ensure_ascii=False, indent=2)); return 0
    repo = PackageRepository(root / "packages")
    repo.refresh()
    installer = Installer(repo, root / "backups")
    if args.command.startswith("equipment-aura-"):
        service = EquipmentAuraService(root)
        if args.command == "equipment-aura-list-styles":
            print(json.dumps(service.list_styles(), ensure_ascii=False, indent=2)); return 0
        if args.command == "equipment-aura-rollback":
            if not args.yes:
                raise SystemExit("equipment-aura-rollback 必须显式提供 --yes")
            status = service.rollback(args.server, args.transaction)
            print(json.dumps({"transaction_id": args.transaction, "status": status}, ensure_ascii=False, indent=2)); return 0
        plan = service.preflight(args.server, args.client, args.login, args.input)
        summary = {
            "operation": "equipment-aura",
            "plan_id": plan.plan_id,
            "server": str(plan.paths.server_root),
            "client": str(plan.paths.client_root),
            "login": str(plan.paths.login_root),
            "workbook": str(plan.workbook_path),
            "bindings": [asdict(item) for item in plan.workbook.enabled_bindings],
            "resource_index": plan.resource_index,
            "static_resource_action": plan.static_resource_action,
            "blockers": list(plan.blockers),
            "warnings": list(plan.warnings),
            "changes": [
                {"path": str(item.path), "before_hash": item.before_hash, "after_hash": item.after_hash}
                for item in plan.files
            ],
        }
        if args.command == "equipment-aura-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("equipment-aura-install 必须显式提供 --yes")
        if plan.blockers:
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1
        receipt = service.install(plan)
        print(json.dumps({
            "status": receipt.status,
            "transaction_id": receipt.transaction_id,
            "receipt": str(receipt.receipt_path),
            "changed_files": [str(path) for path in receipt.changed_files],
        }, ensure_ascii=False, indent=2)); return 0
    if args.command.startswith("recycle-config-"):
        service = RecycleConfigService(root)
        if args.command == "recycle-config-search":
            print(json.dumps(service.search(args.input, args.keyword), ensure_ascii=False, indent=2)); return 0
        if args.command == "recycle-config-rollback":
            if not args.yes:
                raise SystemExit("recycle-config-rollback 必须显式提供 --yes")
            transaction = service.rollback(args.server, args.transaction)
            print(json.dumps({"rolled_back": transaction, "operation": "recycle-config-update"}, ensure_ascii=False, indent=2)); return 0
        plan = service.preflight(args.input, args.server)
        summary = {
            "operation": plan.operation,
            "server": plan.server,
            "workbook": plan.workbook,
            "workbook_hash": plan.workbook_hash,
            "categories": [asdict(item) for item in plan.categories],
            "item_names": plan.item_names,
            "reward_types": plan.reward_types,
            "blockers": plan.blockers,
            "warnings": plan.warnings,
            "changes": [
                {"path": item.relative_path, "operation": item.operation,
                 "before_bytes": len(item.before) if item.before is not None else None,
                 "after_bytes": len(item.after)}
                for item in plan.changes
            ],
        }
        if args.command == "recycle-config-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("recycle-config-apply 必须显式提供 --yes")
        receipt = service.install(plan)
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command in {
        "config-sync-bundle-preflight", "config-sync-bundle-install", "config-sync-bundle-rollback",
    }:
        service = ConfigSyncService(root)
        if args.command == "config-sync-bundle-rollback":
            if not args.yes:
                raise SystemExit("config-sync-bundle-rollback 必须显式提供 --yes")
            transaction = service.rollback(args.server, args.transaction, "npc-bundle")
            print(json.dumps({"rolled_back": transaction, "route": "npc-bundle"}, ensure_ascii=False, indent=2))
            return 0
        plan = service.preflight_bundle(
            args.source, args.server, client=args.client, launcher=args.launcher,
        )
        summary = {
            "operation": "npc-bundle-v21",
            "source": plan.source,
            "source_sha256": plan.source_sha256,
            "server": plan.server,
            "client": plan.client,
            "launcher": plan.launcher,
            "active_workbooks": plan.manifest.active_xlsx_count if plan.manifest else 0,
            "excluded": [asdict(item) for item in plan.manifest.excluded] if plan.manifest else [],
            "audit": asdict(plan.audit) if plan.audit else None,
            "child_reports": plan.child_reports,
            "blockers": plan.blockers,
            "warnings": plan.warnings,
            "changes": [_config_sync_change_summary(item) for item in plan.changes],
        }
        if args.command == "config-sync-bundle-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("config-sync-bundle-install 必须显式提供 --yes")
        receipt = service.install_bundle(plan)
        print(json.dumps(_config_sync_receipt_summary(receipt), ensure_ascii=False, indent=2))
        return 0
    if args.command in {"config-sync-preflight", "config-sync-install", "config-sync-rollback"}:
        service = ConfigSyncService(root)
        if args.command == "config-sync-rollback":
            if not args.yes:
                raise SystemExit("config-sync-rollback 必须显式提供 --yes")
            transaction = service.rollback(args.server, args.transaction, args.route)
            print(json.dumps({"rolled_back": transaction, "route": args.route}, ensure_ascii=False, indent=2)); return 0
        plan = service.preflight(args.server, args.file, args.client)
        summary = {
            "operation": "config-sync",
            "route": plan.route,
            "server": plan.server,
            "client": plan.client,
            "selected_documents": [asdict(item) for item in plan.documents],
            "blockers": plan.blockers,
            "warnings": plan.warnings,
            "changes": [_config_sync_change_summary(item) for item in plan.changes],
        }
        if plan.route == "item-synthesis" and plan.inner_plan is not None:
            summary["synthesis_npcs"] = getattr(plan.inner_plan, "npcs", [])
            summary["synthesis_recipes"] = getattr(plan.inner_plan, "recipes", [])
        if args.command == "config-sync-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("config-sync-install 必须显式提供 --yes")
        receipt = service.install(plan)
        print(json.dumps(_config_sync_receipt_summary(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command in {"initial-camp-preflight", "initial-camp-install", "initial-camp-rollback"}:
        service = InitialCampService(root)
        if args.command == "initial-camp-rollback":
            if not args.yes:
                raise SystemExit("initial-camp-rollback 必须显式提供 --yes")
            transaction = service.rollback_latest(args.server)
            print(json.dumps({"rolled_back": transaction, "operation": "initial-camp-seven-npc"}, ensure_ascii=False, indent=2)); return 0
        plan = service.preflight(args.server, args.materials, args.client)
        summary = {
            "operation": plan.operation, "server": plan.server, "client": plan.client,
            "materials": plan.materials,
            "materials_hash": plan.materials_hash, "npcs": [asdict(item) for item in plan.npcs],
            "blockers": plan.blockers, "warnings": plan.warnings,
            "changes": [{"path": item.relative_path, "scope": item.scope,
                         "operation": item.operation, "package": item.package_id}
                        for item in plan.changes],
        }
        if args.command == "initial-camp-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("initial-camp-install 必须显式提供 --yes")
        receipt = service.install(plan)
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command in {"seal-title-preflight", "seal-title-install", "seal-title-rollback"}:
        service = SealTitleService(root)
        if args.command == "seal-title-rollback":
            if not args.yes:
                raise SystemExit("seal-title-rollback 必须显式提供 --yes")
            transaction = service.rollback_latest(args.server)
            print(json.dumps({"rolled_back": transaction, "operation": "seal-title-two-npc"}, ensure_ascii=False, indent=2)); return 0
        plan = service.preflight(args.server, args.materials, args.client)
        summary = {
            "operation": plan.operation, "server": plan.server, "client": plan.client,
            "materials": plan.materials, "materials_hash": plan.materials_hash,
            "npcs": [asdict(item) for item in plan.npcs],
            "blockers": plan.blockers, "warnings": plan.warnings,
            "changes": [
                {"path": item.relative_path, "scope": item.scope,
                 "operation": item.operation, "package": item.package_id}
                for item in plan.changes
            ],
        }
        if args.command == "seal-title-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("seal-title-install 必须显式提供 --yes")
        receipt = service.install(plan)
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command.startswith("script-folder-"):
        library = OptionalScriptLibrary(root)
        if args.command == "script-folder-register":
            print(json.dumps(asdict(library.register(args.source)), ensure_ascii=False, indent=2)); return 0
        if args.command == "script-folder-list":
            print(json.dumps([asdict(item) for item in library.list()], ensure_ascii=False, indent=2)); return 0
        if args.command == "script-folder-link":
            print(json.dumps(asdict(library.link_package(args.id, args.package)), ensure_ascii=False, indent=2)); return 0
        print(json.dumps(asdict(library.show(args.id)), ensure_ascii=False, indent=2)); return 0
    if args.command in {"resident-preflight", "resident-install"}:
        resident = ResidentService(repo, root / "backups")
        plan = resident.preflight(args.server, _params(args.param), args.client)
        candidates = [
            package_id for package_id in plan.package_ids
            if repo.packages[package_id].status == "candidate"
        ]
        summary = {
            "operation": plan.operation_type,
            "target": plan.target_root,
            "packages": plan.package_ids,
            "candidate_packages": candidates,
            "changes": [
                {"path": item.relative_path, "scope": item.scope, "package": item.package_id,
                 "before_bytes": len(item.before) if item.before is not None else None,
                 "after_bytes": len(item.after)}
                for item in plan.changes
            ],
        }
        if args.command == "resident-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 0
        if not args.yes:
            raise SystemExit("resident-install 必须显式提供 --yes")
        receipt = resident.install(plan)
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    optional_preset_commands = {
        "rage-preflight": ("rage", "preflight"),
        "rage-install": ("rage", "install"),
        "rage-rollback": ("rage", "rollback"),
        "donate-preflight": ("donate", "preflight"),
        "donate-install": ("donate", "install"),
        "donate-rollback": ("donate", "rollback"),
    }
    if args.command in optional_preset_commands:
        preset_id, action = optional_preset_commands[args.command]
        service = OptionalPresetService(root)
        if action == "rollback":
            if not args.yes:
                raise SystemExit(f"{args.command} 必须显式提供 --yes")
            transaction = service.rollback_latest(preset_id, args.server)
            print(json.dumps({"rolled_back": transaction, "preset": preset_id}, ensure_ascii=False, indent=2)); return 0
        plan = service.preflight(preset_id, args.server, _params(args.param))
        summary = {
            "operation": plan.operation_type,
            "target": plan.target_root,
            "packages": plan.package_ids,
            "candidate_packages": plan.candidate_packages,
            "parameters": plan.parameters,
            "changes": [
                {"path": item.relative_path, "scope": item.scope, "operation": item.operation, "package": item.package_id}
                for item in plan.changes
            ],
        }
        if action == "preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 0
        if not args.yes:
            raise SystemExit(f"{args.command} 必须显式提供 --yes")
        receipt = service.install(preset_id, plan)
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command.startswith("equipment-"):
        equipment = EquipmentBridge(root)
        if args.command == "equipment-graphics-preflight":
            result = equipment.graphics_preflight(args.config)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 1 if _graphics_result_failed(result) else 0
        if args.command == "equipment-graphics-apply":
            result = equipment.graphics_apply(args.config)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 1 if _graphics_result_failed(result) else 0
        if args.command == "equipment-graphics-rollback":
            result = equipment.graphics_rollback(args.receipt)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 1 if _graphics_result_failed(result) else 0
        if args.command == "equipment-graphics-verify-launcher":
            result = equipment.graphics_verify_launcher(args.receipt)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 1 if _graphics_result_failed(result) else 0
        if args.command == "equipment-inspect":
            print(json.dumps(asdict(equipment.inspect_workbook(args.input)), ensure_ascii=False, indent=2, default=str)); return 0
        if args.command == "equipment-update-export":
            equipment.export_update_workbook(args.server, args.output)
            print(json.dumps({"exported": str(args.output), "server": str(args.server)}, ensure_ascii=False)); return 0
        if args.command == "equipment-hint-export":
            equipment.export_hint_workbook(args.server, args.output)
            print(json.dumps({"exported": str(args.output), "server": str(args.server)}, ensure_ascii=False)); return 0
        if args.command in {
            "equipment-preflight", "equipment-apply",
            "equipment-update-preflight", "equipment-update-apply",
            "equipment-material-preflight", "equipment-material-apply",
            "equipment-hint-preflight", "equipment-hint-apply",
        }:
            is_update = args.command.startswith("equipment-update-")
            is_material = args.command.startswith("equipment-material-")
            is_hint = args.command.startswith("equipment-hint-")
            if is_update:
                plan = equipment.update_preflight(args.input, args.server, args.client_data)
            elif is_material:
                plan = equipment.material_preflight(args.input, args.server, args.client_data)
            elif is_hint:
                plan = equipment.hint_preflight(args.input, args.server, args.client_data)
            else:
                plan = equipment.preflight(args.input, args.server, args.client_data)
            summary = {
                "operation": plan.operation, "target": str(plan.target.root), "workbook_hash": plan.workbook_hash,
                "equipment_names": plan.equipment_names, "blockers": plan.blockers,
                "skipped_existing": list(plan.skipped_existing),
                "warnings": plan.warnings, "base_templates": plan.base_templates,
                "changes": [asdict(change) for change in plan.changes],
            }
            if args.command in {"equipment-preflight", "equipment-update-preflight", "equipment-material-preflight", "equipment-hint-preflight"}:
                print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
            if not args.yes: raise SystemExit(f"{args.command} 必须显式提供 --yes")
            receipt = equipment.install(plan)
            print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
        if not args.yes: raise SystemExit("equipment-rollback 必须显式提供 --yes")
        equipment.rollback(args.server, args.transaction)
        print(json.dumps({"rolled_back": args.transaction}, ensure_ascii=False)); return 0
    if args.command.startswith("monster-workbook-"):
        service = MonsterWorkbookService(root)
        if args.command == "monster-workbook-inspect":
            print(json.dumps(asdict(service.inspect(args.input)), ensure_ascii=False, indent=2)); return 0
        plan = service.preflight(
            args.input,
            args.server,
            args.client_data,
            generator_login_dir=args.generator_login_dir or default_generator_login_dir(args.server),
        )
        summary = service.plan_summary(plan)
        if args.command == "monster-workbook-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("monster-workbook-apply 必须显式提供 --yes")
        receipt = service.install(plan)
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command.startswith("monster-library-"):
        service = MonsterLibraryService(root)
        if args.command == "monster-library-scan":
            result = service.scan(
                args.donor_db, args.donor_wzl_data, args.donor_pak_data, args.donor_pak_rules,
                args.server, args.client_data,
                donor_server_root=args.donor_server_root,
                materialize=not args.no_materialize,
            )
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2)); return 0
        if args.command == "monster-library-list":
            print(json.dumps([asdict(item) for item in service.list_monsters(args.status, args.server)], ensure_ascii=False, indent=2)); return 0
        if args.command == "monster-library-sidecar-import":
            print(json.dumps(asdict(service.import_sidecars(args.source)), ensure_ascii=False, indent=2)); return 0
        if args.command == "monster-library-rollback":
            if not args.yes:
                raise SystemExit("monster-library-rollback 必须显式提供 --yes")
            service.rollback(args.transaction)
            print(json.dumps({"rolled_back": args.transaction}, ensure_ascii=False)); return 0
        plan = service.preflight(
            args.monster_id,
            args.server,
            args.client_data,
            generator_login_dir=args.generator_login_dir or default_generator_login_dir(args.server),
        )
        summary = service.plan_summary(plan)
        if args.command == "monster-library-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit("monster-library-apply 必须显式提供 --yes")
        receipt = service.install(plan)
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command == "king-mode-rollback":
        if not args.yes:
            raise SystemExit("king-mode-rollback 必须显式提供 --yes")
        transaction = KingModeCompleteService(root).rollback(args.server, yes=True)
        print(json.dumps({"rolled_back": transaction}, ensure_ascii=False, indent=2)); return 0
    if args.command in {"execution-preflight", "execution-install", "execution-rollback"}:
        service = ExecutionLabService(root)
        if args.command == "execution-rollback":
            if not args.yes:
                raise SystemExit("execution-rollback 必须显式提供 --yes")
            transaction = service.rollback_latest(args.server)
            print(json.dumps({"rolled_back": transaction, "operation": "execution-lab"}, ensure_ascii=False, indent=2)); return 0
        plan = service.preflight(args.server)
        summary = {
            "operation": plan.operation_type,
            "target": plan.target_root,
            "packages": plan.package_ids,
            "map_rules": {
                "file": plan.parameters.get("map_rules_file"),
                "sha256": plan.parameters.get("map_rules_sha256"),
                "count": plan.parameters.get("map_rule_count"),
                "map_ids": plan.parameters.get("map_rule_ids"),
            },
            "backup_root": str(service.installer.backups_root),
            "changes": [
                {"path": item.relative_path, "scope": item.scope, "operation": item.operation,
                 "before_bytes": len(item.before) if item.before is not None else None,
                 "after_bytes": len(item.after)}
                for item in plan.changes
            ],
        }
        if args.command == "execution-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 0
        if not args.yes or not args.confirm_test_server:
            raise SystemExit("execution-install 必须同时提供 --yes 和 --confirm-test-server")
        receipt = service.install(plan, confirmed_test_server=True)
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command in {"king-mode-flow-preflight", "king-mode-flow-apply", "king-mode-config-apply", "king-mode-one-click"}:
        service = KingModeCompleteService(root)
        plan = service.config_apply(args.server, args.client) if args.command == "king-mode-config-apply" else service.preflight(args.server, args.client, operation=args.command)
        summary = {
            "operation": plan.operation,
            "server": plan.server,
            "client": plan.client,
            "config": plan.config_path,
            "config_hash": plan.config_hash,
            "values": plan.values,
            "blockers": plan.blockers,
            "warnings": plan.warnings,
            "changes": [{"scope": c.scope, "path": c.relative_path, "before_hash": c.before_hash, "after_hash": c.after_hash, "operation": c.operation} for c in plan.changes],
        }
        if args.command == "king-mode-flow-preflight":
            print(json.dumps(summary, ensure_ascii=False, indent=2)); return 1 if plan.blockers else 0
        if not args.yes:
            raise SystemExit(f"{args.command} 必须显式提供 --yes")
        receipt = service.apply(plan, yes=True)
        print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command == "list-packages":
        print(json.dumps([
            {"id": p.id, "version": p.version, "name": p.display_name, "status": p.status,
             "residency": p.residency, "bundle": p.bundle}
            for p in sorted(repo.packages.values(), key=lambda item: item.id)
        ], ensure_ascii=False, indent=2)); return 0
    if args.command == "inspect-target":
        print(json.dumps(asdict(TargetInspector.inspect(args.server)), ensure_ascii=False, indent=2, default=str)); return 0
    if args.command == "runtime-diagnose":
        issues = recent_m2_issues(args.server, max_files=1)
        print(json.dumps({"server": str(args.server), "issues": [item.to_dict() for item in issues]}, ensure_ascii=False, indent=2))
        return 1 if any(item.severity == "block" for item in issues) else 0
    if args.command in {"preflight", "install"}:
        plan = installer.preflight(args.server, args.package, _params(args.param), client_root=args.client)
        summary = {"target": plan.target_root, "packages": plan.package_ids, "changes": [
            {"path": c.relative_path, "scope": c.scope, "operation": c.operation, "package": c.package_id,
             "before_bytes": len(c.before) if c.before is not None else None, "after_bytes": len(c.after)} for c in plan.changes
        ], "warnings": plan.warnings}
        if args.command == "preflight": print(json.dumps(summary, ensure_ascii=False, indent=2)); return 0
        if not args.yes: raise SystemExit("install 必须显式提供 --yes")
        receipt = installer.install(plan); print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2)); return 0
    if args.command == "rollback":
        if not args.yes: raise SystemExit("rollback 必须显式提供 --yes")
        installer.rollback(args.server, args.transaction); print(json.dumps({"rolled_back": args.transaction}, ensure_ascii=False)); return 0
    if args.command == "uninstall":
        if not args.yes: raise SystemExit("uninstall 必须显式提供 --yes")
        installer.uninstall(args.server, args.package); print(json.dumps({"uninstalled": args.package}, ensure_ascii=False)); return 0
    if args.command == "import-package":
        item = PackageImporter(root / "packages").import_archive(args.archive); print(json.dumps({"imported": item.id, "status": item.status}, ensure_ascii=False)); return 0
    if args.command == "register-migration":
        item = MigrationRegistry(root).copy_and_register(args.source, args.package, args.status); print(json.dumps(asdict(item), ensure_ascii=False, indent=2)); return 0
    if args.command == "validate-package":
        item = validate_package(args.package_dir); print(json.dumps({"valid": item.id, "version": item.version, "status": item.status}, ensure_ascii=False)); return 0
    if args.command == "extract-library":
        if not args.yes: raise SystemExit("extract-library 必须显式提供 --yes")
        library = ArtifactLibrary(root)
        review = library.review_deepseek(args.deepseek, _review_decisions(args.decisions))
        extraction = library.extract({"codex_handover": args.codex, "legacy_ai_handoff": args.legacy})
        print(json.dumps({"review": asdict(review), "extraction": asdict(extraction)}, ensure_ascii=False, indent=2)); return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)
