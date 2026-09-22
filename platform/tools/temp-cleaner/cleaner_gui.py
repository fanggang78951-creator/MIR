from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cleaner_core import (
    DEFAULT_MIN_AGE_DAYS,
    CleanerError,
    ScanResult,
    human_size,
    quarantine,
    restore,
    scan,
    write_scan_report,
)


CATEGORY_NAMES = {
    "python_cache": "Python/测试缓存",
    "cache_file": "缓存文件",
    "build_review": "构建目录（人工复核）",
    "tmp_review": "临时施工资料（人工复核）",
    "failed_transaction_review": "失败事务残留（人工复核）",
}


class CleanerApp(tk.Tk):
    def __init__(self, default_root: Path):
        super().__init__()
        self.title("玄渊平台临时文件安全清理器")
        self.geometry("1120x700")
        self.minsize(900, 560)
        self.root_var = tk.StringVar(value=str(default_root))
        self.days_var = tk.StringVar(value=str(DEFAULT_MIN_AGE_DAYS))
        self.status_var = tk.StringVar(value="尚未扫描。扫描本身不会写入或删除文件。")
        self.result: ScanResult | None = None
        self.selected: set[str] = set()
        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="平台根目录").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.root_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(top, text="浏览", command=self._browse_root).grid(row=0, column=2)
        ttk.Label(top, text="默认保留天数").grid(row=0, column=3, padx=(20, 4))
        ttk.Entry(top, textvariable=self.days_var, width=6).grid(row=0, column=4)
        top.columnconfigure(1, weight=1)

        notice = (
            "安全原则：素材库、成果包、表格、证据、备份、发布EXE等目录永久硬保护；"
            "build、tmp和失败事务残留只列出、不默认勾选；清理只移入隔离区，可凭收据恢复。"
        )
        ttk.Label(self, text=notice, foreground="#8a4b08", wraplength=1070).pack(fill="x", padx=12, pady=(0, 8))

        actions = ttk.Frame(self, padding=(10, 0))
        actions.pack(fill="x")
        self.scan_button = ttk.Button(actions, text="只读扫描", command=self._start_scan)
        self.scan_button.pack(side="left")
        ttk.Button(actions, text="勾选明确缓存", command=self._select_safe).pack(side="left", padx=6)
        ttk.Button(actions, text="全部取消", command=self._clear_selection).pack(side="left")
        ttk.Button(actions, text="导出扫描报告", command=self._export_report).pack(side="left", padx=(16, 6))
        self.quarantine_button = ttk.Button(actions, text="隔离已勾选", command=self._quarantine)
        self.quarantine_button.pack(side="left")
        ttk.Button(actions, text="按收据恢复", command=self._restore).pack(side="left", padx=6)

        columns = ("selected", "category", "path", "size", "files", "reason")
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "selected": "选择",
            "category": "类别",
            "path": "相对路径",
            "size": "大小",
            "files": "文件数",
            "reason": "规则/风险",
        }
        widths = {"selected": 55, "category": 150, "path": 330, "size": 90, "files": 75, "reason": 360}
        for name in columns:
            self.tree.heading(name, text=headings[name])
            self.tree.column(name, width=widths[name], minwidth=50, stretch=name in {"path", "reason"})
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._toggle_current)
        self.tree.bind("<space>", self._toggle_current)

        ttk.Label(self, textvariable=self.status_var, anchor="w", padding=10).pack(fill="x")

    def _browse_root(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.root_var.get(), title="选择玄渊平台根目录")
        if selected:
            self.root_var.set(selected)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        state = "disabled" if busy else "normal"
        self.scan_button.configure(state=state)
        self.quarantine_button.configure(state=state)
        if message:
            self.status_var.set(message)

    def _start_scan(self) -> None:
        try:
            days = int(self.days_var.get().strip())
            if days < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("参数错误", "默认保留天数必须是大于等于 0 的整数。")
            return
        root = self.root_var.get().strip()
        self._set_busy(True, "正在只读扫描候选目录……")

        def worker() -> None:
            try:
                result = scan(root, days)
            except Exception as exc:
                self.after(0, lambda: self._scan_failed(exc))
                return
            self.after(0, lambda: self._scan_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_failed(self, exc: Exception) -> None:
        self._set_busy(False, "扫描失败，未修改任何文件。")
        messagebox.showerror("扫描失败", str(exc))

    def _scan_done(self, result: ScanResult) -> None:
        self.result = result
        self.selected = {item.candidate_id for item in result.candidates if item.default_selected}
        self._render()
        safe_count = len(self.selected)
        safe_bytes = sum(item.bytes for item in result.candidates if item.candidate_id in self.selected)
        self._set_busy(
            False,
            f"扫描完成：{len(result.candidates)} 个候选；默认只勾选 {safe_count} 个明确缓存（{human_size(safe_bytes)}）。",
        )

    def _render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        if not self.result:
            return
        for item in self.result.candidates:
            selected = "☑" if item.candidate_id in self.selected else "☐"
            if not item.eligible:
                selected = "禁"
            self.tree.insert(
                "",
                "end",
                iid=item.candidate_id,
                values=(
                    selected,
                    CATEGORY_NAMES.get(item.category, item.category),
                    item.relative_path,
                    human_size(item.bytes),
                    item.file_count,
                    item.reason,
                ),
            )

    def _toggle_current(self, _event=None) -> None:
        if not self.result:
            return
        item_id = self.tree.focus()
        if not item_id:
            return
        item = next((x for x in self.result.candidates if x.candidate_id == item_id), None)
        if not item or not item.eligible:
            return
        if item_id in self.selected:
            self.selected.remove(item_id)
        else:
            self.selected.add(item_id)
        self._render()
        self.tree.focus(item_id)
        self.tree.selection_set(item_id)

    def _select_safe(self) -> None:
        if not self.result:
            return
        self.selected = {item.candidate_id for item in self.result.candidates if item.default_selected}
        self._render()

    def _clear_selection(self) -> None:
        self.selected.clear()
        self._render()

    def _export_report(self) -> None:
        if not self.result:
            messagebox.showinfo("尚未扫描", "请先点击“只读扫描”。")
            return
        destination = filedialog.asksaveasfilename(
            title="保存扫描报告",
            initialdir=str(Path(self.result.root) / "evidence"),
            initialfile="TempCleaner_Scan.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not destination:
            return
        try:
            write_scan_report(self.result, destination)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        messagebox.showinfo("导出完成", destination)

    def _quarantine(self) -> None:
        if not self.result:
            messagebox.showinfo("尚未扫描", "请先点击“只读扫描”。")
            return
        selected_items = [item for item in self.result.candidates if item.candidate_id in self.selected]
        if not selected_items:
            messagebox.showinfo("没有选择", "没有勾选任何项目。")
            return
        review_count = sum(1 for item in selected_items if item.category.endswith("_review"))
        total = sum(item.bytes for item in selected_items)
        text = (
            f"将隔离 {len(selected_items)} 项，共 {human_size(total)}。\n\n"
            "不会永久删除；内容会移入 backups\\cleanup_quarantine，并生成恢复收据。"
        )
        if review_count:
            text += f"\n\n其中 {review_count} 项属于人工复核类别，请确认你确实逐项检查过。"
        if not messagebox.askyesno("确认隔离", text, icon="warning"):
            return
        self._set_busy(True, "正在重新校验并隔离；任一变化都会停止……")
        try:
            receipt = quarantine(self.result, self.selected)
        except Exception as exc:
            self._set_busy(False, "隔离失败；已回退本次操作。")
            messagebox.showerror("隔离失败", str(exc))
            return
        self._set_busy(False, f"隔离完成，恢复收据：{receipt}")
        messagebox.showinfo("隔离完成", f"未永久删除。恢复收据：\n{receipt}")
        self._start_scan()

    def _restore(self) -> None:
        receipt = filedialog.askopenfilename(
            title="选择隔离收据",
            initialdir=str(Path(self.root_var.get()) / "backups" / "cleanup_quarantine"),
            filetypes=[("隔离收据", "receipt.json"), ("JSON", "*.json")],
        )
        if not receipt:
            return
        if not messagebox.askyesno("确认恢复", "将按收据恢复到原路径；原位置有同名内容时会阻止，不会覆盖。"):
            return
        try:
            restored = restore(receipt)
        except Exception as exc:
            messagebox.showerror("恢复失败", str(exc))
            return
        messagebox.showinfo("恢复完成", str(restored))
        self._start_scan()


def load_scan_result(path: Path) -> ScanResult:
    from cleaner_core import Candidate

    data = json.loads(path.read_text(encoding="utf-8"))
    data["candidates"] = [Candidate(**item) for item in data["candidates"]]
    return ScanResult(**data)

