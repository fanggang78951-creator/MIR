from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from .legacy import xy_equip_maker as legacy_core
from .paths import EquipmentPaths
from .planner import EquipmentPlan
from .transaction import atomic_write_bytes, sha256_file
from .item_hint import apply_item_hints, selections_from_compiled


class EquipmentInstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class EquipmentReceipt:
    transaction_id: str
    target_root: str
    equipment_names: tuple[str, ...]
    receipt_path: str


class EquipmentInstaller:
    def __init__(self, platform_root: Path):
        self.platform_root = Path(platform_root).resolve()
        self.backup_root = self.platform_root / "做装备" / "backups"

    @staticmethod
    def _target_id(root: Path) -> str:
        return hashlib.sha256(str(Path(root).resolve()).casefold().encode("utf-8")).hexdigest()[:16]

    def _transaction_root(self, target: Path, transaction_id: str) -> Path:
        return self.backup_root / self._target_id(target) / transaction_id

    @staticmethod
    def _change_key(scope: str, relative_path: str) -> str:
        return relative_path if scope == "server" else f"{scope}:{relative_path}"

    @staticmethod
    def _live_path(plan: EquipmentPlan, scope: str, relative_path: str) -> Path:
        if scope == "server":
            return plan.target.root / Path(relative_path)
        if scope == "client":
            if plan.paths.client_data is None:
                raise EquipmentInstallError("计划包含客户端资源，但没有客户端 data 路径")
            return plan.paths.client_data / Path(relative_path)
        raise EquipmentInstallError(f"未知装备事务范围：{scope}")

    @staticmethod
    def _working_path(working: Path, scope: str, relative_path: str) -> Path:
        root = working if scope == "server" else working / "__client__"
        return root / Path(relative_path)

    @staticmethod
    def _backup_path(original: Path, scope: str, relative_path: str) -> Path:
        root = original if scope == "server" else original / "__client__"
        return root / Path(relative_path)

    def install(self, plan: EquipmentPlan) -> EquipmentReceipt:
        if plan.blockers:
            raise EquipmentInstallError("预检阻止安装：" + "；".join(plan.blockers))
        transaction_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        transaction_root = self._transaction_root(plan.target.root, transaction_id)
        if plan.operation == "material_create" and not plan.equipment_names:
            transaction_root.mkdir(parents=True, exist_ok=False)
            receipt_path = transaction_root / "receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "transaction_id": transaction_id,
                        "created_at": dt.datetime.now().isoformat(),
                        "target_root": str(plan.target.root),
                        "client_root": str(plan.paths.client_data) if plan.paths.client_data is not None else None,
                        "workbook_hash": plan.workbook_hash,
                        "operation": plan.operation,
                        "equipment_names": [],
                        "skipped_existing": list(plan.skipped_existing),
                        "files": {},
                        "status": "no_changes",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return EquipmentReceipt(transaction_id, str(plan.target.root), (), str(receipt_path))
        working = transaction_root / "working"
        original = transaction_root / "original"
        specs = transaction_root / "generated_txt"
        transaction_root.mkdir(parents=True, exist_ok=False)
        specs.mkdir(parents=True)

        metadata: dict[str, dict[str, object]] = {}
        for change in plan.changes:
            source = self._live_path(plan, change.scope, change.relative_path)
            work_path = self._working_path(working, change.scope, change.relative_path)
            backup_path = self._backup_path(original, change.scope, change.relative_path)
            if source.exists():
                work_path.parent.mkdir(parents=True, exist_ok=True)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, work_path)
                shutil.copy2(source, backup_path)
            key = self._change_key(change.scope, change.relative_path)
            metadata[key] = {
                "existed": source.exists(),
                "before_hash": change.before_hash,
                "scope": change.scope,
                "relative_path": change.relative_path,
            }

        old_paths = legacy_core._PATHS
        working_client = working / "__client__" if any(change.scope == "client" for change in plan.changes) else plan.paths.client_data
        working_paths = EquipmentPaths.for_target(self.platform_root, working, working_client)
        create_reads_static_icons = plan.operation == "create" and any(
            "[图标来源]" in row.equipment_text for row in plan.compiled.rows
        )
        if (
            create_reads_static_icons
            and working_client is not None
            and plan.paths.client_data is not None
            and working_client != plan.paths.client_data
        ):
            working_client.mkdir(parents=True, exist_ok=True)
            for library in legacy_core.STATIC_ICON_LIBRARIES:
                for suffix in ("wzl", "wzx"):
                    source = plan.paths.client_data / f"{library}.{suffix}"
                    destination = working_client / source.name
                    if source.exists() and not destination.exists():
                        shutil.copy2(source, destination)
        if plan.operation == "repair_display":
            working_paths.db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan.paths.db_path, working_paths.db_path)
        if plan.operation != "material_create":
            for shared_path in (working_paths.item_desc, working_paths.item_rule, working_paths.group_item):
                if not shared_path.exists():
                    shared_path.parent.mkdir(parents=True, exist_ok=True)
                    shared_path.write_bytes(b"")
        hint_selections = selections_from_compiled(plan.compiled) if plan.operation in {"create", "item_hint_sync"} else ()
        if hint_selections and working_paths.client_data is not None:
            working_paths.client_data.mkdir(parents=True, exist_ok=True)
        if hint_selections and not working_paths.effect_image_list.exists():
            working_paths.effect_image_list.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan.paths.effect_image_list, working_paths.effect_image_list)
        update_icon_cache: dict[int, int] = {}
        update_icon_metadata: list[dict[str, object]] = []
        try:
            legacy_core.configure_paths(working_paths)
            legacy_core.BACKUP_ROOT = transaction_root / "legacy_backups"
            legacy_core.OUTPUT_DIR = transaction_root / "legacy_logs"
            for row in plan.compiled.rows:
                spec_path = specs / f"{legacy_core.safe_filename(row.name)}.txt"
                spec_path.write_text(row.equipment_text, encoding="utf-8")
                if plan.operation == "item_hint_sync":
                    continue
                if plan.operation == "repair_display":
                    spec = legacy_core.parse_spec(spec_path)
                    legacy_core.validate_template_exists(spec)
                    qfunction_text = legacy_core.build_qfunction_text(
                        spec,
                        legacy_core.load_script_props(),
                        allow_existing_effect_branch=True,
                    )
                    if qfunction_text is not None:
                        legacy_core.write_mir_text(legacy_core.QFUNCTION, qfunction_text)
                elif plan.operation == "update" or (plan.operation == "create" and row.operation == "update"):
                    from .update import update_equipment_row
                    update_equipment_row(
                        dict(row.source_values),
                        spec_path,
                        icon_cache=update_icon_cache,
                        icon_metadata=update_icon_metadata,
                    )
                elif plan.operation == "material_create":
                    legacy_core.make_material(spec_path)
                else:
                    legacy_core.make_equipment(spec_path)
                    created_spec = legacy_core.parse_spec(spec_path)
                    if created_spec.icon_source:
                        source_id = int(created_spec.icon_source["source_id"])
                        update_icon_metadata.append({
                            "name": row.name,
                            "source_id": source_id,
                            "old_looks": None,
                            "new_looks": source_id,
                            "action": "reuse_source_id",
                            "client_files_changed": False,
                        })
            if hint_selections:
                apply_item_hints(working_paths, hint_selections)
            if plan.operation != "item_hint_sync":
                connection = sqlite3.connect(working_paths.db_path)
                try:
                    integrity = connection.execute("PRAGMA integrity_check").fetchone()
                finally:
                    connection.close()
                if not integrity or integrity[0] != "ok":
                    raise EquipmentInstallError(f"临时数据库完整性检查失败：{integrity}")
        except Exception as exc:
            raise EquipmentInstallError(f"临时副本生成失败，目标服未修改：{exc}") from exc
        finally:
            legacy_core.configure_paths(old_paths)

        for change in plan.changes:
            current = self._live_path(plan, change.scope, change.relative_path)
            if sha256_file(current) != change.before_hash:
                raise EquipmentInstallError(f"预检后目标文件发生变化，已停止：{change.relative_path}")
            generated = self._working_path(working, change.scope, change.relative_path)
            if not generated.exists():
                raise EquipmentInstallError(f"临时副本缺少计划文件：{change.relative_path}")
            key = self._change_key(change.scope, change.relative_path)
            metadata[key]["after_hash"] = sha256_file(generated)

        committed: list[str] = []
        try:
            for change in plan.changes:
                relative = change.relative_path
                target_path = self._live_path(plan, change.scope, relative)
                generated = self._working_path(working, change.scope, relative)
                atomic_write_bytes(target_path, generated.read_bytes())
                committed.append(self._change_key(change.scope, relative))

            receipt_data = {
                "schema_version": 3,
                "transaction_id": transaction_id,
                "created_at": dt.datetime.now().isoformat(),
                "target_root": str(plan.target.root),
                "client_root": str(plan.paths.client_data) if plan.paths.client_data is not None else None,
                "workbook_hash": plan.workbook_hash,
                "operation": plan.operation,
                "row_operations": {row.name: ("update" if plan.operation == "update" else row.operation) for row in plan.compiled.rows},
                "coverage_count": len(plan.equipment_names) if plan.operation == "update" else None,
                "fixed_durability": 60000 if plan.operation in {"create", "update"} else None,
                "skipped_fields": ["StdMode/Shape"] if plan.operation == "update" else [],
                "source_icon_results": update_icon_metadata if plan.operation in {"create", "update"} else [],
                "source_blank_policy": "保留旧Looks" if plan.operation == "update" else None,
                "equipment_names": plan.equipment_names,
                "skipped_existing": list(plan.skipped_existing),
                "files": metadata,
                "status": "installed",
            }
            receipt_path = transaction_root / "receipt.json"
            receipt_path.write_text(json.dumps(receipt_data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._append_state(
                plan.target.root,
                transaction_id,
                plan.workbook_hash,
                plan.equipment_names,
                plan.operation,
            )
        except Exception as exc:
            for key in reversed(committed):
                info = metadata[key]
                scope = str(info.get("scope", "server"))
                relative = str(info.get("relative_path", key))
                target_path = self._live_path(plan, scope, relative)
                backup_path = self._backup_path(original, scope, relative)
                if info["existed"]:
                    atomic_write_bytes(target_path, backup_path.read_bytes())
                elif target_path.exists():
                    target_path.unlink()
            raise EquipmentInstallError(f"正式提交失败，已恢复安装前文件：{exc}") from exc

        return EquipmentReceipt(transaction_id, str(plan.target.root), tuple(plan.equipment_names), str(receipt_path))

    def _append_state(
        self,
        target: Path,
        transaction_id: str,
        workbook_hash: str,
        names: list[str],
        operation: str,
    ) -> None:
        state_path = target / ".xydp" / "equipment-installed.json"
        state = {"schema_version": 1, "transactions": []}
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
        state.setdefault("transactions", []).append(
            {
                "transaction_id": transaction_id,
                "workbook_hash": workbook_hash,
                "equipment_names": names,
                "operation": operation,
            }
        )
        atomic_write_bytes(state_path, json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))

    def rollback(self, target: Path, transaction_id: str) -> None:
        target = Path(target).resolve()
        transaction_root = self._transaction_root(target, transaction_id)
        receipt_path = transaction_root / "receipt.json"
        if not receipt_path.exists():
            raise EquipmentInstallError(f"找不到安装收据：{transaction_id}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if Path(receipt["target_root"]).resolve() != target:
            raise EquipmentInstallError("安装收据与当前目标服不匹配")
        client_root = Path(receipt["client_root"]).resolve() if receipt.get("client_root") else None

        def live_path(key: str, info: dict[str, object]) -> Path:
            scope = str(info.get("scope", "server"))
            relative = str(info.get("relative_path", key.split(":", 1)[-1] if scope != "server" else key))
            if scope == "server":
                return target / Path(relative)
            if scope == "client" and client_root is not None:
                return client_root / Path(relative)
            raise EquipmentInstallError(f"回滚收据缺少客户端路径：{key}")

        for key, info in receipt["files"].items():
            if sha256_file(live_path(key, info)) != info["after_hash"]:
                raise EquipmentInstallError(f"受管文件已被手工修改，阻止回滚：{key}")
        for key, info in receipt["files"].items():
            scope = str(info.get("scope", "server"))
            relative = str(info.get("relative_path", key.split(":", 1)[-1] if scope != "server" else key))
            target_path = live_path(key, info)
            backup_path = self._backup_path(transaction_root / "original", scope, relative)
            if info["existed"]:
                atomic_write_bytes(target_path, backup_path.read_bytes())
            elif target_path.exists():
                target_path.unlink()
        receipt["status"] = "rolled_back"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        state_path = target / ".xydp" / "equipment-installed.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["transactions"] = [
                item for item in state.get("transactions", []) if item.get("transaction_id") != transaction_id
            ]
            if state["transactions"]:
                atomic_write_bytes(state_path, json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))
            else:
                state_path.unlink()
                try:
                    state_path.parent.rmdir()
                except OSError:
                    pass
