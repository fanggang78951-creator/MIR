"""Version-pinned external driver for the original editor's import/export operations."""
from __future__ import annotations

import argparse
import configparser
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any

from PIL import Image

from .policy import DEFAULT_PROTECTED_ROOTS, WritePolicy

VERSION = "1.0.1"
EDITOR_SHA256 = "014D638FC4DE24009CDF59EA26A4598D21D91624CECE216342857BD3039FC055"
DEFAULT_EDITOR = Path(r"D:\素材文件夹\LFM2[20260707]\工具\Wzl编辑器.exe")
COMMANDS = ("import", "batch-import", "export", "batch-export")
MODES = {"append": ("尾部添加", "从尾部添加"), "replace": ("覆盖图片", "按编号覆盖")}
POINTS = {"open": 28, "import": 364, "export": 414, "batch-import": 464, "batch-export": 520}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def integer(value: Any, name: str, low: int = 0, high: int = 2**31 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def validate_job(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schemaVersion") != 1 or request.get("command") not in COMMANDS:
        raise ValueError("Expected schemaVersion=1 and import/batch-import/export/batch-export")
    args = request.get("arguments", {})
    source = Path(args["source"]).resolve(strict=True)
    if source.suffix.lower() not in (".wzl", ".pak") or not source.is_file():
        raise ValueError("Source must be a WZL or PAK file")
    sources = [source]
    if source.suffix.lower() == ".wzl":
        sources.append(source.with_suffix(".wzx").resolve(strict=True))
    editor = Path(args.get("editorPath", DEFAULT_EDITOR)).resolve(strict=True)
    if sha256(editor) != EDITOR_SHA256:
        raise ValueError("The native editor build does not match the verified 2023-04-03 executable")
    policy = WritePolicy(request.get("policy", {}).get("allowedWriteRoots", []),
                         protected_roots=(*DEFAULT_PROTECTED_ROOTS, Path(r"E:\11周年")))
    output = policy.assert_writable(args["outputRoot"])
    if output.exists():
        raise FileExistsError("outputRoot must be a new job directory")
    if any(path.is_relative_to(output) for path in (*sources, editor)):
        raise ValueError("Job output must not contain its inputs")
    command = request["command"]
    plan = {"command": command, "source": source, "sources": sources,
            "editor": editor, "output": output, "arguments": args}
    if command.endswith("import"):
        mode = args.get("mode")
        if mode not in MODES:
            raise ValueError("Import mode must explicitly be append or replace")
        raw_images = [args["image"]] if command == "import" else args["images"]
        if not isinstance(raw_images, list) or not raw_images:
            raise ValueError("At least one explicitly ordered image is required")
        images = []
        for entry in raw_images:
            if not isinstance(entry, dict):
                raise ValueError("Each image must contain path, x and y")
            path = Path(entry["path"]).resolve(strict=True)
            if path.suffix.lower() not in (".bmp", ".png"):
                raise ValueError("This version accepts BMP and PNG imports")
            with Image.open(path) as image:
                image.verify()
            images.append({"path": path, "sha256": sha256(path), "x": integer(entry.get("x", 0), "x", -32768, 32767),
                           "y": integer(entry.get("y", 0), "y", -32768, 32767)})
        if len({entry["path"].suffix.lower() for entry in images}) != 1:
            raise ValueError("A native batch must use one image extension")
        if not isinstance(args.get("compress", False), bool):
            raise ValueError("compress must be a boolean")
        plan.update(images=images, mode=mode)
        if mode == "replace":
            plan["start"] = integer(args["startId"], "startId")
    else:
        plan["start"] = integer(args["id"] if command == "export" else args["startId"], "startId")
        plan["end"] = plan["start"] if command == "export" else integer(args["endId"], "endId")
        if plan["end"] < plan["start"]:
            raise ValueError("Export range is reversed")
        plan["format"] = str(args.get("format", "PNG")).upper()
        if plan["format"] not in ("PNG", "BMP"):
            raise ValueError("Export format must be PNG or BMP")
    return plan


def password_for(args: dict[str, Any], source: Path) -> str | None:
    reference = args.get("passwordRef")
    if reference is None:
        return os.environ.get("XY_RESOURCE_PASSWORD")
    if not isinstance(reference, dict) or reference.get("kind") != "gui-config":
        raise ValueError("passwordRef must explicitly bind an existing GUI_Config.ini section")
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(Path(reference["path"]), encoding="gb18030")
    section = cfg[reference["section"]]
    if Path(section["filename"]).name.casefold() != source.name.casefold():
        raise ValueError("Password reference is bound to another PAK filename")
    return section["password"]


class NativeEditor:
    def __init__(self, exe: Path, workspace: Path, password: str | None):
        from pywinauto import Application
        from pywinauto.controls.win32_controls import ButtonWrapper, ComboBoxWrapper, EditWrapper
        self.Button, self.Combo, self.Edit = ButtonWrapper, ComboBoxWrapper, EditWrapper
        self.password = password
        self.process = subprocess.Popen([str(exe)], cwd=workspace)
        try:
            self.app = Application(backend="win32").connect(process=self.process.pid, timeout=10)
            self.main = self.app.window(class_name_re=r"(?i)^TFrmMain$")
            self.main.wait("visible", timeout=60)
            self.main.wait("enabled", timeout=60)
        except Exception:
            self.process.terminate()
            self.process.wait(timeout=5)
            raise
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        self.user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]

    def keys(self, control, keys: str) -> None:
        control.set_focus()
        owner = ctypes.c_ulong()
        self.user32.GetWindowThreadProcessId(self.user32.GetForegroundWindow(), ctypes.byref(owner))
        if owner.value != self.process.pid:
            raise RuntimeError("Native editor did not obtain input focus")
        control.type_keys(keys, set_foreground=False, pause=0.02)

    def edit(self, control, text: str) -> None:
        wrapped = control.wrapper_object() if hasattr(control, "wrapper_object") else control
        field = self.Edit(wrapped.element_info)
        if field.window_text() == text:
            return
        if not field.is_enabled():
            raise RuntimeError("A native edit field is disabled and differs from the requested value")
        field.set_edit_text(text)
        if field.window_text() != text:
            raise RuntimeError("Native edit control did not retain the requested value")

    def combo(self, control, value: str) -> None:
        wrapped = control.wrapper_object() if hasattr(control, "wrapper_object") else control
        combo = self.Combo(wrapped.element_info)
        if value not in combo.item_texts():
            raise RuntimeError("Native option list differs from the verified editor")
        combo.select(value)
        if combo.selected_text() != value:
            raise RuntimeError("Native option selection did not take effect")

    def choose(self, control, checked: bool) -> None:
        wrapped = control.wrapper_object() if hasattr(control, "wrapper_object") else control
        if bool(self.Button(wrapped.element_info).get_check_state()) != checked:
            self.keys(control, "{SPACE}")
        if bool(self.Button(wrapped.element_info).get_check_state()) != checked:
            raise RuntimeError("Native checkbox/radio state did not take effect")

    def button(self, dialog, title: str) -> None:
        self.keys(dialog.child_window(title=title, class_name="TBitBtn"), "{SPACE}")

    def dialog(self, class_name: str, title: str | None = None):
        criteria = {"class_name": class_name}
        if title is not None:
            criteria["title"] = title
        dialog = self.app.window(**criteria)
        dialog.wait("visible", timeout=15)
        return dialog

    def toolbar(self, operation: str) -> None:
        self.main.wait("enabled", timeout=5)
        toolbar = self.main.child_window(class_name="TRzToolbar").wrapper_object()
        rect = toolbar.rectangle()
        if rect.height() != 54 or rect.width() < 810:
            raise RuntimeError("The verified toolbar requires the editor's original 100-percent layout")
        point = POINTS[operation] | (24 << 16)
        toolbar.post_message(0x201, 1, point)
        toolbar.post_message(0x202, 0, point)

    def file_dialog(self, title: str, path: Path, image_format: str | None = None) -> None:
        dialog = self.dialog("#32770", title)
        dialog.set_focus()
        if image_format is not None:
            self.combo(dialog.child_window(class_name="ComboBox", control_id=1136), f"{image_format} 文件")
        field = dialog.child_window(class_name="Edit", control_id=1148)
        self.edit(field, str(path))
        self.keys(field, "{ENTER}")
        dialog.wait_not("visible", timeout=15)

    def success(self, verb: str) -> None:
        dialog = self.app.window(class_name="#32770", title="提示信息")
        dialog.wait("visible", timeout=240)
        texts = [entry.window_text() for entry in dialog.descendants(class_name="Static")]
        if not any(f"图片{verb}成功" in text for text in texts):
            raise RuntimeError("Unexpected native result: " + "; ".join(texts))
        self.keys(dialog, "{ENTER}")
        dialog.wait_not("visible", timeout=5)

    def open(self, source: Path) -> None:
        self.toolbar("open")
        self.file_dialog("打开", source)
        password_dialog = self.app.window(title="输入密码", class_name="TForm")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if password_dialog.exists(timeout=0.05) and password_dialog.is_visible():
                if self.password is None:
                    raise ValueError("PAK password is required through passwordRef or XY_RESOURCE_PASSWORD")
                field = password_dialog.child_window(class_name="TEdit")
                password_dialog.set_focus()
                wrapped = field.wrapper_object()
                self.Edit(wrapped.element_info).set_edit_text(self.password)
                self.keys(field, "{ENTER}")
                self.password = None
                password_dialog.wait_not("visible", timeout=5)
                break
            if self.main.is_enabled():
                break
        self.main.wait("enabled", timeout=15)

    def count(self) -> int:
        self.toolbar("batch-export")
        dialog = self.dialog("TFrmBatchExport")
        numbers = sorted(dialog.descendants(class_name="TRzNumericEdit"), key=lambda item: item.rectangle().left)
        if len(numbers) != 2:
            raise RuntimeError("Native export range controls changed")
        count = int(numbers[1].window_text()) + 1
        self.button(dialog, "取消")
        dialog.wait_not("visible", timeout=5)
        return count

    def select(self, image_id: int) -> None:
        self.main.set_focus()
        fields = sorted(self.main.descendants(class_name="TRzButtonEdit"), key=lambda item: item.rectangle().top)
        if len(fields) != 2:
            raise RuntimeError("Native image-number/zoom controls changed")
        self.edit(fields[0], str(image_id))
        self.keys(fields[0], "{ENTER}")

    def export(self, image_id: int, target: Path, image_format: str) -> None:
        self.select(image_id)
        self.toolbar("export")
        self.file_dialog("保存为图片文件", target, image_format)
        self.success("导出")
        if not target.is_file():
            raise RuntimeError("Native single export did not create the requested file")

    def batch_export(self, start: int, end: int, output: Path, image_format: str) -> list[Path]:
        output.mkdir(parents=True, exist_ok=False)
        self.toolbar("batch-export")
        dialog = self.dialog("TFrmBatchExport")
        dialog.set_focus()
        self.combo(dialog.child_window(class_name="TComboBox"), image_format)
        self.edit(dialog.child_window(class_name="TRzButtonEdit"), str(output))
        numbers = sorted(dialog.descendants(class_name="TRzNumericEdit"), key=lambda item: item.rectangle().left)
        self.edit(numbers[0], str(start))
        self.edit(numbers[1], str(end))
        self.button(dialog, "确定")
        self.success("导出")
        if dialog.exists(timeout=0.1) and dialog.is_visible():
            self.button(dialog, "取消")
            dialog.wait_not("visible", timeout=5)
        paths = sorted(output.rglob(f"*.{image_format}"))
        if [int(path.stem) for path in paths] != list(range(start, end + 1)):
            raise RuntimeError("Native batch export did not produce the exact requested IDs")
        return paths

    def import_one(self, image: dict[str, Any], mode: str, target: int, compress: bool) -> None:
        if mode == "replace":
            self.select(target)
        self.toolbar("import")
        self.file_dialog("打开", image["path"])
        dialog = self.dialog("TFrmImport")
        dialog.set_focus()
        self.combo(dialog.child_window(class_name="TComboBox"), MODES[mode][0])
        fields = sorted(dialog.descendants(class_name="TRzNumericEdit"), key=lambda item: item.rectangle().top)
        self.edit(fields[0], str(image["x"]))
        self.edit(fields[1], str(image["y"]))
        self.choose(dialog.child_window(class_name="TCheckBox"), compress)
        self.button(dialog, "确定")
        self.success("导入")

    def batch_import(self, input_dir: Path, mode: str, target: int, count: int, compress: bool) -> None:
        self.toolbar("batch-import")
        dialog = self.dialog("TFrmBatchImport")
        dialog.set_focus()
        self.edit(dialog.child_window(class_name="TRzButtonEdit"), str(input_dir))
        combos = sorted(dialog.descendants(class_name="TComboBox"), key=lambda item: item.rectangle().left)
        self.combo(combos[0], "图片和坐标")
        self.combo(combos[1], MODES[mode][1])
        numbers = sorted(dialog.descendants(class_name="TRzNumericEdit"), key=lambda item: item.rectangle().left)
        if mode == "replace":
            self.edit(numbers[0], str(target))
            self.edit(numbers[1], str(target + count - 1))
        self.choose(dialog.child_window(class_name="TRzRadioButton", title="同名坐标文件"), True)
        self.choose(dialog.child_window(class_name="TGroupButton", title="压缩" if compress else "不压缩"), True)
        self.button(dialog, "确定")
        self.success("导入")

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            if self.main.is_enabled():
                self.main.close()
                self.process.wait(timeout=4)
                return
        except Exception:
            pass
        self.process.terminate()
        self.process.wait(timeout=5)


def image_record(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        record = {"path": str(path), "sha256": sha256(path), "width": image.width, "height": image.height,
                  "mode": image.mode, "rgbaSha256": hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest().upper()}
    position = path.parent / "Placements" / f"{path.stem}.txt"
    if position.is_file():
        values = position.read_text(encoding="ascii").split()
        if len(values) != 2:
            raise RuntimeError("Native placement file must contain exactly X and Y")
        record["x"], record["y"] = map(int, values)
    return record


def run_job(request: dict[str, Any]) -> dict[str, Any]:
    plan = validate_job(request)
    source, output, args = plan["source"], plan["output"], plan["arguments"]
    secret = password_for(args, source) if source.suffix.lower() == ".pak" else None
    before = {str(path): sha256(path) for path in plan["sources"]}
    wzl_before = None
    if source.suffix.lower() == ".wzl" and plan["command"].endswith("import"):
        from .inspector import inspect_pair
        wzl_before = inspect_pair(source, source.with_suffix(".wzx"))
    output.mkdir(parents=True, exist_ok=False)
    editor_dir, resource_dir = output / "editor", output / "resource"
    editor_dir.mkdir()
    resource_dir.mkdir()
    editor_copy = editor_dir / plan["editor"].name
    shutil.copy2(plan["editor"], editor_copy)
    for path in plan["sources"]:
        destination = resource_dir / path.name
        shutil.copy2(path, destination)
        if sha256(destination) != before[str(path)]:
            raise RuntimeError("Source changed while creating the isolated resource copy")
    staged = resource_dir / source.name
    ui = None
    result: dict[str, Any] = {"outputRoot": str(output), "originalEditorSha256": EDITOR_SHA256}
    try:
        ui = NativeEditor(editor_copy, editor_dir, secret)
        secret = None
        ui.open(staged)
        count_before = ui.count()
        command = plan["command"]
        if command.endswith("export"):
            if plan["end"] >= count_before:
                raise ValueError("Export range exceeds the native library count")
            if command == "export":
                exported = output / f"{plan['start']:05d}.{plan['format']}"
                ui.export(plan["start"], exported, plan["format"])
                paths = [exported]
            else:
                paths = ui.batch_export(plan["start"], plan["end"], output / "export", plan["format"])
            result.update(countBefore=count_before, countAfter=count_before, images=[image_record(path) for path in paths])
            for path in plan["sources"]:
                if sha256(resource_dir / path.name) != before[str(path)]:
                    raise RuntimeError("Native export unexpectedly changed its resource copy")
        else:
            images, mode = plan["images"], plan["mode"]
            start = count_before if mode == "append" else plan["start"]
            if mode == "replace" and start + len(images) > count_before:
                raise ValueError("Replace range exceeds the native library count")
            input_dir = output / "images"
            input_dir.mkdir()
            (input_dir / "Placements").mkdir()
            for index, image in enumerate(images):
                file_id = start + index if command == "batch-import" and mode == "replace" else index
                staged_image = input_dir / f"{file_id:05d}{image['path'].suffix.lower()}"
                shutil.copy2(image["path"], staged_image)
                if sha256(staged_image) != image["sha256"] or sha256(image["path"]) != image["sha256"]:
                    raise RuntimeError("An input image changed while staging the native import")
                image["path"] = staged_image
                (input_dir / "Placements" / f"{file_id:05d}.txt").write_bytes(f"{image['x']}\r\n{image['y']}\r\n".encode("ascii"))
            if command == "import":
                ui.import_one(images[0], mode, start, args.get("compress", False))
            else:
                ui.batch_import(input_dir, mode, start, len(images), args.get("compress", False))
            count_after = ui.count()
            if count_after != count_before + (len(images) if mode == "append" else 0):
                raise RuntimeError("Native import count does not match the planned operation")
            paths = ui.batch_export(start, start + len(images) - 1, output / "readback", "PNG")
            records = [image_record(path) for path in paths]
            for expected, actual in zip(images, records, strict=True):
                if (actual.get("x"), actual.get("y")) != (expected["x"], expected["y"]):
                    raise RuntimeError("Native import coordinate readback failed")
                with Image.open(expected["path"]) as original, Image.open(actual["path"]) as exported:
                    actual["inputRgbEqual"] = original.convert("RGB").tobytes() == exported.convert("RGB").tobytes() and original.size == exported.size
                actual["inputSha256"] = expected["sha256"]
            result.update(mode=mode, startId=start, endId=start + len(images) - 1,
                          countBefore=count_before, countAfter=count_after, images=records)
            if wzl_before is not None:
                wzl_after = inspect_pair(staged, staged.with_suffix(".wzx"))
                changed_ids = set(range(start, start + len(images))) if mode == "replace" else set()
                preserved = [entry for entry in wzl_before.entries if entry.image_id not in changed_ids and entry.width and entry.height]
                if any(entry.sha256 != wzl_after.entries[entry.image_id].sha256 for entry in preserved):
                    raise RuntimeError("An unselected visible WZL frame changed")
                empty = [entry for entry in wzl_before.entries if entry.image_id not in changed_ids and (entry.empty or (entry.frame_type == 0 and not entry.width and not entry.height))]
                if any(not (wzl_after.entries[entry.image_id].empty or (wzl_after.entries[entry.image_id].frame_type == 0 and not wzl_after.entries[entry.image_id].width and not wzl_after.entries[entry.image_id].height)) for entry in empty):
                    raise RuntimeError("An unselected empty WZL slot became nonempty")
                result["unmodifiedVisibleWzlFrameHashesVerified"] = len(preserved)
                result["nativeEmptySlotNormalizationCount"] = sum(entry.offset != wzl_after.entries[entry.image_id].offset for entry in empty)
    finally:
        if ui is not None:
            ui.close()
        after = {str(path): sha256(path) for path in plan["sources"]}
        if before != after:
            raise RuntimeError("Original source files changed during the job")
    result["originalSourceUnchanged"] = True
    result["sourceFiles"] = before
    if plan["command"].endswith("import"):
        result["resourceFiles"] = [{"path": str(resource_dir / path.name), "sha256": sha256(resource_dir / path.name)} for path in plan["sources"]]
    elif any(sha256(resource_dir / path.name) != before[str(path)] for path in plan["sources"]):
        raise RuntimeError("Native editor close unexpectedly changed an export resource copy")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Original WZL/PAK resource invocation tool")
    sub = parser.add_subparsers(dest="mode", required=True)
    meta = sub.add_parser("meta")
    meta.add_argument("kind", choices=("version", "capabilities"))
    run = sub.add_parser("run")
    run.add_argument("--request", default="-")
    options = parser.parse_args(argv)
    base = {"schemaVersion": 1, "protocol": "wzl-provider/1", "provider": "xuanyuan-native-resource", "providerVersion": VERSION}
    if options.mode == "meta":
        print(json.dumps({**base, "operations": list(COMMANDS), "formats": ["WZL/WZX", "PAK"],
                          "nativeEditorSha256": EDITOR_SHA256}, separators=(",", ":")))
        return 0
    request = None
    try:
        request = json.load(sys.stdin) if options.request == "-" else json.loads(Path(options.request).read_text(encoding="utf-8-sig"))
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="32-bit application should be automated.*")
            data = run_job(request)
        response = {**base, "requestId": request.get("requestId"), "command": request.get("command"), "ok": True, "data": data}
        Path(data["outputRoot"], "receipt.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as error:
        response = {**base, "requestId": request.get("requestId") if isinstance(request, dict) else None,
                    "command": request.get("command") if isinstance(request, dict) else None,
                    "ok": False, "error": {"type": type(error).__name__, "message": str(error)}}
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
