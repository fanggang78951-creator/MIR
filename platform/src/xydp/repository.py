from __future__ import annotations

import json
from pathlib import Path

from .manifest import ManifestError, PackageManifest


class PackageRepository:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.packages: dict[str, PackageManifest] = {}

    def refresh(self) -> list[PackageManifest]:
        found: dict[str, PackageManifest] = {}
        for path in sorted(self.root.glob("*/*/manifest.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ManifestError(f"无法读取 {path}: {exc}") from exc
            item = PackageManifest.from_dict(data, path)
            if item.id in found:
                raise ManifestError(f"成果包 ID 重复: {item.id}")
            found[item.id] = item
        self.packages = found
        return list(found.values())

    def resolve(self, requested: list[str]) -> list[PackageManifest]:
        result: list[PackageManifest] = []
        state: dict[str, int] = {}

        def visit(package_id: str, trail: list[str]) -> None:
            if state.get(package_id) == 2:
                return
            if state.get(package_id) == 1:
                raise ManifestError(f"循环依赖: {' -> '.join(trail + [package_id])}")
            if package_id not in self.packages:
                raise ManifestError(f"缺少依赖包: {package_id}")
            state[package_id] = 1
            package = self.packages[package_id]
            for dependency in package.dependencies:
                visit(dependency, trail + [package_id])
            state[package_id] = 2
            result.append(package)

        for package_id in requested:
            visit(package_id, [])
        return result
