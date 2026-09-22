from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class MigrationRecord:
    source: str
    destination: str
    sha256: str
    package_id: str
    status: str
    copied_at: str


class MigrationRegistry:
    def __init__(self, platform_root: Path):
        self.platform_root = Path(platform_root)
        self.migration_root = self.platform_root / "migration"
        self.registry_path = self.migration_root / "registry.json"

    def copy_and_register(self, source: Path, package_id: str, status: str) -> MigrationRecord:
        source = Path(source).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if status not in {"candidate", "verified", "archived"}:
            raise ValueError(f"迁移状态无效: {status}")
        destination = self.migration_root / "imported" / package_id / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            stamp = time.strftime("%Y%m%d_%H%M%S")
            destination = destination.with_name(f"{destination.stem}_{stamp}{destination.suffix}")
        shutil.copy2(source, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        record = MigrationRecord(
            source=str(source), destination=str(destination), sha256=digest,
            package_id=package_id, status=status, copied_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        records = json.loads(self.registry_path.read_text(encoding="utf-8")) if self.registry_path.exists() else []
        records.append(asdict(record))
        self.migration_root.mkdir(parents=True, exist_ok=True)
        temp = self.registry_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.registry_path)
        return record
