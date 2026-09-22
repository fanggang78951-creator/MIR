from __future__ import annotations

import json
import hashlib
import os
import threading
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .project_overview_gui import ProjectOverviewMixin
from .importer import PackageImporter
from .installer import InstallError, InstallPlan, Installer
from .optional_scripts import OptionalScriptLibrary
from .optional_presets import OptionalPresetService
from .repository import PackageRepository
from .resident import ResidentService
from .runtime import platform_root
from .storage_paths import workbench_pak_export_jobs_root
from .target import TargetInspector
from .equipment_bridge import EquipmentBridge, EquipmentUiState
from .npc_editor import NpcDraft, NpcEditorError, KingModeNpcConfig, create_package as create_npc_package, direct_install, direct_preflight, king_mode_preflight, load_draft, save_draft, scan_npc_appearances
from .king_mode_flow import KingModeFlowError
from .king_mode_complete import KingModeCompleteService
from .execution_lab import ExecutionLabService
from .initial_camp import InitialCampService
from .seal_title import SealTitleService
from .config_sync import ConfigSyncService
from .monster_library import (
    MonsterLibraryBridge,
    MonsterLibraryService,
    default_generator_login_dir,
)
from .monster_login_integration import verify_custom_monster_login
from .monster_workbook import MonsterWorkbookService
from .recycle_config import RecycleConfigService
from .equipment_aura import EquipmentAuraError, EquipmentAuraService
from .mingge_native import generate_native_candidates, validate_native_output_container
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
from .mingge_dual import MinggeContentService, MinggeNpcService


TAB_TITLES = ("项目总览", "目标管理", "成果包库", "预检报告", "安装历史/回滚", "开发者包导入", "脚本配置同步", "命格", "非常驻脚本", "装备回收", "处决测试", "NPC编辑", "批量做装备", "装备光环", "怪物库")


@dataclass(frozen=True)
class MonsterEngineUiSummary:
    ini_count: int
    dependency_count: int
    target_effect_entry_count: int
    login_status: str
    next_step: str


class PlatformApp(ProjectOverviewMixin, tk.Tk):
    MONSTER_TREE_COLUMN_TITLES = (
        "预览", "库编号", "怪物名称", "引擎模式", "Appr",
        "闭包状态", "依赖数量", "登录器要求", "说明",
    )

    def __init__(self, root_path: Path | None = None):
        super().__init__()
        self.platform_root = (root_path or platform_root()).resolve()
        self.repository = PackageRepository(self.platform_root / "packages")
        self.installer = Installer(self.repository, self.platform_root / "backups")
        self.resident = ResidentService(self.repository, self.platform_root / "backups")
        self.optional_scripts = OptionalScriptLibrary(self.platform_root)
        self.optional_presets = OptionalPresetService(self.platform_root)
        self.equipment = EquipmentBridge(self.platform_root)
        self.king_mode_flow = KingModeCompleteService(self.platform_root)
        self.execution_lab = ExecutionLabService(self.platform_root)
        self.initial_camp = InitialCampService(self.platform_root)
        self.seal_title = SealTitleService(self.platform_root)
        self.config_sync = ConfigSyncService(self.platform_root)
        self.mingge_npc = MinggeNpcService(self.platform_root)
        self.mingge_content = MinggeContentService(self.platform_root)
        self.monster_library = MonsterLibraryBridge(self.platform_root)
        self.monster_workbook = MonsterWorkbookService(self.platform_root)
        self.recycle_config = RecycleConfigService(self.platform_root)
        self.equipment_aura = EquipmentAuraService(self.platform_root)
        self.current_plan: InstallPlan | None = None
        self.current_equipment_plan = None
        self.current_equipment_create_plan = None
        self.current_equipment_update_plan = None
        self.current_king_mode_flow_plan = None
        self.current_execution_plan = None
        self.current_monster_plan = None
        self.current_monster_workbook_plan = None
        self.current_recycle_plan = None
        self.current_equipment_aura_plan = None
        self._equipment_graphics_busy = False
        self.title("玄渊翎风成果植入平台")
        self.geometry("1120x720")
        self.minsize(900, 600)
        self.server_var = tk.StringVar()
        self.client_var = tk.StringVar()
        self.params_var = tk.StringVar(value="{}")
        self.show_candidate_var = tk.BooleanVar(value=False)
        self.execution_server_var = tk.StringVar()
        self.execution_confirm_test_var = tk.BooleanVar(value=False)
        equipment_state = EquipmentUiState(workbook=str(self.equipment.default_workbook))
        self.equipment_server_var = tk.StringVar(value=equipment_state.server_root)
        self.equipment_client_var = tk.StringVar(value=equipment_state.client_data)
        self.equipment_workbook_var = tk.StringVar(value=equipment_state.workbook)
        self.equipment_material_workbook_var = tk.StringVar(value=str(self.equipment.default_material_workbook))
        # 生成与修改共用唯一装备母表；保留旧属性名兼容历史代码。
        self.equipment_update_workbook_var = self.equipment_workbook_var
        self.equipment_hint_workbook_var = tk.StringVar(value=str(self.equipment.default_hint_workbook))
        self.equipment_search_var = tk.StringVar()
        self.equipment_transaction_var = tk.StringVar()
        self.equipment_graphics_config_var = tk.StringVar(
            value=str(self.platform_root / "所需材料表格汇总" / "44_装备素材替换.json")
        )
        self.equipment_graphics_receipt_var = tk.StringVar()
        self.monster_donor_db_var = tk.StringVar(value=r"E:\MirServer明月\Mud2\DB\ApexM2.DB")
        self.monster_donor_wzl_var = tk.StringVar(value=r"E:\明月客户端\data")
        self.monster_donor_pak_var = tk.StringVar(value=r"E:\明月沉默\mycm\data")
        self.monster_donor_rules_var = tk.StringVar(value=r"E:\MirServer明月\登录器\pak.txt")
        self.monster_server_var = tk.StringVar(value=r"D:\MirServer")
        self.monster_client_var = tk.StringVar(value=r"E:\11周年\data")
        self.monster_sidecar_var = tk.StringVar(value=str(workbench_pak_export_jobs_root(self.platform_root)))
        self.monster_workbook_var = tk.StringVar(value=str(self.monster_workbook.default_workbook))
        self.monster_status_var = tk.StringVar(value="可植入")
        self.monster_filter_var = tk.StringVar()
        self.monster_transaction_var = tk.StringVar()
        self.monster_preview_images = {}
        self.npc_client_var = self.client_var
        self.npc_server_var = self.server_var
        self.npc_package_id_var = tk.StringVar(value="xy.npc.new-npc")
        self.npc_display_name_var = tk.StringVar(value="新NPC")
        self.npc_script_path_var = tk.StringVar(value="玄渊NPC/新NPC")
        self.npc_map_var = tk.StringVar(value="0")
        self.npc_x_var = tk.StringVar(value="34")
        self.npc_y_var = tk.StringVar(value="30")
        self.npc_visible_name_var = tk.StringVar(value="新NPC")
        self.npc_appearance_var = tk.StringVar(value="0")
        self.npc_patch_library_var = tk.StringVar(value="Npc")
        self.npc_patch_index_var = tk.StringVar(value="0")
        self.npc_patch_source_var = tk.StringVar()
        self.npc_patch_status_var = tk.StringVar(value="manual-required")
        self.npc_filter_var = tk.StringVar()
        self.npc_appearance_rows = []
        self.current_npc_direct_plan = None
        self.current_king_mode_npc_plan = None
        self.current_initial_camp_plan = None
        self.current_seal_title_plan = None
        self.current_config_sync_plan = None
        self.current_config_sync_bundle_plan = None
        self.config_sync_paths: list[Path] = []
        self.config_sync_document_id: str | None = None
        self.config_sync_bundle_source_var = tk.StringVar()
        self.config_sync_bundle_launcher_var = tk.StringVar(
            value=r"D:\素材文件夹\LFM2[20260707]\登录器"
        )
        self.config_sync_transaction_var = tk.StringVar()
        self.config_sync_route_var = tk.StringVar()
        self.mingge_native_workbook_var = tk.StringVar(
            value=str(self.platform_root / "所需材料表格汇总" / "39_命格P3颜色导入测试.xlsx")
        )
        self.mingge_native_output_var = tk.StringVar(
            value=str(self.platform_root / "outputs" / "mingge-native-candidate")
        )
        self.mingge_native_server_var = tk.StringVar(value=r"D:\MirServer")
        self.mingge_native_candidate_var = tk.StringVar(value="tiebi-defence-5-p1")
        self.mingge_native_transaction_var = tk.StringVar()
        self.current_mingge_native_test_plan = None
        self.mingge_native_p2_candidate_var = tk.StringVar(value="tiebi-vitality-p2")
        self.mingge_native_p2_transaction_var = tk.StringVar()
        self.current_mingge_native_p2_test_plan = None
        self.mingge_native_p3_workbook_var = tk.StringVar(
            value=str(self.platform_root / "所需材料表格汇总" / "39_命格P3颜色导入测试.xlsx")
        )
        self.mingge_native_p3_transaction_var = tk.StringVar()
        self.current_mingge_native_p3_color_test_plan = None
        self.mingge_dual_server_var = tk.StringVar(value=r"D:\MirServer")
        self.mingge_npc_workbook_var = tk.StringVar(
            value=str(self.platform_root / "所需材料表格汇总" / "40_命格NPC规则.xlsx")
        )
        self.mingge_content_workbook_var = tk.StringVar(
            value=str(self.platform_root / "所需材料表格汇总" / "41_命格内容与多色属性.xlsx")
        )
        self.mingge_npc_transaction_var = tk.StringVar()
        self.mingge_content_transaction_var = tk.StringVar()
        self.current_mingge_npc_plan = None
        self.current_mingge_content_plan = None
        self.initial_camp_materials_var = tk.StringVar(value=str(self.platform_root / "所需材料表格汇总"))
        self.recycle_workbook_var = tk.StringVar(value=str(self.recycle_config.default_workbook))
        self.recycle_search_var = tk.StringVar()
        self.recycle_transaction_var = tk.StringVar()
        self.aura_server_var = tk.StringVar(value=r"D:\MirServer")
        self.aura_client_var = tk.StringVar(value=r"E:\11周年")
        self.aura_login_var = tk.StringVar(value=r"D:\素材文件夹\LFM2[20260707]\登录器")
        self.aura_workbook_var = tk.StringVar(value=str(self.platform_root / "所需材料表格汇总" / "36_装备范围光环.xlsx"))
        self.aura_search_var = tk.StringVar(value="灵玉")
        self.aura_equipment_var = tk.StringVar()
        self.aura_style_var = tk.StringVar(value="style01")
        self.aura_multiplier_var = tk.StringVar(value="2")
        self.aura_interval_var = tk.StringVar(value="1")
        self.aura_priority_var = tk.StringVar(value="100")
        self.aura_transaction_var = tk.StringVar()
        self.aura_preview_image = None
        self.notebook = ttk.Notebook(self); self.notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.tabs = {title: ttk.Frame(self.notebook) for title in TAB_TITLES}
        for title, frame in self.tabs.items(): self.notebook.add(frame, text=title)
        self._build_target(); self._build_packages(); self._build_report(); self._build_history(); self._build_import(); self._build_config_sync(); self._build_mingge_native(); self._build_optional_scripts(); self._build_recycle(); self._build_execution_lab(); self._build_npc_editor(); self._build_equipment(); self._build_equipment_aura(); self._build_monster_library()
        self._build_project_overview()
        self.refresh_packages()
        self.refresh_optional_scripts()

    def _row(self, parent, label, variable, command):
        frame = ttk.Frame(parent); frame.pack(fill="x", padx=12, pady=8)
        ttk.Label(frame, text=label, width=14).pack(side="left")
        ttk.Entry(frame, textvariable=variable).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(frame, text="浏览", command=command).pack(side="left")

    def _build_target(self):
        tab = self.tabs["目标管理"]
        ttk.Label(tab, text="选择待植入的翎风服务端；平台不会默认使用 D:\\MirServer。", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=12, pady=12)
        self._row(tab, "服务端根目录", self.server_var, lambda: self._choose_dir(self.server_var))
        self._row(tab, "客户端根目录", self.client_var, lambda: self._choose_dir(self.client_var))
        ttk.Button(tab, text="识别目标", command=self.inspect_target).pack(anchor="w", padx=26, pady=8)
        self.target_result = tk.Text(tab, height=18, wrap="word"); self.target_result.pack(fill="both", expand=True, padx=12, pady=8)
        flow = ttk.Labelframe(tab, text="国王模式完整一键安装（初始端）")
        flow.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Button(flow, text="一键安装国王模式", command=self.king_mode_one_click_install).pack(side="left", padx=6, pady=6)
        ttk.Button(flow, text="预检完整安装", command=self.king_mode_flow_preflight).pack(side="left", padx=6, pady=6)
        ttk.Button(flow, text="读取并应用配置TXT", command=self.king_mode_config_apply).pack(side="left", padx=6, pady=6)
        ttk.Button(flow, text="回滚最近安装", command=self.king_mode_rollback).pack(side="left", padx=6, pady=6)
        ttk.Button(flow, text="打开配置文件夹", command=self.open_king_mode_config).pack(side="left", padx=6, pady=6)
        self.king_mode_flow_report = tk.Text(flow, height=6, wrap="none")
        self.king_mode_flow_report.pack(fill="x", padx=6, pady=(0, 6))

    def _build_packages(self):
        tab = self.tabs["成果包库"]
        toolbar = ttk.Frame(tab); toolbar.pack(fill="x", padx=8, pady=8)
        ttk.Checkbutton(toolbar, text="显示候选包", variable=self.show_candidate_var, command=self.refresh_packages).pack(side="left")
        ttk.Button(toolbar, text="刷新", command=self.refresh_packages).pack(side="left", padx=6)
        ttk.Label(toolbar, text="安装参数(JSON)：").pack(side="left", padx=(20, 4))
        ttk.Entry(toolbar, textvariable=self.params_var).pack(side="left", fill="x", expand=True)
        self.package_tree = ttk.Treeview(tab, columns=("name", "version", "status", "bundle"), show="headings", selectmode="extended")
        for key, title, width in (("name", "名称", 280), ("version", "版本", 90), ("status", "状态", 90), ("bundle", "套件", 180)):
            self.package_tree.heading(key, text=title); self.package_tree.column(key, width=width)
        self.package_tree.pack(fill="both", expand=True, padx=8, pady=8)
        actions = ttk.Frame(tab); actions.pack(fill="x", padx=8, pady=8)
        ttk.Button(actions, text="生成预检报告", command=self.preflight).pack(side="left")
        ttk.Button(actions, text="确认安装", command=self.install).pack(side="left", padx=8)
        ttk.Button(actions, text="一键安装常驻基础", command=self.install_resident_base).pack(side="left", padx=8)

    def _build_report(self):
        self.report = tk.Text(self.tabs["预检报告"], wrap="none")
        self.report.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_history(self):
        tab = self.tabs["安装历史/回滚"]
        ttk.Button(tab, text="刷新历史", command=self.refresh_history).pack(anchor="w", padx=8, pady=8)
        self.history = ttk.Treeview(tab, columns=("time", "packages"), show="headings")
        self.history.heading("time", text="事务时间"); self.history.heading("packages", text="成果包")
        self.history.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(tab, text="回滚选中事务", command=self.rollback_selected).pack(anchor="w", padx=8, pady=8)

    def _build_import(self):
        tab = self.tabs["开发者包导入"]
        ttk.Label(tab, text="导入声明式 .xypkg；包内脚本不会被执行。", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=12, pady=12)
        ttk.Button(tab, text="选择并导入成果包", command=self.import_package).pack(anchor="w", padx=12, pady=8)
        self.import_result = tk.Text(tab, height=20); self.import_result.pack(fill="both", expand=True, padx=12, pady=8)

    def _build_config_sync(self):
        tab = self.tabs["脚本配置同步"]
        ttk.Label(
            tab,
            text="项目总览可将任意位置的文件绑定到所选功能；本页直接选择仍按登记文件名识别。",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 6))
        toolbar = ttk.Frame(tab); toolbar.pack(fill="x", padx=12, pady=6)
        ttk.Button(toolbar, text="选择配置文件", command=self.choose_config_sync_files).pack(side="left")
        ttk.Button(toolbar, text="打开汇总目录", command=lambda: os.startfile(self.config_sync.documents_root)).pack(side="left", padx=8)
        ttk.Button(toolbar, text="清空选择", command=self.clear_config_sync_files).pack(side="left")
        ttk.Button(toolbar, text="预检所选文件", command=self.config_sync_preflight).pack(side="left", padx=(20, 8))
        ttk.Button(toolbar, text="确认植入", command=self.config_sync_install).pack(side="left")
        ttk.Button(toolbar, text="回滚本次植入", command=self.config_sync_rollback).pack(side="left", padx=8)
        self.config_sync_selected = tk.Listbox(tab, height=5, selectmode="extended")
        self.config_sync_selected.pack(fill="x", padx=12, pady=6)
        bundle = ttk.Labelframe(tab, text="NPC 批量包")
        bundle.pack(fill="x", padx=12, pady=(6, 4))
        source = ttk.Frame(bundle); source.pack(fill="x", padx=6, pady=(6, 3))
        ttk.Label(source, text="ZIP/目录", width=10).pack(side="left")
        ttk.Entry(source, textvariable=self.config_sync_bundle_source_var).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(source, text="选择ZIP", command=self.choose_config_sync_bundle_zip).pack(side="left")
        ttk.Button(source, text="选择目录", command=self.choose_config_sync_bundle_directory).pack(side="left", padx=(6, 0))
        launcher = ttk.Frame(bundle); launcher.pack(fill="x", padx=6, pady=3)
        ttk.Label(launcher, text="登录器", width=10).pack(side="left")
        ttk.Entry(launcher, textvariable=self.config_sync_bundle_launcher_var).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(
            launcher, text="浏览",
            command=lambda: self._choose_dir(self.config_sync_bundle_launcher_var),
        ).pack(side="left")
        actions = ttk.Frame(bundle); actions.pack(fill="x", padx=6, pady=(3, 6))
        ttk.Button(actions, text="统一预检", command=self.config_sync_bundle_preflight).pack(side="left")
        ttk.Button(actions, text="确认批量安装", command=self.config_sync_bundle_install).pack(side="left", padx=8)
        ttk.Label(
            actions,
            text="一次预检、一个总事务；安装后由你重载/重启M2验收。",
            foreground="#7a4b00",
        ).pack(side="left", padx=8)
        transaction = ttk.Frame(tab); transaction.pack(fill="x", padx=12, pady=4)
        ttk.Label(transaction, text="最近事务", width=10).pack(side="left")
        ttk.Entry(transaction, textvariable=self.config_sync_transaction_var, state="readonly").pack(side="left", fill="x", expand=True)
        self.config_sync_report = tk.Text(tab, wrap="none")
        self.config_sync_report.pack(fill="both", expand=True, padx=12, pady=(4, 10))

    def _build_mingge_native_legacy(self):
        tab = self.tabs["命格原生多色"]
        ttk.Label(
            tab,
            text="V2只填写中文具体部位、中文属性、数值与显示片段；编译为离线候选，不写服务端、客户端或数据库。",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 4))
        ttk.Label(
            tab,
            text="推荐使用两页中文简表：只填写装备、部位、命格名称、颜色和最多三项属性；编号、顺序、单位与显示片段由平台自动生成。旧表仍可读取。",
        ).pack(anchor="w", padx=12, pady=(0, 8))
        self._row(
            tab,
            "命格配置表格",
            self.mingge_native_workbook_var,
            lambda: self._choose_file(self.mingge_native_workbook_var, [("Excel 工作簿", "*.xlsx")]),
        )
        self._row(
            tab,
            "候选输出目录",
            self.mingge_native_output_var,
            lambda: self._choose_dir(self.mingge_native_output_var),
        )
        actions = ttk.Frame(tab)
        actions.pack(fill="x", padx=12, pady=8)
        ttk.Button(actions, text="生成离线文件", command=self.mingge_native_generate).pack(side="left")
        ttk.Button(actions, text="打开表格", command=self.open_mingge_native_workbook).pack(side="left", padx=8)
        ttk.Button(actions, text="打开输出目录", command=self.open_mingge_native_output).pack(side="left")
        test = ttk.Labelframe(tab, text="P1隔离游戏验收（只允许防御+5黄金样本）")
        test.pack(fill="x", padx=12, pady=(4, 8))
        self._row(test, "服务端根目录", self.mingge_native_server_var, lambda: self._choose_dir(self.mingge_native_server_var))
        candidate = ttk.Frame(test); candidate.pack(fill="x", padx=12, pady=4)
        ttk.Label(candidate, text="隔离候选ID", width=14).pack(side="left")
        ttk.Entry(candidate, textvariable=self.mingge_native_candidate_var).pack(side="left", fill="x", expand=True, padx=6)
        transaction = ttk.Frame(test); transaction.pack(fill="x", padx=12, pady=4)
        ttk.Label(transaction, text="最近P1事务", width=14).pack(side="left")
        ttk.Entry(transaction, textvariable=self.mingge_native_transaction_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(transaction, text="P1预检", command=self.mingge_native_test_preflight).pack(side="left")
        ttk.Button(transaction, text="安装隔离测试", command=self.mingge_native_test_install).pack(side="left", padx=8)
        ttk.Button(transaction, text="精确回滚", command=self.mingge_native_test_rollback).pack(side="left")
        p2 = ttk.Labelframe(tab, text="P2三属性隔离验收（防御+5、生命值+100、魔法值+100）")
        p2.pack(fill="x", padx=12, pady=(0, 8))
        p2_candidate = ttk.Frame(p2); p2_candidate.pack(fill="x", padx=12, pady=4)
        ttk.Label(p2_candidate, text="固定P2候选ID", width=14).pack(side="left")
        ttk.Entry(p2_candidate, textvariable=self.mingge_native_p2_candidate_var, state="readonly").pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(
            p2_candidate,
            text="防御已实测；生命值、魔法值依据官网规则，待本端游戏验收。",
            foreground="#8a4f00",
        ).pack(side="left", padx=6)
        p2_transaction = ttk.Frame(p2); p2_transaction.pack(fill="x", padx=12, pady=4)
        ttk.Label(p2_transaction, text="最近P2事务", width=14).pack(side="left")
        ttk.Entry(p2_transaction, textvariable=self.mingge_native_p2_transaction_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(p2_transaction, text="P2预检", command=self.mingge_native_p2_test_preflight).pack(side="left")
        ttk.Button(p2_transaction, text="安装三属性测试", command=self.mingge_native_p2_test_install).pack(side="left", padx=8)
        ttk.Button(p2_transaction, text="精确回滚文件", command=self.mingge_native_p2_test_rollback).pack(side="left")
        p2_recovery = ttk.Frame(p2); p2_recovery.pack(fill="x", padx=12, pady=(0, 4))
        ttk.Label(p2_recovery, text="事务安全", width=14).pack(side="left")
        ttk.Button(p2_recovery, text="只读检查封印/状态", command=self.mingge_native_p2_transaction_inspect).pack(side="left", padx=(6, 8))
        ttk.Button(p2_recovery, text="中断事务恢复回滚", command=self.mingge_native_p2_transaction_recover_rollback).pack(side="left")
        ttk.Label(p2_recovery, text="恢复入口只接受HMAC封印事务；未知文件漂移时保持零覆盖。", foreground="#8a4f00").pack(side="left", padx=10)
        p3 = ttk.Labelframe(tab, text="命格快速安装（地图3“龙魂觉醒”）")
        p3.pack(fill="x", padx=12, pady=(0, 8))
        self._row(
            p3,
            "命格配置表",
            self.mingge_native_p3_workbook_var,
            lambda: self._choose_file(self.mingge_native_p3_workbook_var, [("Excel 工作簿", "*.xlsx")]),
        )
        p3_transaction = ttk.Frame(p3); p3_transaction.pack(fill="x", padx=12, pady=4)
        ttk.Label(p3_transaction, text="最近安装事务", width=14).pack(side="left")
        ttk.Entry(p3_transaction, textvariable=self.mingge_native_p3_transaction_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(p3_transaction, text="检查配置", command=self.mingge_native_p3_color_test_preflight).pack(side="left")
        ttk.Button(p3_transaction, text="安装到龙魂觉醒", command=self.mingge_native_p3_color_test_install).pack(side="left", padx=8)
        ttk.Button(p3_transaction, text="恢复安装前文件", command=self.mingge_native_p3_color_test_rollback).pack(side="left")
        ttk.Label(
            p3,
            text="编辑并保存表格后可直接安装，平台会自动检查；恢复文件不会修改已经写入装备实例的最后一次命格。",
            foreground="#8a4f00",
        ).pack(anchor="w", padx=18, pady=(0, 4))
        self.mingge_native_report = tk.Text(tab, wrap="none")
        self.mingge_native_report.pack(fill="both", expand=True, padx=12, pady=(4, 10))

    def _build_mingge_native(self):
        tab = self.tabs["命格"]
        ttk.Label(tab, text="命格双包：NPC规则与命格内容完全独立，可按任意顺序注入和单独回滚。", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        ttk.Label(tab, text="平台只接入目标服现有NPC，不生成或替换NPC布局；未安装内容包时，洗练会先停止且不扣费。", foreground="#8a4f00").pack(anchor="w", padx=12, pady=(0, 6))
        self._row(tab, "服务端根目录", self.mingge_dual_server_var, lambda: self._choose_dir(self.mingge_dual_server_var))

        npc = ttk.Labelframe(tab, text="命格NPC规则包（xy.optional.mingge-npc）")
        npc.pack(fill="x", padx=12, pady=(4, 6))
        self._row(npc, "NPC规则表格", self.mingge_npc_workbook_var, lambda: self._choose_file(self.mingge_npc_workbook_var, [("Excel 工作簿", "*.xlsx")]))
        npc_actions = ttk.Frame(npc)
        npc_actions.pack(fill="x", padx=12, pady=4)
        ttk.Button(npc_actions, text="打开表格", command=lambda: self._open_path(Path(self.mingge_npc_workbook_var.get().strip()))).pack(side="left")
        ttk.Button(npc_actions, text="检查配置", command=self.mingge_npc_preflight).pack(side="left", padx=6)
        ttk.Button(npc_actions, text="查看修改计划", command=lambda: self.mingge_npc_preflight(False)).pack(side="left")
        ttk.Button(npc_actions, text="确认注入", command=self.mingge_npc_install).pack(side="left", padx=6)
        ttk.Label(npc_actions, text="事务号").pack(side="left", padx=(12, 4))
        ttk.Entry(npc_actions, textvariable=self.mingge_npc_transaction_var, width=24).pack(side="left")
        ttk.Button(npc_actions, text="独立回滚", command=self.mingge_npc_rollback).pack(side="left", padx=6)

        content = ttk.Labelframe(tab, text="命格内容包（xy.optional.mingge-content）")
        content.pack(fill="x", padx=12, pady=(0, 6))
        self._row(content, "命格内容表格", self.mingge_content_workbook_var, lambda: self._choose_file(self.mingge_content_workbook_var, [("Excel 工作簿", "*.xlsx")]))
        content_actions = ttk.Frame(content)
        content_actions.pack(fill="x", padx=12, pady=4)
        ttk.Button(content_actions, text="打开表格", command=lambda: self._open_path(Path(self.mingge_content_workbook_var.get().strip()))).pack(side="left")
        ttk.Button(content_actions, text="检查配置", command=self.mingge_content_preflight).pack(side="left", padx=6)
        ttk.Button(content_actions, text="查看修改计划", command=lambda: self.mingge_content_preflight(False)).pack(side="left")
        ttk.Button(content_actions, text="确认注入", command=self.mingge_content_install).pack(side="left", padx=6)
        ttk.Label(content_actions, text="事务号").pack(side="left", padx=(12, 4))
        ttk.Entry(content_actions, textvariable=self.mingge_content_transaction_var, width=24).pack(side="left")
        ttk.Button(content_actions, text="独立回滚", command=self.mingge_content_rollback).pack(side="left", padx=6)

        preview = ttk.Labelframe(tab, text="原生多色实时文本预览")
        preview.pack(fill="x", padx=12, pady=(0, 6))
        self.mingge_content_preview = tk.Text(preview, height=4, wrap="word")
        self.mingge_content_preview.pack(fill="x", padx=8, pady=6)
        self.mingge_native_report = tk.Text(tab, wrap="none")
        self.mingge_native_report.pack(fill="both", expand=True, padx=12, pady=(4, 10))

    @staticmethod
    def _dual_plan_summary(plan):
        return {
            "路由": plan.route,
            "包ID": plan.package_id,
            "计划号": plan.plan_id,
            "服务端": str(plan.server_root),
            "工作簿": str(plan.workbook),
            "阻止项": list(plan.blockers),
            "提醒": list(plan.warnings),
            "修改计划": [
                {"文件": item.relative_path, "类型": item.kind, "操作": "新增" if item.before is None else "更新"}
                for item in plan.changes
            ],
        }

    def _render_mingge_preview(self, plan):
        widget = self.mingge_content_preview
        widget.delete("1.0", "end")
        colors = {
            31: "#77E6E6", 69: "#66A8FF", 147: "#D2A6FF", 239: "#A7F0C0",
            249: "#FF7272", 250: "#75E875", 251: "#F7B7FF", 252: "#78B7FF", 255: "#D0D0D0",
        }
        for name, segments in plan.previews[:8]:
            widget.insert("end", f"{name}：")
            for text_value, color_id in segments:
                tag = f"mg-color-{color_id}"
                widget.tag_configure(tag, foreground=colors.get(color_id, "#dcdcdc"))
                widget.insert("end", text_value, tag)
            widget.insert("end", "\n")

    def mingge_npc_preflight(self, show_success=True):
        try:
            plan = self.mingge_npc.preflight(Path(self.mingge_dual_server_var.get().strip()), Path(self.mingge_npc_workbook_var.get().strip()))
            self.current_mingge_npc_plan = plan
            self._write(self.mingge_native_report, json.dumps(self._dual_plan_summary(plan), ensure_ascii=False, indent=2))
            if show_success:
                messagebox.showinfo("NPC规则检查完成", "配置已读取；有阻止项时不会写入。")
            return plan
        except Exception as exc:
            messagebox.showerror("NPC规则检查失败", str(exc))
            return None

    def mingge_content_preflight(self, show_success=True):
        try:
            plan = self.mingge_content.preflight(Path(self.mingge_dual_server_var.get().strip()), Path(self.mingge_content_workbook_var.get().strip()))
            self.current_mingge_content_plan = plan
            self._render_mingge_preview(plan)
            self._write(self.mingge_native_report, json.dumps(self._dual_plan_summary(plan), ensure_ascii=False, indent=2))
            if show_success:
                messagebox.showinfo("命格内容检查完成", "配置已读取，多色文本已在页面预览。")
            return plan
        except Exception as exc:
            messagebox.showerror("命格内容检查失败", str(exc))
            return None

    def mingge_npc_install(self):
        plan = self.mingge_npc_preflight(show_success=False)
        if plan is None or plan.blockers or not messagebox.askyesno("确认注入NPC规则包", "只写入NPC规则包及公共接口受管块，继续吗？"):
            return None
        try:
            receipt = self.mingge_npc.install(plan)
            self.mingge_npc_transaction_var.set(receipt.transaction_id)
            self._write(self.mingge_native_report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2, default=str))
            return receipt
        except Exception as exc:
            messagebox.showerror("NPC规则包注入失败", str(exc))
            return None

    def mingge_content_install(self):
        plan = self.mingge_content_preflight(show_success=False)
        if plan is None or plan.blockers or not messagebox.askyesno("确认注入命格内容包", "只写入命格内容、显示和重算受管块，继续吗？"):
            return None
        try:
            receipt = self.mingge_content.install(plan)
            self.mingge_content_transaction_var.set(receipt.transaction_id)
            self._write(self.mingge_native_report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2, default=str))
            return receipt
        except Exception as exc:
            messagebox.showerror("命格内容包注入失败", str(exc))
            return None

    def mingge_npc_rollback(self):
        try:
            receipt = self.mingge_npc.rollback(Path(self.mingge_dual_server_var.get().strip()), self.mingge_npc_transaction_var.get().strip())
            self._write(self.mingge_native_report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2, default=str))
            return receipt
        except Exception as exc:
            messagebox.showerror("NPC规则包回滚失败", str(exc))
            return None

    def mingge_content_rollback(self):
        try:
            receipt = self.mingge_content.rollback(Path(self.mingge_dual_server_var.get().strip()), self.mingge_content_transaction_var.get().strip())
            self._write(self.mingge_native_report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2, default=str))
            return receipt
        except Exception as exc:
            messagebox.showerror("命格内容包回滚失败", str(exc))
            return None

    def mingge_native_generate(self):
        try:
            workbook = Path(self.mingge_native_workbook_var.get().strip())
            output = Path(self.mingge_native_output_var.get().strip())
            receipt = generate_native_candidates(
                workbook,
                output,
                allowed_output_root=self.platform_root / "outputs",
            )
            self._write(
                self.mingge_native_report,
                json.dumps(asdict(receipt), ensure_ascii=False, indent=2),
            )
            messagebox.showinfo(
                "候选生成完成",
                f"已生成 {len(receipt.candidate_ids)} 个离线候选。\n未写服务端、客户端或数据库。",
            )
            return receipt
        except Exception as exc:
            messagebox.showerror("候选生成失败", str(exc))
            return None

    def open_mingge_native_workbook(self):
        try:
            os.startfile(str(Path(self.mingge_native_workbook_var.get().strip())))
        except Exception as exc:
            messagebox.showerror("打开表格失败", str(exc))

    def open_mingge_native_output(self):
        try:
            output = Path(self.mingge_native_output_var.get().strip())
            output = validate_native_output_container(
                output,
                allowed_output_root=self.platform_root / "outputs",
            )
            output.mkdir(parents=True, exist_ok=True)
            os.startfile(str(output))
        except Exception as exc:
            messagebox.showerror("打开输出目录失败", str(exc))

    @staticmethod
    def _mingge_native_test_plan_summary(plan) -> dict:
        return {
            "operation": "mingge-native-p1-test",
            "plan_id": plan.plan_id,
            "candidate_id": plan.candidate_id,
            "workbook": str(plan.workbook),
            "workbook_sha256": plan.workbook_sha256,
            "server": str(plan.server_root),
            "engine_version": plan.engine_version,
            "engine_sha256": plan.engine_sha256,
            "blockers": list(plan.blockers),
            "warnings": list(plan.warnings),
            "changes": [
                {
                    "relative_path": item.relative_path,
                    "path": str(item.path),
                    "before_sha256": item.before_sha256,
                    "after_sha256": item.after_sha256,
                }
                for item in plan.files
            ],
            "writes_client": False,
            "writes_database": False,
        }

    def mingge_native_test_preflight(self):
        try:
            plan = plan_native_test_install(
                Path(self.mingge_native_workbook_var.get().strip()),
                self.mingge_native_candidate_var.get().strip(),
                Path(self.mingge_native_server_var.get().strip()),
            )
            self.current_mingge_native_test_plan = plan
            self._write(
                self.mingge_native_report,
                json.dumps(self._mingge_native_test_plan_summary(plan), ensure_ascii=False, indent=2),
            )
            if plan.blockers:
                messagebox.showerror("P1预检阻止", "\n".join(plan.blockers))
                return None
            messagebox.showinfo(
                "P1预检通过",
                "只会变更UserCmd、QFunction受管块和一份独立验收脚本；不写数据库、客户端或旧37号命格路线。",
            )
            return plan
        except Exception as exc:
            self.current_mingge_native_test_plan = None
            messagebox.showerror("P1预检失败", str(exc))
            return None

    def mingge_native_test_install(self):
        plan = self.current_mingge_native_test_plan
        if plan is None:
            messagebox.showwarning("尚未预检", "请先点击“P1预检”。")
            return None
        if plan.blockers:
            messagebox.showerror("禁止安装", "预检仍有阻止项。")
            return None
        if not messagebox.askyesno(
            "安装P1隔离测试",
            "将安装管理员专用命令@命格平台验收。不会操作引擎；安装后需要关闭M2并等待GameCenter自动拉起再测试。\n\n确认继续？",
        ):
            return None
        try:
            receipt = install_native_test_candidate(plan, self.platform_root)
            self.mingge_native_transaction_var.set(receipt.transaction_id)
            self.current_mingge_native_test_plan = None
            self._write(
                self.mingge_native_report,
                json.dumps({
                    "operation": "mingge-native-p1-test-install",
                    "status": receipt.status,
                    "transaction_id": receipt.transaction_id,
                    "receipt": str(receipt.receipt_path),
                    "files": list(receipt.files),
                }, ensure_ascii=False, indent=2),
            )
            messagebox.showinfo(
                "P1隔离测试已安装",
                f"事务：{receipt.transaction_id}\n下一步：关闭M2并等待GameCenter自动拉起，然后输入@命格平台验收。",
            )
            return receipt
        except Exception as exc:
            messagebox.showerror("P1隔离测试安装失败", str(exc))
            return None

    def mingge_native_test_rollback(self):
        transaction_id = self.mingge_native_transaction_var.get().strip()
        if not transaction_id:
            messagebox.showwarning("缺少事务", "请填写或保留最近P1事务编号。")
            return None
        if not messagebox.askyesno(
            "精确回滚P1隔离测试",
            "仅当三个目标文件自安装后未被其他任务改动时才会回滚；检测到漂移会拒绝覆盖。\n\n确认继续？",
        ):
            return None
        try:
            receipt = rollback_native_test_install(
                self.platform_root,
                transaction_id,
                Path(self.mingge_native_server_var.get().strip()),
            )
            self._write(
                self.mingge_native_report,
                json.dumps({
                    "operation": "mingge-native-p1-test-rollback",
                    "status": receipt.status,
                    "transaction_id": receipt.transaction_id,
                    "receipt": str(receipt.receipt_path),
                }, ensure_ascii=False, indent=2),
            )
            messagebox.showinfo("P1隔离测试已回滚", f"事务：{receipt.transaction_id}")
            return receipt
        except Exception as exc:
            messagebox.showerror("P1隔离测试回滚失败", str(exc))
            return None

    @staticmethod
    def _mingge_native_p2_plan_summary(plan) -> dict:
        return {
            "operation": "mingge-native-p2-test",
            "plan_id": plan.plan_id,
            "candidate_id": plan.candidate_id,
            "candidate_spec_sha256": plan.candidate_spec_sha256,
            "compiled_script_sha256": plan.compiled_script_sha256,
            "workbook": str(plan.workbook),
            "workbook_sha256": plan.workbook_sha256,
            "server": str(plan.server_root),
            "blockers": list(plan.blockers),
            "warnings": list(plan.warnings),
            "evidence_status": list(plan.evidence_status),
            "evidence": [asdict(item) for item in plan.evidence],
            "changes": [{
                "relative_path": item.relative_path, "path": str(item.path),
                "before_sha256": item.before_sha256, "after_sha256": item.after_sha256,
            } for item in plan.files],
            "writes_client": False,
            "writes_database_directly": False,
            "runtime_item_instance_may_change_after_player_command": True,
            "game_validation_status": "pending",
        }

    def mingge_native_p2_test_preflight(self):
        try:
            plan = plan_native_p2_test_install(
                Path(self.mingge_native_workbook_var.get().strip()),
                self.mingge_native_p2_candidate_var.get().strip(),
                Path(self.mingge_native_server_var.get().strip()),
            )
            self.current_mingge_native_p2_test_plan = plan
            self._write(self.mingge_native_report, json.dumps(self._mingge_native_p2_plan_summary(plan), ensure_ascii=False, indent=2))
            if plan.blockers:
                messagebox.showerror("P2预检阻止", "\n".join(plan.blockers))
                return None
            messagebox.showinfo(
                "P2预检通过",
                "只会安装UserCmd 98、QFunction独立受管块和一份P2验收脚本。生命值、魔法值仍是网上资料待实测。",
            )
            return plan
        except Exception as exc:
            self.current_mingge_native_p2_test_plan = None
            messagebox.showerror("P2预检失败", str(exc))
            return None

    def mingge_native_p2_test_install(self):
        plan = self.current_mingge_native_p2_test_plan
        if plan is None:
            messagebox.showwarning("尚未预检", "请先点击“P2预检”。")
            return None
        if plan.blockers:
            messagebox.showerror("禁止安装", "P2预检仍有阻止项。")
            return None
        if not messagebox.askyesno(
            "安装P2三属性测试",
            "将安装管理员命令@命格平台三属性验收。安装器不操作引擎、不直写数据库；玩家执行命令后M2会修改当前可废弃测试物品实例，文件回滚不能恢复该实例。\n\n确认继续？",
        ):
            return None
        try:
            receipt = install_native_p2_test_candidate(plan, self.platform_root)
            self.mingge_native_p2_transaction_var.set(receipt.transaction_id)
            self.current_mingge_native_p2_test_plan = None
            self._write(self.mingge_native_report, json.dumps({
                "operation": "mingge-native-p2-test-install", "status": receipt.status,
                "transaction_id": receipt.transaction_id, "receipt": str(receipt.receipt_path),
                "files": list(receipt.files), "game_validation_status": "pending",
            }, ensure_ascii=False, indent=2))
            messagebox.showinfo(
                "P2三属性测试已安装",
                f"事务：{receipt.transaction_id}\n下一步由你关闭M2并等待GameCenter自动拉起，再输入@命格平台三属性验收。",
            )
            return receipt
        except Exception as exc:
            messagebox.showerror("P2三属性测试安装失败", str(exc))
            return None

    def mingge_native_p2_test_rollback(self):
        transaction_id = self.mingge_native_p2_transaction_var.get().strip()
        if not transaction_id:
            messagebox.showwarning("缺少事务", "请填写或保留最近P2事务编号。")
            return None
        if not messagebox.askyesno(
            "精确回滚P2文件事务",
            "回滚只恢复三个脚本文件；不会恢复已经由M2修改的测试物品实例。检测到文件漂移或备份异常时会零写入拒绝。\n\n确认继续？",
        ):
            return None
        try:
            receipt = rollback_native_p2_test_install(
                self.platform_root, transaction_id, Path(self.mingge_native_server_var.get().strip()),
            )
            self._write(self.mingge_native_report, json.dumps({
                "operation": "mingge-native-p2-test-rollback", "status": receipt.status,
                "transaction_id": receipt.transaction_id, "receipt": str(receipt.receipt_path),
                "runtime_item_instance_restored": False,
            }, ensure_ascii=False, indent=2))
            messagebox.showinfo("P2文件事务已回滚", f"事务：{receipt.transaction_id}\n测试物品实例未由文件回滚恢复。")
            return receipt
        except Exception as exc:
            messagebox.showerror("P2文件事务回滚失败", str(exc))
            return None

    def mingge_native_p2_transaction_inspect(self):
        transaction_id = self.mingge_native_p2_transaction_var.get().strip()
        if not transaction_id:
            messagebox.showwarning("缺少事务", "请填写或保留最近P2事务编号。")
            return None
        try:
            result = inspect_native_p2_test_transaction(
                self.platform_root, transaction_id, Path(self.mingge_native_server_var.get().strip()),
            )
            self._write(self.mingge_native_report, json.dumps(result, ensure_ascii=False, indent=2))
            messagebox.showinfo("P2事务只读检查完成", f"状态：{result['state']}")
            return result
        except Exception as exc:
            messagebox.showerror("P2事务检查失败", str(exc))
            return None

    def mingge_native_p2_transaction_recover_rollback(self):
        transaction_id = self.mingge_native_p2_transaction_var.get().strip()
        if not transaction_id:
            messagebox.showwarning("缺少事务", "请填写或保留最近P2事务编号。")
            return None
        if not messagebox.askyesno(
            "恢复并回滚P2中断事务",
            "仅当manifest和日志HMAC通过，且三个目标均可判定为安装前或安装后状态时才会恢复回滚。未知漂移将零覆盖停止；物品实例不会恢复。\n\n确认继续？",
        ):
            return None
        try:
            receipt = recover_native_p2_test_transaction(
                self.platform_root, transaction_id, Path(self.mingge_native_server_var.get().strip()), "rollback",
            )
            self._write(self.mingge_native_report, json.dumps({
                "operation": "mingge-native-p2-test-recover", "strategy": "rollback",
                "status": receipt.status, "transaction_id": receipt.transaction_id,
                "receipt": str(receipt.receipt_path), "runtime_item_instance_restored": False,
            }, ensure_ascii=False, indent=2))
            messagebox.showinfo("P2中断事务已恢复回滚", f"事务：{receipt.transaction_id}")
            return receipt
        except Exception as exc:
            messagebox.showerror("P2中断事务恢复失败", str(exc))
            return None

    @staticmethod
    def _mingge_native_p3_color_plan_summary(plan) -> dict:
        return {
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
                "relative_path": item.relative_path,
                "path": str(item.path),
                "before_sha256": item.before_sha256,
                "after_sha256": item.after_sha256,
            } for item in plan.files],
            "writes_usercmd": False,
            "writes_qfunction": True,
            "writes_client": False,
            "writes_database": False,
            "writes_real_property": True,
            "game_validation_status": "pending",
        }

    def mingge_native_p3_color_test_preflight(self, *, show_success: bool = True):
        try:
            plan = plan_native_p3_color_test_install(
                Path(self.mingge_native_p3_workbook_var.get().strip()),
                Path(self.mingge_native_server_var.get().strip()),
                self.platform_root,
            )
            self.current_mingge_native_p3_color_test_plan = plan
            self._write(
                self.mingge_native_report,
                json.dumps(self._mingge_native_p3_color_plan_summary(plan), ensure_ascii=False, indent=2),
            )
            if plan.blockers:
                messagebox.showerror("命格配置检查未通过", "\n".join(plan.blockers))
                return None
            if show_success:
                messagebox.showinfo(
                    "命格配置检查通过",
                    "可以生成命格脚本并接入现有龙魂觉醒NPC；不改数据库和客户端。",
                )
            return plan
        except Exception as exc:
            self.current_mingge_native_p3_color_test_plan = None
            messagebox.showerror("命格配置检查失败", str(exc))
            return None

    def mingge_native_p3_color_test_install(self):
        plan = self.mingge_native_p3_color_test_preflight(show_success=False)
        if plan is None:
            return None
        if plan.blockers:
            messagebox.showerror("禁止安装", "命格配置检查仍有阻止项。")
            return None
        if not messagebox.askyesno(
            "安装命格配置",
            "平台将根据中文表格生成命格名称、颜色和最多三项属性，并接入地图3现有“龙魂觉醒”NPC。不会操作引擎、数据库或客户端。\n\n确认继续？",
        ):
            return None
        try:
            receipt = install_native_p3_color_test(plan, self.platform_root)
            self.mingge_native_p3_transaction_var.set(receipt.transaction_id)
            self.current_mingge_native_p3_color_test_plan = None
            self._write(self.mingge_native_report, json.dumps({
                "operation": "mingge-native-p3-color-test-install",
                "status": receipt.status,
                "transaction_id": receipt.transaction_id,
                "receipt": str(receipt.receipt_path),
                "files": list(receipt.files),
                "game_validation_status": "pending",
            }, ensure_ascii=False, indent=2))
            messagebox.showinfo(
                "命格配置已安装",
                f"事务：{receipt.transaction_id}\n平台没有操作引擎；请按当前端既有方式让M2重新读取脚本。",
            )
            return receipt
        except Exception as exc:
            messagebox.showerror("命格配置安装失败", str(exc))
            return None

    def mingge_native_p3_color_test_rollback(self):
        transaction_id = self.mingge_native_p3_transaction_var.get().strip()
        if not transaction_id:
            messagebox.showwarning("缺少事务", "请填写或保留最近P3事务编号。")
            return None
        if not messagebox.askyesno(
            "回滚P3并恢复P2脚本",
            "将按哈希守卫逐字节恢复正式P2脚本，只清理P3自己的活动协调状态；不会修改P2事务，也不会恢复测试物品实例文字。\n\n确认继续？",
        ):
            return None
        try:
            receipt = rollback_native_p3_color_test(
                self.platform_root,
                transaction_id,
                Path(self.mingge_native_server_var.get().strip()),
            )
            self._write(self.mingge_native_report, json.dumps({
                "operation": "mingge-native-p3-color-test-rollback",
                "status": receipt.status,
                "transaction_id": receipt.transaction_id,
                "receipt": str(receipt.receipt_path),
                "p2_stack_order": "P3已先回滚，现在才允许回滚P2",
            }, ensure_ascii=False, indent=2))
            messagebox.showinfo("P3颜色事务已回滚", f"事务：{receipt.transaction_id}\nP2验收脚本已逐字节恢复。")
            return receipt
        except Exception as exc:
            messagebox.showerror("P3颜色事务回滚失败", str(exc))
            return None

    def choose_config_sync_files(self):
        names = filedialog.askopenfilenames(
            title="选择要预检和植入的配置文件",
            initialdir=str(self.config_sync.documents_root),
            filetypes=(("平台配置文件", "*.xlsx *.txt *.csv"), ("Excel", "*.xlsx"), ("文本", "*.txt"), ("CSV", "*.csv")),
        )
        if not names:
            return
        self.config_sync_paths = [Path(name) for name in names]
        self.config_sync_document_id = None
        self.current_config_sync_plan = None
        self.config_sync_selected.delete(0, "end")
        for path in self.config_sync_paths:
            self.config_sync_selected.insert("end", path.name)
        self._write(self.config_sync_report, "已选择：\n" + "\n".join(str(path) for path in self.config_sync_paths))

    def clear_config_sync_files(self):
        self.config_sync_paths = []
        self.config_sync_document_id = None
        self.current_config_sync_plan = None
        self.config_sync_selected.delete(0, "end")
        self._write(self.config_sync_report, "尚未选择配置文件。")

    def choose_config_sync_bundle_zip(self):
        name = filedialog.askopenfilename(
            title="选择 NPC 批量包",
            initialdir=str(Path.home() / "Downloads"),
            filetypes=(("ZIP 压缩包", "*.zip"), ("所有文件", "*.*")),
        )
        if name:
            self.config_sync_bundle_source_var.set(name)
            self.current_config_sync_bundle_plan = None

    def choose_config_sync_bundle_directory(self):
        name = filedialog.askdirectory(title="选择已解压的 NPC 批量包目录")
        if name:
            self.config_sync_bundle_source_var.set(name)
            self.current_config_sync_bundle_plan = None

    @staticmethod
    def _config_sync_change_summary(change):
        return {
            "scope": getattr(change, "scope", "server"),
            "path": getattr(change, "relative_path", ""),
            "operation": getattr(change, "operation", ""),
            "package": getattr(change, "package_id", ""),
            "before_hash": getattr(change, "before_hash", None),
            "after_hash": getattr(change, "after_hash", None),
        }

    @staticmethod
    def _config_sync_receipt_json(receipt) -> str:
        return json.dumps(asdict(receipt), ensure_ascii=False, indent=2, default=str)

    def config_sync_preflight(self):
        try:
            server = self.server_var.get().strip()
            if not server:
                raise ValueError("请先在“目标管理”选择服务端")
            if not self.config_sync_paths:
                raise ValueError("请先点击“选择配置文件”")
            client_text = self.client_var.get().strip()
            plan = self.config_sync.preflight(
                Path(server), self.config_sync_paths,
                Path(client_text) if client_text else None,
                document_id=self.config_sync_document_id,
            )
            self.current_config_sync_plan = plan
            self.config_sync_route_var.set(plan.route)
            summary = {
                "operation": "config-sync",
                "route": plan.route,
                "server": plan.server,
                "client": plan.client,
                "selected_documents": [asdict(item) for item in plan.documents],
                "blockers": plan.blockers,
                "warnings": plan.warnings,
                "changes": [self._config_sync_change_summary(item) for item in plan.changes],
            }
            if plan.route == "item-synthesis" and plan.inner_plan is not None:
                summary["synthesis_npcs"] = getattr(plan.inner_plan, "npcs", [])
                summary["synthesis_recipes"] = getattr(plan.inner_plan, "recipes", [])
            self._write(self.config_sync_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if plan.blockers:
                messagebox.showerror("脚本配置同步预检阻止", "\n".join(plan.blockers))
            else:
                messagebox.showinfo("预检通过", f"已核对 {len(plan.documents)} 个配置文件，计划修改 {len(plan.changes)} 个文件。")
            return plan
        except Exception as exc:
            self.current_config_sync_plan = None
            messagebox.showerror("脚本配置同步预检失败", str(exc))
            return None

    def config_sync_install(self):
        plan = self.current_config_sync_plan or self.config_sync_preflight()
        if plan is None or plan.blockers:
            return
        names = "、".join(item.filename for item in plan.documents)
        if not messagebox.askyesno(
            "脚本配置同步确认",
            f"确认只按以下已预检文件执行事务植入？\n{names}\n\n平台会先备份全部受影响文件，失败自动回滚。",
        ):
            return
        try:
            receipt = self.config_sync.install(plan)
            transaction = str(getattr(receipt, "transaction_id", ""))
            self.config_sync_transaction_var.set(transaction)
            self.config_sync_route_var.set(plan.route)
            self.current_config_sync_plan = None
            self.refresh_history()
            self._write(self.config_sync_report, self._config_sync_receipt_json(receipt))
            messagebox.showinfo("脚本配置同步完成", f"事务：{transaction}\n请由你按功能需要重载/重启M2后验收。")
        except Exception as exc:
            messagebox.showerror("脚本配置同步失败", str(exc))

    def config_sync_bundle_preflight(self):
        try:
            source = self.config_sync_bundle_source_var.get().strip()
            server = self.server_var.get().strip()
            client = self.client_var.get().strip()
            launcher = self.config_sync_bundle_launcher_var.get().strip()
            if not source:
                raise ValueError("请先选择 NPC 批量包 ZIP 或目录")
            if not server or not client or not launcher:
                raise ValueError("请先填写服务端、客户端和登录器目录")
            plan = self.config_sync.preflight_bundle(
                Path(source), Path(server), client=Path(client), launcher=Path(launcher),
            )
            self.current_config_sync_bundle_plan = plan
            self.config_sync_route_var.set("npc-bundle")
            summary = {
                "operation": "config-sync-bundle",
                "source": plan.source,
                "source_sha256": plan.source_sha256,
                "server": plan.server,
                "client": plan.client,
                "launcher": plan.launcher,
                "manifest": asdict(plan.manifest) if plan.manifest is not None else None,
                "audit": asdict(plan.audit) if plan.audit is not None else None,
                "children": plan.child_reports,
                "blockers": plan.blockers,
                "warnings": plan.warnings,
                "changes": [self._config_sync_change_summary(item) for item in plan.changes],
            }
            self._write(self.config_sync_report, json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            if plan.blockers:
                messagebox.showerror("NPC批量包预检阻止", "\n".join(plan.blockers))
            else:
                messagebox.showinfo(
                    "NPC批量包预检通过",
                    f"已核对 {len(plan.child_reports)} 个子模块，计划修改 {len(plan.changes)} 个文件。",
                )
            return plan
        except Exception as exc:
            self.current_config_sync_bundle_plan = None
            messagebox.showerror("NPC批量包预检失败", str(exc))
            return None

    def config_sync_bundle_install(self):
        plan = self.current_config_sync_bundle_plan or self.config_sync_bundle_preflight()
        if plan is None or plan.blockers:
            return
        if not messagebox.askyesno(
            "NPC批量包安装确认",
            f"确认按本次统一预检结果修改 {len(plan.changes)} 个文件？\n\n"
            "平台会在一个事务中备份服务端、客户端和登录器文件，失败时自动回滚。",
        ):
            return
        try:
            receipt = self.config_sync.install_bundle(plan)
            transaction = str(getattr(receipt, "transaction_id", ""))
            self.config_sync_transaction_var.set(transaction)
            self.config_sync_route_var.set("npc-bundle")
            self.current_config_sync_bundle_plan = None
            self.refresh_history()
            self._write(self.config_sync_report, self._config_sync_receipt_json(receipt))
            messagebox.showinfo(
                "NPC批量包已安装",
                f"事务：{transaction}\n状态：已部署待游戏实测。\n请由你重载/重启M2后分组验收。",
            )
        except Exception as exc:
            messagebox.showerror("NPC批量包安装失败", str(exc))

    def config_sync_rollback(self):
        server = self.server_var.get().strip()
        transaction = self.config_sync_transaction_var.get().strip()
        route = self.config_sync_route_var.get().strip()
        if not server or not transaction or not route:
            messagebox.showerror("无法回滚", "当前窗口没有可回滚的脚本配置同步事务。")
            return
        if not messagebox.askyesno("回滚确认", f"确认逐字节回滚事务 {transaction}？"):
            return
        try:
            rolled_back = self.config_sync.rollback(Path(server), transaction, route)
            self.config_sync_transaction_var.set("")
            self.refresh_history()
            self._write(self.config_sync_report, json.dumps({"rolled_back": rolled_back}, ensure_ascii=False, indent=2))
            messagebox.showinfo("回滚完成", rolled_back)
        except Exception as exc:
            messagebox.showerror("回滚失败", str(exc))

    def _build_recycle(self):
        tab = self.tabs["装备回收"]
        ttk.Label(
            tab,
            text="支持19_装备回收配置.xlsx（装备模式）或19B_材料回收配置.xlsx（材料模式）；一次仅选择一表，分别按表内模式处理。",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 6))
        self._row(
            tab, "回收配置表", self.recycle_workbook_var,
            lambda: self._choose_file(self.recycle_workbook_var, [("Excel", "*.xlsx")]),
        )
        self._row(tab, "目标服务端", self.server_var, lambda: self._choose_dir(self.server_var))
        search = ttk.Frame(tab); search.pack(fill="x", padx=12, pady=4)
        ttk.Label(search, text="分类/装备搜索", width=14).pack(side="left")
        ttk.Entry(search, textvariable=self.recycle_search_var, width=34).pack(side="left", padx=6)
        ttk.Button(search, text="搜索配置", command=self.recycle_search).pack(side="left")
        ttk.Button(search, text="打开配置表", command=self.open_recycle_workbook).pack(side="left", padx=8)
        actions = ttk.Frame(tab); actions.pack(fill="x", padx=12, pady=6)
        ttk.Button(actions, text="预检回收配置", command=self.recycle_preflight).pack(side="left")
        ttk.Button(actions, text="确认更新", command=self.recycle_install).pack(side="left", padx=8)
        ttk.Label(actions, text="回滚事务：").pack(side="left", padx=(24, 4))
        ttk.Entry(actions, textvariable=self.recycle_transaction_var, width=30).pack(side="left")
        ttk.Button(actions, text="逐字节回滚", command=self.recycle_rollback).pack(side="left", padx=8)
        ttk.Label(
            tab,
            text="附加奖励三格全部留空即只发主奖励；填写后仍只回收一次装备，再发放两种奖励。",
            foreground="#7a4b00",
        ).pack(anchor="w", padx=12, pady=(0, 4))
        self.recycle_report = tk.Text(tab, wrap="none")
        self.recycle_report.pack(fill="both", expand=True, padx=12, pady=(4, 10))

    @staticmethod
    def _recycle_change_summary(change):
        return {
            "path": change.relative_path,
            "operation": change.operation,
            "before_hash": hashlib.sha256(change.before).hexdigest() if change.before is not None else None,
            "after_hash": hashlib.sha256(change.after).hexdigest(),
        }

    def open_recycle_workbook(self):
        try:
            path = Path(self.recycle_workbook_var.get())
            if not path.is_file():
                raise ValueError(f"回收配置表不存在：{path}")
            os.startfile(path)
        except Exception as exc:
            messagebox.showerror("打开回收配置表失败", str(exc))

    def recycle_search(self):
        try:
            rows = self.recycle_config.search(
                Path(self.recycle_workbook_var.get()), self.recycle_search_var.get()
            )
            self._write(self.recycle_report, json.dumps(rows, ensure_ascii=False, indent=2))
            if not rows:
                messagebox.showinfo("搜索结果", "没有找到匹配的分类或装备。")
        except Exception as exc:
            messagebox.showerror("搜索回收配置失败", str(exc))

    def recycle_preflight(self):
        try:
            server = self.server_var.get().strip()
            if not server:
                raise ValueError("请先选择目标服务端")
            plan = self.recycle_config.preflight(
                Path(self.recycle_workbook_var.get()), Path(server)
            )
            self.current_recycle_plan = plan
            recycle_mode = "材料回收" if plan.operation == "material-recycle-config" else "装备回收"
            recycle_unit = "材料" if recycle_mode == "材料回收" else "装备"
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
                "changes": [self._recycle_change_summary(item) for item in plan.changes],
            }
            self._write(self.recycle_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if plan.blockers:
                messagebox.showerror(f"{recycle_mode}预检阻止", "\n".join(plan.blockers))
            else:
                page_count = plan.page_count or max((item.page for item in plan.categories), default=0)
                mode_note = "材料模式不使用装备回收加成。" if recycle_mode == "材料回收" else "装备模式按装备回收规则结算。"
                messagebox.showinfo(
                    f"{recycle_mode}预检通过",
                    f"分类{len(plan.categories)}个，{recycle_unit}{len(plan.item_names)}件，共{page_count}页；计划修改{len(plan.changes)}个文件。\n{mode_note}",
                )
            return plan
        except Exception as exc:
            self.current_recycle_plan = None
            messagebox.showerror("装备回收预检失败", str(exc))
            return None

    def recycle_install(self):
        plan = self.current_recycle_plan or self.recycle_preflight()
        if plan is None or plan.blockers:
            return
        recycle_mode = "材料回收" if plan.operation == "material-recycle-config" else "装备回收"
        recycle_unit = "材料" if recycle_mode == "材料回收" else "装备"
        if not plan.changes:
            messagebox.showinfo(f"{recycle_mode}无需更新", "目标服已经处于当前表格配置。")
            return
        mode_note = "材料模式不使用装备回收加成。" if recycle_mode == "材料回收" else "装备模式按装备回收规则结算。"
        if not messagebox.askyesno(
            f"{recycle_mode}更新确认",
            f"确认按已预检表格更新{len(plan.categories)}个分类、{len(plan.item_names)}件{recycle_unit}？\n{mode_note}\n\n"
            "平台会完整备份QFunction、QManage和UserCmd，失败自动恢复。",
        ):
            return
        try:
            receipt = self.recycle_config.install(plan)
            self.recycle_transaction_var.set(receipt.transaction_id)
            self.current_recycle_plan = None
            self.refresh_history(); self.refresh_packages()
            self._write(self.recycle_report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
            messagebox.showinfo(
                f"{recycle_mode}更新完成",
                f"事务：{receipt.transaction_id}\n请由你重载或重启M2后进行游戏验收。",
            )
        except Exception as exc:
            messagebox.showerror("装备回收更新失败", str(exc))

    def recycle_rollback(self):
        server = self.server_var.get().strip()
        transaction = self.recycle_transaction_var.get().strip()
        if not server or not transaction:
            messagebox.showerror("无法回滚", "请填写目标服务端和装备回收事务号。")
            return
        if not messagebox.askyesno("装备回收回滚确认", f"确认逐字节回滚事务 {transaction}？"):
            return
        try:
            rolled_back = self.recycle_config.rollback(Path(server), transaction)
            self.recycle_transaction_var.set("")
            self.current_recycle_plan = None
            self.refresh_history(); self.refresh_packages()
            self._write(self.recycle_report, json.dumps({"rolled_back": rolled_back}, ensure_ascii=False, indent=2))
            messagebox.showinfo("装备回收回滚完成", rolled_back)
        except Exception as exc:
            messagebox.showerror("装备回收回滚失败", str(exc))

    def _build_optional_scripts(self):
        tab = self.tabs["非常驻脚本"]
        ttk.Label(tab, text="每个非常驻脚本独立保存；原始脚本首次只登记待验证，不会直接写入服务端。", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=12, pady=10)
        presets = ttk.Labelframe(tab, text="非常驻专项一键安装（狂暴含单一NPC唯一入口；捐献仅业务接口）")
        presets.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(presets, text="预检狂暴", command=lambda: self.optional_preset_preflight("rage")).pack(side="left", padx=6, pady=6)
        ttk.Button(presets, text="一键安装狂暴", command=lambda: self.optional_preset_install("rage")).pack(side="left", padx=6, pady=6)
        ttk.Button(presets, text="回滚狂暴", command=lambda: self.optional_preset_rollback("rage")).pack(side="left", padx=6, pady=6)
        ttk.Button(presets, text="预检捐献", command=lambda: self.optional_preset_preflight("donate")).pack(side="left", padx=6, pady=6)
        ttk.Button(presets, text="一键安装捐献", command=lambda: self.optional_preset_install("donate")).pack(side="left", padx=6, pady=6)
        ttk.Button(presets, text="回滚捐献", command=lambda: self.optional_preset_rollback("donate")).pack(side="left", padx=6, pady=6)
        self.optional_preset_report = tk.Text(presets, height=5, wrap="none")
        self.optional_preset_report.pack(fill="x", padx=6, pady=(0, 6))
        toolbar = ttk.Frame(tab); toolbar.pack(fill="x", padx=12, pady=6)
        ttk.Button(toolbar, text="选择文件夹读取", command=self.register_script_folder).pack(side="left")
        ttk.Button(toolbar, text="导入完整成果包文件夹", command=self.register_script_folder).pack(side="left", padx=8)
        ttk.Button(toolbar, text="刷新", command=self.refresh_optional_scripts).pack(side="left")
        ttk.Button(toolbar, text="打开平台副本目录", command=self.open_optional_script_folder).pack(side="left", padx=8)
        ttk.Button(toolbar, text="转到成果包库", command=self.goto_optional_package).pack(side="left")
        self.optional_tree = ttk.Treeview(tab, columns=("name", "kind", "status", "version", "hash", "path"), show="headings", selectmode="browse")
        for key, title, width in (("name", "名称", 160), ("kind", "类型", 80), ("status", "状态", 90), ("version", "版本", 90), ("hash", "哈希", 140), ("path", "平台路径", 360)):
            self.optional_tree.heading(key, text=title); self.optional_tree.column(key, width=width)
        self.optional_tree.pack(fill="both", expand=True, padx=12, pady=6)
        self.optional_tree.bind("<<TreeviewSelect>>", lambda _event: self.show_optional_script())
        ttk.Label(tab, text="使用说明").pack(anchor="w", padx=12)
        self.optional_instructions = tk.Text(tab, height=10, wrap="word")
        self.optional_instructions.pack(fill="both", expand=True, padx=12, pady=(2, 10))

    def _build_execution_lab(self):
        tab = self.tabs["处决测试"]
        ttk.Label(
            tab,
            text="处决、失衡、韧性与地图规则（地图0实效已验收；当前为平台事务接线候选）",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 4))
        ttk.Label(
            tab,
            text="预检不写目标服；确认导入前保存每个受影响文件的原始字节，失败自动恢复，验收后可一键回滚到导入前。",
            foreground="#9A4D00",
        ).pack(anchor="w", padx=12, pady=(0, 8))
        self._row(tab, "测试服根目录", self.execution_server_var, lambda: self._choose_dir(self.execution_server_var))
        options = ttk.Frame(tab)
        options.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(options, text="同步目标管理路径", command=self.execution_sync_target).pack(side="left")
        ttk.Checkbutton(
            options,
            text="我确认这是独立测试服",
            variable=self.execution_confirm_test_var,
        ).pack(side="left", padx=16)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", padx=12, pady=6)
        ttk.Button(actions, text="预检导入", command=self.execution_preflight).pack(side="left")
        ttk.Button(actions, text="确认导入测试服", command=self.execution_install).pack(side="left", padx=8)
        ttk.Button(actions, text="回滚到导入前", command=self.execution_rollback).pack(side="left", padx=8)
        ttk.Button(actions, text="打开地图处决规则表", command=self.open_execution_rules).pack(side="left", padx=8)
        ttk.Button(actions, text="打开处决施工目录", command=self.open_execution_lab).pack(side="left", padx=8)
        self.execution_report = tk.Text(tab, wrap="none")
        self.execution_report.pack(fill="both", expand=True, padx=12, pady=8)

    def _build_equipment(self):
        tab = self.tabs["批量做装备"]
        ttk.Label(tab, text="生成与修改共用同一装备母表；装备持久固定 60000。默认目标 D:\\MirServer。", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=12, pady=10)
        self._row(tab, "装备生成/修改源表", self.equipment_workbook_var, self._choose_equipment_workbook)
        self._row(tab, "材料源表", self.equipment_material_workbook_var, self._choose_material_workbook)
        self._row(tab, "悬浮分类表", self.equipment_hint_workbook_var, self._choose_equipment_hint_workbook)
        self._row(tab, "服务端目录", self.equipment_server_var, lambda: self._choose_dir(self.equipment_server_var))
        self._row(tab, "客户端 data", self.equipment_client_var, lambda: self._choose_dir(self.equipment_client_var))
        search = ttk.Frame(tab); search.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(search, text="单件搜索", width=14).pack(side="left")
        ttk.Entry(search, textvariable=self.equipment_search_var, width=32).pack(side="left", padx=6)
        ttk.Button(search, text="搜索装备", command=self.equipment_search).pack(side="left")
        actions = ttk.Frame(tab); actions.pack(fill="x", padx=12, pady=6)
        ttk.Button(actions, text="预检", command=self.equipment_preflight).pack(side="left")
        ttk.Button(actions, text="确认生成/修改", command=lambda: self.equipment_install("create")).pack(side="left", padx=8)
        ttk.Button(actions, text="补写M2显示", command=self.equipment_repair_display).pack(side="left", padx=8)
        ttk.Button(actions, text="预检修改", command=self.equipment_update_preflight).pack(side="left", padx=8)
        ttk.Button(actions, text="确认修改", command=lambda: self.equipment_install("update")).pack(side="left", padx=8)
        ttk.Button(actions, text="导出当前服装备清单", command=self.equipment_update_export).pack(side="left", padx=8)
        ttk.Label(actions, text="回滚事务：").pack(side="left", padx=(24, 4))
        ttk.Entry(actions, textvariable=self.equipment_transaction_var, width=30).pack(side="left")
        ttk.Button(actions, text="逐字节回滚", command=self.equipment_rollback).pack(side="left", padx=8)
        material_actions = ttk.Frame(tab); material_actions.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(material_actions, text="材料：只新增目标服尚不存在的材料；已有材料自动跳过，最大叠加 99999。", foreground="#7a4b00").pack(side="left")
        ttk.Button(material_actions, text="预检材料", command=self.equipment_material_preflight).pack(side="left", padx=(18, 6))
        ttk.Button(material_actions, text="确认添加材料", command=self.equipment_material_install).pack(side="left", padx=6)
        hint_actions = ttk.Frame(tab); hint_actions.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(hint_actions, text="悬浮：制式装备=1/2/3，稀有专属=1/2/4，追梦神器=1/2/5；同步艾尔登法环底标。", foreground="#5f3f00").pack(side="left")
        ttk.Button(hint_actions, text="预检悬浮", command=self.equipment_hint_preflight).pack(side="left", padx=(18, 6))
        ttk.Button(hint_actions, text="确认同步悬浮", command=self.equipment_hint_install).pack(side="left", padx=6)
        ttk.Button(hint_actions, text="导出当前悬浮清单", command=self.equipment_hint_export).pack(side="left", padx=6)
        graphics = ttk.Labelframe(tab, text="装备素材替换/追加（配置文件驱动）")
        graphics.pack(fill="x", padx=12, pady=(4, 6))
        self._row(graphics, "装备素材替换/追加配置", self.equipment_graphics_config_var, self._choose_equipment_graphics_config)
        graphics_actions = ttk.Frame(graphics); graphics_actions.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(graphics_actions, text="预检", command=self.equipment_graphics_preflight).pack(side="left")
        ttk.Button(graphics_actions, text="应用", command=self.equipment_graphics_apply).pack(side="left", padx=6)
        ttk.Button(graphics_actions, text="查看结果", command=self.equipment_graphics_view_result).pack(side="left", padx=6)
        ttk.Button(graphics_actions, text="登录器生成后核验", command=self.equipment_graphics_verify_launcher).pack(side="left", padx=6)
        ttk.Label(graphics_actions, text="成功后请手动生成指定登录器。", foreground="#7a4b00").pack(side="left", padx=12)
        self._row(graphics, "素材事务收据", self.equipment_graphics_receipt_var, lambda: None)
        self.equipment_report = tk.Text(tab, wrap="none")
        self.equipment_report.pack(fill="both", expand=True, padx=12, pady=8)

    def _build_equipment_aura(self):
        tab = self.tabs["装备光环"]
        ttk.Label(
            tab,
            text="从目标服搜索真实装备，选择10套圆月斩同结构特效；全部固定3格范围。先保存绑定，再预检和确认部署。",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))
        target = ttk.Labelframe(tab, text="目标与唯一配置表")
        target.pack(fill="x", padx=12, pady=4)
        self._row(target, "服务端根目录", self.aura_server_var, lambda: self._choose_dir(self.aura_server_var))
        self._row(target, "客户端根目录", self.aura_client_var, lambda: self._choose_dir(self.aura_client_var))
        self._row(target, "登录器补丁目录", self.aura_login_var, lambda: self._choose_dir(self.aura_login_var))
        self._row(
            target,
            "装备光环配置表",
            self.aura_workbook_var,
            lambda: self._choose_file(self.aura_workbook_var, [("Excel工作簿", "*.xlsx")]),
        )

        selection = ttk.PanedWindow(tab, orient="horizontal")
        selection.pack(fill="both", expand=True, padx=12, pady=4)
        equipment_frame = ttk.Labelframe(selection, text="1. 搜索并选择目标服装备")
        style_frame = ttk.Labelframe(selection, text="2. 选择光环样式（100%圆月斩尺寸）")
        selection.add(equipment_frame, weight=2)
        selection.add(style_frame, weight=3)

        search = ttk.Frame(equipment_frame)
        search.pack(fill="x", padx=6, pady=6)
        ttk.Entry(search, textvariable=self.aura_search_var).pack(side="left", fill="x", expand=True)
        ttk.Button(search, text="搜索装备", command=self.equipment_aura_search).pack(side="left", padx=(6, 0))
        self.aura_equipment_tree = ttk.Treeview(
            equipment_frame, columns=("idx", "name"), show="headings", height=7, selectmode="browse"
        )
        self.aura_equipment_tree.heading("idx", text="Idx")
        self.aura_equipment_tree.heading("name", text="装备名称")
        self.aura_equipment_tree.column("idx", width=70, anchor="center")
        self.aura_equipment_tree.column("name", width=210)
        self.aura_equipment_tree.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.aura_equipment_tree.bind("<<TreeviewSelect>>", self.equipment_aura_select_equipment)

        style_split = ttk.Frame(style_frame)
        style_split.pack(fill="both", expand=True, padx=6, pady=6)
        self.aura_style_tree = ttk.Treeview(
            style_split, columns=("id", "name", "frames"), show="headings", height=7, selectmode="browse"
        )
        self.aura_style_tree.heading("id", text="样式ID")
        self.aura_style_tree.heading("name", text="视觉名称")
        self.aura_style_tree.heading("frames", text="帧/速度/范围")
        self.aura_style_tree.column("id", width=70, anchor="center")
        self.aura_style_tree.column("name", width=105)
        self.aura_style_tree.column("frames", width=105, anchor="center")
        self.aura_style_tree.pack(side="left", fill="both", expand=True)
        self.aura_style_tree.bind("<<TreeviewSelect>>", self.equipment_aura_select_style)
        self.aura_preview = ttk.Label(style_split, text="选择样式后显示预览", anchor="center")
        self.aura_preview.pack(side="left", fill="both", expand=True, padx=(8, 0))
        for style in self.equipment_aura.list_styles():
            self.aura_style_tree.insert(
                "", "end", iid=str(style["style_id"]),
                values=(style["style_id"], style["display_name"], f'{style["frame_count"]}帧/{style["frame_speed_ms"]}ms/3格'),
            )
        self.aura_style_tree.selection_set("style01")
        self.aura_style_tree.focus("style01")
        self.equipment_aura_select_style()

        binding = ttk.Labelframe(tab, text="3. 当前绑定参数")
        binding.pack(fill="x", padx=12, pady=4)
        for label, variable, width in (
            ("装备", self.aura_equipment_var, 22),
            ("样式", self.aura_style_var, 10),
            ("伤害倍率", self.aura_multiplier_var, 7),
            ("间隔秒", self.aura_interval_var, 7),
            ("优先级", self.aura_priority_var, 7),
        ):
            ttk.Label(binding, text=label).pack(side="left", padx=(8, 2), pady=6)
            ttk.Entry(binding, textvariable=variable, width=width, state="readonly" if label in {"装备", "样式"} else "normal").pack(side="left", pady=6)
        ttk.Label(binding, text="视觉与伤害范围固定3格；同时佩戴时只启用最高优先级。", foreground="#7a4b00").pack(side="left", padx=12)

        actions = ttk.Frame(tab)
        actions.pack(fill="x", padx=12, pady=4)
        ttk.Button(actions, text="写入/更新绑定表", command=self.equipment_aura_save_binding).pack(side="left")
        ttk.Button(actions, text="生成预检报告", command=self.equipment_aura_preflight).pack(side="left", padx=6)
        ttk.Button(actions, text="确认部署", command=self.equipment_aura_install).pack(side="left", padx=6)
        ttk.Button(actions, text="打开配置表", command=self.open_equipment_aura_workbook).pack(side="left", padx=6)
        ttk.Label(actions, text="回滚事务").pack(side="left", padx=(18, 3))
        ttk.Entry(actions, textvariable=self.aura_transaction_var, width=25).pack(side="left")
        ttk.Button(actions, text="逐字节回滚", command=self.equipment_aura_rollback).pack(side="left", padx=6)
        self.aura_report = tk.Text(tab, height=7, wrap="none")
        self.aura_report.pack(fill="both", expand=True, padx=12, pady=(2, 8))

    def equipment_aura_search(self):
        try:
            rows = self.equipment_aura.search_target_equipment(
                Path(self.aura_server_var.get().strip() or r"D:\MirServer"),
                self.aura_search_var.get(),
            )
            for item in self.aura_equipment_tree.get_children():
                self.aura_equipment_tree.delete(item)
            for index, item in enumerate(rows):
                self.aura_equipment_tree.insert(
                    "", "end", iid=f"aura-equipment-{index}", values=(item["idx"], item["name"])
                )
            self._write(self.aura_report, f"找到 {len(rows)} 件真实装备。请选择一件装备，再选择光环样式。")
        except Exception as exc:
            messagebox.showerror("装备搜索失败", str(exc))

    def equipment_aura_select_equipment(self, _event=None):
        selected = self.aura_equipment_tree.selection()
        if not selected:
            return
        values = self.aura_equipment_tree.item(selected[0], "values")
        if len(values) >= 2:
            self.aura_equipment_var.set(str(values[1]))
            self.current_equipment_aura_plan = None

    def equipment_aura_select_style(self, _event=None):
        selected = self.aura_style_tree.selection()
        if not selected:
            return
        style_id = str(selected[0])
        self.aura_style_var.set(style_id)
        preview_path = self.platform_root / "assets" / "equipment_aura" / "previews" / f"{style_id}.png"
        if not preview_path.is_file():
            self.aura_preview.configure(image="", text=f"{style_id}\n预览资源待同步")
            self.aura_preview_image = None
            return
        try:
            image = tk.PhotoImage(file=str(preview_path))
            factor = max(1, (image.width() + 279) // 280, (image.height() + 209) // 210)
            if factor > 1:
                image = image.subsample(factor, factor)
            self.aura_preview_image = image
            self.aura_preview.configure(image=image, text="")
        except Exception as exc:
            self.aura_preview.configure(image="", text=f"预览读取失败\n{exc}")
            self.aura_preview_image = None

    def equipment_aura_save_binding(self):
        try:
            equipment_name = self.aura_equipment_var.get().strip()
            if not equipment_name:
                raise EquipmentAuraError("请先搜索并选择目标服中的真实装备")
            exact = [
                item for item in self.equipment_aura.search_target_equipment(
                    Path(self.aura_server_var.get().strip() or r"D:\MirServer"), equipment_name
                )
                if str(item["name"]).casefold() == equipment_name.casefold()
            ]
            if len(exact) != 1:
                raise EquipmentAuraError(f"装备名称无法唯一确认: {equipment_name}")
            row = self.equipment_aura.upsert_binding(
                Path(self.aura_workbook_var.get()),
                equipment_name,
                self.aura_style_var.get(),
                int(self.aura_multiplier_var.get()),
                int(self.aura_interval_var.get()),
                int(self.aura_priority_var.get()),
            )
            self.current_equipment_aura_plan = None
            self._write(
                self.aura_report,
                f"已更新配置表第 {row} 行：{equipment_name} → {self.aura_style_var.get()}。\n"
                "配置表原件已备份；请继续生成预检报告。",
            )
        except Exception as exc:
            messagebox.showerror("更新装备光环绑定失败", str(exc))

    def _equipment_aura_preflight(self):
        return self.equipment_aura.preflight(
            Path(self.aura_server_var.get().strip() or r"D:\MirServer"),
            Path(self.aura_client_var.get().strip() or r"E:\11周年"),
            Path(self.aura_login_var.get().strip() or r"D:\素材文件夹\LFM2[20260707]\登录器"),
            Path(self.aura_workbook_var.get()),
        )

    def _show_equipment_aura_plan(self, plan):
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
        self._write(self.aura_report, json.dumps(summary, ensure_ascii=False, indent=2))

    def equipment_aura_preflight(self):
        try:
            plan = self._equipment_aura_preflight()
            self.current_equipment_aura_plan = plan
            self._show_equipment_aura_plan(plan)
            if plan.blockers:
                messagebox.showerror("装备光环预检阻止", "\n".join(plan.blockers))
            elif not plan.files:
                messagebox.showinfo("装备光环无需修改", "目标已是当前配置。")
        except Exception as exc:
            self.current_equipment_aura_plan = None
            messagebox.showerror("装备光环预检失败", str(exc))

    def equipment_aura_install(self):
        plan = self.current_equipment_aura_plan
        if plan is None:
            messagebox.showwarning("尚未预检", "请先生成装备光环预检报告。")
            return
        if plan.blockers:
            messagebox.showerror("预检存在阻止项", "\n".join(plan.blockers))
            return
        if not plan.files:
            messagebox.showinfo("无需部署", "目标已是当前配置。")
            return
        if not messagebox.askyesno(
            "确认部署装备光环",
            f"将事务修改 {len(plan.files)} 个文件并逐字节备份。\n\n"
            "平台不会操作游戏引擎；部署后由你重载或重启验证。是否继续？",
        ):
            return
        try:
            receipt = self.equipment_aura.install(plan)
            self.current_equipment_aura_plan = None
            self.aura_transaction_var.set(receipt.transaction_id)
            self._write(self.aura_report, json.dumps({
                "status": receipt.status,
                "transaction_id": receipt.transaction_id,
                "receipt": str(receipt.receipt_path),
                "changed_files": [str(path) for path in receipt.changed_files],
            }, ensure_ascii=False, indent=2))
            messagebox.showinfo("装备光环部署完成", f"事务：{receipt.transaction_id}\n请自行重载或重启后游戏验收。")
        except Exception as exc:
            messagebox.showerror("装备光环部署失败", str(exc))

    def equipment_aura_rollback(self):
        transaction = self.aura_transaction_var.get().strip()
        if not transaction:
            messagebox.showwarning("缺少事务号", "请填写需要回滚的装备光环事务号。")
            return
        if not messagebox.askyesno("确认逐字节回滚", f"确认回滚装备光环事务 {transaction}？"):
            return
        try:
            result = self.equipment_aura.rollback(
                Path(self.aura_server_var.get().strip() or r"D:\MirServer"), transaction
            )
            self.current_equipment_aura_plan = None
            self._write(self.aura_report, json.dumps({"transaction_id": transaction, "status": result}, ensure_ascii=False, indent=2))
            messagebox.showinfo("装备光环回滚完成", transaction)
        except Exception as exc:
            messagebox.showerror("装备光环回滚失败", str(exc))

    def open_equipment_aura_workbook(self):
        try:
            os.startfile(str(Path(self.aura_workbook_var.get()).resolve()))
        except Exception as exc:
            messagebox.showerror("打开装备光环配置表失败", str(exc))

    def _build_monster_library(self):
        tab = self.tabs["怪物库"]
        ttk.Label(
            tab,
            text="本地保存完整Monster资料与正确动作补丁；选中库编号后可把怪物和补丁一起事务化植入。",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=8)
        source = ttk.Labelframe(tab, text="明月供体与目标")
        source.pack(fill="x", padx=12, pady=(0, 6))
        rows = (
            ("明月怪物DB", self.monster_donor_db_var, lambda: self._choose_file(self.monster_donor_db_var, [("SQLite DB", "*.DB"), ("全部文件", "*.*")])),
            ("明月WZL data", self.monster_donor_wzl_var, lambda: self._choose_dir(self.monster_donor_wzl_var)),
            ("明月PAK data", self.monster_donor_pak_var, lambda: self._choose_dir(self.monster_donor_pak_var)),
            ("明月pak.txt", self.monster_donor_rules_var, lambda: self._choose_file(self.monster_donor_rules_var, [("PAK规则", "pak.txt"), ("文本", "*.txt")])),
            ("目标服务端", self.monster_server_var, lambda: self._choose_dir(self.monster_server_var)),
            ("目标客户端data", self.monster_client_var, lambda: self._choose_dir(self.monster_client_var)),
        )
        for index, (label, variable, command) in enumerate(rows):
            frame = ttk.Frame(source)
            frame.grid(row=index // 2, column=(index % 2) * 3, columnspan=3, sticky="ew", padx=6, pady=3)
            ttk.Label(frame, text=label, width=14).pack(side="left")
            ttk.Entry(frame, textvariable=variable).pack(side="left", fill="x", expand=True, padx=4)
            ttk.Button(frame, text="浏览", command=command).pack(side="left")
        source.columnconfigure(0, weight=1)
        source.columnconfigure(3, weight=1)

        bridge = ttk.Frame(tab)
        bridge.pack(fill="x", padx=12, pady=3)
        ttk.Label(bridge, text="PAK桥接索引", width=14).pack(side="left")
        ttk.Entry(bridge, textvariable=self.monster_sidecar_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(bridge, text="选择sidecar", command=self._choose_monster_sidecar).pack(side="left")
        ttk.Button(bridge, text="导入桥接缩略图", command=self.monster_import_sidecars).pack(side="left", padx=6)

        workbook = ttk.Labelframe(tab, text="按表格批量生成新怪物（完成后自动准备登录器）")
        workbook.pack(fill="x", padx=12, pady=3)
        ttk.Label(workbook, text="怪物生成表", width=14).pack(side="left", padx=(6, 0), pady=5)
        ttk.Entry(workbook, textvariable=self.monster_workbook_var).pack(side="left", fill="x", expand=True, padx=4, pady=5)
        ttk.Button(workbook, text="浏览", command=self._choose_monster_workbook).pack(side="left", padx=4)
        ttk.Button(workbook, text="预检（可选）", command=self.monster_workbook_preflight).pack(side="left", padx=4)
        ttk.Button(workbook, text="一键同步怪物", command=self.monster_workbook_install).pack(side="left", padx=(4, 8))

        actions = ttk.Frame(tab)
        actions.pack(fill="x", padx=12, pady=5)
        ttk.Button(actions, text="按引擎规则扫描供体并重建V3怪物库", command=self.monster_scan).pack(side="left")
        ttk.Button(actions, text="刷新列表", command=self.monster_refresh).pack(side="left", padx=6)
        ttk.Label(actions, text="状态").pack(side="left", padx=(16, 4))
        ttk.Combobox(actions, textvariable=self.monster_status_var, values=("可植入", "本端已有", "已跳过", "全部"), state="readonly", width=10).pack(side="left")
        ttk.Label(actions, text="编号/名称筛选").pack(side="left", padx=(12, 4))
        ttk.Entry(actions, textvariable=self.monster_filter_var, width=14).pack(side="left")
        ttk.Button(actions, text="过滤", command=self.monster_refresh).pack(side="left", padx=4)
        ttk.Button(actions, text="全选可植入", command=self.monster_select_ready).pack(side="left", padx=8)
        ttk.Button(actions, text="预检选中", command=self.monster_preflight).pack(side="left", padx=8)
        ttk.Button(actions, text="一键植入", command=self.monster_install).pack(side="left", padx=4)
        ttk.Label(actions, text="回滚事务").pack(side="left", padx=(14, 4))
        ttk.Entry(actions, textvariable=self.monster_transaction_var, width=24).pack(side="left")
        ttk.Button(actions, text="逐字节回滚", command=self.monster_rollback).pack(side="left", padx=4)

        split = ttk.PanedWindow(tab, orient="vertical")
        split.pack(fill="both", expand=True, padx=12, pady=5)
        list_frame = ttk.Labelframe(split, text="怪物库编号（Ctrl/Shift多选）")
        style = ttk.Style(self)
        style.configure("Monster.Treeview", rowheight=92)
        self.monster_tree = ttk.Treeview(
            list_frame,
            columns=("id", "name", "engine", "appr", "closure", "dependencies", "login", "reason"),
            show="tree headings",
            selectmode="extended",
            style="Monster.Treeview",
            height=6,
        )
        self.monster_tree.heading("#0", text=self.MONSTER_TREE_COLUMN_TITLES[0])
        self.monster_tree.column("#0", width=110, stretch=False)
        for key, title, width in (
            ("id", "库编号", 75), ("name", "怪物名称", 170), ("engine", "引擎模式", 105),
            ("appr", "Appr", 65), ("closure", "闭包状态", 105),
            ("dependencies", "依赖数量", 75), ("login", "登录器要求", 140),
            ("reason", "说明", 260),
        ):
            self.monster_tree.heading(key, text=title)
            self.monster_tree.column(key, width=width)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.monster_tree.yview)
        self.monster_tree.configure(yscrollcommand=scrollbar.set)
        self.monster_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        split.add(list_frame, weight=3)
        report_frame = ttk.Labelframe(split, text="扫描、预检与事务报告")
        self.monster_report = tk.Text(report_frame, wrap="none", height=8)
        self.monster_report.pack(fill="both", expand=True, padx=4, pady=4)
        split.add(report_frame, weight=2)
        try:
            self.monster_refresh()
        except Exception:
            pass

    def _build_king_mode_flow(self):
        tab = self.tabs["国王模式流程"]
        ttk.Label(tab, text="国王模式：登录大厅 → 报名 → 10秒倒计时 → 双方野区刷怪 → 进入XYGDZY。配置 TXT 是母表，脚本由平台渲染。", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=12, pady=10)
        self._row(tab, "服务端目录", self.server_var, lambda: self._choose_dir(self.server_var))
        self._row(tab, "客户端目录", self.client_var, lambda: self._choose_dir(self.client_var))
        actions = ttk.Frame(tab); actions.pack(fill="x", padx=12, pady=6)
        ttk.Button(actions, text="预检赛前流程", command=self.king_mode_flow_preflight).pack(side="left")
        ttk.Button(actions, text="确认应用流程", command=self.king_mode_flow_apply).pack(side="left", padx=8)
        ttk.Button(actions, text="读取并应用配置TXT", command=self.king_mode_config_apply).pack(side="left", padx=8)
        ttk.Button(actions, text="打开配置文件夹", command=lambda: os.startfile(str(Path(self.server_var.get()) / "Mir200" / "Envir" / "QuestDiary" / "玄渊配置"))).pack(side="left", padx=8)
        self.king_mode_flow_report = tk.Text(tab, wrap="none")
        self.king_mode_flow_report.pack(fill="both", expand=True, padx=12, pady=8)

    def _build_npc_editor(self):
        tab = self.tabs["NPC编辑"]
        ttk.Label(tab, text="编辑 NPC 对话、注册位置和外观；完成后生成独立 NPC 候选成果包。", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=12, pady=10)
        form = ttk.Frame(tab); form.pack(fill="x", padx=12, pady=2)
        left = ttk.Frame(form); left.pack(side="left", fill="x", expand=True, padx=(0, 10))
        right = ttk.Frame(form); right.pack(side="left", fill="x", expand=True)
        for label, var in (("成果包ID", self.npc_package_id_var), ("显示名称", self.npc_display_name_var), ("脚本注册路径", self.npc_script_path_var), ("地图代码", self.npc_map_var), ("X坐标", self.npc_x_var)):
            row = ttk.Frame(left); row.pack(fill="x", pady=3); ttk.Label(row, text=label, width=14).pack(side="left"); ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        for label, var in (("头顶可见名称", self.npc_visible_name_var), ("Y坐标", self.npc_y_var), ("外观编号", self.npc_appearance_var), ("外观补丁组", self.npc_patch_library_var), ("补丁图片编号", self.npc_patch_index_var)):
            row = ttk.Frame(right); row.pack(fill="x", pady=3); ttk.Label(row, text=label, width=14).pack(side="left"); ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        source = ttk.Frame(tab); source.pack(fill="x", padx=12, pady=3)
        target = ttk.Frame(tab); target.pack(fill="x", padx=12, pady=3)
        ttk.Label(target, text="目标服务端", width=14).pack(side="left")
        ttk.Entry(target, textvariable=self.npc_server_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(target, text="浏览", command=lambda: self._choose_dir(self.npc_server_var)).pack(side="left")
        ttk.Label(source, text="客户端 data", width=14).pack(side="left")
        ttk.Entry(source, textvariable=self.npc_client_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(source, text="浏览", command=lambda: self._choose_dir(self.npc_client_var)).pack(side="left")
        patch = ttk.Frame(tab); patch.pack(fill="x", padx=12, pady=3)
        ttk.Label(patch, text="补丁来源", width=14).pack(side="left")
        ttk.Entry(patch, textvariable=self.npc_patch_source_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(patch, text="选择 Npc.wzx", command=self._choose_npc_patch).pack(side="left")
        ttk.Label(patch, text="状态").pack(side="left", padx=(10, 4))
        ttk.Combobox(patch, textvariable=self.npc_patch_status_var, values=("manual-required", "source-selected", "reuse-installed"), state="readonly", width=16).pack(side="left")
        actions = ttk.Frame(tab); actions.pack(fill="x", padx=12, pady=6)
        ttk.Button(actions, text="扫描客户端NPC外观", command=self.npc_scan_appearances).pack(side="left")
        ttk.Button(actions, text="基础对话模板", command=self.npc_dialogue_template).pack(side="left", padx=6)
        ttk.Button(actions, text="保存草稿", command=self.npc_save_draft).pack(side="left", padx=6)
        ttk.Button(actions, text="导入草稿", command=self.npc_load_draft).pack(side="left", padx=6)
        ttk.Button(actions, text="预检直接导入", command=self.npc_direct_preflight).pack(side="left", padx=12)
        ttk.Button(actions, text="确认直接导入当前服务端", command=self.npc_direct_import).pack(side="left", padx=6)
        ttk.Button(actions, text="国王模式NPC预设", command=self.king_mode_npc_dialog).pack(side="left", padx=12)
        ttk.Button(actions, text="初始之地七NPC", command=self.initial_camp_dialog).pack(side="left", padx=6)
        ttk.Button(actions, text="神印与称号双NPC", command=self.seal_title_dialog).pack(side="left", padx=6)
        ttk.Label(actions, text="筛选外观").pack(side="left", padx=(18, 4))
        ttk.Entry(actions, textvariable=self.npc_filter_var, width=18).pack(side="left")
        ttk.Button(actions, text="过滤", command=self.npc_render_appearances).pack(side="left", padx=4)
        split = ttk.PanedWindow(tab, orient="vertical"); split.pack(fill="both", expand=True, padx=12, pady=6)
        appearance_frame = ttk.Labelframe(split, text="可选 NPC 外观（双击选择）")
        self.npc_appearance_tree = ttk.Treeview(appearance_frame, columns=("library", "index", "state", "wzx"), show="headings", height=7)
        for key, title, width in (("library", "补丁组", 100), ("index", "图片编号", 90), ("state", "索引状态", 100), ("wzx", "来源", 520)):
            self.npc_appearance_tree.heading(key, text=title); self.npc_appearance_tree.column(key, width=width)
        self.npc_appearance_tree.pack(fill="both", expand=True)
        self.npc_appearance_tree.bind("<Double-1>", lambda _event: self.npc_select_appearance())
        split.add(appearance_frame, weight=1)
        dialogue_frame = ttk.Labelframe(split, text="NPC对话脚本（完整文本，必须包含 [@Main] 和 #SAY）")
        self.npc_script_text = tk.Text(dialogue_frame, height=10, wrap="none")
        self.npc_script_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.npc_dialogue_template()
        split.add(dialogue_frame, weight=2)
        report_frame = ttk.Labelframe(tab, text="直接导入预检摘要")
        self.npc_direct_report = tk.Text(report_frame, height=5, wrap="none")
        self.npc_direct_report.pack(fill="both", expand=True, padx=5, pady=5)
        report_frame.pack(fill="x", padx=12, pady=(0, 8))

    def _npc_draft_from_ui(self) -> NpcDraft:
        return NpcDraft(
            package_id=self.npc_package_id_var.get(),
            display_name=self.npc_display_name_var.get(),
            script_path=self.npc_script_path_var.get(),
            map_code=self.npc_map_var.get(),
            x=self.npc_x_var.get(),
            y=self.npc_y_var.get(),
            visible_name=self.npc_visible_name_var.get(),
            appearance=self.npc_appearance_var.get(),
            patch_library=self.npc_patch_library_var.get(),
            patch_index=self.npc_patch_index_var.get(),
            patch_source=self.npc_patch_source_var.get(),
            patch_status=self.npc_patch_status_var.get(),
            script_text=self.npc_script_text.get("1.0", "end"),
        )

    def _npc_apply_draft(self, draft: NpcDraft):
        self.npc_package_id_var.set(draft.package_id)
        self.npc_display_name_var.set(draft.display_name)
        self.npc_script_path_var.set(draft.script_path)
        self.npc_map_var.set(draft.map_code)
        self.npc_x_var.set(str(draft.x)); self.npc_y_var.set(str(draft.y))
        self.npc_visible_name_var.set(draft.visible_name)
        self.npc_appearance_var.set(str(draft.appearance))
        self.npc_patch_library_var.set(draft.patch_library)
        self.npc_patch_index_var.set(str(draft.patch_index))
        self.npc_patch_source_var.set(draft.patch_source)
        self.npc_patch_status_var.set(draft.patch_status)
        self._write(self.npc_script_text, draft.script_text)

    def npc_dialogue_template(self):
        self._write(self.npc_script_text, "[@Main]\n#SAY\n欢迎来到新NPC。\\\n<关闭/@exit>\n")

    def _choose_npc_patch(self):
        selected = filedialog.askopenfilename(title="选择客户端 Npc*.wzx", filetypes=[("NPC索引", "Npc*.wzx"), ("所有文件", "*.*")])
        if selected:
            path = Path(selected)
            self.npc_patch_source_var.set(str(path))
            self.npc_patch_library_var.set(path.stem)
            self.npc_patch_status_var.set("source-selected")
            self.npc_scan_appearances()

    def npc_scan_appearances(self):
        try:
            rows = scan_npc_appearances(Path(self.npc_client_var.get()))
            self.npc_appearance_rows = rows
            self.npc_render_appearances()
            self._write(self.npc_script_text, self.npc_script_text.get("1.0", "end"))
            messagebox.showinfo("NPC外观扫描完成", f"已读取 {len(rows)} 个 NPC 图片索引；双击列表中的编号即可选择。")
        except Exception as exc:
            messagebox.showerror("NPC外观扫描失败", str(exc))

    def npc_render_appearances(self):
        if not hasattr(self, "npc_appearance_tree"):
            return
        for item in self.npc_appearance_tree.get_children():
            self.npc_appearance_tree.delete(item)
        keyword = self.npc_filter_var.get().strip().lower()
        for row in self.npc_appearance_rows:
            marker = f"{row['library']} {row['index']} {row['wzx']}".lower()
            if keyword and keyword not in marker:
                continue
            state = "空索引" if row["empty"] else "可用索引"
            iid = f"{row['library']}:{row['index']}"
            self.npc_appearance_tree.insert("", "end", iid=iid, values=(row["library"], row["index"], state, row["wzx"]))

    def npc_select_appearance(self):
        selected = self.npc_appearance_tree.selection()
        if not selected:
            return
        item = self.npc_appearance_tree.item(selected[0])
        library = str(item["values"][0]); index = int(item["values"][1])
        match = next((row for row in self.npc_appearance_rows if row["library"] == library and row["index"] == index), None)
        if match is None:
            return
        if match["empty"]:
            messagebox.showwarning("空外观索引", "这个编号在 WZX 中是空索引，请选择可用索引。")
            return
        self.npc_patch_library_var.set(library)
        self.npc_patch_index_var.set(str(index))
        self.npc_appearance_var.set(str(index))
        self.npc_patch_source_var.set(match["wzx"])
        self.npc_patch_status_var.set("source-selected")

    def npc_save_draft(self):
        try:
            draft = self._npc_draft_from_ui()
            safe_id = draft.package_id.replace("/", "-").replace("\\", "-")
            path = save_draft(draft, self.platform_root / "migration" / "npc_drafts" / f"{safe_id}.json")
            messagebox.showinfo("NPC草稿已保存", str(path))
        except Exception as exc:
            messagebox.showerror("NPC草稿保存失败", str(exc))

    def npc_load_draft(self):
        selected = filedialog.askopenfilename(title="导入NPC草稿", initialdir=str(self.platform_root / "migration" / "npc_drafts"), filetypes=[("NPC草稿", "*.json")])
        if not selected:
            return
        try:
            self._npc_apply_draft(load_draft(Path(selected)))
        except Exception as exc:
            messagebox.showerror("NPC草稿导入失败", str(exc))

    def npc_create_package(self):
        try:
            draft = self._npc_draft_from_ui()
            if draft.patch_status == "manual-required":
                if not messagebox.askyesno("客户端补丁尚未选择", "当前没有选择 Npc*.wzx 外观来源。仍生成候选包，但安装前必须补齐或复用客户端补丁，是否继续？"):
                    return
            package_root = create_npc_package(draft, self.platform_root)
            self.repository.refresh()
            self.show_candidate_var.set(True)
            self.refresh_packages()
            messagebox.showinfo("NPC候选成果包已生成", str(package_root))
        except Exception as exc:
            messagebox.showerror("NPC成果包生成失败", str(exc))

    def npc_direct_preflight(self):
        try:
            self.current_npc_direct_plan = direct_preflight(self._npc_draft_from_ui(), Path(self.npc_server_var.get()))
            plan = self.current_npc_direct_plan
            summary = {
                "operation": plan.operation,
                "target": str(plan.target.root),
                "npc": plan.draft.display_name,
                "script_path": plan.draft.script_path,
                "map": plan.draft.map_code,
                "blockers": plan.blockers,
                "warnings": plan.warnings,
                "changes": [{"path": item.relative_path, "operation": item.operation, "created": item.before is None, "changed": item.before != item.after} for item in plan.changes],
            }
            self._write(self.npc_direct_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if plan.blockers:
                messagebox.showerror("NPC直接导入被阻止", "\n".join(plan.blockers))
            else:
                messagebox.showinfo("NPC直接导入预检通过", "可以点击“确认直接导入当前服务端”。")
        except Exception as exc:
            messagebox.showerror("NPC直接导入预检失败", str(exc))

    def npc_direct_import(self):
        if self.current_npc_direct_plan is None:
            self.npc_direct_preflight()
        plan = self.current_npc_direct_plan
        if plan is None or plan.blockers:
            return
        if not messagebox.askyesno("NPC直接导入确认", f"将向 {plan.target.root} 写入 NPC 脚本和 MerChant 注册行，确认继续？"):
            return
        try:
            receipt = direct_install(plan, self.installer)
            self.current_npc_direct_plan = None
            self._write(self.npc_direct_report, json.dumps({"transaction": receipt.transaction_id, "operation": receipt.operation_type, "target": receipt.target_root, "changes": receipt.changes}, ensure_ascii=False, indent=2))
            self.refresh_history()
            messagebox.showinfo("NPC直接导入完成", f"事务：{receipt.transaction_id}\n请重载/重启 M2 后进游戏验收。")
        except Exception as exc:
            messagebox.showerror("NPC直接导入失败", str(exc))

    def king_mode_npc_dialog(self):
        """打开国王模式四个 NPC 的批量直接导入窗口。"""
        win = tk.Toplevel(self)
        win.title("国王模式完整活动预设（XYGDZY）")
        win.geometry("720x610")
        win.transient(self)
        fields = [
            ("地图代码", "map_code", "XYGDZY"),
            ("A打坐X", "a_recovery_x", "20"), ("A打坐Y", "a_recovery_y", "50"),
            ("B打坐X", "b_recovery_x", "95"), ("B打坐Y", "b_recovery_y", "50"),
            ("破釜沉舟X", "breakthrough_x", "58"), ("破釜沉舟Y", "breakthrough_y", "50"),
            ("恶魔契约X", "demon_x", "58"), ("恶魔契约Y", "demon_y", "55"),
            ("打坐A外观", "appearance_recovery_a", "0"), ("打坐B外观", "appearance_recovery_b", "0"),
            ("破釜沉舟外观", "appearance_breakthrough", "0"), ("恶魔契约外观", "appearance_demon", "0"),
        ]
        vars_map = {key: tk.StringVar(value=value) for _label, key, value in fields}
        form = ttk.Frame(win); form.pack(fill="x", padx=12, pady=10)
        for index, (label, key, _default) in enumerate(fields):
            row = index // 2; col = (index % 2) * 2
            ttk.Label(form, text=label, width=16).grid(row=row, column=col, sticky="w", padx=4, pady=4)
            ttk.Entry(form, textvariable=vars_map[key], width=20).grid(row=row, column=col + 1, sticky="ew", padx=4, pady=4)
        form.columnconfigure(1, weight=1); form.columnconfigure(3, weight=1)
        ttk.Label(win, text="此预设会把核心脚本、配置/状态文件、4个NPC、MerChant注册、登录入口、QFunction和QManage一次性纳入事务。复活点默认 A(15,50)、B(100,50)。", foreground="#8a4b08", wraplength=680).pack(anchor="w", padx=12, pady=(0, 6))
        report = tk.Text(win, height=17, wrap="none"); report.pack(fill="both", expand=True, padx=12, pady=6)

        def make_config() -> KingModeNpcConfig:
            return KingModeNpcConfig(**{key: vars_map[key].get() for _label, key, _default in fields})

        def preflight():
            try:
                server = self.npc_server_var.get().strip() or self.server_var.get().strip()
                if not server:
                    raise NpcEditorError("请先选择目标服务端目录")
                plan = king_mode_preflight(make_config(), Path(server))
                self.current_king_mode_npc_plan = plan
                summary = {
                    "operation": plan.operation,
                    "target": str(plan.target.root),
                    "map": plan.drafts[0].map_code if plan.drafts else "",
                    "npcs": [{"name": item.visible_name, "script": item.script_path, "x": item.x, "y": item.y, "appearance": item.appearance} for item in plan.drafts],
                    "blockers": plan.blockers,
                    "warnings": plan.warnings,
                    "changes": [{"path": item.relative_path, "operation": item.operation, "changed": item.before != item.after} for item in plan.changes],
                }
                self._write(report, json.dumps(summary, ensure_ascii=False, indent=2))
                if plan.blockers:
                    messagebox.showerror("国王模式 NPC 预设被阻止", "\n".join(plan.blockers), parent=win)
                else:
                    messagebox.showinfo("国王模式完整活动预检通过", "核心文件、NPC注册和运行入口均已纳入计划，可以点击确认直接导入。", parent=win)
            except Exception as exc:
                messagebox.showerror("国王模式 NPC 预检失败", str(exc), parent=win)

        def install():
            if self.current_king_mode_npc_plan is None:
                preflight()
            plan = self.current_king_mode_npc_plan
            if plan is None or plan.blockers:
                return
            if not messagebox.askyesno("国王模式完整活动导入确认", "将一次性写入核心脚本、配置/状态文件、4个NPC、MerChant注册、登录入口、QFunction和QManage，确认继续？", parent=win):
                return
            try:
                receipt = direct_install(plan, self.installer)
                self.current_king_mode_npc_plan = None
                self.refresh_history()
                self._write(report, json.dumps({"transaction": receipt.transaction_id, "operation": receipt.operation_type, "target": receipt.target_root, "changes": receipt.changes}, ensure_ascii=False, indent=2))
                messagebox.showinfo("国王模式完整活动导入完成", f"事务：{receipt.transaction_id}\n请重载/重启 M2 后验收。", parent=win)
            except Exception as exc:
                messagebox.showerror("国王模式 NPC 导入失败", str(exc), parent=win)

        actions = ttk.Frame(win); actions.pack(fill="x", padx=12, pady=8)
        ttk.Button(actions, text="预检预设", command=preflight).pack(side="left")
        ttk.Button(actions, text="确认直接导入", command=install).pack(side="left", padx=8)
        ttk.Button(actions, text="关闭", command=win.destroy).pack(side="right")

    def initial_camp_dialog(self):
        """七个独立NPC共用一个材料表目录和一个服务端/客户端安装事务。"""
        win = tk.Toplevel(self)
        win.title("初始之地七NPC导入")
        win.geometry("900x650")
        win.transient(self)
        ttk.Label(
            win,
            text="读取七个XLSX，在 xycamp 出生点附近自动选择可走空位；赞助说明同步到已选客户端，狂暴只迁移入口。",
            wraplength=850,
            foreground="#7a4300",
        ).pack(anchor="w", padx=12, pady=(12, 6))
        row = ttk.Frame(win); row.pack(fill="x", padx=12, pady=4)
        ttk.Label(row, text="材料表文件夹", width=14).pack(side="left")
        ttk.Entry(row, textvariable=self.initial_camp_materials_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="选择", command=lambda: self._choose_dir(self.initial_camp_materials_var)).pack(side="left")
        ttk.Button(row, text="打开", command=lambda: os.startfile(self.initial_camp_materials_var.get())).pack(side="left", padx=6)
        report = tk.Text(win, wrap="none")
        report.pack(fill="both", expand=True, padx=12, pady=8)

        def preflight():
            try:
                server = self.npc_server_var.get().strip() or self.server_var.get().strip()
                if not server:
                    raise NpcEditorError("请先在目标管理选择服务端")
                client = self.client_var.get().strip()
                if not client:
                    raise NpcEditorError("请先在目标管理选择客户端，赞助称号说明需要同步客户端")
                plan = self.initial_camp.preflight(
                    Path(server), Path(self.initial_camp_materials_var.get()), Path(client)
                )
                self.current_initial_camp_plan = plan
                summary = {
                    "operation": plan.operation, "server": plan.server, "client": plan.client,
                    "materials": plan.materials,
                    "materials_hash": plan.materials_hash, "npcs": [asdict(item) for item in plan.npcs],
                    "blockers": plan.blockers, "warnings": plan.warnings,
                    "changes": [{"path": item.relative_path, "scope": item.scope,
                                 "operation": item.operation, "changed": item.before != item.after}
                                 for item in plan.changes],
                }
                self._write(report, json.dumps(summary, ensure_ascii=False, indent=2))
                if plan.blockers:
                    messagebox.showerror("初始之地七NPC预检阻止", "\n".join(plan.blockers), parent=win)
                else:
                    messagebox.showinfo("预检通过", "七个NPC、材料配置、称号显示和实效链已纳入同一事务，可以确认导入。", parent=win)
            except Exception as exc:
                messagebox.showerror("预检失败", str(exc), parent=win)

        def install():
            if self.current_initial_camp_plan is None:
                preflight()
            plan = self.current_initial_camp_plan
            if plan is None or plan.blockers:
                return
            if not messagebox.askyesno(
                "初始之地七NPC导入确认",
                "确认备份后写入七个NPC、MerChant、称号数据库、公共接口和客户端称号说明？\n未配置项目只显示待配置，不会扣材料。",
                parent=win,
            ):
                return
            try:
                receipt = self.initial_camp.install(plan)
                self.current_initial_camp_plan = None
                self.refresh_history()
                self._write(report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
                messagebox.showinfo("导入完成", f"事务：{receipt.transaction_id}\n请由你重载/重启M2后游戏验收。", parent=win)
            except Exception as exc:
                messagebox.showerror("导入失败", str(exc), parent=win)

        def rollback():
            server = self.npc_server_var.get().strip() or self.server_var.get().strip()
            if not server or not messagebox.askyesno("回滚确认", "确认逐字节回滚最近一次初始之地七NPC导入？", parent=win):
                return
            try:
                transaction = self.initial_camp.rollback_latest(Path(server))
                self.current_initial_camp_plan = None
                self._write(report, json.dumps({"rolled_back": transaction}, ensure_ascii=False, indent=2))
                self.refresh_history()
                messagebox.showinfo("回滚完成", transaction, parent=win)
            except Exception as exc:
                messagebox.showerror("回滚失败", str(exc), parent=win)

        actions = ttk.Frame(win); actions.pack(fill="x", padx=12, pady=8)
        ttk.Button(actions, text="读取并预检", command=preflight).pack(side="left")
        ttk.Button(actions, text="确认一键导入", command=install).pack(side="left", padx=8)
        ttk.Button(actions, text="回滚最近导入", command=rollback).pack(side="left", padx=8)
        ttk.Button(actions, text="关闭", command=win.destroy).pack(side="right")

    def seal_title_dialog(self):
        """独立候选：读取21/22号表，生成神印基础属性与称号晋升双NPC。"""
        win = tk.Toplevel(self)
        win.title("神印基础属性与称号晋升双NPC")
        win.geometry("920x680")
        win.transient(self)
        ttk.Label(
            win,
            text=(
                "只读取21_神印基础属性.xlsx与22_称号晋升.xlsx。空表只生成“待配置”NPC；"
                "填写完整后才会生成属性、称号数据库和基础爆率链。当前候选不会替换xy.ops.title。"
            ),
            wraplength=875,
            foreground="#7a4300",
        ).pack(anchor="w", padx=12, pady=(12, 6))
        row = ttk.Frame(win); row.pack(fill="x", padx=12, pady=4)
        ttk.Label(row, text="材料表文件夹", width=14).pack(side="left")
        ttk.Entry(row, textvariable=self.initial_camp_materials_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="选择", command=lambda: self._choose_dir(self.initial_camp_materials_var)).pack(side="left")
        ttk.Button(row, text="打开", command=lambda: os.startfile(self.initial_camp_materials_var.get())).pack(side="left", padx=6)
        report = tk.Text(win, wrap="none")
        report.pack(fill="both", expand=True, padx=12, pady=8)

        def preflight():
            try:
                server = self.npc_server_var.get().strip() or self.server_var.get().strip()
                if not server:
                    raise NpcEditorError("请先在目标管理选择服务端")
                client_text = self.client_var.get().strip()
                plan = self.seal_title.preflight(
                    Path(server),
                    Path(self.initial_camp_materials_var.get()),
                    Path(client_text) if client_text else None,
                )
                self.current_seal_title_plan = plan
                summary = {
                    "operation": plan.operation, "server": plan.server, "client": plan.client,
                    "materials": plan.materials, "materials_hash": plan.materials_hash,
                    "npcs": [asdict(item) for item in plan.npcs],
                    "blockers": plan.blockers, "warnings": plan.warnings,
                    "changes": [
                        {"path": item.relative_path, "scope": item.scope,
                         "operation": item.operation, "changed": item.before != item.after}
                        for item in plan.changes
                    ],
                }
                self._write(report, json.dumps(summary, ensure_ascii=False, indent=2))
                if plan.blockers:
                    messagebox.showerror("神印与称号双NPC预检阻止", "\n".join(plan.blockers), parent=win)
                else:
                    messagebox.showinfo(
                        "预检通过",
                        "已生成只读差异计划。待配置表只会得到待配置NPC，不会写有效升级逻辑。",
                        parent=win,
                    )
            except Exception as exc:
                messagebox.showerror("预检失败", str(exc), parent=win)

        def install():
            if self.current_seal_title_plan is None:
                preflight()
            plan = self.current_seal_title_plan
            if plan is None or plan.blockers:
                return
            if not messagebox.askyesno(
                "候选双NPC导入确认",
                "确认备份后写入本次预检列出的候选脚本与NPC注册？\n当前不会替换xy.ops.title。",
                parent=win,
            ):
                return
            try:
                receipt = self.seal_title.install(plan)
                self.current_seal_title_plan = None
                self.refresh_history()
                self._write(report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
                messagebox.showinfo("导入完成", f"事务：{receipt.transaction_id}\n请由你决定何时重载M2并游戏验收。", parent=win)
            except Exception as exc:
                messagebox.showerror("导入失败", str(exc), parent=win)

        def rollback():
            server = self.npc_server_var.get().strip() or self.server_var.get().strip()
            if not server or not messagebox.askyesno("回滚确认", "确认逐字节回滚最近一次神印与称号双NPC安装？", parent=win):
                return
            try:
                transaction = self.seal_title.rollback_latest(Path(server))
                self.current_seal_title_plan = None
                self._write(report, json.dumps({"rolled_back": transaction}, ensure_ascii=False, indent=2))
                self.refresh_history()
                messagebox.showinfo("回滚完成", transaction, parent=win)
            except Exception as exc:
                messagebox.showerror("回滚失败", str(exc), parent=win)

        actions = ttk.Frame(win); actions.pack(fill="x", padx=12, pady=8)
        ttk.Button(actions, text="读取21/22并预检", command=preflight).pack(side="left")
        ttk.Button(actions, text="确认安装", command=install).pack(side="left", padx=8)
        ttk.Button(actions, text="回滚最近导入", command=rollback).pack(side="left", padx=8)
        ttk.Button(actions, text="关闭", command=win.destroy).pack(side="right")

    def _choose_dir(self, variable):
        selected = filedialog.askdirectory()
        if selected: variable.set(selected)

    def _choose_file(self, variable, filetypes):
        selected = filedialog.askopenfilename(filetypes=filetypes)
        if selected: variable.set(selected)

    def _choose_monster_sidecar(self):
        selected = filedialog.askopenfilename(filetypes=[("PAK桥接索引", "*.sidecar.json"), ("JSON", "*.json")])
        if selected: self.monster_sidecar_var.set(selected)

    def _choose_monster_workbook(self):
        selected = filedialog.askopenfilename(
            initialdir=str(self.platform_root / "所需材料表格汇总"),
            filetypes=[("怪物生成表", "*.xlsx")],
        )
        if selected:
            self.monster_workbook_var.set(selected)
            self.current_monster_workbook_plan = None

    def monster_scan(self):
        if not messagebox.askyesno(
            "明月怪物资料入库确认",
            "将按引擎规则只读扫描供体并重建V3怪物库：普通怪物按标准Appr资源闭包，\n"
            "SmartMonster按同名INI、EffectImageList及全部动作依赖闭包入库。确认继续？",
        ):
            return
        try:
            result = self.monster_library.scan(
                Path(self.monster_donor_db_var.get()),
                Path(self.monster_donor_wzl_var.get()),
                Path(self.monster_donor_pak_var.get()),
                Path(self.monster_donor_rules_var.get()),
                Path(self.monster_server_var.get()),
                Path(self.monster_client_var.get()),
                materialize=True,
            )
            summary = asdict(result)
            summary["localized_gib"] = round(result.localized_bytes / 1024 ** 3, 3)
            self._write(self.monster_report, json.dumps(summary, ensure_ascii=False, indent=2))
            self.monster_status_var.set("可植入")
            self.monster_refresh()
            messagebox.showinfo(
                "怪物库重建完成",
                f"怪物记录：{result.total_monsters}\n可植入：{result.ready}\n本端已有：{result.existing}\n已跳过：{result.skipped}\n"
                f"本地化图库：{result.localized_libraries}",
            )
        except Exception as exc:
            messagebox.showerror("怪物库重建失败", str(exc))

    def monster_import_sidecars(self):
        try:
            result = self.monster_library.import_sidecars(Path(self.monster_sidecar_var.get()))
            self._write(self.monster_report, json.dumps(asdict(result), ensure_ascii=False, indent=2))
            self.monster_refresh()
            messagebox.showinfo("桥接缩略图已导入", f"更新怪物：{result.updated_monsters}\n跳过索引：{result.skipped_sidecars}")
        except Exception as exc:
            messagebox.showerror("桥接索引导入失败", str(exc))

    def monster_refresh(self):
        status_key = {"可植入": "ready", "本端已有": "existing", "已跳过": "skipped", "全部": "all"}.get(
            self.monster_status_var.get(), "ready"
        )
        records = self.monster_library.list_monsters(status_key, Path(self.monster_server_var.get()))
        filter_text = self.monster_filter_var.get().strip().casefold()
        if filter_text:
            records = [
                item for item in records
                if filter_text in str(item.monster_id).casefold()
                or filter_text in item.monster_name.casefold()
                or filter_text in str(item.appearance_id).casefold()
                or filter_text in f"mon{item.library_no}".casefold()
            ]
        for item in self.monster_tree.get_children():
            self.monster_tree.delete(item)
        self.monster_preview_images.clear()
        for record in records:
            image_object = None
            if record.preview_path and Path(record.preview_path).is_file():
                try:
                    image_object = tk.PhotoImage(file=record.preview_path)
                    factor = max(1, (max(image_object.width(), image_object.height()) + 83) // 84)
                    if factor > 1:
                        image_object = image_object.subsample(factor, factor)
                    self.monster_preview_images[record.monster_id] = image_object
                except Exception:
                    image_object = None
            row = list(self._monster_tree_row(record))
            row[0] = "已索引" if image_object else "待桥接"
            insert_options = {
                "iid": str(record.monster_id),
                "text": row[0],
                "values": tuple(row[1:]),
            }
            if image_object is not None:
                insert_options["image"] = image_object
            self.monster_tree.insert("", "end", **insert_options)

    @staticmethod
    def _monster_tree_row(record) -> tuple[object, ...]:
        try:
            manifest = json.loads(record.resource_manifest_json or "[]")
        except (TypeError, json.JSONDecodeError):
            manifest = []
        dependency_count = len(manifest) if isinstance(manifest, list) else 0
        engine_label = {
            "standard_appr": "普通Appr",
            "smartmonster": "SmartMonster",
        }.get(record.engine_mode, record.engine_mode)
        closure_label = {
            "ready_verified": "已验证",
            "ready_opaque": "待单怪验收",
            "incomplete": "闭包不完整",
            "complex_ability": "复杂能力",
        }.get(record.closure_status, record.closure_status)
        login_label = {
            "none": "按需重生成登录器",
            "standard_launcher": "按需重生成登录器",
            "custom_monster_dat_required": "待生成DAT/登录器",
            "custom_monster_dat": "待生成DAT/登录器",
        }.get(record.login_policy, record.login_policy)
        preview_label = "已索引" if record.preview_path and Path(record.preview_path).is_file() else "待桥接"
        description = record.skip_reason or ("完整引擎闭包" if record.status == "ready" else "")
        return (
            preview_label,
            record.monster_id,
            record.monster_name,
            engine_label,
            record.appearance_id,
            closure_label,
            dependency_count,
            login_label,
            description,
        )

    @staticmethod
    def _monster_engine_summary(plan) -> MonsterEngineUiSummary | None:
        if not bool(getattr(plan, "requires_custom_monster_dat", False)):
            return None
        server_root = Path(plan.server_root)
        generated_ini_paths: list[Path] = []
        for value in getattr(plan, "generated_files_after", {}):
            candidate = Path(value)
            if candidate.suffix.casefold() != ".ini":
                continue
            generated_ini_paths.append(candidate if candidate.is_absolute() else server_root / candidate)
        assignments = tuple(getattr(plan, "engine_assignments", ()))
        target_entries: set[tuple[str, object]] = set()
        for assignment in assignments:
            target_index = assignment.get("target_index")
            target_entry = assignment.get("target_entry")
            if target_index is not None:
                target_entries.add(("index", int(target_index)))
            elif target_entry:
                target_entries.add(("entry", str(target_entry).casefold()))
        effect_list = server_root / "Mir200" / "Envir" / "EffectImageList.txt"
        status = verify_custom_monster_login(
            Path(getattr(plan, "generator_login_dir", None) or default_generator_login_dir(server_root)),
            Path(
                getattr(plan, "custom_monster_dat_path", "")
                or server_root / "Mir200" / "自定义怪物.dat"
            ),
            Path(plan.client_data).parent / "传奇登陆器.exe",
            (effect_list, *generated_ini_paths),
        )
        return MonsterEngineUiSummary(
            ini_count=len(generated_ini_paths),
            dependency_count=len(assignments),
            target_effect_entry_count=len(target_entries),
            login_status=status.status,
            next_step=status.next_step,
        )

    @staticmethod
    def _monster_engine_summary_text(plan) -> str:
        summary = PlatformApp._monster_engine_summary(plan)
        if summary is None:
            return ""
        return PlatformApp._format_monster_engine_summary(summary)

    @staticmethod
    def _format_monster_engine_summary(summary: MonsterEngineUiSummary) -> str:
        return (
            f"SmartMonster闭包：INI数：{summary.ini_count}　依赖映射：{summary.dependency_count}　"
            f"目标EffectImageList条目：{summary.target_effect_entry_count}\n"
            f"真实登录状态：{summary.login_status}\n{summary.next_step}"
        )

    @staticmethod
    def _with_monster_engine_summary(plan, message: str) -> str:
        summary = PlatformApp._monster_engine_summary_text(plan)
        return f"{message}\n{summary}" if summary else message

    def monster_select_ready(self):
        self.monster_status_var.set("可植入")
        self.monster_refresh()
        self.monster_tree.selection_set(self.monster_tree.get_children())

    def monster_preflight(self):
        selected = [int(item) for item in self.monster_tree.selection()]
        try:
            server_root = Path(self.monster_server_var.get())
            self.current_monster_plan = self.monster_library.preflight(
                selected,
                server_root,
                Path(self.monster_client_var.get()),
                generator_login_dir=default_generator_login_dir(server_root),
            )
            summary = MonsterLibraryService.plan_summary(self.current_monster_plan)
            self._write(self.monster_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if self.current_monster_plan.blockers:
                messagebox.showerror("怪物库预检阻止", "\n".join(self.current_monster_plan.blockers))
            else:
                messagebox.showinfo(
                    "怪物库预检通过",
                    PlatformApp._with_monster_engine_summary(
                        self.current_monster_plan,
                        f"选择库编号：{len(selected)}\n将写入怪物：{len(self.current_monster_plan.monster_names)}\n"
                        f"涉及完整补丁：{len(self.current_monster_plan.library_numbers)}\n"
                        f"自动跳过：{len(self.current_monster_plan.skipped)}",
                    ),
                )
        except Exception as exc:
            messagebox.showerror("怪物库预检失败", str(exc))

    def monster_install(self):
        plan = self.current_monster_plan
        if plan is None:
            messagebox.showwarning("尚未预检", "请先选择编号并点击“预检选中”。")
            return
        if plan.blockers:
            messagebox.showerror("禁止植入", "预检报告仍有阻止项。")
            return
        if not messagebox.askyesno(
            "怪物库一键植入确认",
            PlatformApp._with_monster_engine_summary(
                plan,
                f"将向目标 Monster 数据库新增 {len(plan.monster_names)} 只怪物，"
                f"并向 {plan.client_data} 同步 {len(plan.library_numbers)} 组正确动作补丁。\n"
                "同名怪物不会覆盖；不修改爆率、刷怪和地图脚本。请确认M2已关闭后继续。",
            ),
        ):
            return
        try:
            receipt = self.monster_library.install(plan)
            self.monster_transaction_var.set(receipt.transaction_id)
            self.current_monster_plan = None
            launcher_message = self._prepare_monster_login_generator(plan)
            messagebox.showinfo(
                "怪物库植入完成",
                f"事务：{receipt.transaction_id}\n怪物：{len(receipt.monster_names)}\n"
                f"补丁：{len(receipt.library_numbers)}\n{launcher_message}",
            )
        except Exception as exc:
            messagebox.showerror("怪物库植入失败", str(exc))

    def monster_workbook_preflight(self, show_success: bool = True) -> bool:
        try:
            server_root = Path(self.monster_server_var.get())
            self.current_monster_workbook_plan = self.monster_workbook.preflight(
                Path(self.monster_workbook_var.get()),
                server_root,
                Path(self.monster_client_var.get()),
                generator_login_dir=default_generator_login_dir(server_root),
            )
            plan = self.current_monster_workbook_plan
            summary = self.monster_workbook.plan_summary(plan)
            self._write(self.monster_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if plan.blockers:
                messagebox.showerror("怪物生成表预检阻止", "\n".join(plan.blockers))
                return False
            if show_success:
                messagebox.showinfo(
                    "怪物生成表预检通过",
                    PlatformApp._with_monster_engine_summary(
                        plan,
                        f"总处理怪物：{len(plan.monster_names)}\n"
                        f"新增：{len(plan.inserted_names)}　更新属性：{len(plan.updated_names)}\n"
                        f"显式换模：{len(plan.appearance_changed_names)}　自动兼容改选：{len(plan.auto_reselected)}\n"
                        f"已是目标值：{len(plan.unchanged_names)}　动作补丁：{len(plan.library_numbers)}\n"
                        f"名字颜色：{sum(item['matched_rows'] for item in plan.name_color_assignments)}条刷新记录\n"
                        f"跳过：{len(plan.skipped)}",
                    ),
                )
            return True
        except Exception as exc:
            messagebox.showerror("怪物生成表预检失败", str(exc))
            return False

    def monster_workbook_install(self):
        if not self.monster_workbook_preflight(show_success=False):
            return
        plan = self.current_monster_workbook_plan
        if plan is None:
            return
        if plan.blockers:
            messagebox.showerror("禁止批量生成", "预检报告仍有阻止项。")
            return
        if not messagebox.askyesno(
            "怪物批量同步确认",
            PlatformApp._with_monster_engine_summary(
                plan,
                f"将处理 {len(plan.monster_names)} 只怪物：新增 {len(plan.inserted_names)}，"
                f"更新属性 {len(plan.updated_names)}，显式换模 {len(plan.appearance_changed_names)}。\n"
                f"同步 {len(plan.library_numbers)} 组完整动作补丁；自动兼容改选 {len(plan.auto_reselected)}。\n"
                f"同步名字颜色到 {sum(item['matched_rows'] for item in plan.name_color_assignments)} 条已有MonGen记录。\n"
                "已有怪模型留空时保持当前外观；不新增刷怪，不修改位置、数量、间隔、爆率、地图或AI。请确认M2已关闭后继续。",
            ),
        ):
            return
        try:
            receipt = self.monster_workbook.install(plan)
            self.monster_transaction_var.set(receipt.transaction_id)
            self.current_monster_workbook_plan = None
            launcher_message = self._prepare_monster_login_generator(plan)
            messagebox.showinfo(
                "怪物批量同步完成",
                f"事务：{receipt.transaction_id}\n总处理：{len(plan.monster_names)}\n"
                f"新增：{len(plan.inserted_names)}　更新：{len(plan.updated_names)}\n"
                f"补丁：{len(receipt.library_numbers)}　颜色记录：{sum(item['matched_rows'] for item in plan.name_color_assignments)}\n"
                f"{launcher_message}",
            )
        except Exception as exc:
            messagebox.showerror("怪物批量同步失败", str(exc))

    @staticmethod
    def _prepare_monster_login_generator(plan) -> str:
        smart_summary = PlatformApp._monster_engine_summary(plan)
        if smart_summary is not None:
            summary_text = PlatformApp._format_monster_engine_summary(smart_summary)
            generator_dir = Path(
                getattr(plan, "generator_login_dir", None)
                or default_generator_login_dir(Path(plan.server_root))
            )
            executable = generator_dir / "MakeGameLogin.exe"
            if smart_summary.login_status == "missing_dat":
                action = f"请先生成自定义怪物DAT。{smart_summary.next_step}"
            elif smart_summary.login_status == "generator_not_configured":
                action = (
                    f"请手动打开：{executable}，配置自定义怪物DAT集成。"
                    f"{smart_summary.next_step}"
                )
            elif smart_summary.login_status == "launcher_stale":
                action = (
                    f"请手动打开：{executable}，重新生成登录器。"
                    f"{smart_summary.next_step}"
                )
            elif smart_summary.login_status == "ready":
                action = "登录器集成门禁已通过；继续进行单怪身体与五类动作验收。"
            else:
                action = smart_summary.next_step
            return f"{summary_text}\n{action}"
        needs_regeneration = any(
            change.scope == "client" or change.kind == "generator-pak-rules"
            for change in plan.changes
        ) or bool(getattr(plan, "requires_login_regeneration", False))
        if not needs_regeneration:
            return "本次没有新增或更换怪物补丁，无需重新生成登录器。"
        if plan.generator_login_dir is None:
            return "补丁已同步，但未定位到登录器目录。"
        executable = Path(plan.generator_login_dir) / "MakeGameLogin.exe"
        return (
            f"登录器规则已自动同步 {len(plan.generator_rules_added)} 条；请手动打开：{executable}，"
            "按引擎流程重新生成登录器。普通Appr不需要自定义怪物DAT。"
        )

    def monster_rollback(self):
        transaction = self.monster_transaction_var.get().strip()
        if not transaction:
            messagebox.showwarning("缺少事务", "请输入怪物库植入事务号。")
            return
        if not messagebox.askyesno("怪物库回滚确认", f"确认逐字节回滚事务 {transaction}？"):
            return
        try:
            self.monster_library.rollback(transaction)
            messagebox.showinfo("怪物库回滚完成", transaction)
        except Exception as exc:
            messagebox.showerror("怪物库回滚失败", str(exc))

    def _choose_equipment_workbook(self):
        selected = filedialog.askopenfilename(filetypes=[("装备源表", "*.xlsx"), ("兼容表格", "*.csv")])
        if selected: self.equipment_workbook_var.set(selected)

    def _choose_equipment_update_workbook(self):
        selected = filedialog.askopenfilename(filetypes=[("修改装备源表", "*.xlsx"), ("兼容表格", "*.csv")])
        if selected: self.equipment_update_workbook_var.set(selected)

    def _choose_material_workbook(self):
        selected = filedialog.askopenfilename(filetypes=[("材料源表", "*.xlsx"), ("兼容表格", "*.csv")])
        if selected: self.equipment_material_workbook_var.set(selected)

    def _choose_equipment_hint_workbook(self):
        selected = filedialog.askopenfilename(filetypes=[("装备悬浮分类表", "*.xlsx"), ("兼容表格", "*.csv")])
        if selected: self.equipment_hint_workbook_var.set(selected)

    def _choose_equipment_graphics_config(self):
        selected = filedialog.askopenfilename(
            title="选择装备素材替换配置文件",
            filetypes=[("装备素材替换配置", "*.json"), ("所有文件", "*.*")],
        )
        if selected:
            self.equipment_graphics_config_var.set(selected)

    def _equipment_graphics_config(self):
        text = self.equipment_graphics_config_var.get().strip()
        if not text:
            raise ValueError("请先选择装备素材替换配置文件。")
        return Path(text)

    def _show_equipment_graphics_result(self, result):
        self._write(self.equipment_report, json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if isinstance(result, dict):
            receipt = result.get("receipt_path") or result.get("receiptPath") or result.get("receipt")
            if receipt:
                self.equipment_graphics_receipt_var.set(str(receipt))

    @staticmethod
    def _graphics_result_failed(result):
        if not isinstance(result, dict):
            return True
        if result.get("success") is False:
            return True
        status = str(result.get("status", "")).strip().lower()
        if status.startswith(("failed", "error", "blocked")) or status in {"aborted", "rollback_failed"}:
            return True
        return bool(result.get("blockers"))

    @staticmethod
    def _graphics_result_success(result):
        if not isinstance(result, dict):
            return False
        if result.get("success") is True:
            return True
        return str(result.get("status", "")).strip().lower() in {"applied", "noop"}

    @staticmethod
    def _graphics_result_error(result):
        if not isinstance(result, dict):
            return "核心返回了无效结果。"
        blockers = result.get("blockers")
        if blockers:
            return "\n".join(map(str, blockers))
        return str(result.get("message") or result.get("error") or result.get("status") or "核心报告失败。")

    def _run_equipment_graphics_async(self, operation, worker, on_result):
        if self._equipment_graphics_busy:
            messagebox.showwarning("装备素材替换忙碌", "已有装备素材操作正在执行，请等待结果。")
            return
        self._equipment_graphics_busy = True

        def finish(result=None, error=None):
            self._equipment_graphics_busy = False
            if error is not None:
                messagebox.showerror(operation, str(error))
                return
            on_result(result)

        def run():
            try:
                result = worker()
            except Exception as exc:
                self.after(0, lambda exc=exc: finish(error=exc))
            else:
                self.after(0, lambda result=result: finish(result=result))

        threading.Thread(target=run, name="equipment-graphics", daemon=True).start()

    def _handle_graphics_result(self, result, error_title, success_message=None):
        self._show_equipment_graphics_result(result)
        if self._graphics_result_failed(result):
            messagebox.showerror(error_title, self._graphics_result_error(result))
        elif success_message and self._graphics_result_success(result):
            messagebox.showinfo("装备素材替换完成", success_message)

    def equipment_graphics_preflight(self):
        try:
            config = self._equipment_graphics_config()
            self._run_equipment_graphics_async(
                "装备素材替换预检失败",
                lambda: self.equipment.graphics_preflight(config),
                lambda result: self._handle_graphics_result(result, "装备素材替换预检被阻止"),
            )
        except Exception as exc:
            messagebox.showerror("装备素材替换预检失败", str(exc))

    def equipment_graphics_apply(self):
        try:
            if not messagebox.askyesno("确认应用装备素材替换", "将由装备素材核心按配置执行可回滚事务；继续吗？"):
                return
            config = self._equipment_graphics_config()
            self._run_equipment_graphics_async(
                "装备素材替换失败",
                lambda: self.equipment.graphics_apply(config),
                lambda result: self._handle_graphics_result(result, "装备素材替换失败", success_message="应用完成，请手动生成指定登录器，再点击“登录器生成后核验”。"),
            )
        except Exception as exc:
            messagebox.showerror("装备素材替换失败", str(exc))

    def equipment_graphics_view_result(self):
        path = self.equipment_graphics_receipt_var.get().strip()
        if not path:
            messagebox.showinfo("装备素材替换结果", "请先执行预检或应用。")
            return
        try:
            result = json.loads(Path(path).read_text(encoding="utf-8"))
            self._show_equipment_graphics_result(result)
        except Exception as exc:
            messagebox.showerror("读取装备素材替换结果失败", str(exc))

    def equipment_graphics_verify_launcher(self):
        try:
            path = self.equipment_graphics_receipt_var.get().strip()
            if not path:
                raise ValueError("请先执行应用并提供事务收据。")
            self._run_equipment_graphics_async(
                "登录器生成后核验失败",
                lambda: self.equipment.graphics_verify_launcher(Path(path)),
                lambda result: self._handle_graphics_result(result, "登录器核验失败", success_message="登录器核验通过。"),
            )
        except Exception as exc:
            messagebox.showerror("登录器生成后核验失败", str(exc))

    def goto_project_entry(self):
        """Route only the graphics card locally; preserve all mixin routes."""
        try:
            card = self._selected_project_card()
        except Exception:
            return super().goto_project_entry()
        graphics_defaults = {
            "document:equipment_graphics": "44_装备素材替换.json",
            "document:equipment_graphics_append": "45_装备素材追加.json",
        }
        if card["id"] not in graphics_defaults:
            return super().goto_project_entry()
        try:
            entry = card["entry"]
            if not entry["supported"]:
                raise ValueError("此项仅供专项处理或历史回退，不能直接安装。")
            if entry["tab"] not in self.tabs:
                messagebox.showinfo("专项平台入口", f"请打开{card['platform']}，使用功能卡中的专项预检流程。")
                return
            selected = self.overview_input.get().strip()
            self.equipment_graphics_config_var.set(
                selected or str(self.platform_root / "所需材料表格汇总" / graphics_defaults[card["id"]])
            )
            self.notebook.select(self.tabs[entry["tab"]])
        except Exception as exc:
            messagebox.showerror("转到预检入口", str(exc))

    def equipment_preflight(self):
        try:
            client = Path(self.equipment_client_var.get()) if self.equipment_client_var.get().strip() else None
            self.current_equipment_plan = self.equipment.preflight(
                Path(self.equipment_workbook_var.get()), Path(self.equipment_server_var.get()), client
            )
            self.current_equipment_create_plan = self.current_equipment_plan
            plan = self.current_equipment_plan
            summary = {
                "target": str(plan.target.root), "equipment_names": plan.equipment_names,
                "blockers": plan.blockers, "warnings": plan.warnings,
                "base_templates": plan.base_templates,
                "changes": [asdict(change) for change in plan.changes],
            }
            self._write(self.equipment_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if plan.blockers: messagebox.showerror("装备预检阻止", "\n".join(plan.blockers))
        except Exception as exc: messagebox.showerror("装备预检失败", str(exc))

    def equipment_material_preflight(self):
        try:
            client_text = self.equipment_client_var.get().strip()
            if not client_text:
                messagebox.showerror("材料预检失败", "请先选择客户端 data 目录，用于读取并同步材料形态。")
                return
            self.current_equipment_plan = self.equipment.material_preflight(
                Path(self.equipment_material_workbook_var.get()),
                Path(self.equipment_server_var.get()),
                Path(client_text),
            )
            plan = self.current_equipment_plan
            summary = {
                "operation": plan.operation,
                "target": str(plan.target.root),
                "client_data": str(plan.paths.client_data),
                "material_names": plan.equipment_names,
                "skipped_existing": list(plan.skipped_existing),
                "fixed_fields": {"StdMode": 46, "OverLap": 2, "DuraMax": 99999},
                "blockers": plan.blockers,
                "warnings": plan.warnings,
                "base_templates": plan.base_templates,
                "changes": [asdict(change) for change in plan.changes],
            }
            self._write(self.equipment_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if plan.blockers:
                messagebox.showerror("材料预检阻止", "\n".join(plan.blockers))
            elif not plan.equipment_names:
                messagebox.showinfo(
                    "材料预检通过",
                    f"表中 {len(plan.skipped_existing)} 种材料均已存在，平台将全部跳过，不会重复添加。",
                )
            else:
                messagebox.showinfo(
                    "材料预检通过",
                    f"将新增 {len(plan.equipment_names)} 种材料，跳过已存在 {len(plan.skipped_existing)} 种；"
                    "可以点击“确认添加材料”。",
                )
        except Exception as exc:
            messagebox.showerror("材料预检失败", str(exc))

    def equipment_install(self, expected_operation: str | None = None):
        plan = {
            "create": self.current_equipment_create_plan,
            "update": self.current_equipment_update_plan,
        }.get(expected_operation, self.current_equipment_plan)
        if plan is None:
            messagebox.showwarning("尚未预检", "请先执行批量装备预检"); return
        if expected_operation is not None and plan.operation != expected_operation:
            messagebox.showerror("计划类型不匹配", "当前按钮不能执行另一种操作的预检计划，请重新预检。")
            return
        if plan.blockers:
            messagebox.showerror("禁止生成", "预检存在阻止项"); return
        operation = plan.operation
        action = {
            "repair_display": "补写 M2 自定义属性显示",
            "update": "修改全服同名装备定义",
            "material_create": "添加可叠加材料",
            "item_hint_sync": "同步装备悬浮分类",
        }.get(operation, "生成装备")
        unit = "种材料" if operation == "material_create" else "件装备"
        if operation == "material_create" and not plan.equipment_names:
            receipt = self.equipment.install(plan)
            self.equipment_transaction_var.set(receipt.transaction_id)
            if self.current_equipment_plan is plan:
                self.current_equipment_plan = None
            messagebox.showinfo("无需添加材料", "源表材料均已存在，本次没有修改服务端或客户端。")
            return
        if not messagebox.askyesno("批量生成确认", f"将向 {plan.target.root} {action} {len(plan.equipment_names)} {unit}，确认继续？"): return
        try:
            receipt = self.equipment.install(plan)
            self.equipment_transaction_var.set(receipt.transaction_id)
            if self.current_equipment_plan is plan:
                self.current_equipment_plan = None
            if operation == "create":
                self.current_equipment_create_plan = None
            elif operation == "update":
                self.current_equipment_update_plan = None
            title = {
                "material_create": "材料添加完成",
                "item_hint_sync": "装备悬浮同步完成",
            }.get(operation, "批量装备完成")
            messagebox.showinfo(title, f"事务：{receipt.transaction_id}")
        except Exception as exc: messagebox.showerror("批量装备生成失败", str(exc))

    def equipment_material_install(self):
        if self.current_equipment_plan is None or self.current_equipment_plan.operation != "material_create":
            messagebox.showwarning("尚未预检材料", "请先点击“预检材料”，确认报告无阻止项后再添加。")
            return
        self.equipment_install()

    def equipment_hint_preflight(self):
        try:
            client_text = self.equipment_client_var.get().strip()
            if not client_text:
                messagebox.showerror("悬浮预检失败", "请先选择客户端 data 目录，用于同步 XY_ItemHint.wzl/wzx。")
                return
            self.current_equipment_plan = self.equipment.hint_preflight(
                Path(self.equipment_hint_workbook_var.get()),
                Path(self.equipment_server_var.get()),
                Path(client_text),
            )
            plan = self.current_equipment_plan
            summary = {
                "operation": plan.operation,
                "target": str(plan.target.root),
                "client_data": str(plan.paths.client_data),
                "equipment_names": plan.equipment_names,
                "contract": {"制式装备": [1, 2, 3], "稀有专属": [1, 2, 4], "追梦神器": [1, 2, 5]},
                "blockers": plan.blockers,
                "warnings": plan.warnings,
                "changes": [asdict(change) for change in plan.changes],
            }
            self._write(self.equipment_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if plan.blockers:
                messagebox.showerror("悬浮预检阻止", "\n".join(plan.blockers))
            else:
                messagebox.showinfo("悬浮预检通过", "可以点击“确认同步悬浮”；服务端和客户端文件纳入同一事务回滚。")
        except Exception as exc:
            messagebox.showerror("悬浮预检失败", str(exc))

    def equipment_hint_install(self):
        if self.current_equipment_plan is None or self.current_equipment_plan.operation != "item_hint_sync":
            messagebox.showwarning("尚未预检悬浮", "请先点击“预检悬浮”，确认报告无阻止项后再同步。")
            return
        self.equipment_install()

    def equipment_hint_export(self):
        try:
            output = Path(self.equipment_hint_workbook_var.get())
            if output.exists() and not messagebox.askyesno("覆盖悬浮分类表确认", f"将按当前服真实绑定覆盖 {output}，确认继续？"):
                return
            self.equipment.export_hint_workbook(Path(self.equipment_server_var.get()), output)
            messagebox.showinfo("悬浮分类表已导出", str(output))
        except Exception as exc:
            messagebox.showerror("导出悬浮分类表失败", str(exc))

    def equipment_repair_display(self):
        try:
            self.current_equipment_plan = self.equipment.repair_display_preflight(
                Path(self.equipment_workbook_var.get()), Path(self.equipment_server_var.get())
            )
            plan = self.current_equipment_plan
            summary = {
                "operation": plan.operation, "target": str(plan.target.root),
                "equipment_names": plan.equipment_names, "blockers": plan.blockers,
                "warnings": plan.warnings, "changes": [asdict(change) for change in plan.changes],
            }
            self._write(self.equipment_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if plan.blockers: messagebox.showerror("补写 M2 显示被阻止", "\n".join(plan.blockers))
        except Exception as exc: messagebox.showerror("补写 M2 显示预检失败", str(exc))

    def equipment_update_preflight(self):
        try:
            client_text = self.equipment_client_var.get().strip()
            self.current_equipment_plan = self.equipment.update_preflight(
                Path(self.equipment_workbook_var.get()),
                Path(self.equipment_server_var.get()),
                Path(client_text) if client_text else None,
            )
            self.current_equipment_update_plan = self.current_equipment_plan
            plan = self.current_equipment_plan
            summary = {
                "operation": plan.operation, "target": str(plan.target.root),
                "equipment_names": plan.equipment_names, "blockers": plan.blockers,
                "warnings": plan.warnings, "changes": [asdict(change) for change in plan.changes],
            }
            self._write(self.equipment_report, json.dumps(summary, ensure_ascii=False, indent=2))
            if plan.blockers: messagebox.showerror("修改装备预检被阻止", "\n".join(plan.blockers))
        except Exception as exc: messagebox.showerror("修改装备预检失败", str(exc))

    def equipment_update_export(self):
        try:
            export_dir = self.platform_root / "做装备" / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            selected = filedialog.asksaveasfilename(
                title="另存当前服装备参考清单（不会覆盖正式母表）",
                initialdir=str(export_dir),
                initialfile="当前服装备参考清单.xlsx",
                defaultextension=".xlsx",
                filetypes=[("Excel 工作簿", "*.xlsx")],
            )
            if not selected:
                return
            output = Path(selected)
            if output.resolve() == Path(self.equipment_workbook_var.get()).resolve():
                messagebox.showerror("禁止覆盖正式母表", "参考清单必须另存为其他文件。")
                return
            self.equipment.export_update_workbook(Path(self.equipment_server_var.get()), output)
            messagebox.showinfo("当前服装备参考清单已导出", str(output))
        except Exception as exc: messagebox.showerror("导出修改装备表失败", str(exc))

    def equipment_search(self):
        try:
            matches = self.equipment.search_equipment(
                Path(self.equipment_server_var.get()), self.equipment_search_var.get()
            )
            self._write(self.equipment_report, json.dumps({"keyword": self.equipment_search_var.get(), "matches": matches}, ensure_ascii=False, indent=2))
            if not matches:
                messagebox.showinfo("未找到装备", "没有找到包含该关键词的装备名称。")
        except Exception as exc: messagebox.showerror("搜索装备失败", str(exc))

    def equipment_rollback(self):
        transaction = self.equipment_transaction_var.get().strip()
        if not transaction: messagebox.showwarning("缺少事务", "请输入或粘贴装备事务号"); return
        if not messagebox.askyesno("装备回滚确认", f"确认逐字节回滚事务 {transaction}？"): return
        try:
            self.equipment.rollback(Path(self.equipment_server_var.get()), transaction)
            messagebox.showinfo("装备回滚完成", transaction)
        except Exception as exc: messagebox.showerror("装备回滚失败", str(exc))

    def _king_mode_flow_plan(self, operation: str):
        server = Path(self.server_var.get().strip() or r"D:\MirServer")
        client = Path(self.client_var.get().strip() or r"E:\11周年")
        return self.king_mode_flow.config_apply(server, client) if operation == "king-mode-config-apply" else self.king_mode_flow.preflight(server, client, operation)

    def _show_king_mode_flow_plan(self, plan):
        summary = {
            "operation": plan.operation,
            "server": plan.server,
            "client": plan.client,
            "config": plan.config_path,
            "values": plan.values,
            "blockers": plan.blockers,
            "warnings": plan.warnings,
            "changes": [{"scope": item.scope, "path": item.relative_path, "before_hash": item.before_hash, "after_hash": item.after_hash, "operation": item.operation} for item in plan.changes],
        }
        self._write(self.king_mode_flow_report, json.dumps(summary, ensure_ascii=False, indent=2))
        # 用户要求在“目标管理”截图中的同一区域完成预检、安装和回滚，
        # 因此报告写入后保持在当前一键安装界面，不再跳转到旧流程页。
        self.notebook.select(self.tabs["目标管理"])
        if plan.blockers:
            messagebox.showerror("国王模式流程预检阻止", "\n".join(plan.blockers))
        elif plan.warnings:
            messagebox.showwarning("国王模式流程预检警告", "\n".join(plan.warnings))

    def king_mode_flow_preflight(self):
        try:
            plan = self._king_mode_flow_plan("king-mode-flow-preflight")
            self.current_king_mode_flow_plan = plan
            self._show_king_mode_flow_plan(plan)
        except Exception as exc:
            messagebox.showerror("国王模式流程预检失败", str(exc))

    def king_mode_one_click_install(self):
        try:
            plan = self._king_mode_flow_plan("king-mode-one-click")
            self.current_king_mode_flow_plan = plan
            self._show_king_mode_flow_plan(plan)
            if plan.blockers:
                return
            server_changes = sum(1 for item in plan.changes if item.scope == "server")
            client_changes = sum(1 for item in plan.changes if item.scope == "client")
            message = (
                "将把已验收的完整国王模式安装到所选初始端。\n\n"
                f"服务端：{plan.server}\n客户端：{plan.client}\n"
                f"服务端变更：{server_changes} 项\n客户端变更：{client_changes} 项\n\n"
                "包含神力倍攻、暴击伤害、国王称号数据库、地图、NPC、国家、复活和击杀结算。\n"
                "确认备份后执行一键安装？"
            )
            if not messagebox.askyesno("国王模式一键安装确认", message):
                return
            receipt = self.king_mode_flow.apply(plan, yes=True)
            self.current_king_mode_flow_plan = None
            self._write(self.king_mode_flow_report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
            if receipt.transaction_id == "already-installed":
                messagebox.showinfo("国王模式已是最新版本", "目标端已经完整安装，无需重复写入。")
            else:
                messagebox.showinfo(
                    "国王模式一键安装完成",
                    f"事务：{receipt.transaction_id}\n请重启M2，并使用客户端根目录中的“国王模式.exe”进入。",
                )
            self.refresh_packages()
        except Exception as exc:
            messagebox.showerror("国王模式一键安装失败", str(exc))

    def king_mode_config_apply(self):
        try:
            plan = self._king_mode_flow_plan("king-mode-config-apply")
            self.current_king_mode_flow_plan = plan
            self._show_king_mode_flow_plan(plan)
            if plan.blockers:
                return
            if not messagebox.askyesno("配置渲染确认", "将读取目标服国王模式配置TXT并渲染固定流程脚本，确认继续？"):
                return
            receipt = self.king_mode_flow.apply(plan, yes=True)
            self._write(self.king_mode_flow_report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
            messagebox.showinfo("国王模式配置已应用", f"事务：{receipt.transaction_id}")
        except Exception as exc:
            messagebox.showerror("国王模式配置应用失败", str(exc))

    def king_mode_flow_apply(self):
        self.king_mode_one_click_install()

    def king_mode_rollback(self):
        server = Path(self.server_var.get().strip() or r"D:\MirServer")
        if not messagebox.askyesno(
            "国王模式回滚确认",
            f"确认逐字节回滚该服务端最近一次国王模式一键安装？\n\n{server}",
        ):
            return
        try:
            transaction = self.king_mode_flow.rollback(server, yes=True)
            self.current_king_mode_flow_plan = None
            self._write(self.king_mode_flow_report, json.dumps({"rolled_back": transaction}, ensure_ascii=False, indent=2))
            messagebox.showinfo("国王模式回滚完成", f"事务：{transaction}")
        except Exception as exc:
            messagebox.showerror("国王模式回滚失败", str(exc))

    def open_king_mode_config(self):
        server = Path(self.server_var.get().strip() or r"D:\MirServer")
        folder = server / "Mir200" / "Envir" / "QuestDiary" / "玄渊配置"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except Exception as exc:
            messagebox.showerror("打开配置文件夹失败", str(exc))

    def _write(self, widget, value):
        widget.delete("1.0", "end"); widget.insert("end", value)

    def inspect_target(self):
        try: self._write(self.target_result, json.dumps(asdict(TargetInspector.inspect(Path(self.server_var.get()))), ensure_ascii=False, indent=2, default=str))
        except Exception as exc: messagebox.showerror("识别失败", str(exc))

    def refresh_packages(self):
        try: self.repository.refresh()
        except Exception as exc: messagebox.showerror("包扫描失败", str(exc)); return
        for item in self.package_tree.get_children(): self.package_tree.delete(item)
        for package in sorted(self.repository.packages.values(), key=lambda p: (p.bundle or "", p.id)):
            if package.status == "candidate" and not self.show_candidate_var.get(): continue
            if package.status == "deprecated": continue
            self.package_tree.insert("", "end", iid=package.id, values=(package.display_name, package.version, package.status, package.bundle or ""))

    def _selection(self): return list(self.package_tree.selection())

    def preflight(self):
        try:
            params = json.loads(self.params_var.get() or "{}")
            client = Path(self.client_var.get()) if self.client_var.get().strip() else None
            self.current_plan = self.installer.preflight(Path(self.server_var.get()), self._selection(), params, client_root=client)
            summary = {"target": self.current_plan.target_root, "packages": self.current_plan.package_ids, "changes": [
                {"path": c.relative_path, "scope": c.scope, "operation": c.operation, "package": c.package_id,
                 "before_bytes": len(c.before) if c.before is not None else None, "after_bytes": len(c.after)} for c in self.current_plan.changes
            ]}
            self._write(self.report, json.dumps(summary, ensure_ascii=False, indent=2))
        except Exception as exc: messagebox.showerror("预检失败", str(exc))

    def install(self):
        if not self.current_plan: messagebox.showwarning("尚未预检", "请先生成预检报告"); return
        selected = [self.repository.packages[item] for item in self.current_plan.package_ids]
        if any(item.status == "candidate" for item in selected):
            if not messagebox.askyesno("候选包确认", "所选内容包含未完成游戏验证的候选包，是否仅在独立测试服继续？"): return
        if not messagebox.askyesno("安装确认", f"将修改 {len(self.current_plan.changes)} 个文件并自动备份，确认安装？"): return
        try:
            receipt = self.installer.install(self.current_plan); self.current_plan = None
            messagebox.showinfo("安装完成", f"事务：{receipt.transaction_id}"); self.refresh_history()
        except Exception as exc: messagebox.showerror("安装失败", str(exc))

    def install_resident_base(self):
        try:
            params = json.loads(self.params_var.get() or "{}")
            client = Path(self.client_var.get()) if self.client_var.get().strip() else None
            plan = self.resident.preflight(Path(self.server_var.get()), params, client)
            candidates = [
                package_id for package_id in plan.package_ids
                if self.repository.packages[package_id].status == "candidate"
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
            self._write(self.report, json.dumps(summary, ensure_ascii=False, indent=2))
            self.notebook.select(self.tabs["预检报告"])
            if not plan.changes:
                messagebox.showinfo("常驻基础无需修改", "目标服已处于当前常驻基础版本。")
                return
            if candidates and not messagebox.askyesno(
                "常驻候选包确认",
                "常驻基础包含尚未完成独立游戏验收的候选包：\n" + "\n".join(candidates) + "\n\n是否继续？",
            ):
                return
            if not messagebox.askyesno(
                "安装常驻基础确认",
                f"预检通过，将向 {plan.target_root} 修改 {len(plan.changes)} 个文件并自动备份，确认安装？",
            ):
                return
            receipt = self.resident.install(plan)
            messagebox.showinfo("常驻基础安装完成", f"事务：{receipt.transaction_id}")
            self.refresh_history()
        except Exception as exc:
            messagebox.showerror("常驻基础安装失败", str(exc))

    def register_script_folder(self):
        selected = filedialog.askdirectory(title="选择非常驻脚本或完整成果包文件夹")
        if not selected:
            return
        try:
            record = self.optional_scripts.register(Path(selected))
            self.refresh_optional_scripts()
            self.optional_tree.selection_set(record.script_id)
            self.optional_tree.focus(record.script_id)
            self.show_optional_script()
            if record.kind == "package":
                self.refresh_packages()
                messagebox.showinfo("成果包文件夹已导入", f"{record.package_id}\n状态：{record.status}")
            else:
                messagebox.showinfo("原始脚本已登记", "状态：待验证。首次由 Codex 按使用说明验证后再转为成果包。")
        except Exception as exc:
            messagebox.showerror("脚本文件夹读取失败", str(exc))

    def _optional_preset_plan(self, preset_id: str):
        params = json.loads(self.params_var.get() or "{}")
        if not isinstance(params, dict):
            raise InstallError("安装参数必须是JSON对象")
        server = Path(self.server_var.get().strip() or r"D:\MirServer")
        return self.optional_presets.preflight(preset_id, server, params)

    def _show_optional_preset_plan(self, preset_id: str, plan):
        summary = {
            "operation": plan.operation_type,
            "target": plan.target_root,
            "packages": plan.package_ids,
            "candidate_packages": plan.candidate_packages,
            "map_rules": {
                "file": plan.parameters.get("map_rules_file"),
                "sha256": plan.parameters.get("map_rules_sha256"),
                "count": plan.parameters.get("map_rule_count"),
                "map_ids": plan.parameters.get("map_rule_ids"),
            },
            "parameters": plan.parameters,
            "changes": [
                {"path": item.relative_path, "scope": item.scope, "operation": item.operation, "package": item.package_id}
                for item in plan.changes
            ],
        }
        self._write(self.optional_preset_report, json.dumps(summary, ensure_ascii=False, indent=2))
        self.notebook.select(self.tabs["非常驻脚本"])

    def optional_preset_preflight(self, preset_id: str):
        try:
            plan = self._optional_preset_plan(preset_id)
            self._show_optional_preset_plan(preset_id, plan)
            if not plan.changes:
                messagebox.showinfo("非常驻专项无需修改", "目标服已处于当前预设版本。")
        except Exception as exc:
            messagebox.showerror("非常驻专项预检失败", str(exc))

    def optional_preset_install(self, preset_id: str):
        try:
            definition = self.optional_presets.definition(preset_id)
            plan = self._optional_preset_plan(preset_id)
            self._show_optional_preset_plan(preset_id, plan)
            if not plan.changes:
                messagebox.showinfo(f"{definition.display_name}无需修改", "目标服已处于当前预设版本。")
                return
            if not messagebox.askyesno(
                f"{definition.display_name}候选安装确认",
                "本预设尚未完成游戏验收，仅允许安装到独立测试服。\n\n"
                f"将以单一事务安装核心、NPC入口和命令入口，共修改 {len(plan.changes)} 个文件。是否继续？",
            ):
                return
            receipt = self.optional_presets.install(preset_id, plan)
            self._write(self.optional_preset_report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
            messagebox.showinfo(f"{definition.display_name}安装完成", f"事务：{receipt.transaction_id}\n请重启或重载M2后验收。")
            self.refresh_history()
        except Exception as exc:
            messagebox.showerror("非常驻专项安装失败", str(exc))

    def optional_preset_rollback(self, preset_id: str):
        try:
            definition = self.optional_presets.definition(preset_id)
            server = Path(self.server_var.get().strip() or r"D:\MirServer")
            transaction = self.optional_presets.latest_transaction(preset_id, server)
            if not messagebox.askyesno(
                f"{definition.display_name}回滚确认",
                f"确认逐字节回滚最近一次{definition.display_name}安装？\n\n事务：{transaction}",
            ):
                return
            self.optional_presets.rollback_latest(preset_id, server)
            self._write(self.optional_preset_report, json.dumps({"rolled_back": transaction}, ensure_ascii=False, indent=2))
            messagebox.showinfo(f"{definition.display_name}回滚完成", transaction)
            self.refresh_history()
        except Exception as exc:
            messagebox.showerror("非常驻专项回滚失败", str(exc))

    def execution_sync_target(self):
        source = self.server_var.get().strip()
        if not source:
            messagebox.showwarning("目标管理尚未选择", "请先在“目标管理”选择服务端，或直接浏览测试服目录。")
            return
        self.execution_server_var.set(source)

    def _execution_target(self) -> Path:
        value = self.execution_server_var.get().strip()
        if not value:
            raise InstallError("请先选择独立测试服根目录")
        return Path(value)

    def _show_execution_plan(self, plan):
        summary = {
            "operation": plan.operation_type,
            "target": plan.target_root,
            "packages": plan.package_ids,
            "candidate_packages": plan.candidate_packages,
            "safety": {
                "preflight_writes_target": False,
                "backup_root": str(self.execution_lab.installer.backups_root),
                "rollback_scope": "仅处决测试事务",
                "target_change_after_preflight": "阻止导入",
                "manual_change_after_install": "阻止回滚并报告",
            },
            "changes": [
                {
                    "path": item.relative_path,
                    "operation": item.operation,
                    "before_hash": hashlib.sha256(item.before).hexdigest() if item.before is not None else None,
                    "after_hash": hashlib.sha256(item.after).hexdigest(),
                    "backup": "逐字节备份" if item.before is not None else "回滚时删除新文件",
                }
                for item in plan.changes
            ],
        }
        self._write(self.execution_report, json.dumps(summary, ensure_ascii=False, indent=2))
        self.notebook.select(self.tabs["处决测试"])

    def execution_preflight(self):
        try:
            plan = self.execution_lab.preflight(self._execution_target())
            self.current_execution_plan = plan
            self._show_execution_plan(plan)
            if not plan.changes:
                messagebox.showinfo("处决测试无需修改", "目标服已经是当前试验脚本版本。")
        except Exception as exc:
            self.current_execution_plan = None
            messagebox.showerror("处决测试预检失败", str(exc))

    def execution_install(self):
        if self.current_execution_plan is None:
            messagebox.showwarning("尚未预检", "请先点击“预检导入”，确认变更与备份范围。")
            return
        if not self.execution_confirm_test_var.get():
            messagebox.showwarning("未确认测试服", "必须勾选“我确认这是独立测试服”。")
            return
        plan = self.current_execution_plan
        if not plan.changes:
            messagebox.showinfo("无需导入", "目标服已经是当前试验脚本版本。")
            return
        if not messagebox.askyesno(
            "处决测试导入确认",
            "地图0实效已验收；当前版本仍需复验平台安装链，只允许导入独立测试服。\n\n"
            f"目标：{plan.target_root}\n受影响文件：{len(plan.changes)} 个\n"
            f"独立备份目录：{self.execution_lab.installer.backups_root}\n\n"
            "平台会再次核对预检哈希，先保存原始字节再原子写入；失败自动恢复。确认继续？",
        ):
            return
        try:
            receipt = self.execution_lab.install(plan, confirmed_test_server=True)
            self.current_execution_plan = None
            self._write(self.execution_report, json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
            messagebox.showinfo(
                "处决测试已导入",
                f"事务：{receipt.transaction_id}\n备份：{receipt.backup_root}\n\n"
                "请按验收清单测试；需要撤销时点击“回滚到导入前”。",
            )
        except Exception as exc:
            messagebox.showerror("处决测试导入失败", str(exc))

    def execution_rollback(self):
        try:
            server = self._execution_target()
            transaction = self.execution_lab.latest_transaction(server)
            if not messagebox.askyesno(
                "处决测试回滚确认",
                f"将逐字节恢复处决导入前状态。\n\n目标：{server}\n事务：{transaction}\n\n确认继续？",
            ):
                return
            self.execution_lab.rollback_latest(server)
            self.current_execution_plan = None
            self._write(
                self.execution_report,
                json.dumps({"rolled_back": transaction, "restored": "byte-exact"}, ensure_ascii=False, indent=2),
            )
            messagebox.showinfo("处决测试回滚完成", f"已恢复事务：{transaction}")
        except Exception as exc:
            messagebox.showerror("处决测试回滚失败", str(exc))

    def open_execution_lab(self):
        try:
            os.startfile(str(self.execution_lab.lab_root))
        except Exception as exc:
            messagebox.showerror("打开处决施工目录失败", str(exc))

    def open_execution_rules(self):
        try:
            os.startfile(str(self.execution_lab.rules_path))
        except Exception as exc:
            messagebox.showerror("打开地图处决规则表失败", str(exc))

    def refresh_optional_scripts(self):
        if not hasattr(self, "optional_tree"):
            return
        for item in self.optional_tree.get_children():
            self.optional_tree.delete(item)
        try:
            for record in self.optional_scripts.list():
                self.optional_tree.insert(
                    "", "end", iid=record.script_id,
                    values=(record.display_name, record.kind, record.status, record.version, record.source_hash[:12], record.platform_path),
                )
        except Exception as exc:
            messagebox.showerror("非常驻脚本刷新失败", str(exc))

    def _selected_optional_record(self):
        selected = self.optional_tree.selection()
        if not selected:
            return None
        return self.optional_scripts.show(selected[0])

    def show_optional_script(self):
        record = self._selected_optional_record()
        if record is None:
            return
        details = (
            f"名称：{record.display_name}\n类型：{record.kind}\n状态：{record.status}\n"
            f"版本：{record.version}\n来源：{record.source_path}\n平台副本：{record.platform_path}\n"
            f"SHA-256：{record.source_hash}\n\n{record.instructions}"
        )
        self._write(self.optional_instructions, details)

    def open_optional_script_folder(self):
        record = self._selected_optional_record()
        if record is None:
            messagebox.showwarning("尚未选择", "请先选择一个非常驻脚本。")
            return
        os.startfile(record.platform_path)

    def goto_optional_package(self):
        record = self._selected_optional_record()
        if record is None or not record.package_id:
            messagebox.showinfo("尚未转包", "待验证原始脚本不能安装；首次验证后才能转为成果包。")
            return
        self.show_candidate_var.set(True)
        self.refresh_packages()
        if self.package_tree.exists(record.package_id):
            self.package_tree.selection_set(record.package_id)
            self.package_tree.focus(record.package_id)
        self.notebook.select(self.tabs["成果包库"])

    def refresh_history(self):
        for item in self.history.get_children(): self.history.delete(item)
        state = Path(self.server_var.get()) / ".xydp/installed.json"
        if not state.exists(): return
        data = json.loads(state.read_text(encoding="utf-8"))
        for transaction in data.get("transactions", []):
            receipt = self.platform_root / "backups" / transaction / "receipt.json"
            packages = ""
            if receipt.exists(): packages = ", ".join(json.loads(receipt.read_text(encoding="utf-8")).get("packages", {}))
            self.history.insert("", "end", iid=transaction, values=(transaction, packages))

    def rollback_selected(self):
        selected = self.history.selection()
        if not selected: return
        transaction = selected[0]
        if not messagebox.askyesno("回滚确认", f"确认逐字节回滚事务 {transaction}？"): return
        try: self.installer.rollback(Path(self.server_var.get()), transaction); self.refresh_history(); messagebox.showinfo("回滚完成", transaction)
        except Exception as exc: messagebox.showerror("回滚失败", str(exc))

    def import_package(self):
        archive = filedialog.askopenfilename(filetypes=[("玄渊成果包", "*.xypkg")])
        if not archive: return
        try:
            item = PackageImporter(self.platform_root / "packages").import_archive(Path(archive))
            self._write(self.import_result, f"已导入：{item.id}\n状态：{item.status}\n版本：{item.version}")
            self.refresh_packages()
        except Exception as exc: messagebox.showerror("导入失败", str(exc))


def main():
    import sys
    app = PlatformApp()
    if "--overview-smoke-report" in sys.argv:
        argument = sys.argv.index("--overview-smoke-report")
        report = Path(sys.argv[argument + 1]).resolve()
        if not report.is_relative_to((app.platform_root / "evidence").resolve()):
            app.destroy()
            raise ValueError("GUI冒烟报告必须位于本平台evidence目录")
        def capture_overview():
            try:
                from PIL import ImageGrab
                app.overview_search.set("洗练")
                app.refresh_project_overview()
                app.overview_tree.selection_set("document:equipment_wash_import")
                app.show_project_card()
                app.update_idletasks()
                screenshot = report.with_suffix(".png")
                ImageGrab.grab(window=app.winfo_id()).save(screenshot)
                value = {"status": "passed", "cards": len(app.overview_service.cards()),
                         "selected": list(app.overview_tree.selection()), "input": app.overview_input.get(),
                         "screenshot": str(screenshot), "target_written": False}
                report.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                report.write_text(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), encoding="utf-8")
            finally:
                app.destroy()
        app.after(600, capture_overview)
    app.mainloop()


if __name__ == "__main__":
    main()
