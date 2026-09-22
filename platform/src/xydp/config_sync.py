from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .initial_camp import InitialCampPlan, InitialCampService
from .growth_stage import GrowthStagePlan, GrowthStageService
from .installer import InstallPlan, Installer
from .king_mode_complete import KingModeCompleteService
from .king_mode_flow import FlowPlan
from .repository import PackageRepository
from .recycle_config import RecycleConfigPlan, RecycleConfigService
from .equipment_collection import EquipmentCollectionPlan, EquipmentCollectionService
from .item_synthesis import ItemSynthesisPlan, ItemSynthesisService
from .mingge import MingGePlan, MingGeService
from .mingge_dual import (
    CONTENT_ROUTE,
    NPC_ROUTE,
    DualInstallPlan,
    MinggeContentService,
    MinggeNpcService,
)
from .weapon_enchant import ROUTE as WEAPON_ENCHANT_ROUTE, WeaponEnchantService
from .attack_speed_breakthrough import (
    ROUTE as ATTACK_SPEED_BREAKTHROUGH_ROUTE,
    AttackSpeedBreakthroughService,
)
from .equipment_wash import ROUTE as EQUIPMENT_WASH_IMPORT_ROUTE, EquipmentWashImportService
from .target import TargetInspector
from .user_documents import documents_root
from .npc_bundle import NpcBundleBatchPlan, NpcBundleService


REGISTRY_NAME = "00_填写文档注册表.json"
ALLOWED_SUFFIXES = {".xlsx", ".txt", ".csv"}
INITIAL_CAMP_IDS = {"rage", "donate", "sponsor", "rebirth", "sword", "relic", "gift"}
RECYCLE_CONFIG_IDS = {"recycle_config", "material_recycle"}
GROWTH_STAGE_IDS = {"nmgf_sword", "nmgf_relic"}
EQUIPMENT_COLLECTION_IDS = {"equipment_collection"}
ITEM_SYNTHESIS_IDS = {"item_synthesis", "item_synthesis_npcs"}
MINGGE_SYSTEM_IDS = {"mingge_system"}
MINGGE_NPC_IDS = {"mingge_npc"}
MINGGE_CONTENT_IDS = {"mingge_content"}
WEAPON_ENCHANT_IDS = {"weapon_enchant"}
ATTACK_SPEED_BREAKTHROUGH_IDS = {"attack_speed_breakthrough"}
EQUIPMENT_WASH_IMPORT_IDS = {"equipment_wash_import"}
FEATURE_BY_DOCUMENT = {
    "rage": "rage",
    "donate": "donate",
    "sponsor": "sponsor",
    "rebirth": "rebirth",
    "sword": "horse",
    "relic": "relic",
    "gift": "gift",
}
PACKAGE_BY_DOCUMENT = {
    "first_pick": "xy.ops.first-pick",
    "revive_icon": "xy.ui.attr-overview",
}
SPECIALIST_GUIDANCE = {
    "layered_map": "该文件属于地图/多层传送专用事务，请使用玄渊界面施工台的地图功能预检。",
    "equipment_create": "该文件是装备生成/修改共享母表；请在“批量做装备”页中，新建使用“预检”，修改已有装备使用“预检修改”。",
    "material_create": "该文件属于批量做材料，请使用“批量做装备”页的材料预检入口。",
    "warrior_skill_upgrade": "该文件需要先由技能强化编译器生成成果包；当前请使用技能强化专项入口。",
    "monster_execution_rules": "该表由“处决测试”页直接读取并与处决本体同事务预检、安装、回滚；通用脚本配置同步不重复植入。",
    "monster_create": "该文件属于怪物批量生成，请使用“怪物库”页的“预检生成表”。",
    "seal_base": "该文件属于神印与称号双NPC专项事务，请使用“NPC编辑”页的“神印与称号双NPC”入口。",
    "title_advance": "该文件属于神印与称号双NPC专项事务，请使用“NPC编辑”页的“神印与称号双NPC”入口。",
}


class ConfigSyncError(ValueError):
    pass


@dataclass(frozen=True)
class RegisteredDocument:
    id: str
    filename: str
    consumer: str
    path: str
    sha256: str


@dataclass
class ConfigSyncPlan:
    server: str
    client: str | None
    route: str
    documents: list[RegisteredDocument] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[Any] = field(default_factory=list)
    inner_plan: Any | None = None


class ConfigSyncService:
    """Route explicitly selected user documents through registered features.

    No folder scan is performed. Direct config-sync selections must match a
    registered file. Project Overview may bind one external file to the
    registry id of the feature the user explicitly selected.
    """

    def __init__(self, platform_root: Path):
        self.root = Path(platform_root).resolve()
        self.documents_root = documents_root(self.root).resolve()
        self.registry_path = self.documents_root / REGISTRY_NAME
        self.repository = PackageRepository(self.root / "packages")
        self.repository.refresh()
        self.installer = Installer(self.repository, self.root / "backups")
        self.initial_camp = InitialCampService(self.root)
        self.king_mode = KingModeCompleteService(self.root)
        self.recycle_config = RecycleConfigService(self.root)
        self.growth_stage = GrowthStageService(self.root)
        self.equipment_collection = EquipmentCollectionService(self.root)
        self.item_synthesis = ItemSynthesisService(self.root)
        self.mingge = MingGeService(self.root)
        self.mingge_npc = MinggeNpcService(self.root)
        self.mingge_content = MinggeContentService(self.root)
        self.weapon_enchant = WeaponEnchantService(self.root)
        self.attack_speed_breakthrough = AttackSpeedBreakthroughService(self.root)
        self.equipment_wash_import = EquipmentWashImportService(self.root)
        self.npc_bundle = NpcBundleService(self.root)

    def preflight_bundle(
        self,
        source: Path,
        server: Path,
        *,
        client: Path,
        launcher: Path,
    ) -> NpcBundleBatchPlan:
        return self.npc_bundle.preflight_bundle(
            source, server, client=client, launcher=launcher,
        )

    def install_bundle(self, plan: NpcBundleBatchPlan):
        return self.npc_bundle.install_bundle(plan)

    def _registry(self) -> dict[str, dict[str, str]]:
        if not self.registry_path.is_file():
            raise ConfigSyncError(f"填写文档注册表不存在：{self.registry_path}")
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigSyncError(f"填写文档注册表读取失败：{exc}") from exc
        documents = payload.get("documents")
        if not isinstance(documents, list):
            raise ConfigSyncError("填写文档注册表缺少 documents 列表")
        result: dict[str, dict[str, str]] = {}
        for item in documents:
            if not isinstance(item, dict):
                raise ConfigSyncError("填写文档注册表包含无效记录")
            document_id = str(item.get("id", "")).strip()
            filename = str(item.get("file", "")).strip()
            consumer = str(item.get("consumer", "")).strip()
            if not document_id or not filename or not consumer:
                raise ConfigSyncError("填写文档注册表记录缺少 id、file 或 consumer")
            if filename in result:
                raise ConfigSyncError(f"填写文档注册表文件名重复：{filename}")
            result[filename] = {"id": document_id, "consumer": consumer}
        return result

    def resolve(
        self, paths: list[Path], document_id: str | None = None
    ) -> list[RegisteredDocument]:
        if not paths:
            raise ConfigSyncError("请至少选择一个配置文件")
        registry = self._registry()
        bound_entry: dict[str, str] | None = None
        if document_id is not None:
            if len(paths) != 1:
                raise ConfigSyncError("项目总览的一项功能只能绑定一个文件")
            matches = [entry for entry in registry.values() if entry["id"] == document_id]
            if len(matches) != 1:
                raise ConfigSyncError(f"未登记的功能编号：{document_id}")
            bound_entry = matches[0]
        resolved: list[RegisteredDocument] = []
        seen: set[str] = set()
        for raw in paths:
            source = Path(raw)
            if source.is_symlink():
                raise ConfigSyncError(f"禁止选择路径链接：{source}")
            path = source.resolve()
            if not path.is_file():
                raise ConfigSyncError(f"选择的文件不存在：{path}")
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                raise ConfigSyncError(f"不支持的配置文件类型：{path.name}")
            if bound_entry is None:
                entry = registry.get(path.name)
                if entry is None:
                    raise ConfigSyncError(f"文件未在 {REGISTRY_NAME} 登记：{path.name}")
            else:
                entry = bound_entry
            if path.name in seen:
                continue
            seen.add(path.name)
            data = path.read_bytes()
            resolved.append(RegisteredDocument(
                entry["id"], path.name, entry["consumer"], str(path),
                hashlib.sha256(data).hexdigest(),
            ))
        return resolved

    @staticmethod
    def _route(documents: list[RegisteredDocument]) -> str:
        ids = {item.id for item in documents}
        if ids <= INITIAL_CAMP_IDS:
            return "initial-camp-selected"
        if len(documents) == 1 and ids <= RECYCLE_CONFIG_IDS:
            return "recycle-config"
        if ids <= GROWTH_STAGE_IDS:
            return "growth-stage"
        if ids == EQUIPMENT_COLLECTION_IDS:
            return "equipment-collection"
        if ids and ids <= ITEM_SYNTHESIS_IDS:
            return "item-synthesis"
        if ids == MINGGE_SYSTEM_IDS:
            return "mingge-system"
        if ids == MINGGE_NPC_IDS:
            return NPC_ROUTE
        if ids == MINGGE_CONTENT_IDS:
            return CONTENT_ROUTE
        if ids == WEAPON_ENCHANT_IDS:
            return WEAPON_ENCHANT_ROUTE
        if ids == ATTACK_SPEED_BREAKTHROUGH_IDS:
            return ATTACK_SPEED_BREAKTHROUGH_ROUTE
        if ids == EQUIPMENT_WASH_IMPORT_IDS:
            return EQUIPMENT_WASH_IMPORT_ROUTE
        if ids == {"king_mode"}:
            return "king-mode-config"
        if ids <= set(PACKAGE_BY_DOCUMENT):
            return "package-documents"
        if len(ids) == 1 and next(iter(ids)) in SPECIALIST_GUIDANCE:
            return "specialist"
        return "incompatible"

    def preflight(
        self,
        server: Path,
        selected_paths: list[Path],
        client: Path | None = None,
        document_id: str | None = None,
    ) -> ConfigSyncPlan:
        documents: list[RegisteredDocument] = []
        plan = ConfigSyncPlan(str(Path(server).absolute()), str(Path(client).absolute()) if client else None, "unknown")
        try:
            documents = self.resolve(selected_paths, document_id=document_id)
            plan.documents = documents
            plan.route = self._route(documents)
            if plan.route == "incompatible":
                raise ConfigSyncError("所选文件属于不同安装核心，不能合并为一个事务；请分开预检和植入")
            if plan.route == "specialist":
                plan.blockers.append(SPECIALIST_GUIDANCE[documents[0].id])
                return plan
            if plan.route == "initial-camp-selected":
                features = {FEATURE_BY_DOCUMENT[item.id] for item in documents}
                inner = self.initial_camp.preflight_selected(
                    Path(server), self.documents_root, features, client,
                    operation="config-sync",
                    material_overrides={
                        filename: Path(item.path)
                        for item in documents
                        for filename, entry in self._registry().items()
                        if entry["id"] == item.id
                    },
                )
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = inner.changes
                plan.client = inner.client
                return plan
            if plan.route == "recycle-config":
                inner = self.recycle_config.preflight(
                    Path(documents[0].path), Path(server)
                )
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = inner.changes
                return plan
            if plan.route == "growth-stage":
                inner = self.growth_stage.preflight(
                    Path(server), [Path(item.path) for item in documents]
                )
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = inner.changes
                return plan
            if plan.route == "equipment-collection":
                inner = self.equipment_collection.preflight(
                    Path(documents[0].path), Path(server), client
                )
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = inner.changes
                plan.client = inner.client
                return plan
            if plan.route == "item-synthesis":
                by_id = {item.id: Path(item.path) for item in documents}
                inner = self.item_synthesis.preflight(
                    by_id.get("item_synthesis", self.item_synthesis.default_workbook),
                    Path(server),
                    by_id.get("item_synthesis_npcs", self.item_synthesis.default_npc_config),
                )
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = inner.changes
                return plan
            if plan.route == "mingge-system":
                plan.blockers.append(
                    "37号旧版命格组合路由只保留历史事务回滚；新服请分别选择40号NPC规则表或41号命格内容表。"
                )
                return plan
            if plan.route in {NPC_ROUTE, CONTENT_ROUTE}:
                service = self.mingge_npc if plan.route == NPC_ROUTE else self.mingge_content
                inner = service.preflight(Path(server), Path(documents[0].path))
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = list(inner.changes)
                return plan
            if plan.route == WEAPON_ENCHANT_ROUTE:
                inner = self.weapon_enchant.preflight(Path(server), Path(documents[0].path))
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = list(inner.changes)
                return plan
            if plan.route == ATTACK_SPEED_BREAKTHROUGH_ROUTE:
                inner = self.attack_speed_breakthrough.preflight(Path(server), Path(documents[0].path))
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = list(inner.changes)
                return plan
            if plan.route == EQUIPMENT_WASH_IMPORT_ROUTE:
                inner = self.equipment_wash_import.preflight(Path(server), Path(documents[0].path), client=client)
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = list(inner.changes)
                return plan
            if plan.route == "king-mode-config":
                inner = self.king_mode.config_apply(Path(server), client)
                plan.inner_plan = inner
                plan.blockers.extend(inner.blockers)
                plan.warnings.extend(inner.warnings)
                plan.changes = inner.changes
                plan.client = inner.client
                return plan
            packages = [PACKAGE_BY_DOCUMENT[item.id] for item in documents]
            inner = self.installer.preflight(
                Path(server), packages, {}, client_root=client,
                operation_type="config-sync",
            )
            target = TargetInspector.inspect(Path(server))
            state_path = target.root / ".xydp" / "installed.json"
            installed: set[str] = set()
            if state_path.is_file():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    installed = set(state.get("packages", {}))
                except (OSError, json.JSONDecodeError):
                    installed = set()
            if set(packages) <= installed:
                selected_targets: set[tuple[str, str]] = set()
                by_id = {item.id: item for item in documents}
                for document_id, package_id in PACKAGE_BY_DOCUMENT.items():
                    if document_id not in by_id:
                        continue
                    package = self.repository.packages[package_id]
                    registered_filename = next(
                        filename for filename, entry in self._registry().items()
                        if entry["id"] == document_id
                    )
                    matches = [
                        operation for operation in package.operations
                        if operation.get("user_document") == registered_filename
                    ]
                    if len(matches) != 1:
                        raise ConfigSyncError(f"{by_id[document_id].filename} 对应的成果包配置操作不唯一")
                    operation = matches[0]
                    selected_targets.add((str(operation.get("scope", "server")), str(operation["target"])))
                inner.changes = [
                    change for change in inner.changes
                    if (change.scope, change.relative_path) in selected_targets
                ]
                inner.package_ids = packages
                inner.package_versions = {
                    package_id: self.repository.packages[package_id].version for package_id in packages
                }
                inner.candidate_packages = [
                    package_id for package_id in packages
                    if self.repository.packages[package_id].status == "candidate"
                ]
                inner.superseded_package_ids = []
                inner.warnings.append("目标服已登记对应成果包，本次只更新所选配置文件对应的目标配置，不重装核心脚本。")
            else:
                missing = sorted(set(packages) - installed)
                inner.warnings.append(
                    "目标服未登记对应成果包，将连同必要核心首次安装：" + "、".join(missing)
                )
            inner.parameters.update({
                "selected_documents": [item.filename for item in documents],
                "selected_document_hashes": {item.filename: item.sha256 for item in documents},
            })
            plan.inner_plan = inner
            plan.warnings.extend(inner.warnings)
            plan.changes = inner.changes
            plan.client = inner.client_root
        except (OSError, ValueError, RuntimeError) as exc:
            plan.blockers.append(str(exc))
        return plan

    def install(self, plan: ConfigSyncPlan):
        if plan.blockers or plan.inner_plan is None:
            raise ConfigSyncError("脚本配置同步被阻止：\n" + "\n".join(plan.blockers))
        for document in plan.documents:
            path = Path(document.path)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != document.sha256:
                raise ConfigSyncError(f"预检后配置文件已变化，请重新预检：{document.filename}")
        if plan.route == "initial-camp-selected":
            assert isinstance(plan.inner_plan, InitialCampPlan)
            return self.initial_camp.install(plan.inner_plan)
        if plan.route == "recycle-config":
            assert isinstance(plan.inner_plan, RecycleConfigPlan)
            return self.recycle_config.install(plan.inner_plan)
        if plan.route == "growth-stage":
            assert isinstance(plan.inner_plan, GrowthStagePlan)
            return self.growth_stage.install(plan.inner_plan)
        if plan.route == "equipment-collection":
            assert isinstance(plan.inner_plan, EquipmentCollectionPlan)
            return self.equipment_collection.install(plan.inner_plan)
        if plan.route == "item-synthesis":
            assert isinstance(plan.inner_plan, ItemSynthesisPlan)
            return self.item_synthesis.install(plan.inner_plan)
        if plan.route == "mingge-system":
            raise ConfigSyncError("旧mingge-system组合路由已停止新安装，只允许按历史事务回滚")
        if plan.route == NPC_ROUTE:
            assert isinstance(plan.inner_plan, DualInstallPlan)
            return self.mingge_npc.install(plan.inner_plan)
        if plan.route == CONTENT_ROUTE:
            assert isinstance(plan.inner_plan, DualInstallPlan)
            return self.mingge_content.install(plan.inner_plan)
        if plan.route == WEAPON_ENCHANT_ROUTE:
            return self.weapon_enchant.install(plan.inner_plan)
        if plan.route == ATTACK_SPEED_BREAKTHROUGH_ROUTE:
            return self.attack_speed_breakthrough.install(plan.inner_plan)
        if plan.route == EQUIPMENT_WASH_IMPORT_ROUTE:
            return self.equipment_wash_import.install(plan.inner_plan)
        if plan.route == "king-mode-config":
            assert isinstance(plan.inner_plan, FlowPlan)
            return self.king_mode.apply(plan.inner_plan, yes=True)
        assert isinstance(plan.inner_plan, InstallPlan)
        return self.installer.install(plan.inner_plan)

    def rollback(self, server: Path, transaction_id: str, route: str) -> str:
        if route == "npc-bundle":
            self.npc_bundle.rollback_bundle(server, transaction_id)
            return transaction_id
        if route == "king-mode-config":
            return self.king_mode.rollback(server, yes=True)
        if route == "recycle-config":
            return self.recycle_config.rollback(server, transaction_id)
        if route == "equipment-collection":
            return self.equipment_collection.rollback(server, transaction_id)
        if route == "item-synthesis":
            return self.item_synthesis.rollback(server, transaction_id)
        if route == "mingge-system":
            return self.mingge.rollback(server, transaction_id)
        if route == NPC_ROUTE:
            return self.mingge_npc.rollback(server, transaction_id).transaction_id
        if route == CONTENT_ROUTE:
            return self.mingge_content.rollback(server, transaction_id).transaction_id
        if route == WEAPON_ENCHANT_ROUTE:
            return self.weapon_enchant.rollback(server, transaction_id).transaction_id
        if route == ATTACK_SPEED_BREAKTHROUGH_ROUTE:
            return self.attack_speed_breakthrough.rollback(server, transaction_id).transaction_id
        if route == EQUIPMENT_WASH_IMPORT_ROUTE:
            return self.equipment_wash_import.rollback(server, transaction_id).transaction_id
        self.installer.rollback(server, transaction_id)
        return transaction_id
