"""Read-only capability cards derived from the live package and document registries."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from uuid import uuid4
from pathlib import Path


DOC_DIRECTORY = "所需材料表格汇总"
REGISTRY = "00_填写文档注册表.json"
CONFIG_CONSUMERS = {
    "initial-camp", "king-mode", "xy.ops.first-pick", "xy.ui.attr-overview",
    "recycle-config", "growth-stage", "equipment-collection", "item-synthesis",
    "mingge-npc", "mingge-content", "weapon-enchant", "attack-speed-breakthrough",
    "equipment-wash-import",
}
SPECIALIST_TABS = {
    "equipment": "批量做装备", "monster-library": "怪物库",
    "equipment-graphics": "批量做装备",
    "seal-title-two-npc": "NPC编辑", "equipment-aura": "装备光环",
    "monster-execution-pilot": "处决测试", "map-workbench": "玄渊界面施工台",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default


def _equipment_graphics_target_root(config_path: Path) -> Path:
    manifest = _json(config_path)
    target = manifest.get("target") if isinstance(manifest, dict) else None
    if not isinstance(target, dict):
        raise ValueError("装备素材替换配置必须提供 target.serverRoot 或 target.database")

    server_root_path: Path | None = None
    server_root = target.get("serverRoot")
    if server_root is not None:
        if not isinstance(server_root, str) or not Path(server_root).is_absolute():
            raise ValueError("装备素材替换配置 target.serverRoot 必须为绝对路径")
        server_root_path = Path(server_root).resolve()

    database = target.get("database")
    if database is not None:
        if not isinstance(database, str) or not Path(database).is_absolute():
            raise ValueError("装备素材替换配置 target.database 必须为绝对路径")
        database_path = Path(database).resolve()
        if server_root_path is not None:
            if not database_path.is_relative_to(server_root_path):
                raise ValueError("装备素材替换配置 target.database 必须位于 target.serverRoot 目录内")
        elif database_path.parent.name.casefold() == "db" and database_path.parent.parent.name.casefold() == "mud2":
            server_root_path = database_path.parent.parent.parent
        else:
            raise ValueError("无法从 target.database 推断服务端根目录；请补充 target.serverRoot")

    if server_root_path is None:
        raise ValueError("装备素材替换配置必须提供 target.serverRoot 或 target.database")
    return server_root_path


class ProjectOverview:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _inside(self, relative: str) -> Path:
        p = (self.root / relative).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError(f"平台路径越界：{relative}")
        return p

    def _input(self, filename: str) -> dict:
        if Path(filename).name != filename or filename in {"", ".", ".."} or "\\" in filename or "/" in filename:
            raise ValueError(f"填写文档路径无效：{filename}")
        p = self._inside(f"{DOC_DIRECTORY}/{filename}")
        return {"name": filename, "path": str(p), "exists": p.is_file(), "sha256": digest(p) if p.is_file() else ""}

    def cards(self) -> list[dict]:
        annotations = _json(self.root / "catalog/feature_annotations.json", {}).get("features", {})
        # The release is small source code; resources are bound per package below.
        self._execution_sources = {str(p.relative_to(self.root)).replace("\\", "/")
                                   for folder in (self.root / "src/xydp", self.root / "做装备/src/xyequip")
                                   if folder.is_dir() for p in folder.rglob("*.py")}
        cards = []
        registry = _json(self.root / DOC_DIRECTORY / REGISTRY, {"documents": []})
        self._package_manifests = {}
        for path in (self.root / "packages").glob("*/*/manifest.json"):
            if path.parent.parent.name not in {"verified", "candidate"}: continue
            self._inside(str(path.relative_to(self.root)))
            manifest = _json(path)
            if manifest["id"] in self._package_manifests: raise ValueError(f"活动成果包ID重复：{manifest['id']}")
            self._package_manifests[manifest["id"]] = (path, manifest)
        seen = set()
        for doc in registry["documents"]:
            ident = "document:" + doc["id"]
            if ident in seen: raise ValueError(f"填写文档ID重复：{ident}")
            seen.add(ident)
            consumer = doc["consumer"]
            supported = consumer in CONFIG_CONSUMERS or consumer in SPECIALIST_TABS
            tab = "脚本配置同步" if consumer in CONFIG_CONSUMERS else SPECIALIST_TABS.get(consumer, "")
            input_names = [doc["file"]]
            if consumer == "item-synthesis":
                input_names = [d["file"] for d in registry["documents"] if d["consumer"] == consumer]
            card = {"id": ident, "name": Path(doc["file"]).stem, "kind": "填写文档", "version": "随平台发布",
                    "package_status": "", "residency": "", "dependencies": [],
                    "inputs": [self._input(name) for name in input_names], "source": str(self.root/DOC_DIRECTORY/REGISTRY),
                    "entry": {"tab": tab, "route": consumer, "supported": supported},
                    "platform": "玄渊界面施工台" if consumer == "map-workbench" else "玄渊成果植入平台"}
            self._annotate(card, annotations.get(ident, {}))
            cards.append(card)
        package_ids = set()
        for state in ("verified", "candidate"):
            base = self.root / "packages" / state
            if not base.is_dir(): continue
            for path in sorted(base.glob("*/manifest.json")):
                self._inside(str(path.relative_to(self.root)))
                manifest = _json(path)
                ident = manifest["id"]
                if ident in package_ids: raise ValueError(f"活动成果包ID重复：{ident}")
                package_ids.add(ident)
                inputs = sorted({op["user_document"] for op in manifest.get("operations", []) if op.get("user_document")})
                install_route = manifest.get("install_route", "")
                entry = {"tab": "成果包库", "route": ident, "supported": bool(manifest.get("operations"))}
                if install_route and install_route != "generic":
                    inputs = sorted({d["file"] for d in registry["documents"] if d["consumer"] == install_route})
                    entry = {"tab": "脚本配置同步" if install_route in CONFIG_CONSUMERS else SPECIALIST_TABS.get(install_route, ""),
                             "route": install_route, "supported": bool(inputs) and (install_route in CONFIG_CONSUMERS or install_route in SPECIALIST_TABS)}
                card = {"id": "package:" + ident, "name": manifest.get("display_name", ident), "kind": "成果包",
                        "version": manifest.get("version", ""), "package_status": manifest.get("status", state),
                        "residency": manifest.get("residency", ""), "dependencies": manifest.get("dependencies", []),
                        "inputs": [self._input(f) for f in inputs], "source": str(path),
                        "entry": entry,
                        "platform": "玄渊成果植入平台"}
                self._annotate(card, annotations.get(card["id"], {}))
                cards.append(card)
        return cards

    def _annotate(self, card: dict, note: dict):
        card['auxiliary_inputs'] = []
        if card['entry']['route'] == 'equipment-wash-import':
            extra = self._input('洗练目标参数.json')
            extra['optional'] = True
            card['auxiliary_inputs'].append(extra)
        card["purpose"] = note.get("purpose", card["name"])
        card["input_help"] = note.get("input_help", ["按正式填写文件中的说明页、列名和数据验证填写；先预检，再按变更计划处理。"])
        card["interfaces"] = note.get("interfaces", [])
        card["evidence"] = note.get("evidence", [])
        card["limitations"] = list(note.get("limitations", []))
        marks = note.get("verified_fingerprints", {})
        valid = bool(note.get("game_verified") and marks and card["evidence"])
        required = set(self._execution_sources)
        if (self.root / 'catalog/current-release.json').is_file():
            required.add('catalog/current-release.json')
        required.add(str(Path(card["source"]).relative_to(self.root)).replace("\\", "/"))
        if card["inputs"]: required.add(f"{DOC_DIRECTORY}/{REGISTRY}")
        if card["kind"] == "成果包":
            parent = Path(card["source"]).parent
            required.update(str(p.relative_to(self.root)).replace("\\", "/") for p in parent.rglob("*")
                            if p.is_file() and "evidence" not in p.relative_to(parent).parts)
        dependencies = list(card["dependencies"])
        visited = set()
        while dependencies:
            dependency = dependencies.pop()
            ident = dependency if isinstance(dependency, str) else dependency.get("id", "")
            if ident in visited: continue
            visited.add(ident)
            found = self._package_manifests.get(ident)
            if found is None:
                valid = False
                card["limitations"].append(f"依赖包缺失：{ident}")
                continue
            path, manifest = found
            dependencies.extend(manifest.get("dependencies", []))
            required.update(str(p.relative_to(self.root)).replace("\\", "/") for p in path.parent.rglob("*")
                            if p.is_file() and "evidence" not in p.relative_to(path.parent).parts)
        card["required_fingerprints"] = sorted(required)
        if not required.issubset(marks): valid = False
        checked = {}
        for relative, expected in marks.items():
            path = self._inside(relative)
            actual = digest(path) if path.is_file() else ""
            checked[relative] = actual
            if actual.lower() != str(expected).lower():
                valid = False
                card["limitations"].append(f"验收后文件变化：{relative}")
        for evidence in card["evidence"]:
            path = Path(evidence.get("path", ""))
            expected = evidence.get("sha256", "")
            if not path.is_file() or not expected or digest(path).lower() != expected.lower(): valid = False
        if card["kind"] == "成果包":
            relative = str(Path(card["source"]).relative_to(self.root)).replace("\\", "/")
            if relative not in marks: valid = False
            if card["package_status"] != "verified": valid = False
        if not valid:
            card["limitations"].append("当前版本尚未绑定完整的游戏验收证据；可预检，不能按已验收能力直接派单。")
        card["capability_verified"] = valid
        accepted_inputs = note.get("accepted_input_hashes", {})
        card["configuration_changed"] = any(accepted_inputs.get(f["name"], "").lower() != f["sha256"].lower()
                                            for f in card["inputs"] + card['auxiliary_inputs'])
        if valid and card["configuration_changed"]:
            card["limitations"].append("能力已有验收依据；当前填写内容变化，必须重新运行平台预检。")
        for item in card["inputs"]:
            if not item["exists"]:
                valid = False
                card["limitations"].append(f"填写文件缺失：{item['name']}")
        if not card["entry"]["supported"]:
            valid = False
            card["capability_verified"] = False
            card["limitations"].append("此项需专项处理或仅供历史回退，禁止转为通用安装。")
        card["fingerprints"] = checked
        card["dispatch_ready"] = valid and not card["configuration_changed"]
        card["status"] = "已完成" if card["dispatch_ready"] else "待验证"
        card["success_criteria"] = ["预检无阻止项，写入范围与任务单一致", "写后哈希与事务收据一致，重复预检零变更", "需要游戏实效时完成当前版本验收"]
        card["recovery"] = "按实际安装路由和事务收据回滚；目标已经变化时停止，不覆盖后续修改。"

    def get(self, ident: str) -> dict:
        for card in self.cards():
            if card["id"] == ident: return card
        raise ValueError(f"功能不存在：{ident}")

    def results(self, ident: str, server: Path) -> list[dict]:
        card = self.get(ident)
        route = card["entry"]["route"]
        base = self._inside("backups/" + route) if card["entry"]["tab"] != "成果包库" else self.root / "backups"
        target = str(Path(server).resolve()).casefold()
        results = []
        for path in sorted(base.glob("*/receipt.json"), reverse=True):
            self._inside(str(path.relative_to(self.root)))
            receipt = _json(path)
            declared = receipt.get("server", receipt.get("target_root", receipt.get("target", "")))
            if not declared or str(Path(declared).resolve()).casefold() != target: continue
            if card["entry"]["tab"] == "成果包库" and route not in receipt.get("packages", {}): continue
            if card['entry']['tab'] != '成果包库' and receipt.get('operation') != route: continue
            if card['kind'] == '成果包' and card['entry']['tab'] != '成果包库' and receipt.get('package_id') != card['id'].removeprefix('package:'): continue
            status = 'rolled-back' if receipt.get('rolled_back_at') else receipt.get('status', '以收据为准')
            rollback = path.parent / 'rollback.json'
            rollback_info = {}
            if rollback.is_file():
                self._inside(str(rollback.relative_to(self.root)))
                record = _json(rollback)
                if record.get('operation') == route + '-rollback' and record.get('transaction_id') == receipt.get('transaction_id') and record.get('status') == 'rolled-back':
                    status = 'rolled-back'
                    rollback_info = {'rollback_receipt':str(rollback), 'rollback_sha256':digest(rollback)}
            results.append({"transaction_id": receipt.get("transaction_id", path.parent.name),
                            "status": status, "receipt": str(path), "sha256": digest(path), **rollback_info,
                            "note": "安装收据不代表游戏验收；当前目标状态以重新预检为准。"})
            if len(results) >= 20: break
        return results

    def search(self, query: str = "") -> list[dict]:
        query = query.casefold().strip()
        return [c for c in self.cards() if not query or query in json.dumps(c, ensure_ascii=False).casefold()]

    def task_order(self, ident: str, server: Path, client: Path | None = None, validation: bool = False, task_id: str | None = None) -> dict:
        task_id = task_id or ('XY-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
        if not task_id.strip() or len(task_id) > 160 or any(c in task_id for c in '\r\n\0'):
            raise ValueError('任务编号不能为空或包含换行')
        card = self.get(ident)
        if not validation and not card["capability_verified"]:
            raise ValueError("该功能当前版本未完成验收；只能安排独立验证任务。")
        if any(not f["exists"] for f in card["inputs"]): raise ValueError("填写文件缺失，不能派单。")
        if not card["entry"]["supported"]: raise ValueError("此功能没有可用的平台入口。")
        release = _json(self.root / "catalog/current-release.json", {})
        cli = release.get("cli", {})
        binary = self._inside(cli.get("path", "bin/xydp-cli.exe"))
        frozen_ok = bool(cli.get("sha256") and binary.is_file() and digest(binary).lower() == cli["sha256"].lower())
        if frozen_ok:
            for relative, expected in release.get('source_and_package_fingerprints', {}).items():
                source = self._inside(relative)
                if not source.is_file() or digest(source).lower() != expected.lower():
                    raise ValueError(f'平台源码或成果包与发布版本不一致：{relative}')
        if not validation and not frozen_ok: raise ValueError("正式CLI未绑定发布指纹，禁止正式派单。")
        if not frozen_ok and not (self.root / "run_cli.py").is_file():
            raise ValueError("平台验证入口run_cli.py缺失，不能生成可执行任务单。")
        argv = [str(binary), "--root", str(self.root)] if frozen_ok else [sys.executable, str(self.root/"run_cli.py"), "--root", str(self.root)]
        entry = card["entry"]
        if entry["tab"] == "脚本配置同步":
            argv += ["config-sync-preflight", "--server", str(Path(server).resolve())]
            if client: argv += ["--client", str(Path(client).resolve())]
            for item in card["inputs"]: argv += ["--file", item["path"]]
        elif card["kind"] == "成果包":
            argv += ["preflight", "--server", str(Path(server).resolve()), "--package", entry["route"]]
            if client: argv += ["--client", str(Path(client).resolve())]
        elif entry["route"] == "equipment-graphics":
            if len(card["inputs"]) != 1:
                raise ValueError("装备图形入口必须绑定一个配置文件")
            config_path = Path(card["inputs"][0]["path"])
            configured_root = _equipment_graphics_target_root(config_path)
            requested_root = Path(server).resolve()
            if str(configured_root).casefold() != str(requested_root).casefold():
                raise ValueError(
                    "装备素材配置目标与任务单目标不一致："
                    f"配置为 {configured_root}，任务单为 {requested_root}；"
                    "请修改配置 target.serverRoot 或 target.database 后再派单"
                )
            argv += ["equipment-graphics-preflight", "--config", card["inputs"][0]["path"]]
        else:
            argv = []
        return {"schema_version": 1, 'task_id':task_id, "feature_id": ident, "mode": "validation" if validation else "production",
                "platform_root": str(self.root), "server": str(Path(server).resolve()), "client": str(client) if client else None,
                "release_id": release.get("release_id", "source-validation"), "cli_sha256": digest(binary) if frozen_ok else None,
                "inputs": card["inputs"], 'auxiliary_inputs':card['auxiliary_inputs'], "feature_fingerprints": card["fingerprints"], "preflight_argv": argv,
                "configuration_changed": card["configuration_changed"], "preflight_required": True,
                "manual_entry": entry, "target_write_authorized": False, "handoff_owner": "总控",
                "rules": ["只使用指定平台入口；不得临时改源码或复制旧脚本", "输入、平台或目标变化必须重新预检",
                          "无预检命令时使用指定专项页面，不能猜测通用命令", "执行窗口只提交结果与证据，不写公共交班索引"],
                "acceptance": card["success_criteria"], "limitations": card["limitations"]}

    def format_card(self, card: dict) -> str:
        lines = [card["name"], f"状态：{card['status']}　版本：{card['version']}", card["purpose"],
                 f"所属平台：{card['platform']}　入口：{card['entry']['tab']}", "", "填写文件："]
        lines += [f"- {f['path']}" for f in card["inputs"]] or ["- 按成果包参数填写，无集中表格。"]
        for extra in card['auxiliary_inputs']:
            lines.append(f"- 可选目标参数：{extra['path']}（{'已提供，平台会读取' if extra['exists'] else '未提供，沿用可识别的目标注册或包默认值'}）")
        for title, key in [("填写说明", "input_help"), ("接口", "interfaces"), ("限制与待办", "limitations"), ("成功判据", "success_criteria")]:
            lines += ["", title + "："] + ["- " + str(x) for x in card[key]]
        lines += ["", "恢复方式：" + card["recovery"], "", "证据："]
        lines += [json.dumps(x, ensure_ascii=False) for x in card["evidence"]] or ["尚未绑定当前版本的验收证据。"]
        return "\n".join(lines)
