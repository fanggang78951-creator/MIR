from __future__ import annotations

import hashlib
import os
from pathlib import Path


TARGET = Path(
    r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊功能\国王模式赛前\国王模式赛前流程.txt"
)
START = "[@XY_KING_FLOW_CANCEL_IMPL]"
END = "[@XY_KING_FLOW_ADMIN_RESET_ALL_IMPL]"


NEW_BLOCK = r"""[@XY_KING_FLOW_CANCEL_IMPL]
{
#IF
EQUAL G120 0
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队国王名单.txt <$USERNAME>
#ACT
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队国王名单.txt <$USERNAME>
ExitNation
#CALL [\玄渊功能\国王模式赛前\国王模式赛前流程.txt] @XY_KING_FLOW_CANCEL_DEC_A_KING
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_CLEAR_TITLE
MOV N$XY_KING_FLOW_REGISTERED 0
MOV N$XY_KING_FLOW_COUNTED 0
MESSAGEBOX 已退出A方国王报名，国王称号已回收。
BREAK
#IF
EQUAL G120 0
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队平民名单.txt <$USERNAME>
#ACT
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队平民名单.txt <$USERNAME>
ExitNation
#CALL [\玄渊功能\国王模式赛前\国王模式赛前流程.txt] @XY_KING_FLOW_CANCEL_DEC_A_COMMONER
MOV N$XY_KING_FLOW_REGISTERED 0
MOV N$XY_KING_FLOW_COUNTED 0
MESSAGEBOX 已退出A方平民报名。
BREAK
#IF
EQUAL G120 0
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队国王名单.txt <$USERNAME>
#ACT
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队国王名单.txt <$USERNAME>
ExitNation
#CALL [\玄渊功能\国王模式赛前\国王模式赛前流程.txt] @XY_KING_FLOW_CANCEL_DEC_B_KING
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_CLEAR_TITLE
MOV N$XY_KING_FLOW_REGISTERED 0
MOV N$XY_KING_FLOW_COUNTED 0
MESSAGEBOX 已退出B方国王报名，国王称号已回收。
BREAK
#IF
EQUAL G120 0
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队平民名单.txt <$USERNAME>
#ACT
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队平民名单.txt <$USERNAME>
ExitNation
#CALL [\玄渊功能\国王模式赛前\国王模式赛前流程.txt] @XY_KING_FLOW_CANCEL_DEC_B_COMMONER
MOV N$XY_KING_FLOW_REGISTERED 0
MOV N$XY_KING_FLOW_COUNTED 0
MESSAGEBOX 已退出B方平民报名。
BREAK
#IF
EQUAL G120 0
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
#ACT
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队名单.txt <$USERNAME>
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队国王名单.txt <$USERNAME>
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\A队平民名单.txt <$USERNAME>
ExitNation
#CALL [\玄渊功能\国王模式赛前\国王模式赛前流程.txt] @XY_KING_FLOW_CANCEL_DEC_A_ONLY
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_CLEAR_TITLE
MOV N$XY_KING_FLOW_REGISTERED 0
MOV N$XY_KING_FLOW_COUNTED 0
MESSAGEBOX 已清理A方残留报名数据，国王称号已尝试回收。
BREAK
#IF
EQUAL G120 0
CheckTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
#ACT
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队名单.txt <$USERNAME>
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队国王名单.txt <$USERNAME>
DelTextList ..\QuestDiary\玄渊数据\xy_king_mode\B队平民名单.txt <$USERNAME>
ExitNation
#CALL [\玄渊功能\国王模式赛前\国王模式赛前流程.txt] @XY_KING_FLOW_CANCEL_DEC_B_ONLY
#CALL [\玄渊功能\国王模式\国王模式核心.txt] @XY_KING_CLEAR_TITLE
MOV N$XY_KING_FLOW_REGISTERED 0
MOV N$XY_KING_FLOW_COUNTED 0
MESSAGEBOX 已清理B方残留报名数据，国王称号已尝试回收。
BREAK
#IF
EQUAL G120 0
#ACT
MESSAGEBOX 你当前没有可取消的报名。
BREAK
#ELSEACT
MESSAGEBOX 倒计时或活动已经开始，不能退出当前选择。
BREAK
}

[@XY_KING_FLOW_CANCEL_DEC_A_KING]
{
#IF
LARGE G121 0
#ACT
DEC G121 1
#IF
LARGE G123 0
#ACT
DEC G123 1
BREAK
}

[@XY_KING_FLOW_CANCEL_DEC_A_COMMONER]
{
#IF
LARGE G121 0
#ACT
DEC G121 1
#IF
LARGE G124 0
#ACT
DEC G124 1
BREAK
}

[@XY_KING_FLOW_CANCEL_DEC_B_KING]
{
#IF
LARGE G122 0
#ACT
DEC G122 1
#IF
LARGE G125 0
#ACT
DEC G125 1
BREAK
}

[@XY_KING_FLOW_CANCEL_DEC_B_COMMONER]
{
#IF
LARGE G122 0
#ACT
DEC G122 1
#IF
LARGE G126 0
#ACT
DEC G126 1
BREAK
}

[@XY_KING_FLOW_CANCEL_DEC_A_ONLY]
{
#IF
LARGE G121 0
#ACT
DEC G121 1
BREAK
}

[@XY_KING_FLOW_CANCEL_DEC_B_ONLY]
{
#IF
LARGE G122 0
#ACT
DEC G122 1
BREAK
}

"""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def main() -> None:
    original = TARGET.read_bytes()
    text = original.decode("gb18030")
    if text.count(START) != 1 or text.count(END) != 1:
        raise SystemExit("取消入口或后续管理员入口无法唯一识别，未写入。")

    begin = text.index(START)
    finish = text.index(END, begin)
    old_block = text[begin:finish]
    if "EQUAL N$XY_KING_FLOW_REGISTERED 1" not in old_block:
        raise SystemExit("现有取消块与预期旧版本不一致，未写入。")

    updated = text[:begin] + NEW_BLOCK + text[finish:]
    checks = {
        "不再依赖易失报名变量": "EQUAL N$XY_KING_FLOW_REGISTERED 1" not in NEW_BLOCK,
        "四类角色名单均参与判断": all(
            f"CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\{name}.txt <$USERNAME>"
            in NEW_BLOCK
            for name in ("A队国王名单", "A队平民名单", "B队国王名单", "B队平民名单")
        ),
        "A/B残留队伍名单可清理": all(
            f"CheckTextList ..\\QuestDiary\\玄渊数据\\xy_king_mode\\{name}.txt <$USERNAME>"
            in NEW_BLOCK
            for name in ("A队名单", "B队名单")
        ),
        "国王分支回收称号": NEW_BLOCK.count("@XY_KING_CLEAR_TITLE") == 4,
        "离开国家阵营": NEW_BLOCK.count("ExitNation") == 6,
        "人数只在大于零时递减": NEW_BLOCK.count("LARGE G") == 10,
        "明确区分报名期和活动期": "#ELSEACT\nMESSAGEBOX 倒计时或活动已经开始" in NEW_BLOCK,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise SystemExit("静态检查失败：" + "、".join(failed))

    payload = updated.encode("gb18030")
    temporary = TARGET.with_suffix(TARGET.suffix + ".xydp-tmp")
    temporary.write_bytes(payload)
    reread = temporary.read_bytes()
    if reread != payload or START.encode("gb18030") not in reread:
        temporary.unlink(missing_ok=True)
        raise SystemExit("临时副本校验失败，未写入正式文件。")
    os.replace(temporary, TARGET)

    print(f"TARGET={TARGET}")
    print(f"OLD_SHA256={sha256(original)}")
    print(f"NEW_SHA256={sha256(payload)}")
    for name, ok in checks.items():
        print(f"CHECK {name}={'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
