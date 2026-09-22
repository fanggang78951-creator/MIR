from __future__ import annotations

import json
import hashlib
import os
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping

from .monster_engine import EngineDependency, MonsterEngineClosure


class MonsterLibraryError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_v2_catalog(catalog_path: Path, backup_root: Path) -> Path:
    """Create or reuse a content-addressed, hash-verified V2 catalog backup."""
    source = Path(catalog_path)
    if not source.is_file():
        raise MonsterLibraryError(f"V2怪物库不存在，无法备份：{source}")
    source_hash = _sha256_file(source)
    destination_root = Path(backup_root)
    destination = destination_root / f"catalog-v2-{source_hash}.sqlite"
    if destination.exists():
        if _sha256_file(destination) != source_hash:
            raise MonsterLibraryError(f"V2怪物库备份哈希不一致：{destination}")
        return destination
    destination_root.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f"{destination.name}.staging-{uuid.uuid4().hex}")
    try:
        shutil.copyfile(source, staging)
        if _sha256_file(staging) != source_hash:
            raise MonsterLibraryError(f"V2怪物库备份回读哈希不一致：{staging}")
        os.replace(staging, destination)
        if _sha256_file(destination) != source_hash:
            raise MonsterLibraryError(f"V2怪物库备份回读哈希不一致：{destination}")
    except OSError as exc:
        raise MonsterLibraryError(f"V2怪物库备份失败：{exc}") from exc
    finally:
        staging.unlink(missing_ok=True)
    return destination


@dataclass(frozen=True)
class MonsterRecord:
    monster_id: int
    source_rowid: int
    monster_name: str
    appearance_id: int
    library_no: int
    slot_no: int
    race: int
    race_img: int
    level: int
    exp: int
    hp: int
    hit: int
    monster_json: str
    monster_hash: str
    source_kind: str
    resource_name: str
    source_path: str
    companion_path: str | None
    source_hash: str | None
    companion_hash: str | None
    source_size: int
    preview_path: str | None
    preview_state: str
    status: str
    skip_reason: str | None
    pak_password: str | None
    engine_mode: str = "standard_appr"
    closure_status: str = "ready_verified"
    closure_hash: str = ""
    smart_ini_path: str | None = None
    smart_ini_hash: str | None = None
    source_effect_list_path: str | None = None
    source_effect_list_hash: str | None = None
    resource_manifest_json: str = "[]"
    login_policy: str = "none"
    capability_policy: str = "not_applicable"
    total_verified_play_frames: int = 0

    @property
    def monster_values(self) -> dict[str, object]:
        value = json.loads(self.monster_json)
        if not isinstance(value, dict):
            raise MonsterLibraryError(f"怪物资料损坏：{self.monster_name}")
        return value


@dataclass(frozen=True)
class MonsterDependencyRecord:
    monster_id: int
    ordinal: int
    source_index: int
    entry: str
    kind: str
    source_path: str
    companion_path: str | None
    source_hash: str
    companion_hash: str | None
    pak_password: str | None


CATALOG_V3_SCHEMA_SQL = """
CREATE TABLE monsters (
  monster_id INTEGER PRIMARY KEY,
  monster_name TEXT NOT NULL,
  monster_json TEXT NOT NULL,
  engine_mode TEXT NOT NULL,
  closure_status TEXT NOT NULL,
  closure_hash TEXT NOT NULL,
  smart_ini_path TEXT,
  smart_ini_hash TEXT,
  source_effect_list_path TEXT,
  source_effect_list_hash TEXT,
  resource_manifest_json TEXT NOT NULL,
  login_policy TEXT NOT NULL,
  capability_policy TEXT NOT NULL,
  total_verified_play_frames INTEGER NOT NULL,
  preview_path TEXT,
  preview_state TEXT NOT NULL,
  skip_reason TEXT,
  source_rowid INTEGER NOT NULL,
  appearance_id INTEGER NOT NULL,
  library_no INTEGER NOT NULL,
  slot_no INTEGER NOT NULL,
  race INTEGER NOT NULL,
  race_img INTEGER NOT NULL,
  level INTEGER NOT NULL,
  exp INTEGER NOT NULL,
  hp INTEGER NOT NULL,
  hit INTEGER NOT NULL,
  monster_hash TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  resource_name TEXT NOT NULL,
  source_path TEXT NOT NULL,
  companion_path TEXT,
  source_hash TEXT,
  companion_hash TEXT,
  source_size INTEGER NOT NULL,
  status TEXT NOT NULL,
  pak_password TEXT
);
CREATE TABLE monster_dependencies (
  monster_id INTEGER NOT NULL,
  ordinal INTEGER NOT NULL,
  source_index INTEGER NOT NULL,
  entry TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_path TEXT NOT NULL,
  companion_path TEXT,
  source_hash TEXT NOT NULL,
  companion_hash TEXT,
  pak_password TEXT,
  PRIMARY KEY(monster_id, ordinal)
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX idx_monsters_closure_status ON monsters(closure_status, monster_id);
CREATE INDEX idx_monsters_status ON monsters(status, monster_id);
CREATE INDEX idx_monsters_name ON monsters(monster_name);
CREATE INDEX idx_monsters_appearance ON monsters(appearance_id, monster_id);
CREATE INDEX idx_monsters_library ON monsters(library_no, slot_no);
"""


class CatalogV3Repository:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.catalog_path = self.root / "catalog.sqlite"

    @staticmethod
    def _dependency_records(monster_id: int, closure: MonsterEngineClosure) -> tuple[MonsterDependencyRecord, ...]:
        return tuple(
            MonsterDependencyRecord(
                monster_id=monster_id,
                ordinal=ordinal,
                source_index=dependency.source_index,
                entry=dependency.entry,
                kind=dependency.kind,
                source_path=dependency.source_path,
                companion_path=dependency.companion_path,
                source_hash=dependency.source_hash,
                companion_hash=dependency.companion_hash,
                pak_password=dependency.pak_password,
            )
            for ordinal, dependency in enumerate(closure.dependencies)
        )

    @staticmethod
    def _record_with_closure(record: MonsterRecord, closure: MonsterEngineClosure | None) -> MonsterRecord:
        if closure is None:
            return record
        dependencies = CatalogV3Repository._dependency_records(record.monster_id, closure)
        manifest = json.dumps(
            [asdict(dependency) for dependency in dependencies],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return replace(
            record,
            engine_mode=closure.engine_mode,
            closure_status=closure.closure_status,
            closure_hash=closure.closure_hash,
            smart_ini_path=closure.smart_ini_path,
            smart_ini_hash=closure.smart_ini_hash,
            resource_manifest_json=manifest,
            login_policy=closure.login_policy,
            capability_policy=closure.capability_policy,
            total_verified_play_frames=closure.total_verified_play_frames,
            skip_reason=closure.reason or record.skip_reason,
        )

    def _has_v3_schema(self) -> bool:
        if not self.catalog_path.is_file():
            return False
        connection = sqlite3.connect(self.catalog_path)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "monsters" not in tables or "meta" not in tables:
                return False
            columns = {row[1] for row in connection.execute("PRAGMA table_info(monsters)")}
            version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            return version is not None and version[0] == "3" and "engine_mode" in columns
        except sqlite3.Error:
            return False
        finally:
            connection.close()

    def rebuild(
        self,
        records: Iterable[MonsterRecord],
        closures: Mapping[int, MonsterEngineClosure] | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        if self.catalog_path.is_file() and not self._has_v3_schema():
            backup_v2_catalog(self.catalog_path, self.root / "backups" / "v2-catalog")
        closure_by_id = closures or {}
        persisted = [
            self._record_with_closure(record, closure_by_id.get(record.monster_id))
            for record in records
        ]
        dependencies = [
            dependency
            for record in persisted
            if (closure := closure_by_id.get(record.monster_id)) is not None
            for dependency in self._dependency_records(record.monster_id, closure)
        ]
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.catalog_path.with_name(f"catalog.sqlite.staging-{uuid.uuid4().hex}")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(staging)
            connection.executescript("PRAGMA journal_mode=DELETE;" + CATALOG_V3_SCHEMA_SQL)
            fields = tuple(MonsterRecord.__dataclass_fields__)
            connection.executemany(
                f"INSERT INTO monsters ({','.join(fields)}) VALUES ({','.join(f':{field}' for field in fields)})",
                [asdict(record) for record in persisted],
            )
            dependency_fields = tuple(MonsterDependencyRecord.__dataclass_fields__)
            connection.executemany(
                f"INSERT INTO monster_dependencies ({','.join(dependency_fields)}) VALUES ({','.join(f':{field}' for field in dependency_fields)})",
                [asdict(dependency) for dependency in dependencies],
            )
            connection.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '3')")
            connection.executemany(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                sorted((str(key), str(value)) for key, value in (metadata or {}).items()),
            )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise MonsterLibraryError(f"怪物库完整性检查失败：{integrity}")
            connection.commit()
            connection.close()
            connection = None
            os.replace(staging, self.catalog_path)
        except (OSError, sqlite3.Error) as exc:
            raise MonsterLibraryError(f"怪物库V3重建失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
            staging.unlink(missing_ok=True)

    def open(self) -> sqlite3.Connection:
        if not self.catalog_path.is_file():
            raise MonsterLibraryError(f"怪物库尚未建立：{self.catalog_path}")
        connection = sqlite3.connect(self.catalog_path)
        connection.row_factory = sqlite3.Row
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "monsters" not in tables:
                raise MonsterLibraryError("检测到已废弃的怪物外观库V1，请点击“扫描明月并重建怪物库”")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(monsters)")}
            version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() if "meta" in tables else None
            if version is None or version[0] != "3" or "engine_mode" not in columns:
                raise MonsterLibraryError("检测到V2怪物库，不能猜测引擎闭包；请重新扫描并重建V3怪物库")
            return connection
        except Exception:
            connection.close()
            raise

    def list_monsters(self, status: str = "all") -> list[MonsterRecord]:
        if status not in {"all", "ready", "existing", "skipped"}:
            raise MonsterLibraryError(f"未知怪物状态：{status}")
        connection = self.open()
        try:
            if status == "ready":
                rows = connection.execute(
                    "SELECT * FROM monsters WHERE status='ready' AND closure_status='ready_verified' ORDER BY monster_id"
                ).fetchall()
            elif status == "all":
                rows = connection.execute("SELECT * FROM monsters ORDER BY monster_id").fetchall()
            else:
                rows = connection.execute("SELECT * FROM monsters WHERE status=? ORDER BY monster_id", (status,)).fetchall()
        finally:
            connection.close()
        fields = tuple(MonsterRecord.__dataclass_fields__)
        return [MonsterRecord(**{field: row[field] for field in fields}) for row in rows]

    def dependencies_for(self, monster_id: int) -> list[MonsterDependencyRecord]:
        connection = self.open()
        try:
            rows = connection.execute(
                "SELECT * FROM monster_dependencies WHERE monster_id=? ORDER BY ordinal", (int(monster_id),)
            ).fetchall()
        finally:
            connection.close()
        fields = tuple(MonsterDependencyRecord.__dataclass_fields__)
        return [MonsterDependencyRecord(**{field: row[field] for field in fields}) for row in rows]
