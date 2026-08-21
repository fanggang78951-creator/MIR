from __future__ import annotations

import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
PHASE1 = BASE.parent / "phase1_script" / "交给平台应用窗口_材料Idx映射.json"


def load(name: str) -> dict:
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    required = [
        "00_上游状态与平台只读预检.md",
        "01_材料编号颜色模板映射.xlsx",
        "01_材料编号颜色模板映射.json",
        "02_材料来源怪物与掉率映射.xlsx",
        "02_材料来源怪物与掉率映射.json",
        "03_专属装备来源等级登记.json",
        "04_强合成与任务奖励装备平台表.xlsx",
        "05_平台预检或导入结果.md",
        "06_编号重复与交叉冲突报告.md",
        "07_交给脚本窗口_平台对象映射.json",
        "08_平台变更清单与回滚说明.md",
    ]
    missing = [name for name in required if not (BASE / name).is_file()]
    require(not missing, f"缺少平台成果：{missing}")

    phase1 = json.loads(PHASE1.read_text(encoding="utf-8"))
    materials = load("01_材料编号颜色模板映射.json")
    sources = load("02_材料来源怪物与掉率映射.json")
    equipment_sources = load("03_专属装备来源等级登记.json")
    handoff = load("07_交给脚本窗口_平台对象映射.json")

    require(materials["schemaVersion"] == "1.0", "材料映射schema版本错误")
    require(len(materials["materials"]) == 68, "材料对象必须为68条")
    require(len(materials["reservedSlots"]) == 12, "匿名预留位必须为12条")
    require(
        [row["actualIdx"] for row in materials["materials"]]
        == [row["actualIdx"] for row in phase1["materials"]],
        "材料Idx顺序或取值偏离脚本窗口映射",
    )
    require(
        [row["logicalMaterialId"] for row in materials["materials"]]
        == [row["logicalMaterialId"] for row in phase1["materials"]],
        "材料逻辑ID偏离脚本窗口映射",
    )
    require(
        len({row["actualIdx"] for row in materials["materials"]}) == 68,
        "68种材料存在重复Idx",
    )
    require(
        [row["actualIdx"] for row in materials["reservedSlots"]] == list(range(972, 984)),
        "匿名预留位必须固定为972-983",
    )
    require(sum(row["existingInDatabase"] for row in materials["materials"]) == 3, "复用材料应为3条")
    require(
        sum(row["deploymentState"] == "待本地平台导入" for row in materials["materials"]) == 65,
        "新增材料待导入数应为65条",
    )

    source_rows = sources["sources"]
    require(len(source_rows) == 32, "四证来源必须为32条")
    require(len({row["logicalMaterialId"] for row in source_rows}) == 32, "四证逻辑材料ID重复")
    require(len({row["logicalMonsterId"] for row in source_rows}) == 32, "怪物逻辑ID重复")
    require(all(row["actualMonsterName"] is None for row in source_rows), "不得伪造实际怪物名")
    require(all(row["actualMonsterId"] is None for row in source_rows), "不得伪造实际怪物ID")
    require(all(row["deploymentState"] == "逐项阻断" for row in source_rows), "32条来源当前均应逐项阻断")
    require(sum(not row["mapExists"] for row in source_rows) == 0, "32个四证地图号应全部唯一存在")

    registrations = equipment_sources["sourceEquipment"]
    require(len(registrations) == 44, "11个配方应登记44件来源装备")
    require(len({row["name"] for row in registrations}) == 44, "来源装备名称必须唯一")
    require(all(row["actualIdx"] is None for row in registrations), "不得猜测来源装备Idx")

    require(len(handoff["materials"]) == 68, "交给脚本窗口的材料映射应为68条")
    require(len(handoff["monsterSources"]) == 32, "交给脚本窗口的来源映射应为32条")
    require(len(handoff["equipment"]) == 15, "装备映射应含11件强合成与4件任务奖励")
    require(sum(row["objectKind"] == "强合成成品" for row in handoff["equipment"]) == 11, "强合成装备应为11件")
    require(sum(row["objectKind"] == "四证装备奖励" for row in handoff["equipment"]) == 4, "四证装备奖励应为4件")
    require(all(row["actualIdx"] is None for row in handoff["equipment"]), "不得猜测装备Idx")
    require(all(row["sourceNumber"] is None for row in handoff["equipment"]), "不得猜测装备来源编号")
    require(handoff["upstream"]["commit"] == "7c4ca82fb8dfac0225d9b171344211416de9dae2", "上游提交SHA错误")

    for name in ("01_材料编号颜色模板映射.xlsx", "02_材料来源怪物与掉率映射.xlsx", "04_强合成与任务奖励装备平台表.xlsx"):
        require((BASE / name).stat().st_size > 4096, f"工作簿异常或为空：{name}")

    print("PASS: platform_app contract (68 materials, 32 sources, 44 source equipment, 15 target equipment)")


if __name__ == "__main__":
    main()
