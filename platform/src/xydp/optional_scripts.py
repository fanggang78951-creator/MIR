from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .encoding import read_text_document
from .importer import PackageImporter
from .validator import validate_package


FORBIDDEN_EXTENSIONS = {".exe", ".dll", ".bat", ".cmd", ".ps1", ".py"}
INSTRUCTION_NAMES = ("使用说明.md", "使用说明.txt")


class OptionalScriptError(RuntimeError):
    pass


def _is_path_link(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    return path.is_symlink() or os.path.islink(path) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


@dataclass(frozen=True)
class OptionalScriptRecord:
    script_id: str
    display_name: str
    kind: str
    status: str
    version: str
    source_path: str
    platform_path: str
    source_hash: str
    instructions: str
    files: tuple[dict[str, object], ...]
    package_id: str | None
    imported_at: str

    @classmethod
    def from_dict(cls, data: dict) -> "OptionalScriptRecord":
        values = dict(data)
        values["files"] = tuple(values.get("files", []))
        return cls(**values)


class OptionalScriptLibrary:
    def __init__(self, platform_root: Path):
        self.platform_root = Path(platform_root).resolve()
        self.root = self.platform_root / "非常驻脚本"
        self.pending_root = self.root / "pending"
        self.packaged_root = self.root / "packaged"
        self.templates_root = self.root / "templates"
        self.registry_path = self.root / "registry.json"

    def _ensure_layout(self) -> None:
        for path in (self.pending_root, self.packaged_root, self.templates_root):
            path.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._write_records([])

    def _write_records(self, records: list[OptionalScriptRecord]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {"schema_version": 1, "records": [asdict(item) for item in records]}
        temp = self.registry_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.registry_path)

    def list(self) -> list[OptionalScriptRecord]:
        self._ensure_layout()
        data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return [OptionalScriptRecord.from_dict(item) for item in data.get("records", [])]

    def show(self, script_id: str) -> OptionalScriptRecord:
        for record in self.list():
            if record.script_id == script_id:
                return record
        raise OptionalScriptError(f"未登记非常驻脚本: {script_id}")

    def _scan(self, source: Path) -> tuple[str, tuple[dict[str, object], ...]]:
        if _is_path_link(source):
            raise OptionalScriptError(f"禁止导入路径链接: {source}")
        records: list[dict[str, object]] = []
        aggregate = hashlib.sha256()
        total = 0
        for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix().lower()):
            if _is_path_link(path):
                raise OptionalScriptError(f"禁止导入路径链接: {path}")
            if path.is_dir():
                continue
            if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
                raise OptionalScriptError(f"禁止导入可执行文件: {path.name}")
            relative = path.relative_to(source).as_posix()
            data = path.read_bytes()
            total += len(data)
            if total > 512 * 1024 * 1024:
                raise OptionalScriptError("脚本文件夹超过 512MB")
            digest = hashlib.sha256(data).hexdigest()
            records.append({"path": relative, "sha256": digest, "size": len(data)})
            aggregate.update(relative.encode("utf-8"))
            aggregate.update(b"\0")
            aggregate.update(digest.encode("ascii"))
            aggregate.update(b"\0")
        return aggregate.hexdigest(), tuple(records)

    def _instructions(self, source: Path) -> str:
        for name in INSTRUCTION_NAMES:
            path = source / name
            if path.is_file():
                return read_text_document(path).text
        raise OptionalScriptError("原始脚本文件夹必须包含 使用说明.md 或 使用说明.txt")

    def register(self, source: Path) -> OptionalScriptRecord:
        source = Path(source).resolve()
        if not source.is_dir():
            raise OptionalScriptError(f"脚本文件夹不存在: {source}")
        self._ensure_layout()
        source_hash, files = self._scan(source)
        manifest_path = source / "manifest.json"
        manifest_data = None
        if manifest_path.is_file():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise OptionalScriptError(f"manifest.json 格式错误: {exc}") from exc
        script_id = str(manifest_data.get("id")) if manifest_data else source.name
        if not script_id or script_id in {".", ".."} or any(char in script_id for char in '<>:"/\\|?*'):
            raise OptionalScriptError(f"脚本文件夹名称无效: {script_id}")
        existing = {item.script_id: item for item in self.list()}
        if script_id in existing:
            if existing[script_id].source_hash == source_hash:
                return existing[script_id]
            raise OptionalScriptError(f"{script_id} 已登记但内容不同，请使用新版本号或新文件夹名称")

        if manifest_data is not None:
            manifest = PackageImporter(self.platform_root / "packages").import_directory(source)
            platform_path = str(manifest.root)
            record = OptionalScriptRecord(
                script_id=manifest.id,
                display_name=manifest.display_name,
                kind="package",
                status=manifest.status,
                version=manifest.version,
                source_path=str(source),
                platform_path=platform_path,
                source_hash=source_hash,
                instructions="完整成果包，可在成果包库中预检和安装。",
                files=files,
                package_id=manifest.id,
                imported_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        else:
            instructions = self._instructions(source)
            destination = self.pending_root / script_id
            temp = Path(tempfile.mkdtemp(prefix=f".{script_id}-", dir=self.pending_root))
            try:
                shutil.copytree(source, temp, dirs_exist_ok=True)
                os.replace(temp, destination)
            except Exception:
                shutil.rmtree(temp, ignore_errors=True)
                raise
            record = OptionalScriptRecord(
                script_id=script_id,
                display_name=script_id,
                kind="raw",
                status="pending",
                version="unpackaged",
                source_path=str(source),
                platform_path=str(destination),
                source_hash=source_hash,
                instructions=instructions,
                files=files,
                package_id=None,
                imported_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        records = list(existing.values()) + [record]
        self._write_records(sorted(records, key=lambda item: item.script_id.lower()))
        return record

    def link_package(self, script_id: str, package_id: str) -> OptionalScriptRecord:
        records = self.list()
        record = next((item for item in records if item.script_id == script_id), None)
        if record is None:
            raise OptionalScriptError(f"未登记非常驻脚本: {script_id}")
        package_roots = [
            self.platform_root / "packages" / status / package_id
            for status in ("verified", "candidate")
        ]
        package_root = next((path for path in package_roots if path.is_dir()), None)
        if package_root is None:
            raise OptionalScriptError(f"成果包不存在: {package_id}")
        try:
            manifest = validate_package(package_root)
        except Exception as exc:
            raise OptionalScriptError(f"成果包校验失败: {exc}") from exc
        if manifest.id != package_id:
            raise OptionalScriptError(f"成果包 ID 不一致: {manifest.id}")
        if manifest.residency != "optional":
            raise OptionalScriptError("非常驻脚本只能关联 residency=optional 的成果包")
        linked = replace(record, status="packaged", version=manifest.version, package_id=manifest.id)
        marker_root = self.packaged_root / script_id
        marker_root.mkdir(parents=True, exist_ok=True)
        marker = marker_root / "link.json"
        marker.write_text(json.dumps({
            "script_id": script_id,
            "package_id": manifest.id,
            "package_status": manifest.status,
            "version": manifest.version,
            "linked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        updated = [linked if item.script_id == script_id else item for item in records]
        self._write_records(updated)
        return linked
