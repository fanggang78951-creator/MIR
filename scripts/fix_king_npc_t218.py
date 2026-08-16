from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path


PLATFORM = Path(r"D:\XuanYuanDevPlatform")
SERVER = Path(r"D:\MirServer")
ENVIR = SERVER / "Mir200" / "Envir"
MARKET = ENVIR / "Market_Def"
sys.path.insert(0, str(PLATFORM / "src"))

from xydp.installer import InstallPlan, Installer, PlannedChange  # noqa: E402
from xydp.repository import PackageRepository  # noqa: E402


PAIRS = (
    ("玄渊国王模式_赛前报名-chushidi.txt", "玄渊国王模式_赛前报名-T218.txt"),
    ("玄渊国王模式_返回大厅-chushidi.txt", "玄渊国王模式_返回大厅-T218.txt"),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    merchant_raw = (ENVIR / "MerChant.txt").read_bytes()
    merchant = merchant_raw.decode("gb18030")
    required = (
        "玄渊国王模式_赛前报名\tT218\t12\t16\t国王模式报名官\t0\t24\t0",
        "玄渊国王模式_返回大厅\tT218\t16\t16\t裁判老秦\t0\t24\t0",
    )
    for line in required:
        if merchant.count(line) != 1:
            raise RuntimeError(f"NPC注册不是唯一预期状态：{line}")

    sources: dict[str, bytes] = {}
    for old_name, new_name in PAIRS:
        source = MARKET / old_name
        destination = MARKET / new_name
        if not source.is_file():
            raise RuntimeError(f"源脚本不存在：{source}")
        if destination.exists():
            raise RuntimeError(f"目标脚本已经存在，禁止覆盖：{destination}")
        raw = source.read_bytes()
        text = raw.decode("gb18030")
        if text.count("[@Main]") != 1:
            raise RuntimeError(f"源脚本[@Main]数量异常：{source}")
        sources[new_name] = raw

    stamp = time.strftime("%Y%m%d_%H%M%S")
    manual_backup = SERVER / "Backup" / f"XuanYuan_KingNpc_T218_{stamp}"
    manual_backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(ENVIR / "MerChant.txt", manual_backup / "MerChant.txt")
    for old_name, _ in PAIRS:
        shutil.copy2(MARKET / old_name, manual_backup / old_name)

    changes = [
        PlannedChange(
            relative_path=f"Mir200/Envir/Market_Def/{new_name}",
            before=None,
            after=raw,
            operation="copy_npc_script_for_map",
            package_id="xy.direct.king-npc.t218",
        )
        for new_name, raw in sources.items()
    ]
    plan = InstallPlan(
        target_root=str(SERVER),
        client_root=None,
        package_ids=["xy.direct.king-npc.t218"],
        package_versions={"xy.direct.king-npc.t218": "1.0.0"},
        parameters={"map": "T218", "preserve_old_scripts": True},
        changes=changes,
        warnings=["复用当前客户端已安装并验证的NPC外观24，无需覆盖客户端补丁。"],
        operation_type="direct-king-npc-t218-script-fix",
    )
    receipt = Installer(PackageRepository(PLATFORM / "packages"), PLATFORM / "backups").install(plan)

    checks = {}
    for old_name, new_name in PAIRS:
        old_raw = (MARKET / old_name).read_bytes()
        new_raw = (MARKET / new_name).read_bytes()
        checks[new_name] = {
            "same_as_source": old_raw == new_raw,
            "sha256": sha256(new_raw),
            "main_count": new_raw.decode("gb18030").count("[@Main]"),
        }
    if not all(v["same_as_source"] and v["main_count"] == 1 for v in checks.values()):
        raise RuntimeError("写入后脚本校验失败")

    print(json.dumps({
        "transaction_id": receipt.transaction_id,
        "platform_backup": receipt.backup_root,
        "manual_backup": str(manual_backup),
        "checks": checks,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
