from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .encoding import TextDocument, encode_text_document, read_text_document
from .initial_camp import (
    InitialCampError,
    _consistent_first,
    _cost_lines,
    _cost_summary,
    _equipment_counts,
    _equipment_indices,
    _integer,
    _map_geometry,
    _script_token,
    _single_tier_route_lines,
    _text,
    _validate_equipment_chain,
    _walkable,
    read_workbook,
)
from .installer import InstallPlan, Installer, PlannedChange
from .npc_editor import _platform_owns_change
from .repository import PackageRepository
from .target import TargetInspector, is_executable_running
from .textpatch import TextPatchError, add_unique_line, scan_labels


class GrowthStageError(ValueError):
    pass


@dataclass(frozen=True)
class GrowthStageSpec:
    document_id: str
    filename: str
    feature: str
    start_item: str
    package_id: str
    script_path: str
    prefix: str
    default_name: str
    default_map: str
    default_x: int
    default_y: int
    default_appearance: int


STAGE_SPECS = {
    "nmgf_sword": GrowthStageSpec(
        "nmgf_sword", "23_宁姆格福_圣律之剑.xlsx", "圣律之剑", "圣律之剑LV10",
        "xy.growth-stage.nmgf-sword", "玄渊成长/圣律之剑进阶", "XY_NMGF_SWORD",
        "圣律之剑进阶", "XY_NMGF_MAIN", 80, 92, 220,
    ),
    "nmgf_relic": GrowthStageSpec(
        "nmgf_relic", "24_宁姆格福_黄金圣物.xlsx", "黄金圣物", "黄金圣物LV10",
        "xy.growth-stage.nmgf-relic", "玄渊成长/黄金圣物进阶", "XY_NMGF_RELIC",
        "黄金圣物进阶", "XY_NMGF_MAIN", 88, 92, 221,
    ),
}
SPEC_BY_FILENAME = {item.filename: item for item in STAGE_SPECS.values()}
PACKAGE_VERSION = "1.0.0-candidate.2"


@dataclass(frozen=True)
class GrowthStageNpc:
    document_id: str
    name: str
    script_path: str
    map_code: str
    x: int
    y: int
    appearance: int
    state: str


@dataclass
class GrowthStagePlan:
    server: str
    documents: list[str] = field(default_factory=list)
    document_hashes: dict[str, str] = field(default_factory=dict)
    npcs: list[GrowthStageNpc] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[PlannedChange] = field(default_factory=list)
    install_plan: InstallPlan | None = None
    operation: str = "growth-stage-npc"


def _new_document(text: str) -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    return encode_text_document(TextDocument("", "gb18030", "\r\n"), normalized)


def _map_filename(mapinfo: str, map_code: str) -> str:
    match = re.search(
        rf"(?im)^\s*\[\s*{re.escape(map_code)}(?:\|([^\s\]]+))?\s+",
        mapinfo,
    )
    if not match:
        raise GrowthStageError(f"MapInfo.txt 中找不到地图：{map_code}")
    return (match.group(1) or map_code) + ".map"


def _pending_script(spec: GrowthStageSpec, npc_name: str) -> str:
    return (
        "[@Main]\n"
        "#IF\n"
        f"CHECKITEM {spec.start_item} 1\n"
        "#ACT\n"
        f"GOTO @{spec.prefix}_PENDING\n"
        "BREAK\n\n"
        "#IF\n"
        "#SAY\n"
        f"【{npc_name}】只承接宁姆格福阶段的成长。\\\n"
        f"请先在初始营地将{spec.feature}提升至LV10，并放入背包。\\\n"
        "<关闭/@exit>\n\n"
        f"[@{spec.prefix}_PENDING]\n"
        "#IF\n"
        "#SAY\n"
        f"【{npc_name}】已识别{spec.start_item}。\\\n"
        "宁姆格福后续成长表尚未配置，当前不会扣除任何物品或货币。\\\n"
        "<关闭/@exit>\n"
    )


def _stage_script(
    spec: GrowthStageSpec,
    npc_name: str,
    rows: tuple[dict[str, object], ...],
    database: bytes,
) -> tuple[str, str]:
    invalid_states = sorted({
        _text(row.get("状态"))
        for row in rows
        if _text(row.get("状态")) not in {"", "可安装", "待配置"}
    })
    if invalid_states:
        raise GrowthStageError(
            f"{spec.filename} 状态只允许填写“可安装”或“待配置”：{'、'.join(invalid_states)}"
        )
    active = tuple(row for row in rows if _text(row.get("状态")) == "可安装")
    if not active:
        counts = _equipment_counts(database, {spec.start_item})
        if counts.get(spec.start_item) != 1:
            raise GrowthStageError(f"阶段起点装备必须在StdItems中唯一存在：{spec.start_item}")
        return _pending_script(spec, npc_name), "待配置"

    configured = _validate_equipment_chain(spec.feature, active, database)
    if not configured or configured[0][1] != spec.start_item:
        actual = configured[0][1] if configured else "空"
        raise GrowthStageError(
            f"{spec.filename} 第一条可安装记录必须从{spec.start_item}开始，当前为：{actual}"
        )
    states = [configured[0][1], *(next_item for _, _, next_item in configured)]
    indices = _equipment_indices(database, set(states), spec.feature)
    lines = _single_tier_route_lines(spec.prefix, tuple(states), "backpack_equipment")
    for index, (row, current, next_item) in enumerate(configured, 1):
        checks, actions = _cost_lines(row)
        lines += [
            f"[@{spec.prefix}_VIEW_{index}]", "#IF", "#SAY", "< /FCOLOR=250>\\",
            f"<> <{npc_name}：/FCOLOR=158> <宁姆格福阶段只显示当前下一档/FCOLOR=218>\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<> <当前装备:/FCOLOR=161>{{{current}/SCOLOR=249}}\\",
            f"<> <下一装备:/FCOLOR=161>{{{next_item}/SCOLOR=253}}\\",
            f"<> <升级消耗:/FCOLOR=161>{{{_cost_summary(row)}/SCOLOR=251}}\\",
            "<> <将鼠标移到图标查看下一装备的完整属性。/FCOLOR=147>\\",
            "<> <---------------------------------------------------------------/FCOLOR=10>\\",
            f"<ItemShow:{indices[next_item]}:0:260:-90:1>　【<确认升级/@{spec.prefix}_{index}>】　<关闭/@exit>\\",
            "", f"[@{spec.prefix}_{index}]", "#IF", "CHECKBAGSIZE 1", f"CHECKITEM {current} 1",
        ]
        for higher in states[index:]:
            lines.append(f"NOT CHECKITEM {higher} 1")
        lines += [*checks, "#ACT", f"TAKE {current} 1", *actions, f"GIVE {next_item} 1"]
        lines += [
            f"SENDMSG 6 [{npc_name}] 已将{current}升级为{next_item}。",
            "GOTO @Main", "BREAK", "#ELSEACT",
            "MESSAGEBOX 当前装备不是背包内最高档，或材料、货币、背包空间不满足。",
            "BREAK", "",
        ]

    lines += [
        f"[@{spec.prefix}_NONE]", "#IF", "#SAY", "< /FCOLOR=250>\\",
        f"<> <{npc_name}：/FCOLOR=158> <未找到本大陆可升级装备/FCOLOR=218>\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\",
        f"<> <请先在初始营地将{spec.feature}提升至LV10，并把装备放入背包。/FCOLOR=251>\\",
        "<> <穿戴中的装备不参与识别。/FCOLOR=147>\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\", "<> <关闭/@exit>\\", "",
        f"[@{spec.prefix}_FULL]", "#IF", "#SAY", "< /FCOLOR=250>\\",
        f"<> <{npc_name}：/FCOLOR=158> <本大陆阶段已经完成/FCOLOR=218>\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\",
        f"<> <当前装备:/FCOLOR=161>{{{states[-1]}/SCOLOR=249}}\\",
        "<> <状态:/FCOLOR=161>{宁姆格福阶段已完成/SCOLOR=253}\\",
        "<> <后续大陆请前往对应成长NPC。/FCOLOR=147>\\",
        "<> <---------------------------------------------------------------/FCOLOR=10>\\", "<> <关闭/@exit>\\", "",
    ]
    script = "\n".join(lines).rstrip("\n") + "\n"
    duplicates = scan_labels(script).duplicates
    if duplicates:
        raise GrowthStageError(f"{spec.filename} 生成了重复标签：{duplicates}")
    return script, "可安装"


class GrowthStageService:
    def __init__(self, platform_root: Path):
        self.root = Path(platform_root).resolve()
        repository = PackageRepository(self.root / "packages")
        repository.refresh()
        self.installer = Installer(repository, self.root / "backups")

    def preflight(self, server: Path, documents: list[Path]) -> GrowthStagePlan:
        plan = GrowthStagePlan(str(Path(server).absolute()))
        try:
            if not documents:
                raise GrowthStageError("至少选择一份大陆成长装备表")
            target = TargetInspector.inspect(Path(server))
            if is_executable_running(target.mir200 / "M2Server.exe"):
                plan.warnings.append("M2正在运行；本次允许预检和写入，新脚本需由用户稍后重载或重启M2后生效。")
            database_path = target.root / "Mud2" / "DB" / "ApexM2.DB"
            if not database_path.is_file():
                raise GrowthStageError("目标服缺少 Mud2/DB/ApexM2.DB")
            database = database_path.read_bytes()
            map_doc = read_text_document(target.envir / "MapInfo.txt")
            merchant_path = target.envir / "MerChant.txt"
            merchant_doc = read_text_document(merchant_path) if merchant_path.is_file() else TextDocument("", "gb18030", "\r\n")
            merchant_text = merchant_doc.text
            used_documents: set[str] = set()
            used_positions: set[tuple[str, int, int]] = set()
            package_ids: list[str] = []

            for source in documents:
                path = Path(source).resolve()
                spec = SPEC_BY_FILENAME.get(path.name)
                if spec is None:
                    raise GrowthStageError(f"不是已登记的大陆成长装备表：{path.name}")
                if path.name in used_documents:
                    continue
                used_documents.add(path.name)
                sheet = read_workbook(path)
                plan.documents.append(str(path))
                plan.document_hashes[path.name] = sheet.sha256
                ids = {_text(row.get("功能ID")) for row in sheet.rows if _text(row.get("功能ID"))}
                if ids and ids != {spec.document_id}:
                    raise GrowthStageError(f"{path.name} 功能ID必须全部为 {spec.document_id}")
                npc_name = _text(_consistent_first(sheet.rows, "NPC名称", path.name, spec.default_name)) or spec.default_name
                map_code = _text(_consistent_first(sheet.rows, "地图", path.name, spec.default_map)) or spec.default_map
                if map_code.casefold() != spec.default_map.casefold():
                    raise GrowthStageError(f"{path.name} 当前阶段地图必须填写 {spec.default_map}")
                x = _integer(_consistent_first(sheet.rows, "X坐标", path.name, spec.default_x), spec.default_x)
                y = _integer(_consistent_first(sheet.rows, "Y坐标", path.name, spec.default_y), spec.default_y)
                appearance = _integer(
                    _consistent_first(sheet.rows, "外观", path.name, spec.default_appearance),
                    spec.default_appearance,
                )
                if x is None or y is None or appearance is None or appearance < 0:
                    raise GrowthStageError(f"{path.name} 的坐标或外观无效")
                position = (map_code.casefold(), x, y)
                if position in used_positions:
                    raise GrowthStageError(f"两份成长表使用了相同NPC坐标：{map_code} {x},{y}")
                used_positions.add(position)

                map_file = target.root / "Mir200" / "Map" / _map_filename(map_doc.text, map_code)
                if not map_file.is_file():
                    raise GrowthStageError(f"目标服缺少地图文件：{map_file.name}")
                map_data = map_file.read_bytes()
                width, height, cell_size = _map_geometry(map_data)
                if not _walkable(map_data, width, height, cell_size, x, y):
                    raise GrowthStageError(f"{path.name} 的NPC坐标不可走：{map_code} {x},{y}")

                for line in merchant_text.splitlines():
                    fields = line.split("\t")
                    if len(fields) < 7 or fields[1].casefold() != map_code.casefold():
                        continue
                    same_key = fields[0] == spec.script_path
                    try:
                        same_position = int(fields[2]) == x and int(fields[3]) == y
                    except ValueError:
                        same_position = False
                    if same_position and not same_key:
                        raise GrowthStageError(f"{path.name} 的NPC坐标已被占用：{line}")
                    if fields[4] == npc_name and not same_key:
                        raise GrowthStageError(f"{path.name} 的NPC名称在本地图已占用：{npc_name}")

                script, state = _stage_script(spec, npc_name, sheet.rows, database)
                script_relative = f"Mir200/Envir/Market_Def/{spec.script_path}-{map_code}.txt"
                script_path = target.root / Path(script_relative.replace("/", "\\"))
                before = script_path.read_bytes() if script_path.is_file() else None
                if before is not None:
                    current = read_text_document(script_path)
                    after = encode_text_document(current, script.replace("\n", current.newline))
                    if before != after and not _platform_owns_change(target.root, spec.package_id, script_relative, before):
                        raise GrowthStageError(f"NPC脚本已存在且不属于本平台当前收据，禁止覆盖：{script_relative}")
                else:
                    after = _new_document(script)
                if before != after:
                    plan.changes.append(PlannedChange(
                        script_relative, before, after, "growth-stage-script", spec.package_id
                    ))

                merchant_line = (
                    f"{spec.script_path}\t{map_code}\t{x}\t{y}\t{npc_name}\t0\t{appearance}\t0"
                )
                merchant_text = add_unique_line(
                    merchant_text, merchant_line, [0, 1], merchant_doc.newline
                ).text
                package_ids.append(spec.package_id)
                plan.npcs.append(GrowthStageNpc(
                    spec.document_id, npc_name, spec.script_path, map_code, x, y, appearance, state
                ))

            merchant_after = encode_text_document(merchant_doc, merchant_text)
            merchant_before = merchant_path.read_bytes() if merchant_path.is_file() else None
            if merchant_before != merchant_after:
                plan.changes.append(PlannedChange(
                    "Mir200/Envir/MerChant.txt", merchant_before, merchant_after,
                    "growth-stage-register", package_ids[0],
                ))
            plan.install_plan = InstallPlan(
                target_root=str(target.root), client_root=None, package_ids=package_ids,
                package_versions={item: PACKAGE_VERSION for item in package_ids},
                parameters={
                    "documents": plan.documents,
                    "document_hashes": plan.document_hashes,
                    "npcs": [item.__dict__ for item in plan.npcs],
                },
                changes=plan.changes, warnings=plan.warnings,
                operation_type=plan.operation, candidate_packages=package_ids,
            )
            if not plan.changes:
                plan.warnings.append("目标服已经与所选大陆成长表一致，本次无需写入。")
        except (OSError, UnicodeError, ValueError, InitialCampError, TextPatchError) as exc:
            plan.blockers.append(str(exc))
        return plan

    def install(self, plan: GrowthStagePlan):
        if plan.blockers or plan.install_plan is None:
            raise GrowthStageError("大陆成长NPC安装被阻止：\n" + "\n".join(plan.blockers))
        for source in plan.documents:
            path = Path(source)
            if not path.is_file():
                raise GrowthStageError(f"预检后表格已不存在：{path.name}")
            current_hash = read_workbook(path).sha256
            if current_hash != plan.document_hashes.get(path.name):
                raise GrowthStageError(f"预检后表格已变化，请重新预检：{path.name}")
        return self.installer.install(plan.install_plan)
