from collections import defaultdict
import math,re


ATTRS = [
"攻击下限","攻击上限","魔法下限","魔法上限","道术下限","道术上限",
"HP","MP","防御下限","防御上限","魔御下限","魔御上限",
"攻击加成","魔法加成","道术加成","神力增量","伤害系数","打怪伤害","攻击伤害",
"暴击几率","暴击伤害","致命几率","致命伤害","固定切割","每秒回血","攻击速度","攻速突破","准确",
"武器幸运","项链幸运","处决概率","处决倍率","处决时间","韧性","对怪伤害吸收",
"伤害吸收上限","吸血","爆率","最大爆率","人物爆率","鞭尸","首刀斩杀","尾刀斩杀","HP百分比","回收增加"
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
        mult=2+.2*ep*100+raw["处决倍率"]/100 if ep>0 else 1
        n=max(0,int(math.floor(dur*rate*hit)))
        cov=1-(1-ep)**n if ep>0 else 0
        fact=1+cov*(mult-1)
        # Only ordinary portion benefits in this hypothetical sustained-window model.
        out[f"处决{resist}_有效概率"]=ep;out[f"处决{resist}_覆盖率"]=cov
        out[f"处决{resist}_窗口倍率"]=mult;out[f"处决{resist}_秒"]=dur
        out[f"处决{resist}_长战DPS"]=((expected*skill*fact+cut)*rate*hit+aoe_dps)*uptime
    return out