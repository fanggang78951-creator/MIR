from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .project_overview import ProjectOverview


SELECTABLE_INPUT_SUFFIXES = {".csv", ".txt", ".xlsx"}


def selectable_files_in(folder: Path) -> list[str]:
    """Return compatible direct child files for the overview selector."""
    return sorted(
        str(path)
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SELECTABLE_INPUT_SUFFIXES
    )


class ProjectOverviewMixin:
    """Capability navigation only; installation stays with existing guarded pages."""

    def _build_project_overview(self):
        tab = self.tabs["项目总览"]
        self.overview_service = ProjectOverview(self.platform_root)
        self.overview_search = tk.StringVar()
        self.overview_input = tk.StringVar()
        self.overview_browse_dir = self.platform_root / "所需材料表格汇总"
        self.overview_status = tk.StringVar(value="全部")
        top = ttk.Frame(tab); top.pack(fill="x", padx=12, pady=10)
        ttk.Label(top, text="想用平台做什么：").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.overview_search, width=30)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self.refresh_project_overview())
        ttk.Combobox(top, textvariable=self.overview_status, values=("全部", "可直接派单", "待验证"), state="readonly", width=12).pack(side="left", padx=8)
        ttk.Button(top, text="查找 / 刷新", command=self.refresh_project_overview).pack(side="left")
        ttk.Label(tab, text="选择功能 → 填写配置 → 平台预检 → 按计划执行与验收", font=("Microsoft YaHei UI", 11)).pack(anchor="w", padx=12)
        body = ttk.Panedwindow(tab, orient="horizontal"); body.pack(fill="both", expand=True, padx=12, pady=8)
        left = ttk.Frame(body); right = ttk.Frame(body); body.add(left, weight=2); body.add(right, weight=3)
        self.overview_tree = ttk.Treeview(left, columns=("name", "kind", "status"), show="headings", selectmode="browse")
        for name, title, width in (("name", "功能", 240), ("kind", "类型", 70), ("status", "验收状态", 90)):
            self.overview_tree.heading(name, text=title); self.overview_tree.column(name, width=width)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.overview_tree.yview)
        self.overview_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y"); self.overview_tree.pack(fill="both", expand=True)
        self.overview_tree.bind("<<TreeviewSelect>>", self.show_project_card)
        self.overview_detail = tk.Text(right, wrap="word", state="disabled")
        detail_scroll = ttk.Scrollbar(right, command=self.overview_detail.yview)
        self.overview_detail.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side="right", fill="y"); self.overview_detail.pack(fill="both", expand=True)
        bottom = ttk.Frame(tab); bottom.pack(fill="x", padx=12, pady=(0, 10))
        self.overview_input_combo = ttk.Combobox(bottom, textvariable=self.overview_input, state="readonly", width=36)
        self.overview_input_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="选择文件夹", command=self.choose_overview_folder).pack(side="left", padx=5)
        ttk.Button(bottom, text="选择文件", command=self.choose_overview_file).pack(side="left", padx=(0, 5))
        ttk.Button(bottom, text="打开填写文件", command=self.open_project_input).pack(side="left", padx=5)
        ttk.Button(bottom, text="转到预检入口", command=self.goto_project_entry).pack(side="left", padx=5)
        ttk.Button(bottom, text="复制验证任务单", command=self.copy_project_task_order).pack(side="left", padx=5)
        ttk.Button(bottom, text="查看安装结果", command=self.show_project_results).pack(side="left")
        self.refresh_project_overview()

    def refresh_project_overview(self):
        try:
            cards = self.overview_service.search(self.overview_search.get())
            self.overview_tree.delete(*self.overview_tree.get_children())
            state = self.overview_status.get()
            for card in cards:
                if state == "可直接派单" and not card["dispatch_ready"]: continue
                if state == "待验证" and card["dispatch_ready"]: continue
                self.overview_tree.insert("", "end", iid=card["id"], values=(card["name"], card["kind"], card["status"]))
            self.overview_input_combo["values"] = (); self.overview_input.set("")
            self.overview_detail.configure(state="normal"); self.overview_detail.delete("1.0", "end")
            self.overview_detail.insert("end", f"已读取 {len(cards)} 项。选择功能查看填写方式、当前版本和验收限制。")
            self.overview_detail.configure(state="disabled")
        except Exception as exc:
            messagebox.showerror("项目总览读取失败", str(exc))

    def _selected_project_card(self):
        selection = self.overview_tree.selection()
        if not selection: raise ValueError("请先选择一项功能。")
        return self.overview_service.get(selection[0])

    def show_project_card(self, _event=None):
        try:
            card = self._selected_project_card()
            self.overview_detail.configure(state="normal"); self.overview_detail.delete("1.0", "end")
            self.overview_detail.insert("end", self.overview_service.format_card(card)); self.overview_detail.configure(state="disabled")
            values = [item["path"] for item in card["inputs"]]
            self.overview_input_combo["values"] = values; self.overview_input.set(values[0] if values else "")
        except ValueError:
            return

    def choose_overview_folder(self):
        folder = filedialog.askdirectory(
            parent=self,
            title="选择填写文件所在文件夹",
            initialdir=str(self.overview_browse_dir),
        )
        if not folder:
            return
        self.overview_browse_dir = Path(folder)
        values = selectable_files_in(self.overview_browse_dir)
        self.overview_input_combo["values"] = values
        self.overview_input.set(values[0] if values else "")
        if not values:
            messagebox.showinfo("选择文件夹", "该文件夹中没有可选择的 XLSX、TXT 或 CSV 文件。")

    def choose_overview_file(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="选择填写文件",
            initialdir=str(self.overview_browse_dir),
            filetypes=(
                ("支持的填写文件", "*.xlsx *.txt *.csv"),
                ("Excel 工作簿", "*.xlsx"),
                ("文本文件", "*.txt"),
                ("CSV 文件", "*.csv"),
                ("所有文件", "*.*"),
            ),
        )
        if not path:
            return
        selected = str(Path(path))
        self.overview_browse_dir = Path(path).parent
        values = list(self.overview_input_combo["values"])
        if selected not in values:
            values.append(selected)
        self.overview_input_combo["values"] = values
        self.overview_input.set(selected)

    def open_project_input(self):
        try:
            self._selected_project_card()
            path = Path(self.overview_input.get())
            if not path.is_file(): raise ValueError("请选择一个已存在的填写文件。")
            os.startfile(str(path))
        except Exception as exc: messagebox.showerror("打开填写文件", str(exc))

    def goto_project_entry(self):
        try:
            card = self._selected_project_card(); entry = card["entry"]; tab = entry["tab"]
            if not entry["supported"]: raise ValueError("此项仅供专项处理或历史回退，不能直接安装。")
            if tab not in self.tabs:
                messagebox.showinfo("专项平台入口", f"请打开{card['platform']}，使用功能卡中的专项预检流程。")
                return
            if tab == "脚本配置同步":
                selected = self.overview_input.get().strip()
                if not selected: raise ValueError("请先选择一个填写文件。")
                self.config_sync_paths = [Path(selected)]
                self.config_sync_document_id = card["id"].removeprefix("document:")
                self.current_config_sync_plan = None
                self.config_sync_selected.delete(0, "end")
                for path in self.config_sync_paths: self.config_sync_selected.insert("end", str(path))
            elif tab == "批量做装备" and card["inputs"]:
                key = {"document:material_create": "equipment_material_workbook_var", "document:equipment_item_hint": "equipment_hint_workbook_var"}.get(card["id"], "equipment_workbook_var")
                getattr(self, key).set(self.overview_input.get() or card["inputs"][0]["path"])
            elif tab == "成果包库":
                self.show_candidate_var.set(True); self.refresh_packages()
                key = entry["route"]
                if self.package_tree.exists(key): self.package_tree.selection_set(key); self.package_tree.see(key)
            self.notebook.select(self.tabs[tab])
        except Exception as exc: messagebox.showerror("转到预检入口", str(exc))

    def copy_project_task_order(self):
        try:
            card = self._selected_project_card()
            server = self.server_var.get().strip()
            if not server: raise ValueError("请先在目标管理中选择服务端目录。")
            client = self.client_var.get().strip()
            order = self.overview_service.task_order(card["id"], Path(server), Path(client) if client else None, validation=True)
            self.clipboard_clear(); self.clipboard_append(json.dumps(order, ensure_ascii=False, indent=2))
            messagebox.showinfo("验证任务单已复制", "任务单只授权预检和独立验证；正式安装仍需核对具体变更计划。")
        except Exception as exc: messagebox.showerror("生成任务单", str(exc))

    def show_project_results(self):
        try:
            card = self._selected_project_card()
            server = self.server_var.get().strip()
            if not server: raise ValueError("请先在目标管理中选择服务端目录。")
            results = self.overview_service.results(card["id"], Path(server))
            self.overview_detail.configure(state="normal"); self.overview_detail.delete("1.0", "end")
            self.overview_detail.insert("end", card["name"] + "\n所选目标：" + server + "\n\n")
            self.overview_detail.insert("end", json.dumps(results, ensure_ascii=False, indent=2) if results else "未找到此目标下该功能的安装收据。请先查看对应入口的预检报告；不能仅凭历史说明判定已经安装。")
            self.overview_detail.configure(state="disabled")
        except Exception as exc: messagebox.showerror("查看安装结果", str(exc))
