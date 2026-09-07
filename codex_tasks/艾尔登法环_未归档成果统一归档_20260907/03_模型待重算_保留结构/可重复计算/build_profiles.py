
"""Reproducible, offline half-speed paid-player profile model V1.1.
No game files or GitHub are changed. Assumptions are explicit in ASSUMPTIONS.
Run: python build_profiles.py [directory_containing_source_inputs.json]
"""
from pathlib import Path
import json, math, re, copy, hashlib, random
from collections import defaultdict, Counter

ATTRS = [
"攻击下限","攻击上限","魔法下限","魔法上限","道术下限","道术上限",
"HP","MP","防御下限","防御上限","魔御下限","魔御上限",
"攻击加成","魔法加成","道术加成","神力增量","伤害系数","打怪伤害","攻击伤害",
"暴击几率","暴击伤害","致命几率","致命伤害","固定切割","每秒回血","攻击速度","攻速突破","准确",
"武器幸运","项链幸运","处决概率","处决倍率","处决时间","韧性","对怪伤害吸收",
"伤害吸收上限","吸血","爆率","最大爆率","人物爆率","鞭尸","首刀斩杀","尾刀斩杀","HP百分比","回收增加"
]
PHASES = ["半急速入场","半急速中期","半急速毕业","极端压力"]
ASSUMPTIONS = [
["A01","人物底板", "等效40级，攻击7—13、HP1000、MP200；每10级攻击上限+5、下限+2、HP+400、MP+100",
 "继承前置推定；并非本机等级表","自然攻击±50%、HP±50%只对自然来源变化"],
["A02","命格开槽","C1/C2/C3/C4/C5/C6/C8/C10中期分别达到1/2/3/4/5/6/7/8槽；C1入场即1槽",
 "因实际阈值未提供，作为可替换节奏假设；不改变解锁脚本","C3以后新槽全彩所需100次材料进入自产需求，不能视作免费赠送"],
["A03","彩色组合","半急速用明确列出的均衡彩色组合；无命格攻速突破；已开放槽全部为彩色",
 "用户边界＋模型选配，非宣称彩池等强或P65精确分位","不使用黄/橙平均值，也不宣称最佳彩色"],
["A04","C2成长装备灵符路线","主情景假设圣律真言/黄金之心在C2可用灵符升至LV10；C2入场采用",
 "推定可支付路线，不是已验证脚本事实；另算只有LV1/延迟升满对照","若实际不支持，替换路线开关，不新增付费接口"],
["A05","神印/洗练/幸运/技能","目前无明确灵符替代证据的路径按自产材料/货币；不自动C2神印255或洗练极品",
 "遵守只使用已支持支付路径；神印主情景C2毕业50","额外给C2神印255的孤立敏感性，非正式付费设计"],
["A06","装备取得","普通/稀有逐阶段替换，当前大陆BOSS装备名额中期1、毕业2；当前重点合成毕业1件，生肖与群攻另计",
 "自打取得的规划情景；不购买玩家物品","获取次数与原材料列入反算需求，尚不证明固定小时内可取得"],
["A07","词条抽样","固定种子20260905；洗练只用用户池；普通整件重洗，7/8条开光固定数量",
 "随机模拟一次可实现样本，不把平均词条数当每件真实属性","使用两份自产同名装备轮换试洗，不回滚历史结果或新增锁条功能"],
["A08","幸运","武器幸运按7点计且成本忽略；项链幸运为人物永久进度，换项链不重置；前250次2.4%，后20%",
 "用户2026-09-05纠正：项链幸运绑定人物；武器幸运成本忽略","幸运12固定上限；达到人物项链幸运8后永久保留，后续换项链不重新付费"],
["A09","技能循环","C1入场/中期/毕业平均普通伤害系数1/1.08/1.16，C2中期1.25、毕业以后1.35；极端1.60",
 "仅技能循环估计系数，不作为人物永久属性，不修改技能","另给不含技能DPS；技能系数区间1—1.60"],
["A10","命中与有效时间","命中0.95，有效输出时间0.80；作用各一次","缺少实测时沿用假设","命中0.85—1，有效时间0.65—0.95"],
["A11","神力/攻击伤害","神力来源按增量加算后1+总增量；攻击伤害每点按0.01独立增幅","同类加算是项目规则；攻击伤害单位为假设","攻击伤害每点0.10另列敏感性"],
["A12","暴击/致命","各基础总倍率2；概率封于0—100%；二者独立期望相乘","基础倍率为假设，概率公式为数学定义","基础倍率1.5敏感性"],
["A13","爆率字段","M=(1+基础爆率百分点/100+人物爆率点×1)×(1+最大爆率百分点/100)",
 "内部字段换算假设；不是实际Apex公式；不补差凑100","同时算人物爆率每点0.01倍；两个结果均输出"],
["A14","处决","单独算地图抵扣0/10/20/30个百分点；持续1+0.2×(有效概率百分点-1)+额外秒；总倍率2+0.2×(百分点-1)+额外倍率",
 "PVE概率扣地图值为规则；将持续/倍率框架用于PVE窗口是模型假设","常规DPS不含处决，零抵扣窗口不是怪物实际净DPS"],
["A15","承伤","有效吸收=min(原始吸收,60%+上限增量,99%)；85%仅设计警戒，不偷偷当引擎硬封顶",
 "60/85为项目边界，99%仅避免数学除零","EHP不含怪物防御/控制；回血上限按有效伤害，不计尾刀/过量伤害"],
["A16","旧任务与保护","C2原5魂魄任务按来源继承；C1魂魄任务按原件每图攻魔道+30、韧性+20；用户改过16卷与6神器主情景不预装",
 "C1任务原件已读取；未知本机改版原件不得覆盖","本批压力档也不套用旧神器数值；不代表含本机6神器/16称号卷的全服绝对极限"],
["A17","群攻","群星之核攻击力伤害/间隔，主情景单目标；同目标不重复乘群怪数量；不乘暴击/技能系数",
 "基于原效果的保守映射假设","是否吃其他乘区/多目标吸血留接口，不纳入主回血"],
["A18","彩色投入与数值尺度","C1/C2彩色命格按灵符路径；C3以后每新槽100次保底预算。游戏内金币/元宝统一按原尺度×100，失色锻造石产出/消耗按原尺度×10",
 "用户2026-09-05数值尺度修订；只放大数值显示与资源颗粒，不改变原比例","不存在21765灵符与12小时的换算；其他材料数量不按本条放大"],
["A19","版本状态","本轮只生成离线人物配置、属性和派生结果；不改原表、正式服或GitHub",
 "用户指令","40组不是一批已经实测过的游戏账号"],
]
ALIASES={"暴击":"暴击几率","致命一击":"致命几率","处决伤害":"处决倍率","神力倍攻":"神力增量"}

def pair(v):
    if v in (None,"","—","无"): return (0.,0.)
    if isinstance(v,(int,float)): return float(v),float(v)
    ss=re.findall(r"-?\d+(?:\.\d+)?",str(v).replace("—","~").replace("－","~").replace("-","~"))
    if not ss: return (0.,0.)
    x=float(ss[0]); return (x,float(ss[1]) if len(ss)>1 else x)

def numeric(v):
    if v in (None,"","—","无"): return 0.
    if isinstance(v,(int,float)): return float(v)
    return float(str(v).strip().replace("%",""))

def stats_from_gear(g):
    out={}
    for k in ["攻击","魔法","道术","防御","魔御"]:
        lo,hi=pair(g.get(k))
        if lo: out[k+"下限"]=lo
        if hi: out[k+"上限"]=hi
    for k in ATTRS:
        if k in g and k not in ["武器幸运","项链幸运"]:
            out[k]=numeric(g[k])
    if g.get("神力倍攻"): out["神力增量"]=numeric(g["神力倍攻"])
    return {k:v for k,v in out.items() if v}

def stat_attr(k,v):
    k=ALIASES.get(k,k)
    if k in ["攻击","魔法","道术","防御","魔御"]:
        return {k+"下限":float(v),k+"上限":float(v)}
    return {k:float(v)} if k in ATTRS else {}

def sumstats(sources):
    ret={k:0. for k in ATTRS}
    for s in sources:
        for k,v in s["stats"].items():
            if k not in ret: raise ValueError("Unknown stat "+k)
            ret[k]+=v
    return ret

def weapon_speed(s):
    s=max(0,min(50,s))
    anchors={0:1.75,10:2.2,20:2.9,30:4.3,40:8.5,50:14.3}
    if s in anchors: return anchors[s]
    if s<=40: return 1000/(570.111430-11.295503*s)
    # Unmeasured 41-49: interpolate attack intervals, not rates.
    return 1000/(1000/8.5+(s-40)/10*(1000/14.3-1000/8.5))

def derive(raw, skill=1.35, aoe_interval=0, hit=.95, uptime=.8, attk_unit=.01,
           person_unit=1., critbase=2, lethalbase=2):
    atklo=raw["攻击下限"]*(1+raw["攻击加成"]/100)
    atkhi=raw["攻击上限"]*(1+raw["攻击加成"]/100)
    luck=raw["武器幸运"]+raw["项链幸运"]
    rollw=1 if luck>=12 else .5+.5*max(luck,0)/12
    atk=atklo+(atkhi-atklo)*rollw
    hp=raw["HP"]*(1+raw["HP百分比"]/100)
    extra_luck_damage=15 if luck>=15 else 0
    extra_luck_exec=5 if luck>=15 else 0
    rate=weapon_speed(min(raw["攻击速度"],20+min(30,raw["攻速突破"])))
    pcrit=max(0,min(1,raw["暴击几率"]/100))
    plethal=max(0,min(1,raw["致命几率"]/100))
    critm=1+pcrit*(critbase+raw["暴击伤害"]/100-1)
    lethalm=1+plethal*(lethalbase+raw["致命伤害"]/100-1)
    linear=(1+raw["伤害系数"]/100+extra_luck_damage/100)*(1+raw["打怪伤害"]/100)*(1+raw["神力增量"])*(1+raw["攻击伤害"]*attk_unit)
    ordinary=atk*linear
    expected=ordinary*critm*lethalm
    cut=raw["固定切割"]
    pure_dps=(expected+cut)*rate*hit
    skill_dps=(expected*skill+cut)*rate*hit
    aoe_dps=atk/aoe_interval*hit if aoe_interval>0 else 0
    sust=(skill_dps+aoe_dps)*uptime
    absorb=min(.99,raw["对怪伤害吸收"]/100,.60+raw["伤害吸收上限"]/100)
    absorb=max(0,absorb)
    ehp=hp/(1-absorb)
    lifepct=max(0,raw["吸血"]/100)
    # Sustainable dummy healing excludes cuts, first/tail strikes and aoe; actual target overkill is not counted.
    leech_upper=expected*skill*rate*hit*uptime*lifepct
    heal_minute=leech_upper+raw["每秒回血"]
    gold_bonus=1.5 # Already all-sources model total, not 1.5 plus fate again
    m=(1+raw["爆率"]/100+raw["人物爆率"]*person_unit)*(1+raw["最大爆率"]/100)
    m_alt=(1+raw["爆率"]/100+raw["人物爆率"]*.01)*(1+raw["最大爆率"]/100)
    out={
        "面板攻击下限":atklo,"面板攻击上限":atkhi,
        "面板魔法下限":raw["魔法下限"]*(1+raw["魔法加成"]/100),
        "面板魔法上限":raw["魔法上限"]*(1+raw["魔法加成"]/100),
        "面板道术下限":raw["道术下限"]*(1+raw["道术加成"]/100),
        "面板道术上限":raw["道术上限"]*(1+raw["道术加成"]/100),
        "HP":hp,"MP":raw["MP"],"期望攻击取值":atk,"有效幸运":luck,"幸运额外伤害系数":extra_luck_damage,
        "有效攻速点":min(50,max(0,min(raw["攻击速度"],20+min(30,raw["攻速突破"])))),"刀每秒":rate,
        "普通单刀":ordinary,"暴致命期望单刀":expected,"普攻站桩DPS":pure_dps,
        "技能系数":skill,"技能站桩DPS":skill_dps,"群攻单目标DPS":aoe_dps,
        "有效常规DPS":sust,"有效吸收":absorb,"等效HP不计防御":ehp,
        "吸血理论上限每秒":leech_upper,"含固定回复上限每秒":heal_minute,
        "有效爆率_主换算":m,"有效爆率_小单位对照":m_alt,
        "鞭尸期望倍数":1+min(1,max(0,raw["鞭尸"]/100)),"货币回收倍率":gold_bonus,
        "处决总概率百分点":raw["处决概率"]+extra_luck_exec,
        "首刀":raw["首刀斩杀"],"尾刀":raw["尾刀斩杀"],
        "暴击期望乘区":critm,"致命期望乘区":lethalm
    }
    for resist in [0,10,20,30]:
        ep=max(0,min(1,(out["处决总概率百分点"]-resist)/100))
        dur=1+.2*max(0,ep*100-1)+raw["处决时间"] if ep>0 else 0
        mult=2+.2*max(0,ep*100-1)+raw["处决倍率"]/100 if ep>0 else 1
        n=max(0,int(math.floor(dur*rate*hit)))
        cov=1-(1-ep)**n if ep>0 else 0
        fact=1+cov*(mult-1)
        # Only ordinary portion benefits in this hypothetical sustained-window model.
        out[f"处决{resist}_有效概率"]=ep;out[f"处决{resist}_覆盖率"]=cov
        out[f"处决{resist}_窗口倍率"]=mult;out[f"处决{resist}_秒"]=dur
        out[f"处决{resist}_长战DPS"]=((expected*skill*fact+cut)*rate*hit+aoe_dps)*uptime
    return out

class Model:
    def __init__(self, inp):
        self.i=inp; self.d=inp["nonmonster"]; self.a=inp["audit"]
        self.catalog={};self.meta={};self.crafts={};self.cols={r[2]:r for r in self.d["collection_single"]}
        self.groups=defaultdict(list)
        for c,g,*_ in self.d["collection_pages"]:
            self.groups[int(c[1:])].append(g)
        for j,g in enumerate(inp["standard"]):
            c=1 if j//8<10 else 2
            self.catalog[g["名称"]]=g
            self.meta[g["名称"]]={"c":c,"group":"制式过渡","group_index":0,"type":"制式","source":"S01","set":j//8+1}
        old={}
        for r in inp["c1_exclusive_metadata"][1:]:
            if r[4]: old[r[4]]=r
        c2={}
        for r in inp["c2_monster_metadata"][1:]:
            if r[16]:c2[r[16]]=r
        for g in inp["exclusive12"]:
            name=g["名称"]; col=self.cols[name];c=int(col[0][1:]);grp=col[1]
            r=old.get(name) if c==1 else c2.get(name)
            self.catalog[name]=g
            self.meta[name]={"c":c,"group":grp,"group_index":self.groups[c].index(grp),
                             "type":col[3],"monster":r[3] if c==1 and r else r[7] if r else "",
                             "source":"S02"}
        for g,r in zip(self.d["gear"],self.d["gear_audit"]):
            self.catalog[g["名称"]]=g
            c=int(r[1][1:]);grp=r[2]
            self.meta[g["名称"]]={"c":c,"group":grp,"group_index":self.groups[c].index(grp),
                                  "type":r[4],"monster":r[3],"source":"S07"}
        for g,r in zip(self.d["crafted_gear"],self.d["crafted_summary"]):
            name=g["名称"];c=int(r[1][1:])
            self.catalog[name]=g
            self.meta[name]={"c":c,"group":"合成","group_index":0,"type":r[3],"source":"S07","recipe":r[0]}
        for row in self.a["cost_rows_core"]:
            if row[6] in self.catalog and any(x in row[4] for x in ["合成","群攻"]):
                self.crafts[row[6]]=row
        self.bases={}
        for r in self.d["crafted_summary"]:
            self.bases[r[2]]=[n.strip() for n in re.split(r"[＋+；;]",str(r[5])) if n.strip() not in ["","—","None"]]
        for r in self.d["aoe"]:
            self.bases[r[2]]=[r[3]]
        self.bases["子鼠·潮舱寻金"]=["腐树子鼠","唤潮旧勋"]
        self.fates={}
        for fd in inp["fate_definitions"][1:]:
            sta=defaultdict(float)
            for fr in inp["fate_attributes"][1:]:
                if fr[0]==fd[0]:
                    for k,v in stat_attr(fr[2],fr[3]).items():sta[k]+=v
            self.fates[fd[0]]={"name":fd[2],"quality":fd[3],"stats":dict(sta)}
        self.tiers={r[0]:r for r in self.a["wash_item_tiers"]}
        self.costs={r[0]:r for r in self.a["cost_rows_aux"]}
        self.corecosts={r[0]:r for r in self.a["cost_rows_core"]}
        self.pool=inp["wash_pool"][1:]
        self.failures=[];self.tests=[];self.rolls=[]
        self.standard_fates=[1092,1093,1081,1090,1089,1097,1086,1082]
        self.extreme_fates=[1092,1093,1081,1090,1095,1087,1086,1082]

    def check(self,name,cond,detail=""):
        self.tests.append({"test":name,"pass":bool(cond),"detail":detail})
        if not cond:self.failures.append(name)

    def src(self,category,name,stats,source,status="原表数值",detail=""):
        return {"category":category,"name":name,"stats":stats,"source":source,"status":status,"detail":detail}

    def slots(self,g):
        p=g["部位"]
        mm={"武器":[1],"衣服":[0],"男衣服":[0],"头盔":[4],"项链":[3],"手镯":[5,6],"戒指":[7,8],
            "腰带":[10],"鞋子":[11],"斗笠":[13],"盾牌":[16],"勋章":[2],
            "时装武器":[19],"时装衣服":[18],"时装头盔":[21],"时装项链":[20],
            "时装手镯":[22,23],"时装戒指":[24,25],"时装勋章":[26],"时装腰带":[27],"时装鞋子":[28]}
        if p in mm:return mm[p]
        if p.startswith("生肖") and p[2:].isdigit():return [39+int(p[2:])]
        if p=="时装首饰盒":
            dic={r[0]:70+int(r[2])-1 for r in self.d["slot_plan"]}
            return [dic[g["名称"]]]
        if p=="灵玉":return [] # Reserved for fate interface, conservative mutual-exclusion assumption
        return []

    def score(self,g,aff=None):
        st=stats_from_gear(g)
        for k,v in (aff or {}).items():st[k]=st.get(k,0)+v
        # Monotone, interpretable *selection* utility; not a combat formula.
        return (pair(g.get("攻击"))[1]+st.get("攻击上限",0)*.15+
                st.get("HP",0)*.00045+st.get("攻击加成",0)*4+
                st.get("打怪伤害",0)*7+st.get("暴击伤害",0)*2+
                st.get("对怪伤害吸收",0)*20+st.get("吸血",0)*45+
                st.get("攻速突破",0)*160+st.get("攻击速度",0)*12)

    def newstate(self):
        return {"inventory":{}, "equipped":{}, "stocks":Counter(), "dropped":Counter(),
                "materials":Counter(),"gold":0.,"yuan":0.,"payments":[],
                "atlas":set(),"independent":set(),"quest_ids":set(),"material_atlas":set(),
                "fate_count":0,"fate_cost_recorded":0,"body":0,"rebirth":0,
                "title_c":1,"sword_level":10,"relic_level":10,"growth_phase":1,
                "skills":1.,"skill_level":0,"weapon_luck":0,"neck_luck":0,"neck_tries":0,
                "roll_counts":Counter(),"open_counts":Counter(),"wash_material":0,
                "weapon_blessed":set(),"serial":0}

    def pay(self,st,c,op,gold=0,yuan=0,mats=None,route="自产",note=""):
        if route=="自产":
            gold=gold*100;yuan=yuan*100
            mats={k:(v*10 if k=="失色锻造石" else v) for k,v in (mats or {}).items()}
            st["gold"]+=gold;st["yuan"]+=yuan
            for k,v in mats.items():st["materials"][k]+=v
        st["payments"].append({"c":c,"op":op,"route":route,"gold":gold if route=="自产" else 0,
                               "yuan":yuan if route=="自产" else 0,"mats":mats or {},"note":note})

    def parse_mats(self,txt):
        ret={}
        if not txt:return ret
        for x in re.split(r"[＋+；;]",str(txt)):
            m=re.match(r"(.+?)×\s*(\d+)(?:\.\d+)?",x.strip())
            if m:ret[m.group(1).strip()]=int(m.group(2))
        return ret

    def consume(self,st,name,c,qty=1):
        for _ in range(qty):
            if st["stocks"][name]<=0:self.produce(st,name,c)
            st["stocks"][name]-=1

    def produce(self,st,name,c):
        if name not in self.crafts:
            st["dropped"][name]+=1;st["stocks"][name]+=1;return
        row=self.crafts[name]
        for base in self.bases.get(name,[]):self.consume(st,base,c)
        self.pay(st,c,"合成:"+name,row[10],row[11],self.parse_mats(row[9]),note="每件实际计划成品计一次；不买玩家材料")
        st["stocks"][name]+=1

    def instance(self,st,name,c):
        # Instances retain their own affixes and luck. An acquired backup is not an attribute clone.
        st["serial"]+=1
        self.consume(st,name,c)
        obj={"id":st["serial"],"name":name,"aff":[],"opened":False,"neck_luck":0,"neck_tries":0,"weapon_luck":0}
        st["inventory"][obj["id"]]=obj
        return obj["id"]

    def eligible(self,name,c,phase):
        meta=self.meta[name]
        if meta["c"]>c:return False
        if name in self.crafts:return False
        if meta["type"]=="制式":
            return meta.get("set",100)<= (max(1,c*10-5) if phase=="中期" else c*10) and c<=2
        if meta["c"]<c:return True
        ng=len(self.groups[c]); front=math.ceil(ng*.55) if phase=="中期" else ng
        if meta["group_index"]>=front:return False
        if phase=="中期" and ("BOSS" in meta["type"] or meta["type"]=="守关"):
            return meta["group_index"]<max(1,front-1)
        return True

    def affordable_craft(self,name,c):
        def last(n,seen=None):
            seen=set() if seen is None else seen
            if n in seen:return 99
            meta=self.meta.get(n,{"c":1});mx=meta["c"]
            if n in self.bases:
                for b in self.bases[n]:mx=max(mx,last(b,seen|{n}))
            return mx
        return last(name)<=c

    def select_equipment(self,st,c,phase,extreme=False):
        slots=sorted(set(x for g in self.catalog.values() for x in self.slots(g)))
        allowed=[n for n in self.catalog if self.eligible(n,c,phase)]
        boss_quota=100 if extreme else (1 if phase=="中期" else 2)
        current_boss_used=0
        # Important physical gear first, remaining slots follow.
        order=[1,0,3,5,6,7,8]+[s for s in slots if s not in [1,0,3,5,6,7,8]]
        planned={}
        used=Counter()
        for slot in order:
            candidates=[]
            for name in allowed:
                if slot not in self.slots(self.catalog[name]):continue
                m=self.meta[name];isb=("BOSS" in m["type"] or m["type"]=="守关") and m["c"]==c
                if isb and current_boss_used>=boss_quota:continue
                if used[name] and not extreme:continue
                candidates.append(name)
            if not candidates:continue
            candidates.sort(key=lambda n:self.score(self.catalog[n]))
            # Select upper-middle of eligible range, not absolute all-slot best.
            idx=len(candidates)-1 if extreme else int((len(candidates)-1)*(.70 if phase=="中期" else .80))
            name=candidates[idx]
            oldid=st["equipped"].get(slot)
            if oldid:
                old=st["inventory"][oldid]
                if self.score(self.catalog[old["name"]],self.aff_stats(old))>=self.score(self.catalog[name]):
                    planned[slot]=oldid;used[old["name"]]+=1;continue
            existing=[id for id,o in st["inventory"].items() if o["name"]==name and id not in planned.values()]
            iid=existing[0] if existing else self.instance(st,name,c)
            planned[slot]=iid;used[name]+=1
            if self.meta[name]["c"]==c and ("BOSS" in self.meta[name]["type"] or self.meta[name]["type"]=="守关"):
                current_boss_used+=1
        # Keep previous equipped objects for slots not otherwise replaced.
        for slot,iid in st["equipped"].items():planned.setdefault(slot,iid)
        st["equipped"]=planned
        # C1 mid excludes post-boss fashion / phase-only items naturally via metadata.
        # A finite, explicit self-craft plan. No item from a later continent is conjured.
        craftnow=[]
        if phase=="毕业":
            ordinary=[n for n in self.crafts if self.meta[n]["c"]==c and self.affordable_craft(n,c)
                      and "生肖" not in self.catalog[n]["部位"]]
            ordinary.sort(key=lambda n:self.score(self.catalog[n]),reverse=True)
            craftnow+=ordinary if extreme else ordinary[:1]
            # One continent zodiac plus current group AOE upgrade, both using self-owned inputs.
            for n in self.crafts:
                if self.meta[n]["c"]==c and "生肖" in self.catalog[n]["部位"] and self.affordable_craft(n,c):
                    craftnow.append(n)
            if c==2 and "子鼠·潮舱寻金" in self.crafts:craftnow.append("子鼠·潮舱寻金")
        if extreme:
            craftnow += [n for n in self.crafts if self.meta[n]["c"]<=c and self.affordable_craft(n,c)]
        for n in dict.fromkeys(craftnow):
            eligible_slots=self.slots(self.catalog[n])
            if not eligible_slots:continue
            slot=min(eligible_slots,key=lambda s:self.score(self.catalog[st["inventory"][st["equipped"][s]]["name"]])
                     if s in st["equipped"] else -1)
            oldid=st["equipped"].get(slot)
            if oldid and self.score(self.catalog[st["inventory"][oldid]["name"]],self.aff_stats(st["inventory"][oldid]))>=self.score(self.catalog[n]):
                continue
            iid=next((id for id,o in st["inventory"].items() if o["name"]==n and id not in st["equipped"].values()),None)
            if iid is None:iid=self.instance(st,n,c)
            st["equipped"][slot]=iid

    def aff_stats(self,obj):
        d=defaultdict(float)
        for a in obj["aff"]:
            for k,v in stat_attr(a["key"],a["value"]).items():d[k]+=v
        return dict(d)

    def roll_aff(self,name,rng,n=None):
        g=self.catalog[name]
        eligible=[]
        for row in self.pool:
            if not row or not row[1]:continue
            key=row[1]
            if key in ["攻击","魔法","道术"] and math.floor(pair(g.get(key))[1]/2)<1:continue
            eligible.append(row)
        nn=n if n else rng.choices([1,2,3,4,5,6,7,8],[.34,.26,.18,.10,.06,.03,.02,.01],k=1)[0]
        ret=[]
        for _ in range(nn):
            r=rng.choices(eligible,[float(x[3]) for x in eligible],k=1)[0]
            key=r[1]; ss=str(r[2]); upper=1
            if key in ["攻击","魔法","道术"]:
                upper=int(math.floor(pair(g.get(key))[1]/2)); val=rng.randint(1,upper)
            elif key=="攻击加成":
                low,upper=pair(ss);val=rng.randint(int(low),int(upper))
            else:
                val=float(re.findall(r"\d+(?:\.\d+)?",ss)[0])
            ret.append({"key":key,"value":val,"pool_index":r[0]})
        return ret

    def wash_score(self,obj):
        g=self.catalog[obj["name"]]; s=self.aff_stats(obj); raw=stats_from_gear(g)
        # Decision weight only; duplicated same-type attributes remain additive in final stats.
        atkbase=max(100,pair(g.get("攻击"))[1]*4)
        return (s.get("攻击上限",0)/atkbase*100 + .38*s.get("攻击加成",0) +
                .8*s.get("暴击几率",0)+1.0*s.get("致命几率",0)+1.5*s.get("伤害系数",0)+
                .45*s.get("处决概率",0)+.2*s.get("处决时间",0)+.1*s.get("处决倍率",0)+
                .04*s.get("韧性",0)+1.1*s.get("最大爆率",0)+.5*s.get("吸血",0)+
                .2*s.get("伤害吸收上限",0)+.35*s.get("攻击速度",0)+2*s.get("攻速突破",0))

    def wash(self,st,c,phase,extreme=False):
        if c<2:return
        normalbudget=[120,160,200,240,280,320,360,400,450][c-2]
        openbudget=[5,8,10,12,14,16,18,20,24][c-2]
        fraction=.4 if phase=="中期" else 1.
        targetn=round(normalbudget*fraction)*(3 if extreme else 1)
        targeto=round(openbudget*fraction)*(3 if extreme else 1)
        # Actual eligible slots are ordinary weapon/clothes/helmet/neck/wrists/rings/belt/boots.
        slots=[s for s in [1,0,4,3,5,6,7,8,10,11] if s in st["equipped"]]
        if not slots:return
        rng=random.Random(20260905+c*200+({"中期":1,"毕业":2}[phase])+(10000 if extreme else 0))
        extra=max(0,targetn-st["roll_counts"][c])
        for k in range(extra):
            slot=slots[k%len(slots)]
            mainid=st["equipped"][slot];main=st["inventory"][mainid];name=main["name"]
            eqids=set(st["equipped"].values())
            backs=[id for id,o in st["inventory"].items() if o["name"]==name and id not in eqids and not o["opened"]]
            bid=backs[0] if backs else self.instance(st,name,c)
            backup=st["inventory"][bid]
            tier=self.tiers[name];cost=tier[4];yuan=tier[6]
            backup["aff"]=self.roll_aff(name,rng)
            st["roll_counts"][c]+=1;st["wash_material"]+=cost
            self.pay(st,c,"普通洗练:"+name,0,yuan,{"失色锻造石":cost},note="洗备份本体，不回滚；按物品固定档"+str(tier[3]))
            if self.wash_score(backup)>self.wash_score(main):
                st["equipped"][slot]=bid
        # Open currently worn 7/8-line copies, overwrite in place (no magical keep-best).
        eligible=[s for s in slots if len(st["inventory"][st["equipped"][s]]["aff"]) in (7,8)]
        remaining=max(0,targeto-st["open_counts"][c])
        for k in range(remaining):
            if not eligible:break
            slot=eligible[k%len(eligible)]
            obj=st["inventory"][st["equipped"][slot]];name=obj["name"];n=len(obj["aff"])
            tier=self.tiers[name];cost=tier[5];yuan=tier[7]
            obj["opened"]=True;obj["aff"]=self.roll_aff(name,rng,n=n)
            st["open_counts"][c]+=1;st["wash_material"]+=cost
            self.pay(st,c,"开光重洗:"+name,0,yuan,{"失色锻造石":cost},
                     note="固定"+str(n)+"条，最终实际结果；不事后返回之前最佳词条")

    def progression(self,st,c,phase,extreme=False):
        targets=[0,50,80,110,140,170,195,220,240,255]
        prior=targets[c-2] if c>=2 else 0
        goal=targets[c-1] if phase=="毕业" else round((prior+targets[c-1])*.5)
        oldbody=st["body"]
        if goal>oldbody:
            selected=[r for r in self.i["body_cost_rows"] if oldbody<r[0]<=goal]
            bones=sum(r[3] for r in selected)
            gold=sum(r[4] for r in selected)
            yuan=sum(r[5] for r in selected)
            self.pay(st,c,f"神印{oldbody+1}—{goal}档",gold,yuan,{"野兽骨片":bones},
                     note="逐级读取神印255档原表，不用阶段总额近似")
        st["body"]=max(st["body"],goal)
        rbmax=0 if c<4 else (5 if c<6 else 10 if c<8 else 15 if c<10 else 20)
        if phase=="中期" and c in [4,6,8,10]:rbmax-=3
        for rr in self.d["rebirth"]:
            if st["rebirth"]<rr[0]<=rbmax:
                self.pay(st,c,rr[3],rr[5],rr[6],self.parse_mats(rr[4]))
        st["rebirth"]=max(st["rebirth"],rbmax)
        if c>=3 and st["title_c"]<c and phase=="中期":
            rr=self.costs[f"C{c:02d}-LONGTITLE"]
            self.pay(st,c,"贯穿称号:"+str(c),rr[8],rr[9],self.parse_mats(rr[7]))
            st["title_c"]=c
        # Concrete fate unlock schedule; prospective assumption only.
        slotgoal=[1,2,3,4,5,6,6,7,7,8][c-1]
        if st["fate_count"]<slotgoal:
            for slot in range(st["fate_count"]+1,slotgoal+1):
                if c<=2:self.pay(st,c,f"命格槽{slot}全彩",route="灵符",note="只对已解锁槽；灵符价格未知不编造")
                else:self.pay(st,c,f"命格槽{slot}全彩保底预算",0,500000,{"神秘符文":100},
                              note="延用全彩目标，100次保底预算；具体彩图选配是条件情景")
            st["fate_count"]=slotgoal
        # Story pages and collection IDs are discrete, never 0.75 of a permanent reward.
        for cc in range(1,c+1):
            groups=self.groups[cc]
            if extreme:complete=len(groups);front=len(groups)
            elif cc<c:complete=max(1,math.floor(len(groups)*.8));front=len(groups)
            else:complete=math.floor(len(groups)*(.3 if phase=="中期" else .6));front=math.ceil(len(groups)*(.55 if phase=="中期" else 1))
            for name,row in self.cols.items():
                if int(row[0][1:])!=cc:continue
                gi=groups.index(row[1])
                wanted=gi<complete or (gi<front and row[3]=="普通" and int(hashlib.sha1(name.encode()).hexdigest()[:4],16)%100<75)
                if wanted and name not in st["atlas"]:
                    self.consume(st,name,c);st["atlas"].add(name)
        for r in self.d["independent_titles"]:
            rc=int(r[1][1:])
            if r[0] not in st["independent"] and (rc<c or rc==c and phase=="毕业"):
                self.pay(st,c,r[2],r[9],r[10],self.parse_mats(r[8]))
                st["independent"].add(r[0])
        for r in self.d["collection_materials"]:
            rc=int(r[0][1:])
            if r[1] not in st["material_atlas"] and (rc<c or (extreme and rc==c)):
                self.pay(st,c,"材料图鉴:"+r[1],mats={r[1]:1})
                st["material_atlas"].add(r[1])
        # Original C2 task rewards (not user-modified rare title scrolls).
        qmax=0
        if c==2:qmax=2 if phase=="中期" else 4
        elif c>2:qmax=5
        for qr in self.i["c2_quests"][1:qmax+1]:
            if qr[2] not in st["quest_ids"]:
                st["quest_ids"].add(qr[2]);self.pay(st,c,"魂魄任务:"+qr[2],mats=self.parse_mats(qr[4]))
        # Skill progression without unverified premium shortcuts.
        desired=(3 if phase=="中期" else 6) if c==1 else (8 if c==2 and phase=="中期" else 9)
        old=st["skill_level"]
        if desired>old:
            # Three relevant basic offensive skills; no automatic 6x all skills.
            mats=3*sum(range(old+1,desired+1))*10
            yb=3*sum(range(old+1,desired+1))*10000
            self.pay(st,c,"三项主要基础技能",0,yb,{"技能残页":mats})
        st["skill_level"]=desired
        st["skills"]= (1.08 if phase=="中期" else 1.16) if c==1 else (1.25 if c==2 and phase=="中期" else 1.35)
        if extreme:st["skills"]=1.6
        if c==2 and phase=="毕业":
            for rr in [r for r in self.a["cost_rows_aux"] if "ADVSKILL" in r[0]][:3]:
                if rr[0] not in st["quest_ids"]:
                    self.pay(st,c,rr[6],rr[8],rr[9],self.parse_mats(rr[7]));st["quest_ids"].add(rr[0])
        # Each new equipped weapon must earn its own luck. No native luck and no free transfer.
        wid=st["equipped"].get(1)
        if wid:
            n=st["inventory"][wid]["name"]
            if wid not in st["weapon_blessed"]:
                st["weapon_blessed"].add(wid)
                st["inventory"][wid]["weapon_luck"]=7
            st["weapon_luck"]=7
        if c>=2 and 3 in st["equipped"] and st["neck_luck"]<8:
            rng=random.Random(20260905+c*31+(9 if extreme else 0)+(1 if phase=="中期" else 2))
            # C2中期先推进100次；C2毕业以及后续继续到人物幸运8。250/280是典型区间，不设装备换代重置。
            cap = st["neck_tries"] + (100 if phase=="中期" else 180 if c==2 else 80)
            actual=0
            while st["neck_luck"]<8 and st["neck_tries"]<cap:
                st["neck_tries"]+=1;actual+=1
                p=.024 if st["neck_tries"]<=250 else .2
                if rng.random()<p:st["neck_luck"]+=1
            # 半急速毕业人物如果仍未到8，继续按软保底推进直到8；这只增加实际尝试成本，不绑定当前项链。
            if phase=="毕业" and not extreme:
                while st["neck_luck"]<8:
                    st["neck_tries"]+=1;actual+=1
                    p=.024 if st["neck_tries"]<=250 else .2
                    if rng.random()<p:st["neck_luck"]+=1
            if actual:
                self.pay(st,c,"人物项链幸运进度",0,10000*actual,{"黄金树芽":actual},
                         note="人物永久进度；达到幸运8后以后换项链不重置、不重复付费")

    def source_rows(self,st,c,phase,extreme):
        out=[];meta={}
        equivlevel=40+(c-1)*10+(0 if phase=="入场" else 5 if phase=="中期" else 10)
        steps=(equivlevel-40)/10
        base={"攻击下限":7+2*steps,"攻击上限":13+5*steps,"HP":1000+400*steps,"MP":200+100*steps}
        out.append(self.src("人物自然","自然等级底板",base,"A01","模型假设"))
        out += [
            self.src("付费状态","第4档赞助",{"处决概率":10,"韧性":50,"爆率":600,"最大爆率":10,"伤害系数":10},"20260903总档"),
            self.src("付费状态","狂暴",{"攻击下限":50,"攻击上限":50,"魔法下限":50,"魔法上限":50,
                "道术下限":50,"道术上限":50,"HP":10000,"暴击几率":10},"20260903总档"),
            self.src("付费状态","沙城捐献",{"攻击下限":99,"攻击上限":99,"魔法下限":99,"魔法上限":99,
                "道术下限":99,"道术上限":99,"暴击几率":10,"爆率":100,"最大爆率":5},"20260903总档"),
        ]
        gphase=st["growth_phase"]; l=st["sword_level"]
        value=5*l if gphase==1 else 50+50*l
        sv={"攻击下限":value,"攻击上限":value,"魔法下限":value,"魔法上限":value,"道术下限":value,"道术上限":value}
        if gphase==1:sv["固定切割"]=5000
        else:sv["鞭尸"]=l
        out.append(self.src("成长装备","圣律之剑LV10" if gphase==1 else f"圣律真言LV{l}",sv,"20260903总档 / A04","原表＋支付路径假设", "占马牌15"))
        lv=st["relic_level"];v=5*lv if gphase==1 else 50+50*lv
        rv={k:v for k in ["攻击下限","攻击上限","魔法下限","魔法上限","道术下限","道术上限"]}
        if gphase==1:rv["每秒回血"]=2000
        else:rv["首刀斩杀"]=lv
        out.append(self.src("成长装备","黄金圣物LV10" if gphase==1 else f"黄金之心LV{lv}",rv,"20260903总档 / A04","原表＋支付路径假设","占军鼓14"))
        t=self.d["titles"][st["title_c"]-1]
        tv={k:t[3] for k in ["攻击下限","攻击上限","魔法下限","魔法上限","道术下限","道术上限"]}
        tv.update(HP=t[4],MP=t[5],爆率=t[6])
        out.append(self.src("贯穿称号",t[2],tv,"S04/01_贯穿称号","原表数值","只取当前阶段，不叠旧阶段"))
        b=st["body"];q=b*(b+1)/2
        bs={k:q for k in ["攻击下限","攻击上限","魔法下限","魔法上限","道术下限","道术上限"]};bs["HP"]=q*100
        out.append(self.src("神印",f"神印{b}档",bs,"S04 / 神印公式","自给进度假设＋原公式"))
        rbd=sum(r[7] for r in self.d["rebirth"] if r[0]<=st["rebirth"])
        out.append(self.src("转生",f"{st['rebirth']}转累计",{"神力增量":rbd},"S07/20转","原表累计"))
        for r in self.d["independent_titles"]:
            if r[0] in st["independent"]:
                tv={k:r[3] for k in ["攻击下限","攻击上限","魔法下限","魔法上限","道术下限","道术上限"]}
                tv.update(HP=r[4],神力增量=r[5],处决概率=r[6],韧性=r[7])
                out.append(self.src("独立称号",r[2],tv,"S04/02_独立称号"))
        # All registered items are discrete. Summarize each source category, retain full ID list separately.
        att=hp=0
        for name in st["atlas"]: att+=self.cols[name][8];hp+=self.cols[name][9]
        cs={k:att for k in ["攻击下限","攻击上限","魔法下限","魔法上限","道术下限","道术上限"]};cs["HP"]=hp
        out.append(self.src("单件图鉴",f"{len(st['atlas'])}件已登记",cs,"S07/collection_single","原表累计","完整名称见数据JSON/图鉴领取"))
        completed_pages=[]
        for r in self.d["collection_pages"]:
            names={name for name,cr in self.cols.items() if cr[0]==r[0] and cr[1]==r[1]}
            if names and names<=st["atlas"]:
                completed_pages.append(r[1])
                out.append(self.src("地图整页",r[0]+"/"+r[1],{"韧性":r[3],"处决概率":r[4],"神力增量":r[5]},"S07/collection_pages"))
        completed_conts=[]
        for r in self.d["collection_continents"]:
            names={n for n,cr in self.cols.items() if cr[0]==r[0]}
            if names and names<=st["atlas"]:
                completed_conts.append(r[0])
                out.append(self.src("大陆全收集",r[0],{"暴击几率":r[4]},"S07/collection_continents","原表累计","不得提前发27%"))
        for r in self.d["collection_materials"]:
            if r[1] in st["material_atlas"]:
                out.append(self.src("材料图鉴",r[1],{"神力增量":r[6],"处决概率":r[7],"韧性":r[8]},"S07/collection_materials"))
        # C1魂魄任务原件：每完成1图固定攻魔道+30、韧性+20；三图累计各+90、韧性+60。
        c1_done=min(3,sum(1 for pg in completed_pages if pg in self.groups[1]))
        c1q={"攻击下限":30*c1_done,"攻击上限":30*c1_done,"魔法下限":30*c1_done,"魔法上限":30*c1_done,
             "道术下限":30*c1_done,"道术上限":30*c1_done,"韧性":20*c1_done}
        out.append(self.src("旧任务","C1地图魂魄任务",c1q,"第一大陆_地图魂魄任务.txt","原件确认","每图+30攻魔道/+20韧性；不再使用+10韧性代理"))
        for qr in self.i["c2_quests"][1:]:
            if qr[2] in st["quest_ids"]:
                stat={"处决概率":2} if qr[0]==5 else {"韧性":20}
                out.append(self.src("旧任务","C2/"+qr[2],stat,"宁姆格福_完整怪物装备任务爆率规划/地图任务"))
        eqrows=[];affrows=[]
        for slot,iid in sorted(st["equipped"].items()):
            obj=st["inventory"][iid];g=self.catalog[obj["name"]];gm=self.meta[obj["name"]]
            out.append(self.src("装备",f"槽{slot}/{obj['name']}",stats_from_gear(g),gm["source"],"原表数值",f"实例{iid}"))
            aff=self.aff_stats(obj)
            if aff:out.append(self.src("洗练",f"槽{slot}/{obj['name']}",aff,"S06＋固定种子","可实现随机样本",f"{len(obj['aff'])}条；开光={obj['opened']}"))
            eqrows.append({"slot":slot,"instance":iid,"name":obj["name"],"part":g["部位"],
                "origin_c":gm["c"],"source":gm["source"],"type":gm["type"],"affixes":obj["aff"],
                "opened":obj["opened"],"neck_luck":0,
                "neck_tries":0,"weapon_luck":obj.get("weapon_luck",0) if slot==1 else 0})
            for j,af in enumerate(obj["aff"],1):
                affrows.append({"slot":slot,"name":obj["name"],"instance":iid,"line":j,**af})
        fi=self.extreme_fates if extreme else self.standard_fates
        fate_rows=[]
        for idx,fid in enumerate(fi[:st["fate_count"]],1):
            f=self.fates[fid]
            out.append(self.src("命格",f"第{idx}槽/{f['name']}",f["stats"],"S03/命格ID"+str(fid),"原表彩色＋选配假设"))
            fate_rows.append({"slot":idx,"id":fid,"name":f["name"],"quality":f["quality"],"stats":f["stats"]})
        wl=st["inventory"][st["equipped"][1]].get("weapon_luck",0) if 1 in st["equipped"] else 0
        nl=st["neck_luck"]
        out.append(self.src("后天幸运","主武器/人物项链幸运",{"武器幸运":wl,"项链幸运":nl},"A08","人物永久进度","项链幸运绑定人物；换项链不重置；武器幸运成本忽略"))
        # A total 50% economic scenario, not a new buff. Show source totals and difference.
        fate_recy=sum(s["stats"].get("回收增加",0) for s in out)
        out.append(self.src("回收预算","其余已定渠道预算",{"回收增加":max(0,50-fate_recy)},"用户总回收50%","经济输入，不是新增属性来源","不重复在命格回收后再加50%"))
        meta.update(equivalent_level=equivlevel,body=st["body"],rebirth=st["rebirth"],title_c=st["title_c"],
                    fate_count=st["fate_count"],sword_phase=gphase,sword_level=l,relic_level=lv,
                    completed_pages=completed_pages,completed_continents=completed_conts,
                    atlas=sorted(st["atlas"]),material_atlas=sorted(st["material_atlas"]),
                    ordinary_rolls=sum(st["roll_counts"].values()),open_rolls=sum(st["open_counts"].values()),
                    equipped_count=len(eqrows),skills=st["skills"],fates=fate_rows,affixes=affrows,gear=eqrows,
                    person_neck_luck=st["neck_luck"],person_neck_tries=st["neck_tries"])
        return out,meta

    def snapshot(self,st,c,phase,extreme=False):
        sources,meta=self.source_rows(st,c,phase,extreme)
        raw=sumstats(sources)
        aoe=0
        for r in self.d["aoe"]:
            if any(g["name"]==r[2] for g in meta["gear"]):aoe=r[6]
        der=derive(raw,st["skills"],aoe)
        code=f"C{c:02d}-"+{"入场":"E","中期":"M","毕业":"X" if extreme else "G"}[phase]
        flags=[]
        if der["有效吸收"]>.85:flags.append("吸收超过85%设计警戒")
        if raw["吸血"]>10:flags.append("角色吸血超10%；武器本体上限与人物总和分开")
        if raw["暴击几率"]>=100:flags.append("暴击已饱和")
        if raw["致命几率"]>=100:flags.append("致命已饱和")
        if der["有效攻速点"]>40:flags.append("41—49攻速使用插值")
        if c>=2:flags.append("C2成长装备灵符路线为假设")
        if extreme:flags.append("压力组合不是绝对极限；6件已修改追梦不强行冒充")
        return {"id":code,"c":c,"continent":self.d["titles"][c-1][1],"phase":PHASES[3] if extreme else {"入场":PHASES[0],"中期":PHASES[1],"毕业":PHASES[2]}[phase],
                "raw":raw,"derived":der,"meta":meta,"sources":sources,"aoe_interval":aoe,
                "payments":copy.deepcopy(st["payments"]),"required_materials":dict(st["materials"]),
                "required_gear_drops":dict(st["dropped"]),"gold_total":st["gold"],"yuan_total":st["yuan"],
                "flags":flags,"inventory_instances":copy.deepcopy(list(st["inventory"].values()))}
    def run(self):
        st=self.newstate();profiles=[]
        # Initial camp purchase complete before first map; no unrelated gear is conjured.
        self.pay(st,0,"初始营地已确认六项前期灵符状态",route="灵符",
                 note="用户实测总21765只作该次交易事实，不换算小时，不代表命格等所有后续开支")
        st["fate_count"]=1
        self.pay(st,0,"命格槽1全彩",route="灵符",note="本轮开槽节奏假设1槽；不伪造灵符金额")
        for c in range(1,11):
            if c==2:
                st["growth_phase"]=2;st["sword_level"]=10;st["relic_level"]=10;st["title_c"]=2
                self.pay(st,2,"第二阶段成长装备/称号升满",route="灵符",note="称号有灵符路径；圣律真言/黄金之心路径为A04假设")
                if st["fate_count"]<2:
                    st["fate_count"]=2;self.pay(st,2,"命格槽2全彩",route="灵符")
            profiles.append(self.snapshot(st,c,"入场"))
            for ph in ["中期","毕业"]:
                self.select_equipment(st,c,ph)
                self.wash(st,c,ph)
                self.progression(st,c,ph)
                profiles.append(self.snapshot(st,c,ph))
            hi=copy.deepcopy(st)
            self.select_equipment(hi,c,"毕业",extreme=True)
            self.wash(hi,c,"毕业",extreme=True)
            self.progression(hi,c,"毕业",extreme=True)
            profiles.append(self.snapshot(hi,c,"毕业",extreme=True))
        self.profiles=profiles
        return profiles

def main(directory=None):
    directory=Path(directory or Path(__file__).parent)
    inp=json.loads((directory/"source_inputs.json").read_text(encoding="utf8"))
    model=Model(inp);profiles=model.run()
    results={"schema":"half-speed-profile-v1.1","seed":20260905,"scope":"40 offline calculated profiles, not deployment or completed drops",
             "assumptions":ASSUMPTIONS,"attributes":ATTRS,"profiles":profiles,
             "catalog":model.catalog,"meta":model.meta,"sources":inp["source_registry"]}
    (directory/"40组半急速人物_完整数据.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf8")
    return model,results

if __name__=="__main__":
    import sys
    m,res=main(sys.argv[1] if len(sys.argv)>1 else None)
    print("profiles",len(res["profiles"]))
    for p in res["profiles"]:
        if p["phase"]=="半急速毕业":
            d=p["derived"]
            print(p["id"],round(d["面板攻击上限"]),round(d["HP"]),round(d["有效常规DPS"]),
                  round(d["有效爆率_主换算"],2))
