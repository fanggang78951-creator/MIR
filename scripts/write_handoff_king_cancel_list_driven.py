from __future__ import annotations

from datetime import datetime
from pathlib import Path


ROOT = Path(r"D:\codex交班记录")
INDEX = ROOT / "00_任务总结索引.txt"
POINTER = ROOT / "01_最近任务指针.txt"
STAMP = datetime.now().strftime("%Y%m%d_%H%M")
NAME = f"{STAMP}_修复国王模式取消报名误判.txt"
HANDOFF = ROOT / NAME
TARGET = Path(
    r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊功能\国王模式赛前\国王模式赛前流程.txt"
)
BACKUP = Path(
    r"D:\XuanYuanDevPlatform\backups\king_cancel_list_driven_20260717_073001"
)


BODY = f"""状态：待验证

任务目标
修复“国王模式报名官 → 取消当前选择”误报“你当前没有可取消的报名”的问题；已报名玩家即使重启或重登后登录变量丢失，也必须能够退出 A/B 队及国王/平民身份。

读取文件
1. D:\\codex交班记录\\00_任务总结索引.txt
2. D:\\codex交班记录\\01_最近任务指针.txt
3. D:\\codex交班记录\\20260716_0026_修复国王模式G变量范围与战士误判.txt
4. D:\\codex交班记录\\20260715_2355_修复国王模式NPC转发死循环.txt
5. {TARGET}
6. D:\\MirServer\\Mir200\\Envir\\Market_Def\\玄渊国王模式_赛前报名-T218.txt
7. D:\\MirServer\\Mir200\\Envir\\QuestDiary\\玄渊数据\\xy_king_mode\\A队名单.txt、A队国王名单.txt、A队平民名单.txt、B队名单.txt、B队国王名单.txt、B队平民名单.txt

修改文件
1. {TARGET}
2. {HANDOFF}
3. {INDEX}
4. {POINTER}

备份路径
{BACKUP}
备份包含修改前的国王模式赛前流程、任务总结索引和最近任务指针。
修改前赛前流程 SHA256：18F1E20980AFBE3AA25CC2BF257A17BAB0255360F21F6D694FD8B0CDDD922E66

实际执行内容
1. 根因确认：原取消入口依赖 N$XY_KING_FLOW_REGISTERED、S$XY_KING_FLOW_TEAM、S$XY_KING_FLOW_ROLE；这些玩家登录变量可能在重启、重登或旧脚本迁移后为空，但报名 TXT 仍保存玩家名，因此产生误报。
2. 将取消逻辑改为直接检查四份持久角色名单：A队国王、A队平民、B队国王、B队平民。
3. 取消成功后同步删除队伍名单与角色名单、退出国家阵营、清零本次玩家报名标记；国王分支继续调用 @XY_KING_CLEAR_TITLE 回收“国王”称号。
4. 增加 A/B 队伍名单残留兜底：角色名单异常缺失时仍可清除当前玩家的残留报名，不再被登录变量卡住。
5. 所有 G121-G126 人数递减均先用 LARGE 检查大于 0，避免现有名单与全局计数不一致时减成负数。
6. 未修改 NPC 注册、NPC 对话、地图、平台程序或当前报名数据。

验证情况
1. GB18030 解码/回写通过，正式文件新 SHA256：F2031A6BADE70C535EC53F8288B0FD7353425637266FACDB6695D3734ED677F0。
2. 取消块已不含 EQUAL N$XY_KING_FLOW_REGISTERED 1。
3. 四份角色名单与 A/B 两份队伍名单共 6 个取消判断均存在。
4. 6 个取消分支均执行 ExitNation；国王及残留分支包含称号回收。
5. 10 个计数递减保护检查存在；新增标签无重复；管理员清空入口保持唯一。
6. 当前只运行 GameCenter 进程且无可控制窗口，M2 未启动，无法完成脚本加载和游戏点击验证。

经验沉淀
国王模式报名的长期真实状态必须以 QuestDiary 下的名单 TXT 为准，N$/S$ 玩家变量只能作为在线缓存，不能作为取消、重连恢复等持久操作的唯一判断条件。

踩坑风险
1. 旧报名名单与 G121-G126 计数当前可能不同步；本修复防止取消时负数，但不负责从历史名单重新计算全局计数。
2. 活动阶段 G120 非 0 时仍按规则禁止取消。
3. M2 必须通过 GameCenter 整套启动后才会重新加载本次脚本。

下轮建议
通过 GameCenter 启动引擎后，用当前已在 A队国王名单中的“发发发”点击“取消当前选择”：应提示已退出 A 方国王、从 A队名单和A队国王名单删除、退出 A 国并收回国王称号。随后重新报名一次，确认可以再次加入。
"""


POINTER_TEXT = f"""状态：待验证
最近一次任务总结：
{HANDOFF}
当前任务：已修复国王模式“取消当前选择”因登录变量丢失而误报未报名。
目标写入：{TARGET}。
备份：{BACKUP}。
结果：取消报名改为以持久名单 TXT 为准，支持 A/B 国王、平民及残留队伍数据；人数递减带非负保护，不修改现有报名数据。
下一步：从 GameCenter 启动整套引擎，使用已报名角色点击“取消当前选择”，验证名单删除、退出国家和国王称号回收。
"""


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if HANDOFF.exists():
        raise SystemExit(f"交班文件已存在，未覆盖：{HANDOFF}")
    HANDOFF.write_text(BODY, encoding="utf-8-sig", newline="\r\n")

    index_text = INDEX.read_text(encoding="utf-8-sig")
    index_line = (
        f"{STAMP} | {NAME} | 国王模式取消报名持久名单修复 | 待验证 | "
        "已将取消报名从易失N$/S$变量判断改为A/B国王/平民持久名单判断，增加残留名单清理、退出国家、国王称号回收和人数非负保护；静态检查通过，待M2加载及游戏点击验证。"
    )
    if NAME not in index_text:
        index_text = index_text.rstrip("\r\n") + "\r\n" + index_line + "\r\n"
        INDEX.write_text(index_text, encoding="utf-8-sig", newline="")

    POINTER.write_text(POINTER_TEXT, encoding="utf-8-sig", newline="\r\n")
    print(f"HANDOFF={HANDOFF}")
    print("INDEX=UPDATED")
    print("POINTER=UPDATED")


if __name__ == "__main__":
    main()
