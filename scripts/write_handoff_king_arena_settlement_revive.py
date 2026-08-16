from __future__ import annotations

from datetime import datetime
from pathlib import Path


ROOT = Path(r"D:\codex交班记录")
INDEX = ROOT / "00_任务总结索引.txt"
POINTER = ROOT / "01_最近任务指针.txt"
STAMP = datetime.now().strftime("%Y%m%d_%H%M")
NAME = f"{STAMP}_修复角斗场击杀结算与自动复活.txt"
HANDOFF = ROOT / NAME
QFUNCTION = Path(r"D:\MirServer\Mir200\Envir\Market_Def\QFunction-0.txt")
CORE = Path(r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊功能\国王模式\国王模式核心.txt")
BACKUP = Path(r"D:\XuanYuanDevPlatform\backups\king_arena_settlement_revive_20260717_081909")


BODY = f"""状态：待验证

任务目标
修复XYGDZY角斗场三项游戏内故障：击杀对方不增加元宝和升级经验、死亡者不扣元宝、死亡后不自动回本方复活点。

读取文件
1. D:\\codex交班记录\\00_任务总结索引.txt
2. D:\\codex交班记录\\01_最近任务指针.txt
3. D:\\codex交班记录\\20260716_2343_实装国王模式百分比击杀经验.txt
4. D:\\codex交班记录\\20260717_0717_实装按死亡地图分流自动复活.txt
5. D:\\codex交班记录\\20260715_1425_国王模式技能脚本沉淀.txt
6. {QFUNCTION}
7. {CORE}
8. D:\\MirServer\\Mir200\\Envir\\QuestDiary\\玄渊配置\\国王模式配置.txt
9. D:\\MirServer\\Mir200\\Envir\\QuestDiary\\玄渊数据\\xy_king_mode 下的A/B队伍、国王、平民名单和状态文件
10. D:\\素材文件夹\\明月地图补丁\\77boss是解压码MirServer\\MirServer\\Mir200\\Envir\\Market_Def\\QFunction-0.txt
11. 翎风官方帮助：杀死人物触发、人物死亡触发、DelayCall、GAMEGOLD和脚本变量大全。

修改文件
1. {QFUNCTION}
2. {CORE}
3. {HANDOFF}
4. {INDEX}
5. {POINTER}

备份路径
{BACKUP}
修改前QFunction SHA256：3DEC194318E47BC49DDF3BFDD903C4467A3DD956BFC1B7A8ACB356E77A882CA0
修改前核心 SHA256：EF35CF6CF0D28943E63A54712D3128B52B50864778BF230178C03701006BEB93

实际执行内容
1. 根因一：击杀结算、经验和复活均被N$XY_KING_MODE、N$XY_KING_FLOW_REGISTERED、S$XY_KING_FLOW_TEAM/ROLE等在线变量限制；重启、重登或未走完整五波传送时，名单仍在但变量为空，三条链同时失效。
2. 根因二：原核心把用户规则中的“元宝”错误写成GAMEDIAMOND（金刚石），即使分支命中也不是目标币种。
3. 将KillPlay公共出口保留为唯一调用，核心@XY_KING_KILL_EXP改为“击杀元宝+百分比经验”统一结算：只检查XYGDZY、击杀者持久A/B队伍名单和被杀者角色名单。
4. 普通成员击杀：击杀者GAMEGOLD +100，当前升级经验+10%；击杀国王：GAMEGOLD +500，经验+50%。角色名单异常缺失但仍在队伍名单时按普通成员兜底。
5. PlayDie只负责死亡者侧结算：使用官方KillByHum限定直接人物击杀；普通死亡最多扣25元宝，国王死亡最多扣500元宝；余额不足只扣现有余额，0时不扣，不会负数。
6. 国王死亡身份、次数和胜负判断改为持久A/B国王名单，不再读取S$国王名字缓存。
7. 自动复活调度改为死亡地图+持久名单：XYKWA只认A队、XYKWB只认B队、XYGDZY分别识别A/B队，统一DelayCall 1000。
8. 野区仍直接回各自50,50；角斗场REALIVE后由@Revival按持久名单送A方15,50或B方100,50。国王满血蓝、普通成员50%血蓝；国王第10次角斗场死亡仍禁止复活。
9. 没有修改地图、数据库、NPC、配置数值、平台母版或当前报名名单。

验证情况
1. 写入事务前校验原文件哈希，临时副本GB18030往返通过，两个正式文件原子替换成功。
2. 13项静态契约全部通过：币种、100/500奖励、25/500扣除、10%/50%经验、四类复活调度、野区分流、A/B角斗场复活点、第10次阻止、标签唯一和共享入口保留。
3. 修改后QFunction SHA256：31D8624EA862D74FF380E1DCBEE7C33066A1F8374BCDF6F67ED9D9DE7DB26CA6。
4. 修改后核心 SHA256：25903F55B94C9E9CBE5FF2EA983FFAE2BCA8B079E688AAA6E3C9EE5B7936B869。
5. 只关闭旧M2 PID6720，GameCenter自动拉起新M2 PID6384；没有单独启动第二个M2。
6. 新日志D:\\MirServer\\Mir200\\Log\\2026-07-17.08-23.txt中脚本错误、死循环、不存在标签、load fail、命令错误、database is locked和NPC坐标错误均为0；M2响应正常。
7. 当前没有游戏客户端进程，尚未完成真实双角色击杀与复活验收，因此状态为待验证。

经验沉淀
1. 报名名单TXT才是跨重启的真实身份来源；N$/S$只适合在线缓存，不能作为击杀结算、复活、取消报名的唯一门禁。
2. @KillPlay当前对象是击杀者，适合直接GAMEGOLD和CHANGEEXP；@PlayDie当前对象是死亡者，适合扣除自身GAMEGOLD并读取<$KILLER>。
3. 元宝=GAMEGOLD，金刚石=GAMEDIAMOND；两者不可混用。
4. 自动复活必须先按死亡地图分流，再按持久名单识别阵营，避免野区死亡进入角斗场。

踩坑风险
1. 当前两名测试角色都在A/B国王名单，所以互杀应走500元宝、50%经验和国王满血蓝路线；普通成员规则需另用平民角色验收。
2. 国王死亡次数N$仍是在线计数，M2重启后的十次累计持久化尚未在本轮重构；本轮只修复用户报告的三条断链。
3. 平台母版仍是旧逻辑，按用户既定要求，当前服游戏验收前不回填平台，避免把未实测代码晋级。

下轮建议
1. A国王击杀B国王：A元宝+500、经验增加MAXEXP的50%；B元宝最多-500；1秒后B在XYGDZY 100,50满血满蓝复活。
2. B国王击杀A国王：反向验证，A应在15,50复活。
3. 用普通成员验证+100元宝、+10%经验、死亡最多-25元宝和50%血蓝。
4. 分别让死亡者拥有0、低于扣除额、刚好等于扣除额、超过扣除额的元宝，确认不出现负数。
5. 游戏验收通过后再回填xy.optional.king-mode成果包并更新平台回归测试。
"""


POINTER_TEXT = f"""状态：待验证
最近一次任务总结：
{HANDOFF}
当前任务：已修复XYGDZY击杀元宝/百分比经验、死亡扣元宝和1秒自动复活三条断链。
目标写入：{QFUNCTION}；{CORE}。
备份：{BACKUP}。
结果：结算和复活全部改为XYGDZY+持久A/B名单驱动，币种由错误的GAMEDIAMOND改为GAMEGOLD；M2 PID6384加载无脚本/命令/数据库错误。
下一步：当前A/B测试角色均为国王，互杀应验证+500元宝、+50%升级经验、死亡最多-500元宝和A15,50/B100,50满血蓝复活；通过后再沉淀平台母版。
"""


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if HANDOFF.exists():
        raise SystemExit(f"交班文件已存在，未覆盖：{HANDOFF}")
    HANDOFF.write_text(BODY, encoding="utf-8-sig", newline="\r\n")

    index_text = INDEX.read_text(encoding="utf-8-sig")
    line = (
        f"{STAMP} | {NAME} | 角斗场击杀结算与自动复活修复 | 待验证 | "
        "已将XYGDZY击杀奖励、死亡扣除和自动复活从易失N$/S$变量改为持久A/B名单驱动，纠正GAMEDIAMOND为GAMEGOLD；M2自动重启后脚本/命令/数据库错误均为0，待双角色游戏验收。"
    )
    if NAME not in index_text:
        INDEX.write_text(index_text.rstrip("\r\n") + "\r\n" + line + "\r\n", encoding="utf-8-sig", newline="")
    POINTER.write_text(POINTER_TEXT, encoding="utf-8-sig", newline="\r\n")
    print(f"HANDOFF={HANDOFF}")
    print("INDEX=UPDATED")
    print("POINTER=UPDATED")


if __name__ == "__main__":
    main()
