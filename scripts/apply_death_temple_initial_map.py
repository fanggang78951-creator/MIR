from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path


PLATFORM = Path(r"D:\XuanYuanDevPlatform")
SERVER = Path(r"D:\MirServer")
CLIENT = Path(r"D:\11周年")
sys.path.insert(0, str(PLATFORM / "src"))

from xydp.encoding import encode_text_document, read_text_document  # noqa: E402
from xydp.installer import InstallPlan, Installer, PlannedChange  # noqa: E402
from xydp.repository import PackageRepository  # noqa: E402


FILES = {
    "mapinfo": Path("Mir200/Envir/MapInfo.txt"),
    "mongen": Path("Mir200/Envir/MonGen.txt"),
    "merchant": Path("Mir200/Envir/MerChant.txt"),
    "config": Path("Mir200/Envir/QuestDiary/玄渊配置/国王模式配置.txt"),
    "flow": Path("Mir200/Envir/QuestDiary/玄渊功能/国王模式赛前/国王模式赛前流程.txt"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}：预期唯一命中1处，实际{count}处")
    return text.replace(old, new, 1)


def main() -> None:
    docs = {name: read_text_document(SERVER / rel) for name, rel in FILES.items()}
    before = {name: (SERVER / rel).read_bytes() for name, rel in FILES.items()}

    mapinfo = replace_once(
        docs["mapinfo"].text,
        "[T218 死亡神殿] NORECALL NORANDOMMOVE NODEARRECALL NOGUILDRECALL NOMasterRECALL NORECONNECT(0) DAY ONKILLMON",
        "[T218 死亡神殿] SAFE NORECALL NORANDOMMOVE NODEARRECALL NOGUILDRECALL NOMasterRECALL NORECONNECT(0) DAY",
        "死亡神殿MapInfo",
    )

    mongen, removed = re.subn(r"(?m)^T218[^\r\n]*(?:\r?\n|$)", "", docs["mongen"].text)
    if removed < 1:
        raise RuntimeError("MonGen中没有找到T218刷怪行，目标状态与预检不一致")

    merchant = replace_once(
        docs["merchant"].text,
        "玄渊国王模式_赛前报名\tchushidi\t29\t26\t国王模式报名官\t0\t24\t0",
        "玄渊国王模式_赛前报名\tT218\t12\t16\t国王模式报名官\t0\t24\t0",
        "国王模式报名官注册",
    )
    merchant = replace_once(
        merchant,
        "玄渊国王模式_返回大厅\tchushidi\t32\t26\t裁判老秦\t0\t24\t0",
        "玄渊国王模式_返回大厅\tT218\t16\t16\t裁判老秦\t0\t24\t0",
        "裁判老秦注册",
    )

    config = replace_once(docs["config"].text, "登录地图=chushidi", "登录地图=T218", "配置登录地图")
    physical_candidates = ("登录物理地图=真彩459.map", "登录物理地图=xycbd.map")
    physical_hits = [value for value in physical_candidates if value in config]
    if len(physical_hits) != 1:
        raise RuntimeError(f"配置登录物理地图：预期唯一旧值，实际命中{physical_hits}")
    config = replace_once(config, physical_hits[0], "登录物理地图=T218.map", "配置登录物理地图")
    config = replace_once(config, "登录落点=29,30", "登录落点=14,16", "配置登录落点")

    flow = replace_once(
        docs["flow"].text,
        "MAPMOVE chushidi 29 30",
        "MAPMOVE T218 14 16",
        "真实登录传送",
    )

    after_text = {
        "mapinfo": mapinfo,
        "mongen": mongen,
        "merchant": merchant,
        "config": config,
        "flow": flow,
    }

    stamp = time.strftime("%Y%m%d_%H%M%S")
    manual_backup = SERVER / "Backup" / f"XuanYuan_InitialMap_DeathTemple_{stamp}"
    for name, rel in FILES.items():
        source = SERVER / rel
        destination = manual_backup / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    changes: list[PlannedChange] = []
    for name, rel in FILES.items():
        after = encode_text_document(docs[name], after_text[name])
        if after == before[name]:
            continue
        changes.append(
            PlannedChange(
                relative_path=rel.as_posix(),
                before=before[name],
                after=after,
                operation="direct_initial_map_death_temple",
                package_id="xy.direct.initial-map.death-temple",
            )
        )

    plan = InstallPlan(
        target_root=str(SERVER),
        client_root=str(CLIENT),
        package_ids=["xy.direct.initial-map.death-temple"],
        package_versions={"xy.direct.initial-map.death-temple": "1.0.0"},
        parameters={
            "login_map": "T218",
            "login_point": "14,16",
            "signup_npc": "12,16",
            "return_npc": "16,16",
            "safe": True,
            "remove_monsters": True,
        },
        changes=changes,
        warnings=["M2重载后生效；关闭M2Server并由GameCenter自动拉起。"],
        operation_type="direct-initial-map-death-temple",
    )
    receipt = Installer(PackageRepository(PLATFORM / "packages"), PLATFORM / "backups").install(plan)

    server_map = SERVER / "Mir200" / "Map" / "T218.map"
    client_map = CLIENT / "Map" / "T218.map"
    if server_map.read_bytes() != client_map.read_bytes():
        raise RuntimeError("服务端与客户端T218.map哈希不一致")

    result = {
        "transaction_id": receipt.transaction_id,
        "platform_backup": receipt.backup_root,
        "manual_backup": str(manual_backup),
        "changed_files": [item.relative_path for item in changes],
        "removed_mongen_lines": removed,
        "map_sha256": sha256(server_map.read_bytes()),
        "before_after": {
            name: {"before": sha256(before[name]), "after": sha256((SERVER / FILES[name]).read_bytes())}
            for name in FILES
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
