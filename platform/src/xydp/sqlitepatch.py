from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any


class SqlitePatchError(ValueError):
    pass


STD_ITEMS_COLUMNS = {
    "Idx", "Name", "StdMode", "Shape", "Weight", "Anicount", "Source", "Reserved",
    "Looks", "DuraMax", "Ac", "Ac2", "Mac", "Mac2", "Dc", "Dc2", "Mc", "Mc2",
    "Sc", "Sc2", "Need", "NeedLevel", "Price", "Stock", "Color", "OverLap", "HP", "MP",
    "Light", "Horse", "Element", "Expand1", "Expand2", "InsuranceCurrency", "InsuranceGold",
    "Expand3", "Expand4", "Expand5", "Asc", "Asc2", "Arc", "Arc2", "Mpc", "Mpc2", "Job",
    "Element26", "CustomItem",
    *(f"Element{index}" for index in range(1, 26)),
}

SQLITE_TABLE_COLUMNS = {"StdItems": STD_ITEMS_COLUMNS}

MAGIC_SKILL_MATCH_FIELDS = {"MagID", "MagName", "Job"}
MAGIC_SKILL_VALUE_FIELDS = {"CanUpgrade", "MaxUpgradeLv"}


def validate_sqlite_magic_skill_update_operation(operation: dict[str, Any]) -> None:
    target = str(operation.get("target", "")).replace("\\", "/")
    if target != "Mud2/DB/ApexM2.DB":
        raise SqlitePatchError("技能升级开关只允许修改 Mud2/DB/ApexM2.DB")

    match = operation.get("match")
    if not isinstance(match, dict) or set(match) != MAGIC_SKILL_MATCH_FIELDS:
        raise SqlitePatchError("技能升级开关 match 字段必须恰好是 MagID、MagName、Job")
    mag_id = match.get("MagID")
    if isinstance(mag_id, bool) or not isinstance(mag_id, int) or mag_id <= 0:
        raise SqlitePatchError("技能升级开关 MagID 必须是正整数")
    if not isinstance(match.get("MagName"), str) or not match["MagName"].strip():
        raise SqlitePatchError("技能升级开关 MagName 必须是非空文本")
    job = match.get("Job")
    allow_normal_professions = operation.get("allow_normal_professions") is True
    if allow_normal_professions:
        if isinstance(job, bool) or not isinstance(job, int) or job not in {0, 1, 2}:
            raise SqlitePatchError("技能升级开关 Job 只允许 0、1、2（普通三职业技能）")
    elif job != 0:
        raise SqlitePatchError("技能升级开关 Job 只允许 0（普通战士技能）")

    values = operation.get("values")
    if not isinstance(values, dict) or set(values) != MAGIC_SKILL_VALUE_FIELDS:
        raise SqlitePatchError("技能升级开关 values 字段必须恰好是 CanUpgrade、MaxUpgradeLv")
    if values.get("CanUpgrade") != 1:
        raise SqlitePatchError("技能升级开关 CanUpgrade 只允许写入 1")
    max_level = values.get("MaxUpgradeLv")
    if isinstance(max_level, bool) or not isinstance(max_level, int) or not 1 <= max_level <= 9:
        raise SqlitePatchError("技能升级开关 MaxUpgradeLv 只允许 1 到 9")


def apply_sqlite_magic_skill_update(
    database_bytes: bytes | None,
    operation: dict[str, Any],
) -> bytes:
    validate_sqlite_magic_skill_update_operation(operation)
    if database_bytes is None:
        raise SqlitePatchError("技能升级开关目标数据库不存在")

    match = dict(operation["match"])
    values = dict(operation["values"])
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
            raise SqlitePatchError(f"SQLite 数据库完整性检查失败: {integrity}")

        schema_columns = {
            str(row[1]) for row in connection.execute('PRAGMA table_info("Magic")').fetchall()
        }
        required = MAGIC_SKILL_MATCH_FIELDS | MAGIC_SKILL_VALUE_FIELDS
        missing = sorted(required - schema_columns)
        if missing:
            raise SqlitePatchError(f"目标 Magic 表缺少字段: {', '.join(missing)}")

        rows = connection.execute(
            'SELECT rowid, "CanUpgrade", "MaxUpgradeLv" FROM "Magic" '
            'WHERE "MagID" = ? AND "MagName" = ? AND "Job" = ?',
            (match["MagID"], match["MagName"], match["Job"]),
        ).fetchall()
        if len(rows) != 1:
            raise SqlitePatchError(
                f"技能记录匹配不唯一: {match['MagName']}（匹配到 {len(rows)} 行）"
            )

        rowid, current_can_upgrade, current_max_level = rows[0]
        desired = (values["CanUpgrade"], values["MaxUpgradeLv"])
        current = (current_can_upgrade, current_max_level)
        if current == desired:
            return database_bytes
        if current != (0, 0):
            raise SqlitePatchError(
                f"当前升级开关状态冲突: {match['MagName']} 为 "
                f"CanUpgrade={current_can_upgrade}, MaxUpgradeLv={current_max_level}"
            )

        cursor = connection.execute(
            'UPDATE "Magic" SET "CanUpgrade" = ?, "MaxUpgradeLv" = ? WHERE rowid = ?',
            (values["CanUpgrade"], values["MaxUpgradeLv"], rowid),
        )
        if cursor.rowcount != 1:
            raise SqlitePatchError(f"技能升级开关更新行数异常: {cursor.rowcount}")
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise SqlitePatchError(f"SQLite 写入后完整性检查失败: {integrity}")
        connection.close()
        connection = None
        return temp_path.read_bytes()
    except sqlite3.Error as exc:
        raise SqlitePatchError(f"SQLite 技能升级开关操作失败: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def validate_sqlite_upsert_operation(operation: dict[str, Any]) -> None:
    table = operation.get("table")
    if table not in SQLITE_TABLE_COLUMNS:
        raise SqlitePatchError(f"SQLite 表不在白名单: {table}")
    if operation.get("unique_key") != ["Name"]:
        raise SqlitePatchError("StdItems 只允许以 Name 作为唯一键")
    if operation.get("allocate") != {"Idx": "max_plus_one"}:
        raise SqlitePatchError("StdItems 必须由平台按 max_plus_one 分配 Idx")
    if operation.get("on_conflict", "error") != "error":
        raise SqlitePatchError("SQLite 冲突策略只允许 error")
    values = operation.get("values")
    if not isinstance(values, dict) or not values:
        raise SqlitePatchError("SQLite values 必须是非空对象")
    if "Idx" in values:
        raise SqlitePatchError("SQLite values 禁止自行指定 Idx")
    if not isinstance(values.get("Name"), str) or not values["Name"].strip():
        raise SqlitePatchError("StdItems Name 必须是非空文本")
    allowed = SQLITE_TABLE_COLUMNS[table]
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise SqlitePatchError(f"SQLite 字段不在白名单: {', '.join(unknown)}")
    for column, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise SqlitePatchError(f"SQLite 字段值类型无效: {column}")
    conflict_keys = operation.get("conflict_keys", [])
    if not isinstance(conflict_keys, list):
        raise SqlitePatchError("conflict_keys 必须是数组")
    for key in conflict_keys:
        if not isinstance(key, list) or not key:
            raise SqlitePatchError("conflict_keys 中每项必须是非空字段数组")
        if any(column not in allowed for column in key):
            raise SqlitePatchError(f"SQLite 冲突字段不在白名单: {key}")
        if any(column not in values for column in key):
            raise SqlitePatchError(f"SQLite 冲突字段缺少写入值: {key}")


def apply_sqlite_upsert(database_bytes: bytes | None, operation: dict[str, Any]) -> bytes:
    validate_sqlite_upsert_operation(operation)
    if database_bytes is None:
        raise SqlitePatchError("SQLite 目标数据库不存在")
    table = str(operation["table"])
    values = dict(operation["values"])
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
            raise SqlitePatchError(f"SQLite 数据库完整性检查失败: {integrity}")
        schema_columns = {
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        required = {"Idx", *values.keys()}
        missing = sorted(required - schema_columns)
        if missing:
            raise SqlitePatchError(f"目标 StdItems 缺少字段: {', '.join(missing)}")

        value_columns = list(values)
        selected = ", ".join(f'"{column}"' for column in value_columns)
        existing = connection.execute(
            f'SELECT {selected} FROM "{table}" WHERE "Name" = ?',
            (values["Name"],),
        ).fetchall()
        if len(existing) > 1:
            raise SqlitePatchError(f"同名记录不唯一: {values['Name']}")
        if existing:
            expected = tuple(values[column] for column in value_columns)
            if existing[0] == expected:
                return database_bytes
            raise SqlitePatchError(f"同名记录存在但属性不一致: {values['Name']}")

        for conflict_key in operation.get("conflict_keys", []):
            where = " AND ".join(f'"{column}" = ?' for column in conflict_key)
            parameters = tuple(values[column] for column in conflict_key)
            occupied = connection.execute(
                f'SELECT "Name" FROM "{table}" WHERE {where} LIMIT 1', parameters
            ).fetchone()
            if occupied:
                fields = ",".join(conflict_key)
                raise SqlitePatchError(f"字段占用冲突 {fields}: 已被 {occupied[0]} 使用")

        next_idx = connection.execute(f'SELECT COALESCE(MAX("Idx"), 0) + 1 FROM "{table}"').fetchone()[0]
        columns = ["Idx", *value_columns]
        placeholders = ", ".join("?" for _ in columns)
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        connection.execute(
            f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders})',
            (next_idx, *(values[column] for column in value_columns)),
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise SqlitePatchError(f"SQLite 写入后完整性检查失败: {integrity}")
        connection.close()
        connection = None
        return temp_path.read_bytes()
    except sqlite3.Error as exc:
        raise SqlitePatchError(f"SQLite 操作失败: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
