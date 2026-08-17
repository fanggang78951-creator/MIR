#!/usr/bin/env python3
"""只读盘点法环脚本与功能，并在 Git 工作区生成可审计快照。"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(r"C:\Users\Administrator\Documents\做传奇")
ROOT = REPO / "传奇私服之旅" / "艾尔登法环项目档案" / "脚本与功能"
SERVER = Path(r"D:\MirServer")
ENVIR = SERVER / "Mir200" / "Envir"
PLATFORM = Path(r"E:\XuanYuanDevPlatform")
REPORTS = ROOT / "报告"
SNAPSHOT = ROOT / "快照"
INTERFACES = ROOT / "接口"
CONFIGS = ROOT / "配置母表"
PACKAGES = ROOT / "平台成果包"
INSTALLED_SCOPE: set[str] = set()
LAW_RING_EXTRA_PACKAGES = {
    # 已在当前法环施工中形成明确游戏验收/沉淀，但旧式直接部署未写入当前收据。
    "xy.combat-suite",
    "xy.optional.equipment-wash-opening",
    "xy.optional.necklace-luck",
    "xy.optional.recycle.core",
    "xy.optional.skill-upgrade.warrior.gongsha-kaitian",
}

TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".ini", ".cfg", ".py", ".ps1", ".yml", ".yaml", ".toml"}
PACKAGE_EXTS = TEXT_EXTS | {".xlsx"}
LABEL_RE = re.compile(r"^\s*\[@([^\]]+)\]", re.M)
CALL_RE = re.compile(r"#CALL\s+\[([^\]]+)\]\s+@([A-Za-z0-9_$.-]+)", re.I)
GOTO_RE = re.compile(r"\bGOTO\s+@([A-Za-z0-9_$.-]+)", re.I)
MANAGED_BEGIN_RE = re.compile(r"^\s*;\s*XYDP-([A-Z-]+)-BEGIN\s+(\S+)(?:\s+(\S+))?", re.I)
MANAGED_END_RE = re.compile(r"^\s*;\s*XYDP-([A-Z-]+)-END\s+(\S+)(?:\s+(\S+))?", re.I)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def decode_bytes(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return data.decode("gb18030", errors="replace"), "gb18030-replace"


def read_text(path: Path) -> tuple[str, str]:
    return decode_bytes(path.read_bytes())


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else ["结果"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_generated() -> None:
    for p in (REPORTS, SNAPSHOT, INTERFACES, CONFIGS, PACKAGES):
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True, exist_ok=True)


def package_in_scope(package_id: str) -> bool:
    excluded_prefixes = (
        "xy.maps.", "xy.ui.world-map", "xy.npc.world-map", "xy.growth-stage.",
    )
    if package_id.startswith(excluded_prefixes):
        return False
    return package_id in INSTALLED_SCOPE or package_id in LAW_RING_EXTRA_PACKAGES


def evidence_summary(evidence) -> tuple[str, str]:
    items = [str(x) for x in (evidence or [])]
    joined = " | ".join(items)
    game = [
        x for x in items
        if re.search(r"game|验收|accepted|acceptance", x, re.I)
        and not re.search(r"pending|required|待验证|未验证", x, re.I)
    ]
    return joined, " | ".join(game)


def collect_packages(installed: dict[str, str]) -> tuple[list[dict], dict[str, Path]]:
    latest: dict[str, tuple[dict, Path]] = {}
    for library_status in ("verified", "candidate"):
        base = PLATFORM / "packages" / library_status
        if not base.exists():
            continue
        for manifest_path in base.glob("*/manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            pid = str(manifest.get("id", manifest_path.parent.name))
            if not package_in_scope(pid):
                continue
            # 同一包以 verified 优先，其次以路径所代表的当前母库版本为准。
            old = latest.get(pid)
            if old is None or library_status == "verified":
                latest[pid] = (manifest, manifest_path.parent)

    rows: list[dict] = []
    paths: dict[str, Path] = {}
    for pid, (m, folder) in sorted(latest.items()):
        paths[pid] = folder
        evidence, game_evidence = evidence_summary(m.get("evidence"))
        installed_version = installed.get(pid, "")
        platform_status = str(m.get("status", "candidate"))
        if platform_status == "deprecated" or ".test-reset" in pid or "test-reset" in pid:
            effective = "已废止"
        elif installed_version:
            if platform_status == "verified" and game_evidence and installed_version == str(m.get("version", "")):
                effective = "游戏内实测通过"
            else:
                effective = "已部署待实测"
        elif platform_status == "verified" and game_evidence:
            effective = "设计定稿"
        else:
            effective = "已写入文件"
        rows.append({
            "功能ID": pid,
            "名称": m.get("display_name", pid),
            "平台版本": m.get("version", ""),
            "正式服版本": installed_version,
            "版本漂移": "是" if installed_version and installed_version != str(m.get("version", "")) else "否",
            "平台状态": platform_status,
            "常驻性": m.get("residency", "optional"),
            "套件": m.get("bundle", ""),
            "依赖": " | ".join(map(str, m.get("dependencies", []))),
            "标签": " | ".join(map(str, m.get("claims", {}).get("labels", []))),
            "变量": " | ".join(map(str, m.get("claims", {}).get("variables", []))),
            "当前状态": effective,
            "游戏证据": game_evidence,
            "全部证据": evidence,
            "母库路径": str(folder),
        })

    # 收据中存在而母库当前目录不存在的包，也必须保留为正式服事实。
    known = {r["功能ID"] for r in rows}
    for pid, version in sorted(installed.items()):
        if pid in known or not package_in_scope(pid) or pid.startswith("npc-direct:"):
            continue
        effective = "已废止" if "test-reset" in pid else "已部署待实测"
        rows.append({
            "功能ID": pid, "名称": pid, "平台版本": "", "正式服版本": version,
            "版本漂移": "母库缺失", "平台状态": "收据记录", "常驻性": "未知", "套件": "",
            "依赖": "", "标签": "", "变量": "", "当前状态": effective,
            "游戏证据": "", "全部证据": "", "母库路径": "",
        })
    return sorted(rows, key=lambda x: x["功能ID"]), paths


def selected_server_files() -> list[Path]:
    files: list[Path] = []
    core = [
        ENVIR / "Market_Def" / "QFunction-0.txt",
        ENVIR / "MapQuest_Def" / "QManage.txt",
        ENVIR / "Robot_def" / "RobotManage.txt",
        ENVIR / "Robot_def" / "AutoRunRobot.txt",
        ENVIR / "UserCmd.txt",
        ENVIR / "EffectImageList.txt",
    ]
    files.extend(p for p in core if p.exists())
    roots = [
        ENVIR / "QuestDiary" / "玄渊成长",
        ENVIR / "QuestDiary" / "玄渊功能",
        ENVIR / "QuestDiary" / "玄渊配置",
        ENVIR / "QuestDiary" / "玄渊实验室",
        ENVIR / "QuestDiary" / "玄渊数据",
        ENVIR / "QuestDiary" / "玄渊验收",
        ENVIR / "QuestDiary" / "玄渊诊断",
        ENVIR / "Market_Def" / "玄渊成长",
        ENVIR / "Market_Def" / "玄渊功能",
        ENVIR / "Market_Def" / "玄渊任务",
        ENVIR / "Market_Def" / "玄渊实验室",
        ENVIR / "Market_Def" / "玄渊新手",
        ENVIR / "Market_Def" / "玄渊运营",
        ENVIR / "Market_Def" / "玄渊NPC",
    ]
    for base in roots:
        if base.exists():
            files.extend(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_EXTS)
    return sorted(set(files), key=lambda p: str(p).lower())


def rel_server(path: Path) -> Path:
    return path.relative_to(SERVER)


def resolve_call(source: Path, raw: str) -> Path | None:
    clean = raw.replace("/", "\\").lstrip("\\")
    candidates = [
        ENVIR / "QuestDiary" / clean,
        ENVIR / "Market_Def" / clean,
        source.parent / clean,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def snapshot_and_audit_server(files: list[Path]) -> tuple[list[dict], list[dict], list[dict]]:
    inventory: list[dict] = []
    issues: list[dict] = []
    managed: list[dict] = []
    raw_root = SNAPSHOT / "正式服原始脚本"
    utf_root = SNAPSHOT / "正式服脚本UTF8"
    for src in files:
        rel = rel_server(src)
        raw_dst = raw_root / rel
        utf_dst = utf_root / rel
        raw_dst.parent.mkdir(parents=True, exist_ok=True)
        utf_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, raw_dst)
        text, encoding = read_text(src)
        utf_dst.write_text(text.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="\n")
        labels = LABEL_RE.findall(text)
        duplicate_labels = sorted(k for k, n in Counter(x.lower() for x in labels).items() if n > 1)
        inventory.append({
            "源文件": str(src), "服务端相对路径": str(rel), "大小": src.stat().st_size,
            "修改时间": datetime.fromtimestamp(src.stat().st_mtime).isoformat(timespec="seconds"),
            "SHA256": sha256(src), "识别编码": encoding, "标签数": len(labels),
            "重复标签": " | ".join(duplicate_labels), "CALL数": len(CALL_RE.findall(text)),
        })
        for label in duplicate_labels:
            issues.append({"类型": "重复标签", "文件": str(src), "位置或目标": label, "说明": "同一文件内重复"})
        label_set = {x.lower() for x in labels}
        for raw_path, target_label in CALL_RE.findall(text):
            target = resolve_call(src, raw_path)
            if target is None:
                issues.append({"类型": "CALL目标文件缺失", "文件": str(src), "位置或目标": f"{raw_path}@{target_label}", "说明": "静态路径解析失败"})
                continue
            target_text, _ = read_text(target)
            target_labels = {x.lower() for x in LABEL_RE.findall(target_text)}
            if target_label.lower() not in target_labels:
                issues.append({"类型": "CALL目标标签缺失", "文件": str(src), "位置或目标": f"{target}@{target_label}", "说明": "目标文件存在但标签不存在"})
        # 只检查带 XY/XYDP 前缀的同文件 GOTO，避免把引擎保留分支误报。
        for target_label in GOTO_RE.findall(text):
            if target_label.upper().startswith("XY_WORLD_MAP_"):
                continue  # 用户已明确排除地图系统，不把外部地图跳转列为本轮功能缺陷。
            if target_label.upper().startswith(("XY_", "XYDP_")) and target_label.lower() not in label_set:
                issues.append({"类型": "GOTO标签缺失", "文件": str(src), "位置或目标": target_label, "说明": "同文件未找到目标标签"})

        stack: list[tuple[str, str, str, int]] = []
        for lineno, line in enumerate(text.splitlines(), 1):
            bm = MANAGED_BEGIN_RE.match(line)
            em = MANAGED_END_RE.match(line)
            if bm:
                event = bm.group(3) or ""
                if event.upper().startswith("SHA256="):
                    event = ""
                stack.append((bm.group(1), bm.group(2), event, lineno))
                if package_in_scope(bm.group(2)):
                    managed.append({"文件": str(rel), "类型": bm.group(1), "功能ID": bm.group(2), "事件或标签": event, "起始行": lineno})
            elif em:
                event = em.group(3) or ""
                if event.upper().startswith("SHA256="):
                    event = ""
                key = (em.group(1).lower(), em.group(2).lower(), event.lower())
                pos = next((i for i in range(len(stack) - 1, -1, -1)
                            if (stack[i][0].lower(), stack[i][1].lower(), stack[i][2].lower()) == key), None)
                if pos is None:
                    issues.append({"类型": "受管块孤立END", "文件": str(src), "位置或目标": line.strip(), "说明": f"第{lineno}行"})
                else:
                    stack.pop(pos)
        for kind, pid, event, lineno in stack:
            issues.append({"类型": "受管块缺少END", "文件": str(src), "位置或目标": f"{kind} {pid} {event}", "说明": f"第{lineno}行"})
    return inventory, issues, managed


def copy_selected_files(source: Path, dest: Path, names: list[str], recursive: bool = False) -> list[dict]:
    rows = []
    for name in names:
        src = source / name
        if not src.exists():
            rows.append({"名称": name, "源路径": str(src), "状态": "缺失", "大小": "", "SHA256": ""})
            continue
        dst = dest / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir() and recursive:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            for p in sorted(dst.rglob("*")):
                if p.is_file():
                    rows.append({"名称": str(p.relative_to(dest)), "源路径": str(src / p.relative_to(dst)), "状态": "已复制", "大小": p.stat().st_size, "SHA256": sha256(p)})
        elif src.is_file():
            shutil.copy2(src, dst)
            rows.append({"名称": name, "源路径": str(src), "状态": "已复制", "大小": src.stat().st_size, "SHA256": sha256(src)})
    return rows


def copy_interfaces() -> list[dict]:
    names = [
        "00_先看这里_接口总索引.txt", "01_玩家命令与NPC脚本接口.txt", "02_UI按钮和图标接口.txt",
        "04_战斗重算与做装备锚点.txt", "05_事件接入和内部占用接口.txt", "06_GPT接入标准与禁止参考.txt",
        "08_初始之地七NPC材料表与装备兑换接口.txt", "09_赞助称号显示与实效验收接口.txt",
        "10_主动选择配置文件同步接口.txt", "11_项链幸运强化接口.txt", "12_测试后台监视与XY_VERIFY事件接口.txt",
        "13_地图怪物处决与怪物韧性接口.txt", "16_处决重甲跪地视觉候选接口.txt", "21_转生神力重算候选接口.txt",
        "22_第一大陆漂流群岛魂魄任务接口.txt", "23_NPC自定义对话框背景接口.txt", "24_装备回收表格配置接口.txt",
        "25_范围自动拾取接口.txt", "25_装备洗练与开光接口.txt", "26_可拖动装备操作台接口.txt",
        "26_自动挂机与四点巡航候选接口.txt", "28_神印基础与称号晋升接口.txt", "29_小偷葛托克随机活动接口.txt",
        "33_装备收集图鉴接口.txt", "34_通用物品合成接口.txt", "37_祖玛教主动态副本接口.txt", "接口清单.json",
    ]
    return copy_selected_files(PLATFORM / "接口", INTERFACES, names)


def copy_configs() -> list[dict]:
    names = [
        "00_填写文档注册表.json", "README_填写与导入说明.txt", "01_狂暴.xlsx", "02_捐献.xlsx", "03_赞助称号.xlsx",
        "04_转生.xlsx", "07_新手礼包.xlsx", "12_战士技能强化.xlsx", "13_地图怪物处决规则.csv", "14_国王模式配置.txt",
        "15_首爆奖励配置.txt", "16_复活图标装备名单.txt", "17_项链幸运强化.xlsx", "19_装备回收配置.xlsx",
        "21_神印基础属性.xlsx", "22_称号晋升.xlsx", "33_装备收集图鉴.xlsx", "34_通用物品合成.xlsx", "35_合成NPC与配方分配.txt",
    ]
    return copy_selected_files(PLATFORM / "所需材料表格汇总", CONFIGS, names)


def copy_package_sources(paths: dict[str, Path]) -> list[dict]:
    rows = []
    for pid, src_root in sorted(paths.items()):
        dst_root = PACKAGES / pid
        for src in sorted(src_root.rglob("*")):
            if not src.is_file() or src.suffix.lower() not in PACKAGE_EXTS:
                continue
            rel = src.relative_to(src_root)
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            rows.append({"功能ID": pid, "相对路径": str(rel), "源路径": str(src), "大小": src.stat().st_size, "SHA256": sha256(src)})
    return rows


def extract_handoff_evidence() -> list[dict]:
    index = Path(r"D:\codex交班记录\00_任务总结索引.txt")
    if not index.exists():
        return []
    text, _ = read_text(index)
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    topics = {
        "战斗属性": ["战斗属性", "神力", "伤害系数", "对怪伤害吸收"],
        "处决与韧性": ["处决", "韧性"],
        "狂暴": ["狂暴"], "捐献": ["捐献"], "称号与转生": ["称号", "转生"],
        "神印": ["神印", "锻体"], "技能强化": ["技能强化"], "项链幸运": ["项链幸运"],
        "回收": ["装备回收", "自动回收"], "洗练开光": ["洗练", "开光"],
        "装备收集功能": ["装备收集"], "通用合成功能": ["通用物品合成", "通用合成"],
        "自动拾取与挂机": ["自动拾取", "自动挂机", "巡航"], "首爆": ["首爆"],
        "副本": ["动态副本"], "活动": ["小偷葛托克"], "初始背包": ["背包200", "初始背包"],
    }
    rows = []
    for topic, keywords in topics.items():
        hit = next((line for line in lines if any(k in line for k in keywords)), "")
        if hit:
            parts = [x.strip() for x in hit.split("|", 4)]
            rows.append({
                "主题": topic, "记录时间": parts[0] if len(parts) > 0 else "",
                "记录文件": parts[1] if len(parts) > 1 else "",
                "任务名称": parts[2] if len(parts) > 2 else "",
                "记录状态": parts[3] if len(parts) > 3 else "",
                "摘要": parts[4] if len(parts) > 4 else hit,
            })
    return rows


def main() -> None:
    global INSTALLED_SCOPE
    clear_generated()
    receipt_path = SERVER / ".xydp" / "installed.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig")) if receipt_path.exists() else {"packages": {}}
    installed = {str(k): str(v) for k, v in receipt.get("packages", {}).items()}
    INSTALLED_SCOPE = set(installed)

    package_rows, package_paths = collect_packages(installed)
    server_rows, issues, managed = snapshot_and_audit_server(selected_server_files())
    interface_rows = copy_interfaces()
    config_rows = copy_configs()
    package_file_rows = copy_package_sources(package_paths)
    handoff_rows = extract_handoff_evidence()

    drift = [r for r in package_rows if r["版本漂移"] not in ("否", "") or r["当前状态"] in ("已废止", "已部署待实测")]
    write_csv(REPORTS / "功能总台账.csv", package_rows)
    write_csv(REPORTS / "正式服托管块台账.csv", managed, ["文件", "类型", "功能ID", "事件或标签", "起始行"])
    write_csv(REPORTS / "脚本文件清单.csv", server_rows)
    write_csv(REPORTS / "脚本引用问题清单.csv", issues, ["类型", "文件", "位置或目标", "说明"])
    write_csv(REPORTS / "接口台账.csv", interface_rows)
    write_csv(REPORTS / "配置母表清单.csv", config_rows)
    write_csv(REPORTS / "平台包文件清单.csv", package_file_rows)
    write_csv(REPORTS / "版本漂移与状态问题.csv", drift)
    write_csv(REPORTS / "交班证据摘录.csv", handoff_rows, ["主题", "记录时间", "记录文件", "任务名称", "记录状态", "摘要"])
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "仅脚本类与功能类；不含地图、客户端地图资源、装备来源编号和装备内容",
        "sources": {"server": str(SERVER), "platform": str(PLATFORM), "receipt": str(receipt_path)},
        "counts": {
            "functions": len(package_rows), "installed_in_scope": sum(bool(r["正式服版本"]) for r in package_rows),
            "version_drift": sum(r["版本漂移"] == "是" for r in package_rows),
            "server_script_files": len(server_rows), "managed_blocks": len(managed),
            "static_issues": len(issues), "interfaces": sum(r["状态"] == "已复制" for r in interface_rows),
            "configs": sum(r["状态"] == "已复制" for r in config_rows), "package_files": len(package_file_rows),
            "handoff_evidence_topics": len(handoff_rows),
        },
        "issue_types": dict(Counter(r["类型"] for r in issues)),
        "excluded": ["地图台账", "地图号与坐标", "客户端MAP资源", "装备来源编号", "装备内容与数据库"],
    }
    write_json(REPORTS / "审计摘要.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
