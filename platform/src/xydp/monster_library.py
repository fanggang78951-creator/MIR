from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Iterable

from .monster_catalog_v3 import (
    CatalogV3Repository,
    MonsterDependencyRecord,
    MonsterLibraryError,
    MonsterRecord,
)
from .monster_engine import (
    EngineDependency,
    MonsterEngineClosure,
    RESOURCE_KEYS,
    build_smartmonster_closure,
    classify_engine_mode,
    derive_donor_server_root,
    parse_effect_image_list,
)
from .target import is_executable_running, running_executable_paths


DEFAULT_GENERATOR_LOGIN_DIR = Path(r"D:\素材文件夹\LFM2[20260707]\登录器")
RESOURCE_EDITOR_EXECUTABLES = frozenset({
    "pakedit.exe", "pakeditor.exe", "wil编辑器.exe", "wzl.exe", "wzleditor.exe", "wzl编辑器.exe",
})
KNOWN_CLIENT_EXECUTABLES = frozenset({
    "client.exe", "game.exe", "mir.exe", "mirclient.exe", "传奇登陆器.exe",
})
MANIFEST_IDENTITY_MAX = 2**63 - 1


def default_generator_login_dir(server_root: Path) -> Path:
    """Return the known MakeGameLogin directory without requiring GUI input."""
    configured = os.environ.get("XYDP_MAKEGAMELOGIN_DIR", "").strip()
    candidates = [
        Path(configured) if configured else None,
        DEFAULT_GENERATOR_LOGIN_DIR,
        Path(server_root) / "登录器",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        if (candidate / "MakeGameLogin.exe").is_file() and (candidate / "pak.txt").is_file():
            return candidate.resolve()
    return DEFAULT_GENERATOR_LOGIN_DIR.resolve()


# 明月和当前翎风端的 Monster 表字段名大小写略有差异，但字段语义一致。
# 平台按不区分大小写的字段名映射，完整保存和回写这 26 个字段。
MONSTER_COLUMNS = (
    "Name", "Race", "RaceImg", "Appr", "Lvl", "Undead", "CoolEye", "Exp",
    "HP", "MP", "AC", "MAC", "DC", "DCMAX", "MC", "SC", "SPEED", "HIT",
    "WALK_SPD", "WalkStep", "WalkWait", "ATTACK_SPD", "AttackState",
    "AttackSource", "ExploreItem", "DisableSimpleActor",
)
REQUIRED_MONSTER_COLUMNS = {item.casefold() for item in MONSTER_COLUMNS}


# 兼容旧的 Python 调用名；活动库和界面均使用 MonsterRecord。
AppearanceRecord = MonsterRecord


@dataclass(frozen=True)
class CatalogScanResult:
    catalog_path: str
    total_monsters: int
    total_appearances: int
    ready: int
    existing: int
    skipped: int
    localized_libraries: int
    localized_bytes: int
    warnings: tuple[str, ...]
    donor_server_root: str = ""
    standard_appr: int = 0
    smartmonster: int = 0
    ready_verified: int = 0
    ready_opaque: int = 0
    incomplete: int = 0
    complex_ability: int = 0


@dataclass(frozen=True)
class SidecarImportResult:
    sidecars: int
    updated_monsters: int
    skipped_sidecars: int
    messages: tuple[str, ...]

    @property
    def updated_appearances(self) -> int:
        return self.updated_monsters


@dataclass(frozen=True)
class MonsterLibraryChange:
    scope: str
    target_path: str
    source_path: str | None
    before_hash: str | None
    after_hash: str
    kind: str


MonsterVisualChange = MonsterLibraryChange


@dataclass
class MonsterLibraryPlan:
    server_root: Path
    client_data: Path
    selected_ids: tuple[int, ...]
    monster_names: tuple[str, ...]
    library_numbers: tuple[int, ...]
    changes: list[MonsterLibraryChange]
    blockers: list[str]
    warnings: list[str]
    skipped: list[str]
    pak_rules_after: bytes | None = None
    generator_login_dir: Path | None = None
    generator_rules_after: bytes | None = None
    generator_rules_added: tuple[str, ...] = ()
    database_after: bytes | None = None
    mon_gen_after: bytes | None = None
    operation: str = "monster-library-install"
    source_workbook_path: str | None = None
    source_workbook_hash: str | None = None
    model_assignments: tuple[dict[str, object], ...] = ()
    inserted_names: tuple[str, ...] = ()
    updated_names: tuple[str, ...] = ()
    appearance_changed_names: tuple[str, ...] = ()
    unchanged_names: tuple[str, ...] = ()
    auto_reselected: tuple[dict[str, object], ...] = ()
    name_color_assignments: tuple[dict[str, object], ...] = ()
    generated_files_after: dict[str, bytes] = field(default_factory=dict)
    engine_assignments: tuple[dict[str, object], ...] = ()
    requires_custom_monster_dat: bool = False
    requires_login_regeneration: bool = False
    custom_monster_dat_path: str | None = None
    client_integration_status: str | None = None


MonsterVisualPlan = MonsterLibraryPlan


@dataclass(frozen=True)
class MonsterLibraryReceipt:
    transaction_id: str
    server_root: str
    client_data: str
    selected_ids: tuple[int, ...]
    monster_names: tuple[str, ...]
    library_numbers: tuple[int, ...]
    receipt_path: str


MonsterVisualReceipt = MonsterLibraryReceipt


def appr_to_library(appearance_id: int) -> tuple[int, int]:
    """翎风实测映射：Appr 1230 -> Mon124.Pak 槽位0。"""
    appearance_id = int(appearance_id)
    if appearance_id < 0:
        raise MonsterLibraryError(f"Appr 不能为负数：{appearance_id}")
    return appearance_id // 10 + 1, appearance_id % 10


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _decode_legacy(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("gb18030", errors="replace")


def _decode_sqlite_text(value: object) -> str:
    if isinstance(value, bytes):
        for encoding in ("utf-8", "gb18030"):
            try:
                return value.decode(encoding)
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _encode_gbk(text: str) -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized.replace("\n", "\r\n").encode("gb18030")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".xydp.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _ensure_client_processes_are_idle(client_data: Path) -> None:
    """Refuse writes while the target client or a known resource editor occupies files.

    This is deliberately inspection-only: process discovery comes from target.py and
    this function never starts, stops, or closes a process.
    """
    client_root = Path(client_data).resolve().parent
    client_executables = tuple(sorted(
        path.resolve() for path in client_root.glob("*.exe")
        if path.is_file() and path.name.casefold() in KNOWN_CLIENT_EXECUTABLES
    ))
    if not client_executables:
        allowed = ", ".join(sorted(KNOWN_CLIENT_EXECUTABLES))
        raise MonsterLibraryError(
            f"无法确认目标客户端可执行文件：{client_root}（允许名称：{allowed}）"
        )
    client_paths = {str(path).casefold() for path in client_executables}
    for executable in running_executable_paths():
        path = Path(executable).resolve()
        if path.name.casefold() in RESOURCE_EDITOR_EXECUTABLES:
            raise MonsterLibraryError(f"资源编辑器正在运行，停止文件写入：{path}")
        if str(path).casefold() in client_paths:
            raise MonsterLibraryError(f"目标客户端正在运行，停止文件写入：{path}")


def _copy_verified(source: Path, target: Path, expected_hash: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and _sha256_file(target) == expected_hash:
        return
    temporary = target.with_name(target.name + ".xydp.tmp")
    shutil.copy2(source, temporary)
    actual = _sha256_file(temporary)
    if actual != expected_hash:
        temporary.unlink(missing_ok=True)
        raise MonsterLibraryError(f"资源复制后哈希不一致：{source}")
    os.replace(temporary, target)


def _table_columns(connection: sqlite3.Connection, table: str) -> dict[str, str]:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {_decode_sqlite_text(row[1]).casefold(): _decode_sqlite_text(row[1]) for row in rows}


def _monster_rows(database: Path) -> list[tuple[int, dict[str, object]]]:
    if not database.is_file():
        raise MonsterLibraryError(f"怪物数据库不存在：{database}")
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        columns = _table_columns(connection, "Monster")
        missing = sorted(REQUIRED_MONSTER_COLUMNS - set(columns))
        if missing:
            raise MonsterLibraryError(f"Monster 表缺少字段：{', '.join(missing)}")
        selected = [columns[item.casefold()] for item in MONSTER_COLUMNS]
        sql_columns = ", ".join(f'"{item}"' for item in selected)
        rows = connection.execute(f'SELECT rowid, {sql_columns} FROM "Monster" ORDER BY rowid').fetchall()
    except sqlite3.Error as exc:
        raise MonsterLibraryError(f"无法读取 Monster 表：{database}：{exc}") from exc
    finally:
        connection.close()

    result: list[tuple[int, dict[str, object]]] = []
    for row in rows:
        values = dict(zip(MONSTER_COLUMNS, row[1:]))
        name = _decode_sqlite_text(values["Name"]).strip()
        values["Name"] = name
        appr = values["Appr"]
        if not name or name.startswith(("-", "=")) or isinstance(appr, bool) or not isinstance(appr, int):
            continue
        if appr < 0 or not any((appr, values["Race"], values["RaceImg"])):
            continue
        for key in MONSTER_COLUMNS[1:]:
            value = values[key]
            if value is None or (
                isinstance(value, (str, bytes)) and not _decode_sqlite_text(value).strip()
            ):
                values[key] = 0
            elif isinstance(value, bool) or not isinstance(value, int):
                try:
                    values[key] = int(value)
                except (TypeError, ValueError) as exc:
                    raise MonsterLibraryError(f"{name} 的字段 {key} 不是整数：{value}") from exc
        result.append((int(row[0]), values))
    return result


def _target_monster_names(database: Path) -> set[str]:
    if not database.is_file():
        return set()
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        columns = _table_columns(connection, "Monster")
        name_column = columns.get("name")
        if not name_column:
            return set()
        return {
            _decode_sqlite_text(row[0]).strip().casefold()
            for row in connection.execute(f'SELECT "{name_column}" FROM "Monster"').fetchall()
            if _decode_sqlite_text(row[0]).strip()
        }
    except sqlite3.Error as exc:
        raise MonsterLibraryError(f"无法读取目标 Monster 表：{database}：{exc}") from exc
    finally:
        connection.close()


def _numbered_files(root: Path, suffix: str) -> dict[int, Path]:
    if not root.is_dir():
        return {}
    pattern = re.compile(rf"^mon(\d+)\.{re.escape(suffix)}$", re.IGNORECASE)
    result: dict[int, Path] = {}
    for item in root.iterdir():
        if not item.is_file():
            continue
        match = pattern.fullmatch(item.name)
        if match:
            result[int(match.group(1))] = item.resolve()
    return result


def _archived_numbered_files(root: Path, suffix: str) -> dict[int, Path]:
    """Return unambiguous Mon<n> resources stored below a content-addressed archive."""
    if not root.is_dir():
        return {}
    pattern = re.compile(rf"^mon(\d+)\.{re.escape(suffix)}$", re.IGNORECASE)
    candidates: dict[int, list[Path]] = {}
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        match = pattern.fullmatch(item.name)
        if match:
            candidates.setdefault(int(match.group(1)), []).append(item.resolve())
    return {
        library_no: paths[0]
        for library_no, paths in candidates.items()
        if len(paths) == 1
    }


def _pak_passwords(rule_file: Path) -> dict[str, set[str]]:
    if not rule_file.is_file():
        return {}
    return _pak_passwords_from_text(_decode_legacy(rule_file.read_bytes()))


def _pak_passwords_from_text(text: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or "|" not in line:
            continue
        source, password = line.rsplit("|", 1)
        name = Path(source.strip()).name.casefold()
        if name:
            result.setdefault(name, set()).add(password.strip())
    return result


def _resource_conflict_reason(
    record: MonsterRecord,
    *,
    pak_rule_file: Path,
    target_passwords: dict[str, set[str]],
    target_paks: dict[int, Path],
    target_wzls: dict[int, Path],
    target_wzxs: dict[int, Path],
) -> str | None:
    source = Path(record.source_path)
    companion = Path(record.companion_path) if record.companion_path else None
    if _sha256_file(source) != record.source_hash:
        return "怪物库补丁缺失或哈希变化"
    library_no = record.library_no
    if record.source_kind == "pak":
        if target_wzls.get(library_no) or target_wzxs.get(library_no):
            return "目标客户端已有同号WZL/WZX，禁止混装PAK"
        target_pak = target_paks.get(library_no)
        if target_pak is not None and _sha256_file(target_pak) != record.source_hash:
            return f"目标存在同名异内容文件 {target_pak.name}"
        if not pak_rule_file.is_file():
            return f"目标登录器缺少pak.txt：{pak_rule_file}"
        if not record.pak_password:
            return "怪物库没有保存PAK密码"
        current = target_passwords.get(record.resource_name.casefold(), set())
        if current and current != {record.pak_password}:
            return "目标pak.txt存在同名但密码不同的登记"
        return None
    if record.source_kind == "wzl":
        if companion is None or _sha256_file(companion) != record.companion_hash:
            return "怪物库WZX缺失或哈希变化"
        if target_paks.get(library_no):
            return "目标客户端已有同号PAK，禁止混装WZL/WZX"
        target_wzl = target_wzls.get(library_no)
        target_wzx = target_wzxs.get(library_no)
        if (target_wzl is None) != (target_wzx is None):
            return "目标WZL/WZX不完整，禁止补半套"
        if target_wzl is not None and (
            _sha256_file(target_wzl) != record.source_hash
            or _sha256_file(target_wzx) != record.companion_hash
        ):
            return "目标存在同号异内容WZL/WZX"
        return None
    return "怪物库补丁类型无效"


def _monster_hash(values: dict[str, object]) -> tuple[str, str]:
    text = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def _catalog_row(row: sqlite3.Row) -> MonsterRecord:
    return MonsterRecord(**{key: row[key] for key in MonsterRecord.__dataclass_fields__})


def _database_with_monsters(
    database_bytes: bytes,
    records: list[MonsterRecord],
    *,
    allow_updates: bool = False,
) -> bytes:
    temp_path: Path | None = None
    connection: sqlite3.Connection | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as handle:
            temp_path = Path(handle.name)
            handle.write(database_bytes)
        connection = sqlite3.connect(temp_path)
        connection.execute("PRAGMA journal_mode=DELETE")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise MonsterLibraryError(f"目标怪物数据库完整性检查失败：{integrity}")
        target_columns = _table_columns(connection, "Monster")
        missing = sorted(REQUIRED_MONSTER_COLUMNS - set(target_columns))
        if missing:
            raise MonsterLibraryError(f"目标 Monster 表缺少字段：{', '.join(missing)}")

        selected_columns = [target_columns[item.casefold()] for item in MONSTER_COLUMNS]
        quoted = ", ".join(f'"{item}"' for item in selected_columns)
        placeholders = ", ".join("?" for _ in selected_columns)
        assignments = ", ".join(f'"{item}"=?' for item in selected_columns)
        target_rows: dict[str, list[tuple[int, tuple[object, ...]]]] = {}
        for row in connection.execute(f'SELECT rowid, {quoted} FROM "Monster"').fetchall():
            name = _decode_sqlite_text(row[1]).strip()
            if name:
                target_rows.setdefault(name.casefold(), []).append((int(row[0]), tuple(row[1:])))
        expected_rows: list[tuple[int, MonsterRecord, tuple[object, ...]]] = []
        changed = False
        for record in records:
            values = record.monster_values
            parameters = tuple(values[item] for item in MONSTER_COLUMNS)
            matches = target_rows.get(record.monster_name.casefold(), [])
            if len(matches) > 1:
                raise MonsterLibraryError(f"目标服存在多个同名怪物，无法唯一同步：{record.monster_name}")
            if matches:
                if not allow_updates:
                    raise MonsterLibraryError(f"目标服已出现同名怪物，停止提交：{record.monster_name}")
                rowid, current = matches[0]
                if current != parameters:
                    connection.execute(
                        f'UPDATE "Monster" SET {assignments} WHERE rowid=?',
                        parameters + (rowid,),
                    )
                    changed = True
            else:
                cursor = connection.execute(
                    f'INSERT INTO "Monster" ({quoted}) VALUES ({placeholders})', parameters
                )
                rowid = int(cursor.lastrowid)
                target_rows.setdefault(record.monster_name.casefold(), []).append((rowid, parameters))
                changed = True
            expected_rows.append((rowid, record, parameters))

        for rowid, record, expected in expected_rows:
            row = connection.execute(
                f'SELECT {quoted} FROM "Monster" WHERE rowid=?', (rowid,)
            ).fetchone()
            if row is None or tuple(row) != expected:
                raise MonsterLibraryError(f"怪物数据库写后回读不一致：{record.monster_name}")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise MonsterLibraryError(f"怪物数据库写入后完整性检查失败：{integrity}")
        if not changed:
            connection.close()
            connection = None
            return database_bytes
        connection.commit()
        connection.close()
        connection = None
        return temp_path.read_bytes()
    except sqlite3.Error as exc:
        raise MonsterLibraryError(f"怪物数据库生成失败：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _smartmonster_ini_indices(data: bytes) -> tuple[int, ...]:
    """Parse the deployed resource references without normalizing the INI bytes."""
    pattern = re.compile(
        r"^\s*(?:" + "|".join(re.escape(key) for key in RESOURCE_KEYS) + r")\s*=\s*(?P<index>-?\d+)"
    )
    return tuple(
        int(match.group("index"))
        for line in _decode_legacy(data).splitlines()
        if (match := pattern.match(line)) is not None
    )


class MonsterLibraryService:
    def __init__(self, platform_root: Path):
        self.platform_root = Path(platform_root).resolve()
        self.root = self.platform_root / "怪物库"
        self.catalog = CatalogV3Repository(self.root)
        self.catalog_path = self.catalog.catalog_path
        self.assets_root = self.root / "assets"
        self.backups_root = self.root / "backups"

    def _old_previews(self) -> dict[tuple[int, str | None], tuple[str | None, str]]:
        if not self.catalog_path.is_file():
            return {}
        connection = sqlite3.connect(self.catalog_path)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            table = "monsters" if "monsters" in tables else "appearances" if "appearances" in tables else ""
            if not table:
                return {}
            return {
                (int(appr), source_hash): (preview_path, preview_state)
                for appr, source_hash, preview_path, preview_state in connection.execute(
                    f"SELECT appearance_id, source_hash, preview_path, preview_state FROM {table}"
                )
            }
        except sqlite3.Error:
            return {}
        finally:
            connection.close()

    def scan(
        self,
        donor_database: Path,
        donor_wzl_data: Path,
        donor_pak_data: Path,
        donor_pak_rules: Path,
        target_server: Path,
        target_client_data: Path,
        *,
        donor_server_root: Path | None = None,
        materialize: bool = True,
    ) -> CatalogScanResult:
        donor_database = Path(donor_database).resolve()
        donor_wzl_data = Path(donor_wzl_data).resolve()
        donor_pak_data = Path(donor_pak_data).resolve()
        donor_pak_rules = Path(donor_pak_rules).resolve()
        target_server = Path(target_server).resolve()
        target_client_data = Path(target_client_data).resolve()
        try:
            resolved_donor_root = (
                Path(donor_server_root).resolve()
                if donor_server_root is not None
                else derive_donor_server_root(donor_database)
            )
        except RuntimeError as exc:
            raise MonsterLibraryError(str(exc)) from exc
        if not donor_wzl_data.is_dir():
            raise MonsterLibraryError(f"明月 WZL data 不存在：{donor_wzl_data}")
        if not donor_pak_data.is_dir():
            raise MonsterLibraryError(f"明月 PAK data 不存在：{donor_pak_data}")
        if not target_client_data.is_dir():
            raise MonsterLibraryError(f"目标客户端 data 不存在：{target_client_data}")

        donor_rows = _monster_rows(donor_database)
        donor_envir = resolved_donor_root / "Mir200" / "Envir"
        donor_effect_list = donor_envir / "EffectImageList.txt"
        donor_smartmonster = donor_envir / "SmartMonster"
        target_database = target_server / "Mud2" / "DB" / "ApexM2.DB"
        warnings: list[str] = []
        if not (donor_envir / "!setup.txt").is_file():
            warnings.append(f"供体服务端缺少!setup.txt：{donor_envir / '!setup.txt'}")
        if target_database.is_file():
            target_names = _target_monster_names(target_database)
        else:
            target_names = set()
            warnings.append(f"目标服未找到 Monster 数据库，入库完成后仍需选择有效目标预检：{target_database}")

        donor_paks = _numbered_files(donor_pak_data, "pak")
        archived_paks = _archived_numbered_files(self.assets_root / "pak", "pak")
        donor_wzls = _numbered_files(donor_wzl_data, "wzl")
        donor_wzxs = _numbered_files(donor_wzl_data, "wzx")
        passwords = _pak_passwords(donor_pak_rules)
        old_previews = self._old_previews()
        localized: dict[tuple[str, int], tuple[Path, Path | None, str, str | None, int]] = {}
        records: list[MonsterRecord] = []
        closures: dict[int, MonsterEngineClosure] = {}
        localized_bytes = 0
        localized_smart_dependencies: dict[tuple[str, str | None], tuple[Path, Path | None]] = {}

        def prepare(kind: str, library_no: int, source: Path, companion: Path | None):
            nonlocal localized_bytes
            key = (kind, library_no)
            if key in localized:
                return localized[key]
            source_hash = _sha256_file(source)
            companion_hash = _sha256_file(companion) if companion else None
            if source_hash is None or (companion is not None and companion_hash is None):
                raise MonsterLibraryError(f"来源图库读取失败：{source}")
            stored_source = source
            stored_companion = companion
            if materialize:
                folder = self.assets_root / kind / source_hash[:16]
                stored_source = folder / source.name
                _copy_verified(source, stored_source, source_hash)
                localized_bytes += source.stat().st_size
                if companion is not None:
                    stored_companion = folder / companion.name
                    _copy_verified(companion, stored_companion, companion_hash or "")
                    localized_bytes += companion.stat().st_size
            value = (
                stored_source.resolve(), stored_companion.resolve() if stored_companion else None,
                source_hash, companion_hash,
                source.stat().st_size + (companion.stat().st_size if companion else 0),
            )
            localized[key] = value
            return value

        def localize_smartmonster(closure: MonsterEngineClosure) -> MonsterEngineClosure:
            nonlocal localized_bytes
            if not materialize or closure.smart_ini_path is None:
                return closure
            closure_root = self.assets_root / "smartmonster" / closure.closure_hash[:16]
            source_ini = Path(closure.smart_ini_path)
            target_ini = closure_root / source_ini.name
            _copy_verified(source_ini, target_ini, closure.smart_ini_hash or "")
            localized_dependencies: list[EngineDependency] = []
            for dependency in closure.dependencies:
                key = (dependency.source_hash, dependency.companion_hash)
                stored = localized_smart_dependencies.get(key)
                if stored is None:
                    source = Path(dependency.source_path)
                    companion = Path(dependency.companion_path) if dependency.companion_path else None
                    dependency_root = self.assets_root / "smartmonster" / "dependencies" / dependency.source_hash[:16]
                    stored_source = dependency_root / source.name
                    _copy_verified(source, stored_source, dependency.source_hash)
                    stored_companion: Path | None = None
                    if companion is not None:
                        stored_companion = dependency_root / companion.name
                        _copy_verified(companion, stored_companion, dependency.companion_hash or "")
                    localized_smart_dependencies[key] = (stored_source.resolve(), stored_companion.resolve() if stored_companion else None)
                    localized_bytes += source.stat().st_size + (companion.stat().st_size if companion else 0)
                    stored = localized_smart_dependencies[key]
                localized_dependencies.append(replace(
                    dependency,
                    source_path=str(stored[0]),
                    companion_path=str(stored[1]) if stored[1] else None,
                ))
            return replace(
                closure,
                smart_ini_path=str(target_ini.resolve()),
                dependencies=tuple(localized_dependencies),
            )

        for source_rowid, values in donor_rows:
            appearance_id = int(values["Appr"])
            library_no, slot_no = appr_to_library(appearance_id)
            monster_name = str(values["Name"])
            monster_json, row_hash = _monster_hash(values)
            status = "ready"
            reason: str | None = None
            kind = ""
            resource_name = ""
            source_path = ""
            companion_path: str | None = None
            source_hash: str | None = None
            companion_hash: str | None = None
            source_size = 0
            pak_password: str | None = None
            engine_mode = classify_engine_mode(values, donor_smartmonster / f"{monster_name}.ini")
            closure: MonsterEngineClosure | None = None

            if engine_mode == "smartmonster":
                closure = build_smartmonster_closure(
                    values,
                    donor_smartmonster / f"{monster_name}.ini",
                    donor_effect_list,
                    (donor_wzl_data, donor_pak_data),
                    passwords,
                )
                try:
                    closure = localize_smartmonster(closure)
                except Exception as exc:
                    closure = replace(
                        closure,
                        closure_status="incomplete",
                        reason=f"SmartMonster本地化失败：{exc}",
                    )
                closures[source_rowid] = closure
                status = "ready" if closure.closure_status in {"ready_verified", "ready_opaque"} else "skipped"
                reason = closure.reason

            if engine_mode == "standard_appr":
                source = donor_paks.get(library_no) or archived_paks.get(library_no)
                companion: Path | None = None
                password_set = passwords.get(source.name.casefold(), set()) if source else set()
                if source is not None and len(password_set) == 1:
                    kind = "pak"
                    resource_name = source.name
                    pak_password = next(iter(password_set))
                else:
                    wzl = donor_wzls.get(library_no)
                    wzx = donor_wzxs.get(library_no)
                    if wzl is not None and wzx is not None:
                        source, companion = wzl, wzx
                        kind = "wzl"
                        resource_name = source.name
                    elif source is not None:
                        status, reason = "skipped", "PAK缺少唯一密码规则，且没有完整WZL/WZX备用图库"
                    else:
                        status, reason = "skipped", "供体没有正确Mon号的完整PAK或WZL/WZX成对图库"

                if source is not None:
                    source_path = str(source)
                    companion_path = str(companion) if companion else None
                    if status == "ready":
                        try:
                            stored, stored_companion, source_hash, companion_hash, source_size = prepare(
                                kind, library_no, source, companion
                            )
                            source_path = str(stored)
                            companion_path = str(stored_companion) if stored_companion else None
                        except Exception as exc:
                            status, reason = "skipped", f"本地化失败：{exc}"

            preview_path, preview_state = old_previews.get((appearance_id, source_hash), (None, "missing"))
            if preview_path and not Path(preview_path).is_file():
                preview_path, preview_state = None, "missing"
            records.append(MonsterRecord(
                monster_id=source_rowid,
                source_rowid=source_rowid,
                monster_name=monster_name,
                appearance_id=appearance_id,
                library_no=library_no,
                slot_no=slot_no,
                race=int(values["Race"]),
                race_img=int(values["RaceImg"]),
                level=int(values["Lvl"]),
                exp=int(values["Exp"]),
                hp=int(values["HP"]),
                hit=int(values["HIT"]),
                monster_json=monster_json,
                monster_hash=row_hash,
                source_kind=kind,
                resource_name=resource_name,
                source_path=source_path,
                companion_path=companion_path,
                source_hash=source_hash,
                companion_hash=companion_hash,
                source_size=source_size,
                preview_path=preview_path,
                preview_state=preview_state,
                status=status,
                skip_reason=reason,
                pak_password=pak_password,
                engine_mode=engine_mode,
                closure_status=(
                    closure.closure_status
                    if closure
                    else "ready_verified" if status == "ready" else "incomplete"
                ),
                closure_hash=closure.closure_hash if closure else row_hash,
                smart_ini_path=closure.smart_ini_path if closure else None,
                smart_ini_hash=closure.smart_ini_hash if closure else None,
                source_effect_list_path=str(donor_effect_list) if closure else None,
                source_effect_list_hash=_sha256_file(donor_effect_list) if closure and donor_effect_list.is_file() else None,
                resource_manifest_json="[]",
                login_policy=closure.login_policy if closure else "none",
                capability_policy=closure.capability_policy if closure else "not_applicable",
                total_verified_play_frames=closure.total_verified_play_frames if closure else 0,
            ))

        classification_counts = {
            "standard_appr": sum(record.engine_mode == "standard_appr" for record in records),
            "smartmonster": sum(record.engine_mode == "smartmonster" for record in records),
            "ready_verified": sum(
                record.status == "ready" and record.closure_status == "ready_verified"
                for record in records
            ),
            "ready_opaque": sum(record.closure_status == "ready_opaque" for record in records),
            "incomplete": sum(record.closure_status == "incomplete" for record in records),
            "complex_ability": sum(record.closure_status == "complex_ability" for record in records),
        }
        self.catalog.rebuild(records, closures, metadata={
            "donor_server_root": str(resolved_donor_root),
            "donor_database": str(donor_database),
            **classification_counts,
        })

        skipped_count = sum(record.status == "skipped" for record in records)
        existing_count = sum(
            record.status == "ready" and record.monster_name.casefold() in target_names
            for record in records
        )
        return CatalogScanResult(
            catalog_path=str(self.catalog_path),
            total_monsters=len(records),
            total_appearances=len({record.appearance_id for record in records}),
            ready=len(records) - skipped_count - existing_count,
            existing=existing_count,
            skipped=skipped_count,
            localized_libraries=len(localized),
            localized_bytes=localized_bytes,
            warnings=tuple(warnings),
            donor_server_root=str(resolved_donor_root),
            **classification_counts,
        )

    def _connect(self) -> sqlite3.Connection:
        return self.catalog.open()

    def list_monsters(
        self,
        status: str = "all",
        server_root: Path | None = None,
    ) -> list[MonsterRecord]:
        if status not in {"all", "ready", "existing", "skipped"}:
            raise MonsterLibraryError(f"未知怪物状态：{status}")
        records = self.catalog.list_monsters("all")

        target_names: set[str] = set()
        if server_root is not None:
            target_database = Path(server_root).resolve() / "Mud2" / "DB" / "ApexM2.DB"
            if target_database.is_file():
                target_names = _target_monster_names(target_database)
        if target_names:
            records = [
                replace(record, status="existing", skip_reason="目标服已有同名怪物，不覆盖")
                if record.status == "ready" and record.monster_name.casefold() in target_names
                else record
                for record in records
            ]
        if status == "ready":
            records = [
                record for record in records
                if record.status == "ready" and record.closure_status == "ready_verified"
            ]
        elif status != "all":
            records = [record for record in records if record.status == status]
        return records

    def list_appearances(self, status: str = "all") -> list[MonsterRecord]:
        return self.list_monsters(status)

    def import_sidecars(self, source: Path) -> SidecarImportResult:
        source = Path(source).resolve()
        if source.is_file():
            sidecars = [source]
        elif source.is_dir():
            sidecars = sorted(source.rglob("*.sidecar.json"))
        else:
            raise MonsterLibraryError(f"PAK桥接索引不存在：{source}")
        connection = self._connect()
        updated = 0
        skipped = 0
        messages: list[str] = []
        try:
            for sidecar_path in sidecars:
                try:
                    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
                    source_name = Path(str(payload.get("sourcePakPath", ""))).name
                    match = re.fullmatch(r"mon(\d+)\.pak", source_name, re.IGNORECASE)
                    if not match:
                        match = re.search(r"mon(\d+)", str(payload.get("library", "")), re.IGNORECASE)
                    if not match:
                        raise ValueError("无法从sidecar识别Mon图库编号")
                    library_no = int(match.group(1))
                    entries = []
                    for item in payload.get("entries", []):
                        index = int(item["index"])
                        preview = Path(str(item.get("preview") or item.get("source"))).resolve()
                        if preview.is_file():
                            entries.append((index, str(preview)))
                    if not entries:
                        raise ValueError("sidecar没有可用预览文件")
                    rows = connection.execute(
                        "SELECT monster_id, slot_no FROM monsters WHERE library_no=?", (library_no,)
                    ).fetchall()
                    local_updates = 0
                    for row in rows:
                        start = int(row["slot_no"]) * 360
                        end = start + 359
                        candidates = [item for item in entries if start <= item[0] <= end]
                        if not candidates and int(row["slot_no"]) == 0:
                            candidates = entries
                        if not candidates:
                            continue
                        preview = min(candidates, key=lambda item: item[0])[1]
                        connection.execute(
                            "UPDATE monsters SET preview_path=?, preview_state='indexed' WHERE monster_id=?",
                            (preview, int(row["monster_id"])),
                        )
                        local_updates += 1
                    updated += local_updates
                    messages.append(f"Mon{library_no}：更新{local_updates}只怪物预览")
                except Exception as exc:
                    skipped += 1
                    messages.append(f"跳过 {sidecar_path.name}：{exc}")
            connection.commit()
        finally:
            connection.close()
        return SidecarImportResult(len(sidecars), updated, skipped, tuple(messages))

    def compatible_models(
        self,
        records: Iterable[MonsterRecord],
        server_root: Path,
        client_data: Path,
    ) -> tuple[list[MonsterRecord], dict[int, str]]:
        server_root = Path(server_root).resolve()
        client_data = Path(client_data).resolve()
        pak_rule_file = server_root / "登录器" / "pak.txt"
        target_rule_text = _decode_legacy(pak_rule_file.read_bytes()) if pak_rule_file.is_file() else ""
        target_passwords = _pak_passwords_from_text(target_rule_text)
        target_paks = _numbered_files(client_data, "pak")
        target_wzls = _numbered_files(client_data, "wzl")
        target_wzxs = _numbered_files(client_data, "wzx")
        compatible: list[MonsterRecord] = []
        conflicts: dict[int, str] = {}
        checked_resources: dict[tuple[object, ...], str | None] = {}
        for record in records:
            resource_key = (
                record.source_kind,
                record.library_no,
                record.source_path,
                record.source_hash,
                record.companion_path,
                record.companion_hash,
                record.resource_name.casefold(),
                record.pak_password,
            )
            if resource_key not in checked_resources:
                checked_resources[resource_key] = _resource_conflict_reason(
                    record,
                    pak_rule_file=pak_rule_file,
                    target_passwords=target_passwords,
                    target_paks=target_paks,
                    target_wzls=target_wzls,
                    target_wzxs=target_wzxs,
                )
            reason = checked_resources[resource_key]
            if reason:
                conflicts[record.monster_id] = reason
            else:
                compatible.append(record)
        return compatible, conflicts

    def _smart_dependencies_for(
        self, record: MonsterRecord
    ) -> tuple[MonsterDependencyRecord | EngineDependency, ...]:
        """Resolve catalog dependencies, including workbook-derived SmartMonster rows."""
        catalog_dependencies = self.catalog.dependencies_for(record.monster_id)
        if catalog_dependencies:
            return tuple(catalog_dependencies)
        try:
            manifest = json.loads(record.resource_manifest_json)
        except (TypeError, ValueError):
            return ()
        if not isinstance(manifest, list):
            return ()
        dependencies: list[EngineDependency] = []
        source_monster_ids: set[int] = set()
        ordinals: set[int] = set()
        for item in manifest:
            if not isinstance(item, dict):
                return ()
            try:
                source_monster_id = item["monster_id"]
                ordinal = item["ordinal"]
                source_index = item["source_index"]
                if not all(type(value) is int for value in (source_monster_id, ordinal, source_index)):
                    return ()
                if not 1 <= source_monster_id <= MANIFEST_IDENTITY_MAX:
                    return ()
                if not 0 <= ordinal <= MANIFEST_IDENTITY_MAX:
                    return ()
                if not 0 <= source_index <= MANIFEST_IDENTITY_MAX:
                    return ()
                if ordinal in ordinals:
                    return ()
                source_monster_ids.add(source_monster_id)
                ordinals.add(ordinal)
                dependencies.append(EngineDependency(
                    source_index,
                    str(item["entry"]),
                    str(item["kind"]),
                    str(item["source_path"]),
                    str(item["companion_path"]) if item.get("companion_path") else None,
                    str(item["source_hash"]),
                    str(item["companion_hash"]) if item.get("companion_hash") else None,
                    str(item["pak_password"]) if item.get("pak_password") else None,
                    ordinal,
                    record.monster_id,
                ))
            except (KeyError, TypeError, ValueError):
                return ()
        if len(source_monster_ids) != 1:
            return ()
        return tuple(sorted(
            dependencies,
            key=lambda dependency: (
                int(dependency.ordinal or 0),
                int(dependency.source_index),
                dependency.kind,
                dependency.entry.casefold(),
                dependency.source_hash,
            ),
        ))

    def preflight(
        self,
        monster_ids: Iterable[int],
        server_root: Path,
        client_data: Path,
        *,
        record_overrides: Iterable[MonsterRecord] | None = None,
        allow_updates: bool = False,
        resource_required_names: Iterable[str] | None = None,
        appearance_changed_names: Iterable[str] = (),
        conflicts_are_blockers: bool = False,
        generator_login_dir: Path | None = None,
    ) -> MonsterLibraryPlan:
        selected = tuple(sorted({int(value) for value in monster_ids}))
        server_root = Path(server_root).resolve()
        client_data = Path(client_data).resolve()
        blockers: list[str] = []
        warnings: list[str] = []
        skipped: list[str] = []
        if not selected:
            blockers.append("没有选择怪物库编号")
        if not server_root.is_dir():
            blockers.append(f"目标服务端不存在：{server_root}")
        if not client_data.is_dir():
            blockers.append(f"目标客户端data不存在：{client_data}")
        target_database = server_root / "Mud2" / "DB" / "ApexM2.DB"
        if not target_database.is_file():
            blockers.append(f"目标服缺少怪物数据库：{target_database}")
        if is_executable_running(server_root / "Mir200" / "M2Server.exe"):
            blockers.append("目标服 M2Server.exe 正在运行；请手动关闭M2后重新预检")
        if blockers:
            return MonsterLibraryPlan(server_root, client_data, selected, (), (), [], blockers, warnings, skipped)

        if record_overrides is None:
            connection = self._connect()
            try:
                placeholders = ",".join("?" for _ in selected)
                rows = connection.execute(
                    f"SELECT * FROM monsters WHERE monster_id IN ({placeholders})", selected
                ).fetchall() if selected else []
                found = {int(row["monster_id"]): _catalog_row(row) for row in rows}
            finally:
                connection.close()
        else:
            found = {int(record.monster_id): record for record in record_overrides}
        for monster_id in selected:
            if monster_id not in found:
                skipped.append(f"库编号{monster_id}：本地怪物库不存在")

        target_rows: dict[str, list[tuple[int, dict[str, object]]]] = {}
        for rowid, values in _monster_rows(target_database):
            target_rows.setdefault(str(values["Name"]).casefold(), []).append((rowid, values))
        target_names = set(target_rows)
        eligible: list[MonsterRecord] = []
        selected_name_keys: set[str] = set()
        for record in found.values():
            if record.status != "ready" or record.closure_status not in {"ready_verified", "ready_opaque"}:
                skipped.append(f"{record.monster_name}：{record.skip_reason or record.closure_status}")
                continue
            name_key = record.monster_name.casefold()
            if name_key in target_names and not allow_updates:
                current_rows = target_rows.get(name_key, [])
                current_values = (
                    tuple(current_rows[0][1][item] for item in MONSTER_COLUMNS)
                    if len(current_rows) == 1 else ()
                )
                expected_values = tuple(record.monster_values[item] for item in MONSTER_COLUMNS)
                if current_values == expected_values:
                    eligible.append(record)
                    continue
                skipped.append(f"{record.monster_name}：目标服已有同名怪物，不迁移、不覆盖")
                continue
            if allow_updates and len(target_rows.get(name_key, [])) > 1:
                blockers.append(f"目标服存在多个同名怪物，无法唯一同步：{record.monster_name}")
                continue
            if name_key in selected_name_keys:
                blockers.append(f"选中了多个同名供体记录，无法唯一导入：{record.monster_name}")
                continue
            selected_name_keys.add(name_key)
            eligible.append(record)

        pak_rule_file = server_root / "登录器" / "pak.txt"
        target_rule_text = _decode_legacy(pak_rule_file.read_bytes()) if pak_rule_file.is_file() else ""
        target_passwords = _pak_passwords_from_text(target_rule_text)
        target_paks = _numbered_files(client_data, "pak")
        target_wzls = _numbered_files(client_data, "wzl")
        target_wzxs = _numbered_files(client_data, "wzx")
        changes: list[MonsterLibraryChange] = []
        new_rule_lines: list[str] = []
        resource_keys = (
            None if resource_required_names is None
            else {str(item).casefold() for item in resource_required_names}
        )
        smart_records = [
            record for record in eligible
            if record.engine_mode == "smartmonster"
            and (resource_keys is None or record.monster_name.casefold() in resource_keys)
        ]
        valid_records: list[MonsterRecord] = [
            record for record in eligible
            if resource_keys is not None
            and record.monster_name.casefold() not in resource_keys
        ]
        applied_libraries: list[int] = []

        generated_files_after: dict[str, bytes] = {}
        engine_assignments: tuple[dict[str, object], ...] = ()
        smart_pak_rules: dict[str, tuple[str, str]] = {}
        if smart_records:
            from .monster_smart_transaction import build_smartmonster_batch

            dependencies = {
                record.monster_id: self._smart_dependencies_for(record)
                for record in smart_records
            }
            batch = build_smartmonster_batch(smart_records, dependencies, server_root, client_data)
            blockers.extend(batch.blockers)
            if blockers:
                return MonsterLibraryPlan(
                    server_root, client_data, selected, (), (), [], blockers, warnings, skipped,
                )
            generated_files_after = {
                item.target_path: item.content for item in batch.generated_files
            }
            if batch.effect_list_after != parse_effect_image_list(Path(batch.effect_list_path)).raw:
                generated_files_after[batch.effect_list_path] = batch.effect_list_after
            engine_assignments = batch.resource_mappings
            for item in batch.generated_files:
                changes.append(MonsterLibraryChange(
                    scope="smartmonster",
                    target_path=item.target_path,
                    source_path=None,
                    before_hash=_sha256_file(Path(item.target_path)),
                    after_hash=item.after_hash,
                    kind="smart-generated-file",
                ))
            if batch.effect_list_after != parse_effect_image_list(Path(batch.effect_list_path)).raw:
                changes.append(MonsterLibraryChange(
                    scope="server",
                    target_path=batch.effect_list_path,
                    source_path=None,
                    before_hash=batch.effect_list_before_hash,
                    after_hash=_sha256_bytes(batch.effect_list_after),
                    kind="effect-image-list",
                ))
            for assignment in engine_assignments:
                if str(assignment.get("kind", "")).casefold() != "pak":
                    continue
                entry = str(assignment["target_entry"])
                password = str(assignment.get("pak_password") or "")
                name = Path(entry).name.casefold()
                planned = smart_pak_rules.get(name)
                if planned is not None:
                    if planned[1] != password:
                        blockers.append(
                            f"SmartMonster PAK {Path(entry).name} 计划存在不同密码："
                            f"{planned[1]} 与 {password}"
                        )
                    continue
                smart_pak_rules[name] = (entry, password)
                current = target_passwords.get(name, set())
                if current and current != {password}:
                    blockers.append(
                        f"SmartMonster PAK {Path(entry).name} 已登记不同密码，停止植入："
                        f"现有 {sorted(current)}，计划 {password}"
                    )
                elif not current:
                    new_rule_lines.append(f"{client_data / entry}|{password}")
            valid_records.extend(smart_records)

        by_library: dict[int, list[MonsterRecord]] = {}
        for record in eligible:
            if record.engine_mode == "smartmonster":
                continue
            if resource_keys is not None and record.monster_name.casefold() not in resource_keys:
                continue
            by_library.setdefault(record.library_no, []).append(record)

        for library_no, records in sorted(by_library.items()):
            record = records[0]
            source = Path(record.source_path)
            companion = Path(record.companion_path) if record.companion_path else None
            library_changes: list[MonsterLibraryChange] = []
            conflict_reason = _resource_conflict_reason(
                record,
                pak_rule_file=pak_rule_file,
                target_passwords=target_passwords,
                target_paks=target_paks,
                target_wzls=target_wzls,
                target_wzxs=target_wzxs,
            )
            if record.source_kind == "pak":
                target_pak = target_paks.get(library_no)
                if not conflict_reason and target_pak is None:
                    target_pak = client_data / record.resource_name
                    library_changes.append(MonsterLibraryChange(
                        scope="client", target_path=str(target_pak), source_path=str(source),
                        before_hash=None, after_hash=record.source_hash or "", kind="copy",
                    ))
                if not conflict_reason:
                    current = target_passwords.get(record.resource_name.casefold(), set())
                    if not current:
                        new_rule_lines.append(f"{target_pak}|{record.pak_password}")
            elif record.source_kind == "wzl":
                if not conflict_reason:
                    target_wzl = target_wzls.get(library_no)
                    target_wzx = target_wzxs.get(library_no)
                    if target_wzl is None and target_wzx is None:
                        library_changes.extend((
                            MonsterLibraryChange(
                                scope="client", target_path=str(client_data / source.name),
                                source_path=str(source), before_hash=None,
                                after_hash=record.source_hash or "", kind="copy",
                            ),
                            MonsterLibraryChange(
                                scope="client", target_path=str(client_data / companion.name),
                                source_path=str(companion), before_hash=None,
                                after_hash=record.companion_hash or "", kind="copy",
                            ),
                        ))

            if conflict_reason:
                affected = "、".join(item.monster_name for item in records)
                message = f"Mon{library_no}（{affected}）：{conflict_reason}"
                if conflicts_are_blockers:
                    blockers.append(message)
                else:
                    skipped.append(message)
                continue
            changes.extend(library_changes)
            valid_records.extend(records)
            applied_libraries.append(library_no)
            if any(item.preview_state != "indexed" for item in records):
                warnings.append(f"Mon{library_no}尚无预览缩略图，但完整补丁和Monster资料可以植入")

        pak_rules_after: bytes | None = None
        if new_rule_lines:
            merged = target_rule_text.rstrip("\r\n")
            if merged:
                merged += "\r\n"
            merged += "\r\n".join(new_rule_lines) + "\r\n"
            pak_rules_after = _encode_gbk(merged)
            changes.append(MonsterLibraryChange(
                scope="server", target_path=str(pak_rule_file), source_path=None,
                before_hash=_sha256_file(pak_rule_file), after_hash=_sha256_bytes(pak_rules_after),
                kind="pak-rules",
            ))

        resolved_generator_dir: Path | None = None
        generator_rules_after: bytes | None = None
        generator_rules_added: list[str] = []
        server_rule_bytes = pak_rules_after
        if server_rule_bytes is None and pak_rule_file.is_file():
            server_rule_bytes = pak_rule_file.read_bytes()
        server_rules: dict[str, tuple[str, str]] = {}
        if server_rule_bytes is not None:
            for raw in _decode_legacy(server_rule_bytes).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                line = raw.strip()
                if not line or "|" not in line:
                    continue
                source, password = line.rsplit("|", 1)
                key = Path(source.strip()).name.casefold()
                if key:
                    server_rules[key] = (line, password.strip())
        required_rule_names = {f"mon{library_no}.pak" for library_no in applied_libraries}
        required_rule_names.update(
            Path(str(assignment["target_entry"])).name.casefold()
            for assignment in engine_assignments
            if str(assignment.get("kind", "")).casefold() == "pak"
        )
        required_rules = {
            key: server_rules[key]
            for key in required_rule_names
            if key in server_rules
        }
        if generator_login_dir is not None:
            resolved_generator_dir = Path(generator_login_dir).resolve()
            generator_exe = resolved_generator_dir / "MakeGameLogin.exe"
            generator_rule_file = resolved_generator_dir / "pak.txt"
            if not generator_exe.is_file():
                blockers.append(f"实际登录器目录缺少 MakeGameLogin.exe：{generator_exe}")
            if not generator_rule_file.is_file():
                blockers.append(f"实际登录器目录缺少 pak.txt：{generator_rule_file}")
            if generator_exe.is_file() and generator_rule_file.is_file() and required_rules:
                generator_before = generator_rule_file.read_bytes()
                generator_text = _decode_legacy(generator_before)
                generator_passwords = _pak_passwords_from_text(generator_text)
                append_lines: list[str] = []
                for name, (line, password) in sorted(required_rules.items()):
                    current = generator_passwords.get(name, set())
                    if current and password not in current:
                        blockers.append(
                            f"实际登录器 {name} 已登记不同密码，停止自动同步："
                            f"现有 {sorted(current)}，服务端 {password}"
                        )
                    elif not current:
                        append_lines.append(line)
                        generator_rules_added.append(name)
                if append_lines and not any("实际登录器" in item and "不同密码" in item for item in blockers):
                    if generator_rule_file.resolve() == pak_rule_file.resolve():
                        generator_rules_after = server_rule_bytes
                    else:
                        merged = generator_text.rstrip("\r\n")
                        if merged:
                            merged += "\r\n"
                        merged += "\r\n".join(append_lines) + "\r\n"
                        generator_rules_after = _encode_gbk(merged)
                        changes.append(MonsterLibraryChange(
                            scope="generator",
                            target_path=str(generator_rule_file),
                            source_path=None,
                            before_hash=_sha256_bytes(generator_before),
                            after_hash=_sha256_bytes(generator_rules_after),
                            kind="generator-pak-rules",
                        ))

        database_after: bytes | None = None
        inserted_names: list[str] = []
        updated_names: list[str] = []
        unchanged_names: list[str] = []
        for record in valid_records:
            matches = target_rows.get(record.monster_name.casefold(), [])
            if not matches:
                inserted_names.append(record.monster_name)
                continue
            current = tuple(matches[0][1][item] for item in MONSTER_COLUMNS)
            expected = tuple(record.monster_values[item] for item in MONSTER_COLUMNS)
            if current == expected:
                unchanged_names.append(record.monster_name)
            else:
                updated_names.append(record.monster_name)

        database_write_names = {
            name.casefold() for name in inserted_names + updated_names
        }
        database_records = [
            record for record in valid_records
            if record.monster_name.casefold() in database_write_names
        ]
        if database_records:
            try:
                database_before = target_database.read_bytes()
                database_after = _database_with_monsters(
                    database_before, database_records, allow_updates=allow_updates,
                )
                if database_after != database_before:
                    changes.append(MonsterLibraryChange(
                        scope="server", target_path=str(target_database), source_path=None,
                        before_hash=_sha256_bytes(database_before), after_hash=_sha256_bytes(database_after),
                        kind="monster-database",
                    ))
            except Exception as exc:
                blockers.append(str(exc))
        if skipped and not blockers:
            blockers.append("所选怪物存在未完成的跳过项；请查看跳过原因")
        operation = "monster-library-install"
        fully_deployed = (
            len(valid_records) == len(selected)
            and {record.monster_id for record in valid_records} == set(selected)
            and not skipped
        )
        if fully_deployed and not changes and not blockers:
            operation = "already-deployed"
        elif not changes and not blockers and not allow_updates:
            blockers.append("所选怪物没有可植入内容；请查看跳过原因")
        return MonsterLibraryPlan(
            server_root=server_root,
            client_data=client_data,
            selected_ids=selected,
            monster_names=tuple(record.monster_name for record in valid_records),
            library_numbers=tuple(applied_libraries),
            changes=changes,
            blockers=blockers,
            warnings=warnings,
            skipped=skipped,
            pak_rules_after=pak_rules_after,
            generator_login_dir=resolved_generator_dir,
            generator_rules_after=generator_rules_after,
            generator_rules_added=tuple(generator_rules_added),
            database_after=database_after,
            operation=operation,
            inserted_names=tuple(inserted_names),
            updated_names=tuple(updated_names),
            appearance_changed_names=tuple(
                name for name in appearance_changed_names if name in {item.monster_name for item in valid_records}
            ),
            unchanged_names=tuple(unchanged_names),
            generated_files_after=generated_files_after,
            engine_assignments=engine_assignments,
            requires_custom_monster_dat=bool(smart_records),
            requires_login_regeneration=bool(smart_records),
            custom_monster_dat_path=str(server_root / "Mir200" / "自定义怪物.dat"),
            client_integration_status=(
                "awaiting-client-integration" if smart_records else "not-required"
            ),
        )

    def preflight_records(
        self,
        records: Iterable[MonsterRecord],
        server_root: Path,
        client_data: Path,
        *,
        allow_updates: bool = False,
        resource_required_names: Iterable[str] | None = None,
        appearance_changed_names: Iterable[str] = (),
        conflicts_are_blockers: bool = False,
        generator_login_dir: Path | None = None,
    ) -> MonsterLibraryPlan:
        """Preflight caller-supplied Monster rows while reusing the V2 resource transaction."""
        materialized = tuple(records)
        return self.preflight(
            (record.monster_id for record in materialized),
            server_root,
            client_data,
            record_overrides=materialized,
            allow_updates=allow_updates,
            resource_required_names=resource_required_names,
            appearance_changed_names=appearance_changed_names,
            conflicts_are_blockers=conflicts_are_blockers,
            generator_login_dir=generator_login_dir,
        )

    @staticmethod
    def plan_summary(plan: MonsterLibraryPlan) -> dict[str, object]:
        custom_monster_dat_path = plan.custom_monster_dat_path or str(
            plan.server_root / "Mir200" / "自定义怪物.dat"
        )
        client_integration_status = plan.client_integration_status or (
            "awaiting-client-integration"
            if plan.requires_custom_monster_dat or plan.requires_login_regeneration
            else "not-required"
        )
        return {
            "operation": plan.operation,
            "server": str(plan.server_root),
            "client_data": str(plan.client_data),
            "generator_login_dir": str(plan.generator_login_dir) if plan.generator_login_dir else None,
            "generator_rules_added": list(plan.generator_rules_added),
            "source_workbook": plan.source_workbook_path,
            "source_workbook_hash": plan.source_workbook_hash,
            "selected_monster_ids": list(plan.selected_ids),
            "monster_names": list(plan.monster_names),
            "library_numbers": list(plan.library_numbers),
            "model_assignments": list(plan.model_assignments),
            "inserted_names": list(plan.inserted_names),
            "updated_names": list(plan.updated_names),
            "appearance_changed_names": list(plan.appearance_changed_names),
            "unchanged_names": list(plan.unchanged_names),
            "auto_reselected": list(plan.auto_reselected),
            "name_color_assignments": list(plan.name_color_assignments),
            "generated_files_after": {
                path: _sha256_bytes(content)
                for path, content in sorted(plan.generated_files_after.items())
            },
            "engine_assignments": list(plan.engine_assignments),
            "requires_custom_monster_dat": plan.requires_custom_monster_dat,
            "requires_login_regeneration": plan.requires_login_regeneration,
            "custom_monster_dat_path": custom_monster_dat_path,
            "client_integration_status": client_integration_status,
            "blockers": plan.blockers,
            "warnings": plan.warnings,
            "skipped": plan.skipped,
            "changes": [asdict(change) for change in plan.changes],
        }

    @staticmethod
    def _target_id(server_root: Path, client_data: Path) -> str:
        value = f"{server_root.resolve()}\0{client_data.resolve()}".casefold().encode("utf-8")
        return hashlib.sha256(value).hexdigest()[:16]

    @staticmethod
    def _verify_smartmonster_commit(plan: MonsterLibraryPlan) -> None:
        """Reopen the committed closure and bind every planned index to its target bytes."""
        if not plan.engine_assignments:
            return
        effect_path = plan.server_root / "Mir200" / "Envir" / "EffectImageList.txt"
        document = parse_effect_image_list(effect_path)
        planned_indices: set[int] = set()
        for assignment in plan.engine_assignments:
            index = int(assignment["target_index"])
            entry = str(assignment["target_entry"])
            if index >= len(document.lines) or document.lines[index].strip() != entry:
                raise MonsterLibraryError(f"EffectImageList回读映射不一致：{index} -> {entry}")
            target = plan.client_data / entry
            if _sha256_file(target) != assignment["source_hash"]:
                raise MonsterLibraryError(f"SmartMonster资源哈希回读不一致：{target}")
            companion_hash = assignment.get("companion_hash")
            if companion_hash and _sha256_file(target.with_suffix(".wzx")) != companion_hash:
                raise MonsterLibraryError(f"SmartMonster WZX哈希回读不一致：{target.with_suffix('.wzx')}")
            if str(assignment.get("kind", "")).casefold() == "pak":
                password = str(assignment.get("pak_password") or "")
                name = Path(entry).name.casefold()
                server_rules = _pak_passwords_from_text(_decode_legacy(
                    (plan.server_root / "登录器" / "pak.txt").read_bytes()
                ))
                if server_rules.get(name) != {password}:
                    raise MonsterLibraryError(f"SmartMonster PAK规则回读不一致：{name}")
                if plan.generator_login_dir is not None:
                    generator_rules = _pak_passwords_from_text(_decode_legacy(
                        (plan.generator_login_dir / "pak.txt").read_bytes()
                    ))
                    if generator_rules.get(name) != {password}:
                        raise MonsterLibraryError(f"实际登录器 SmartMonster PAK规则回读不一致：{name}")
            planned_indices.add(index)
        for target_path, expected in plan.generated_files_after.items():
            target = Path(target_path)
            if _sha256_file(target) != _sha256_bytes(expected):
                raise MonsterLibraryError(f"SmartMonster生成文件哈希回读不一致：{target}")
            if target.suffix.casefold() == ".ini":
                if any(index >= 0 and index not in planned_indices for index in _smartmonster_ini_indices(target.read_bytes())):
                    raise MonsterLibraryError(f"SmartMonster INI存在未计划的目标资源号：{target}")

    @staticmethod
    def _final_receipt_status(status: str, client_integration_status: str) -> str:
        if status == "deployed" and client_integration_status == "awaiting-client-integration":
            return "deployed-awaiting-client-integration"
        return status

    @staticmethod
    def _receipt_payload(
        plan: MonsterLibraryPlan,
        transaction_id: str,
        metadata: list[dict[str, object]],
        *,
        status: str,
        completed: list[int],
    ) -> dict[str, object]:
        custom_monster_dat_path = plan.custom_monster_dat_path or str(
            plan.server_root / "Mir200" / "自定义怪物.dat"
        )
        client_integration_status = plan.client_integration_status or (
            "awaiting-client-integration"
            if plan.requires_custom_monster_dat or plan.requires_login_regeneration
            else "not-required"
        )
        receipt_status = MonsterLibraryService._final_receipt_status(
            status,
            client_integration_status,
        )
        return {
            "schema_version": 4,
            "status": receipt_status,
            "recovery_state": {"completed_indices": completed},
            "transaction_id": transaction_id,
            "operation": plan.operation,
            "server_root": str(plan.server_root),
            "client_data": str(plan.client_data),
            "generator_login_dir": str(plan.generator_login_dir) if plan.generator_login_dir else None,
            "generator_rules_added": list(plan.generator_rules_added),
            "source_workbook": plan.source_workbook_path,
            "source_workbook_hash": plan.source_workbook_hash,
            "selected_monster_ids": list(plan.selected_ids),
            "monster_names": list(plan.monster_names),
            "library_numbers": list(plan.library_numbers),
            "model_assignments": list(plan.model_assignments),
            "inserted_names": list(plan.inserted_names),
            "updated_names": list(plan.updated_names),
            "appearance_changed_names": list(plan.appearance_changed_names),
            "unchanged_names": list(plan.unchanged_names),
            "auto_reselected": list(plan.auto_reselected),
            "name_color_assignments": list(plan.name_color_assignments),
            "engine_assignments": list(plan.engine_assignments),
            "requires_custom_monster_dat": plan.requires_custom_monster_dat,
            "requires_login_regeneration": plan.requires_login_regeneration,
            "custom_monster_dat_path": custom_monster_dat_path,
            "client_integration_status": client_integration_status,
            "files": metadata,
        }

    @staticmethod
    def _write_transaction_payload(path: Path, payload: dict[str, object]) -> None:
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))

    @staticmethod
    def _ensure_payload_processes_are_idle(payload: dict[str, object]) -> None:
        server_root = Path(str(payload["server_root"]))
        if is_executable_running(server_root / "Mir200" / "M2Server.exe"):
            raise MonsterLibraryError("M2Server.exe 正在运行，停止文件写入")
        _ensure_client_processes_are_idle(Path(str(payload["client_data"])))

    def _validate_recovery_manifest(self, manifest_path: Path, payload: dict[str, object]) -> None:
        """Treat a persisted in-progress manifest as untrusted before any restore write."""
        def invalid(reason: str) -> None:
            raise MonsterLibraryError(f"恢复清单无效：{reason}")

        if not isinstance(payload, dict) or payload.get("schema_version") != 4:
            invalid("仅接受schema 4 in-progress清单")
        if payload.get("status") != "in-progress":
            invalid("状态不是in-progress")
        transaction_id = payload.get("transaction_id")
        if not isinstance(transaction_id, str) or not re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{8}", transaction_id):
            invalid("事务号格式不正确")
        resolved_backups = self.backups_root.resolve()
        resolved_manifest = Path(manifest_path).resolve()
        transaction_root = resolved_manifest.parent
        if resolved_manifest.name != "in-progress.json" or transaction_root.name != transaction_id:
            invalid("事务目录与事务号不一致")
        if transaction_root.parent.parent != resolved_backups:
            invalid("事务目录不属于备份根目录")
        try:
            server_root = Path(str(payload["server_root"])).resolve()
            client_data = Path(str(payload["client_data"])).resolve()
        except (KeyError, TypeError, ValueError) as exc:
            invalid(f"目标根目录字段错误：{exc}")
        if transaction_root.parent.name != self._target_id(server_root, client_data):
            invalid("target-id与声明目标不一致")
        generator_value = payload.get("generator_login_dir")
        generator_root = Path(str(generator_value)).resolve() if generator_value else None
        original = (transaction_root / "original").resolve()
        if original.parent != transaction_root:
            invalid("original备份目录发生符号链接逃逸")
        files = payload.get("files")
        if not isinstance(files, list) or not files:
            invalid("文件清单为空或格式错误")

        def contained(path: Path, root: Path) -> bool:
            try:
                path.relative_to(root)
            except ValueError:
                return False
            return path != root

        server_kinds = {"effect-image-list", "monster-database", "monster-name-colors", "pak-rules"}
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                invalid(f"文件清单第{index}项不是对象")
            try:
                target = Path(str(item["target_path"])).resolve()
                backup = Path(str(item["backup_path"])).resolve()
                kind = str(item["kind"])
            except (KeyError, TypeError, ValueError) as exc:
                invalid(f"文件清单第{index}项字段错误：{exc}")
            scope = str(item.get("scope") or "")
            if scope == "server" or kind in server_kinds:
                roots = (server_root,)
            elif scope == "client" or kind == "copy":
                roots = (client_data,)
            elif scope == "generator" or kind == "generator-pak-rules":
                roots = (generator_root,) if generator_root is not None else ()
            elif scope == "smartmonster" or kind == "smart-generated-file":
                roots = (server_root, client_data)
            else:
                invalid(f"文件清单第{index}项范围不可识别：{scope or kind}")
            if not roots or not any(contained(target, root) for root in roots):
                invalid(f"文件清单第{index}项目标越界：{target}")
            if not contained(backup, original):
                invalid(f"文件清单第{index}项备份越界：{backup}")
            if bool(item.get("existed")) and not backup.is_file():
                invalid(f"文件清单第{index}项缺少原始备份：{backup}")

    @staticmethod
    def _restore_payload(payload: dict[str, object], *, allow_before: bool) -> None:
        files = list(payload.get("files", []))
        for item in files:
            target = Path(str(item["target_path"])).resolve()
            current = _sha256_file(target)
            before = item.get("before_hash")
            after = item.get("after_hash")
            if current == after:
                continue
            if allow_before and current == before:
                continue
            if allow_before:
                raise MonsterLibraryError(f"中断后目标文件发生未知漂移，停止恢复：{target}")
            raise MonsterLibraryError(f"目标文件在植入后被修改，停止回滚：{target}")
        for item in reversed(files):
            target = Path(str(item["target_path"])).resolve()
            if allow_before and _sha256_file(target) == item.get("before_hash"):
                continue
            if item.get("existed"):
                backup = Path(str(item["backup_path"])).resolve()
                _copy_verified(backup, target, str(item.get("before_hash")))
            else:
                target.unlink(missing_ok=True)

    def _recover_manifest(self, manifest_path: Path, payload: dict[str, object] | None = None) -> str:
        if payload is None:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._validate_recovery_manifest(manifest_path, payload)
        self._ensure_payload_processes_are_idle(payload)
        self._restore_payload(payload, allow_before=True)
        payload["status"] = "recovered"
        payload["recovery_state"] = {"completed_indices": [], "outcome": "rolled-back"}
        self._write_transaction_payload(manifest_path, payload)
        os.replace(manifest_path, manifest_path.with_name("recovered.json"))
        return str(payload["transaction_id"])

    def recover_in_progress(self) -> tuple[str, ...]:
        manifests = sorted(self.backups_root.glob("*/**/in-progress.json"))
        validated = []
        for path in manifests:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._validate_recovery_manifest(path, payload)
            validated.append((path, payload))
        return tuple(self._recover_manifest(path, payload) for path, payload in validated)

    def install(self, plan: MonsterLibraryPlan) -> MonsterLibraryReceipt:
        if plan.blockers:
            raise MonsterLibraryError("预检阻止植入：" + "；".join(plan.blockers))
        if is_executable_running(plan.server_root / "Mir200" / "M2Server.exe"):
            raise MonsterLibraryError("M2Server.exe 已在预检后启动，停止植入")
        _ensure_client_processes_are_idle(plan.client_data)
        if plan.source_workbook_path:
            workbook = Path(plan.source_workbook_path)
            if _sha256_file(workbook) != plan.source_workbook_hash:
                raise MonsterLibraryError(f"预检后怪物生成表发生变化：{workbook}")
        transaction_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        transaction_root = self.backups_root / self._target_id(plan.server_root, plan.client_data) / transaction_id
        original = transaction_root / "original"
        transaction_root.mkdir(parents=True, exist_ok=False)
        original.mkdir(parents=True)
        metadata: list[dict[str, object]] = []
        for index, change in enumerate(plan.changes):
            target = Path(change.target_path)
            current_hash = _sha256_file(target)
            if current_hash != change.before_hash:
                raise MonsterLibraryError(f"预检后目标文件发生变化：{target}")
            backup = original / f"{index:04d}_{target.name}"
            if target.is_file():
                shutil.copy2(target, backup)
            metadata.append({
                "target_path": str(target),
                "backup_path": str(backup),
                "existed": target.is_file(),
                "before_hash": change.before_hash,
                "after_hash": change.after_hash,
                "kind": change.kind,
                "scope": change.scope,
            })

        manifest_path = transaction_root / "in-progress.json"
        committed: list[int] = []
        manifest_payload = self._receipt_payload(
            plan, transaction_id, metadata, status="in-progress", completed=committed,
        )
        self._write_transaction_payload(manifest_path, manifest_payload)
        try:
            for index, change in enumerate(plan.changes):
                target = Path(change.target_path)
                if change.kind == "pak-rules":
                    if plan.pak_rules_after is None:
                        raise MonsterLibraryError("计划缺少PAK登记内容")
                    _atomic_write(target, plan.pak_rules_after)
                elif change.kind == "generator-pak-rules":
                    if plan.generator_rules_after is None:
                        raise MonsterLibraryError("计划缺少实际登录器PAK登记内容")
                    _atomic_write(target, plan.generator_rules_after)
                elif change.kind == "monster-database":
                    if plan.database_after is None:
                        raise MonsterLibraryError("计划缺少怪物数据库内容")
                    _atomic_write(target, plan.database_after)
                elif change.kind == "monster-name-colors":
                    if plan.mon_gen_after is None:
                        raise MonsterLibraryError("计划缺少怪物名字颜色内容")
                    _atomic_write(target, plan.mon_gen_after)
                elif change.kind in {"smart-generated-file", "effect-image-list"}:
                    content = plan.generated_files_after.get(str(target))
                    if content is None:
                        raise MonsterLibraryError(f"计划缺少SmartMonster生成内容：{target}")
                    _atomic_write(target, content)
                else:
                    if not change.source_path:
                        raise MonsterLibraryError(f"计划缺少来源文件：{target}")
                    _copy_verified(Path(change.source_path), target, change.after_hash)
                if _sha256_file(target) != change.after_hash:
                    raise MonsterLibraryError(f"植入后哈希回读失败：{target}")
                committed.append(index)
                manifest_payload["recovery_state"] = {"completed_indices": committed}
                self._write_transaction_payload(manifest_path, manifest_payload)
            self._verify_smartmonster_commit(plan)
        except Exception as exc:
            try:
                self._restore_payload(manifest_payload, allow_before=True)
                manifest_payload["status"] = "recovered"
                manifest_payload["recovery_state"] = {"completed_indices": [], "outcome": "rolled-back"}
                self._write_transaction_payload(manifest_path, manifest_payload)
                os.replace(manifest_path, manifest_path.with_name("recovered.json"))
            except Exception as rollback_exc:
                raise MonsterLibraryError(f"怪物库植入失败且自动回滚失败：{rollback_exc}") from exc
            raise MonsterLibraryError(f"怪物库植入失败，已回滚：{exc}") from exc

        manifest_payload["status"] = self._final_receipt_status(
            "deployed",
            str(manifest_payload.get("client_integration_status") or "not-required"),
        )
        manifest_payload["recovery_state"] = {"completed_indices": committed}
        self._write_transaction_payload(manifest_path, manifest_payload)
        receipt_path = transaction_root / "receipt.json"
        os.replace(manifest_path, receipt_path)
        return MonsterLibraryReceipt(
            transaction_id=transaction_id,
            server_root=str(plan.server_root),
            client_data=str(plan.client_data),
            selected_ids=plan.selected_ids,
            monster_names=plan.monster_names,
            library_numbers=plan.library_numbers,
            receipt_path=str(receipt_path),
        )

    def rollback(self, transaction_id: str) -> None:
        if not re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{8}", transaction_id):
            raise MonsterLibraryError("事务号格式不正确")
        matches = list(self.backups_root.glob(f"*/{transaction_id}/receipt.json"))
        if not matches:
            in_progress = list(self.backups_root.glob(f"*/{transaction_id}/in-progress.json"))
            if len(in_progress) == 1:
                self._recover_manifest(in_progress[0])
                return
        if len(matches) != 1:
            raise MonsterLibraryError(f"无法唯一定位事务：{transaction_id}")
        payload = json.loads(matches[0].read_text(encoding="utf-8"))
        self._ensure_payload_processes_are_idle(payload)
        self._restore_payload(payload, allow_before=False)


class MonsterLibraryBridge:
    def __init__(self, platform_root: Path):
        self.service = MonsterLibraryService(platform_root)

    @property
    def catalog_path(self) -> Path:
        return self.service.catalog_path

    def scan(self, *args, **kwargs) -> CatalogScanResult:
        return self.service.scan(*args, **kwargs)

    def list_monsters(self, status: str = "all", server_root: Path | None = None) -> list[MonsterRecord]:
        return self.service.list_monsters(status, server_root)

    def list_appearances(self, status: str = "all") -> list[MonsterRecord]:
        return self.service.list_appearances(status)

    def import_sidecars(self, source: Path) -> SidecarImportResult:
        return self.service.import_sidecars(source)

    def preflight(
        self,
        monster_ids: Iterable[int],
        server_root: Path,
        client_data: Path,
        *,
        generator_login_dir: Path | None = None,
    ) -> MonsterLibraryPlan:
        return self.service.preflight(
            monster_ids,
            server_root,
            client_data,
            generator_login_dir=generator_login_dir,
        )

    def install(self, plan: MonsterLibraryPlan) -> MonsterLibraryReceipt:
        return self.service.install(plan)

    def rollback(self, transaction_id: str) -> None:
        self.service.rollback(transaction_id)
