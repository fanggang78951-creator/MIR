from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ManifestError(ValueError):
    pass


REQUIRED_FIELDS = {
    "schema_version",
    "id",
    "version",
    "display_name",
    "status",
    "engine",
    "bundle",
    "dependencies",
    "parameters",
    "claims",
    "operations",
    "preflight_checks",
    "post_checks",
    "evidence",
}


@dataclass(frozen=True)
class PackageManifest:
    schema_version: int
    id: str
    version: str
    display_name: str
    status: str
    engine: str
    bundle: str | None
    dependencies: tuple[str, ...]
    parameters: dict[str, dict[str, Any]]
    claims: dict[str, list[Any]]
    operations: tuple[dict[str, Any], ...]
    preflight_checks: tuple[dict[str, Any], ...]
    post_checks: tuple[dict[str, Any], ...]
    evidence: tuple[Any, ...]
    residency: str
    install_route: str
    source_path: Path = field(compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: Path) -> "PackageManifest":
        missing = REQUIRED_FIELDS - data.keys()
        if missing:
            raise ManifestError(f"{source_path}: 缺少字段 {', '.join(sorted(missing))}")
        if data["schema_version"] != 1:
            raise ManifestError(f"{source_path}: schema_version 只支持 1")
        if data["status"] not in {"candidate", "verified", "deprecated"}:
            raise ManifestError(f"{source_path}: status 无效: {data['status']}")
        if data["engine"] != "LFM2":
            raise ManifestError(f"{source_path}: engine 必须是 LFM2")
        residency = str(data.get("residency", "optional"))
        if residency not in {"resident", "optional"}:
            raise ManifestError(f"{source_path}: residency 无效: {residency}")
        install_route = str(data.get("install_route", "generic"))
        if install_route not in {"generic", "recycle-config", "equipment-collection", "item-synthesis", "weapon-enchant", "attack-speed-breakthrough", "equipment-wash-import"}:
            raise ManifestError(f"{source_path}: install_route 无效: {install_route}")
        package_id = data["id"]
        if not isinstance(package_id, str) or not package_id.startswith("xy."):
            raise ManifestError(f"{source_path}: id 必须以 xy. 开头")
        for key in ("dependencies", "operations", "preflight_checks", "post_checks", "evidence"):
            if not isinstance(data[key], list):
                raise ManifestError(f"{source_path}: {key} 必须是数组")
        if not isinstance(data["parameters"], dict) or not isinstance(data["claims"], dict):
            raise ManifestError(f"{source_path}: parameters/claims 类型错误")
        return cls(
            schema_version=1,
            id=package_id,
            version=str(data["version"]),
            display_name=str(data["display_name"]),
            status=data["status"],
            engine="LFM2",
            bundle=data["bundle"],
            dependencies=tuple(data["dependencies"]),
            parameters=data["parameters"],
            claims=data["claims"],
            operations=tuple(data["operations"]),
            preflight_checks=tuple(data["preflight_checks"]),
            post_checks=tuple(data["post_checks"]),
            evidence=tuple(data["evidence"]),
            residency=residency,
            install_route=install_route,
            source_path=source_path,
        )

    @property
    def root(self) -> Path:
        return self.source_path.parent
