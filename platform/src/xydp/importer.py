from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from .manifest import ManifestError, PackageManifest
from .validator import PackageValidationError, validate_package


class ImportError(RuntimeError):
    pass


def _is_path_link(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    return path.is_symlink() or os.path.islink(path) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


class PackageImporter:
    def __init__(self, packages_root: Path):
        self.packages_root = Path(packages_root)

    def import_archive(self, archive: Path) -> PackageManifest:
        archive = Path(archive)
        if archive.suffix.lower() != ".xypkg":
            raise ImportError("只允许导入 .xypkg 文件")
        self.packages_root.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix=".xydp-import-", dir=self.packages_root))
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                total = sum(item.file_size for item in zf.infolist())
                if total > 512 * 1024 * 1024:
                    raise ImportError("成果包解压后超过 512MB")
                for item in zf.infolist():
                    name = PurePosixPath(item.filename)
                    if name.is_absolute() or ".." in name.parts:
                        raise ImportError(f"压缩包路径越界: {item.filename}")
                    if (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ImportError(f"压缩包不允许符号链接: {item.filename}")
                    destination = temp_root.joinpath(*name.parts)
                    if item.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(zf.read(item))
            manifest_path = temp_root / "manifest.json"
            if not manifest_path.exists():
                raise ImportError("成果包根目录缺少 manifest.json")
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = validate_package(temp_root)
            except (json.JSONDecodeError, ManifestError, PackageValidationError) as exc:
                raise ImportError(str(exc)) from exc
            destination = self.packages_root / manifest.status / manifest.id
            if destination.exists():
                raise ImportError(f"成果包已存在: {manifest.id}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_root, destination)
            return PackageManifest.from_dict(data, destination / "manifest.json")
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise

    def import_directory(self, source: Path, *, default_residency: str = "optional") -> PackageManifest:
        source = Path(source).resolve()
        if not source.is_dir():
            raise ImportError(f"成果包文件夹不存在: {source}")
        self.packages_root.mkdir(parents=True, exist_ok=True)
        for path in [source, *source.rglob("*")]:
            if _is_path_link(path):
                raise ImportError(f"成果包不允许符号链接: {path}")
        temp_root = Path(tempfile.mkdtemp(prefix=".xydp-folder-import-", dir=self.packages_root))
        try:
            shutil.copytree(source, temp_root, dirs_exist_ok=True)
            manifest_path = temp_root / "manifest.json"
            if not manifest_path.exists():
                raise ImportError("成果包根目录缺少 manifest.json")
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                data.setdefault("residency", default_residency)
                manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                manifest = validate_package(temp_root)
            except (json.JSONDecodeError, ManifestError, PackageValidationError) as exc:
                raise ImportError(str(exc)) from exc
            destination = self.packages_root / manifest.status / manifest.id
            if destination.exists():
                raise ImportError(f"成果包已存在: {manifest.id}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_root, destination)
            return PackageManifest.from_dict(data, destination / "manifest.json")
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise
