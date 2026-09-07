
"""Coarse pre-drop model. Values are design assumptions, not engine test results.
Use frozen sources; no network/production writes. python build.py; python verify.py
"""
from pathlib import Path
from collections import Counter, defaultdict
from itertools import combinations
import copy,json,math,statistics,hashlib
import source_adapter as A
import legacy_math as L
B=Path(__file__).resolve().parent
N=A.N; S=A.S; G=N["gear"]; M=N["monsters"]; MI={m["id"]:m for m in M}
RULES=json.loads((B/"rules.json").read_text())
MAPIN=json.loads((B/"inputs/map_registry.json").read_text())
PRO=[]; EVENTS=[]; SOURCES={}; GROUPS=[]; CONT=[]; CHECKS=[]; PROBES=[]
def check(kind,condition,detail=""):
    CHECKS.append({"kind":kind,"pass":bool(condition),"detail":detail})
def round_design(v, sig=2):
    if v<=0:return 0
    unit=10**max(0,int(math.floor(math.log10(v)))-sig+1)
    return max(1,int(round(v/unit)*unit))
def approx(raw):
    d=L.derive(raw,skill=1,aoe_interval=0)
    d["纯属性DPS"]=d["有效常规DPS"]
    d["技能效率DPS"]=d["纯属性DPS"]*RULES["skill_efficiency"]
    d["吸血HPS"]=d["吸血理论上限每秒"]*RULES["leech_skill_factor"]
    d["总回复HPS"]=d["吸血HPS"]+raw["每秒回血"]
    return d
def gear_delta(e):
    d=L.stats_from_gear(G[e["name"]])
    for a in e.get("affixes",[]):
        for k,v in L.stat_attr(a["attribute"],a["value"]).items():d[k]=d.get(k,0)+v
    return d
def replace_options(raw0,gear0,names):
    """No permanent gains, collection, currency or wash in the ordinary-only probe."""
    raw=dict(raw0);gear=copy.deepcopy(gear0);changes=[]
    for n in sorted(names,key=lambda n:(A.merit(n),n)):
        for sid in A.slots(n):
            old=next((e for e in gear if e["slot"]==sid),None)
            if old and old["name"]==n:continue
            trial=dict(raw)
            if old:
                for k,v in gear_delta(old).items():trial[k]-=v
            new={"slot":sid,"name":n,"instance":f"{sid}:{n}","affixes":[],"rolls":0}
            for k,v in gear_delta(new).items():trial[k]+=v
            before=approx(raw);after=approx(trial)
            # Refuse hidden pure-output downgrades; defense can be chosen if output nearly unchanged.
            gain=after["技能效率DPS"]/max(1,before["技能效率DPS"])
            ehpgain=after["等效HP不计防御"]/max(1,before["等效HP不计防御"])
            if n in A.AOE:
                if old and old['name'] in A.AOE and A.RE[A.CR[old['name']]['id']]['c'] >= A.RE[A.CR[n]['id']]['c']:continue
            elif old and old['name'] in A.AOE:continue
            elif old and not (gain**.65*ehpgain**.35>=1.003 and gain>=.94 and ehpgain>=.80):continue
            raw=trial
            if old:gear.remove(old)
            gear.append(new);changes.append({"slot":sid,"old":old["name"] if old else None,"new":n})
    return raw,gear,changes
class State(A.State):
    def __init__(self):
        super().__init__(); self.fates=A.FATE_ORDER[:2]
    def wear_candidates(self,names):
        raw=A.sumstats([s["stats"] for s in self.sources()])
        _,newgear,changes=replace_options(raw,list(self.gear.values()),names)
        for change in changes:
            sid=change["slot"];n=change["new"];key=f"{sid}:{n}"
            if key not in self.instances:
                if self.stock[n]<1:self.acquire(n,reason="穿戴独立实物")
                self.stock[n]-=1
                self.instances[key]={"instance":key,"name":n,"slot":sid,"affixes":[],"rolls":0}
            self.gear[sid]=self.instances[key]
            self.log("换装",n,slot=sid,replaced=change["old"],instance=key)
def snap(st,label,kind):
    ss=st.sources(); refs=[]
    for s in ss:
        key="S"+hashlib.sha256(json.dumps(s,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
        SOURCES[key]=s;refs.append(key)
    raw=A.sumstats([s["stats"] for s in ss]);id=f"P{len(PRO)+1:04d}"
    p={"id":id,"parent":st.last,"c":st.c,"gi":st.gi,"label":label,"kind":kind,"branch":st.branch,
       "raw":raw,"derived":approx(raw),"sources":refs,"gear":copy.deepcopy(list(st.gear.values())),
       "atlas":sorted(st.atlas),"made":sorted(st.made),"paid":sorted(st.paid),"quests":sorted(st.quests),
       "dead":sorted(st.dead),"title":st.title,"body":st.body,"turn":st.turn,"fates":list(st.fates),
       "neck":st.neck,"skills":dict(st.skills),"spent":dict(st.spent),"completion":st.completion(),
       "factor_skill":RULES["skill_efficiency"],"factor_leech":RULES["leech_skill_factor"]}
    check("同名命格不重复",len(set(st.fates))==len(st.fates),id)
    check("人物幸运不超过8",0<=st.neck<=8,id)
    PRO.append(p);st.last=id;return p
def ordinary_probe(st,ns):
    raw=A.sumstats([s["stats"] for s in st.sources()]);gear=list(st.gear.values())
    result=[]
    ks=sorted(set([max(1,math.ceil(len(ns)*.5)),max(1,math.floor(len(ns)*.7))]))
    for k in ks:
        for sub in combinations(ns,k):
            rr,gg,chg=replace_options(raw,gear,sub)
            dd=approx(rr)
            result.append({"names":list(sub),"fraction":k/len(ns),"dps":dd["技能效率DPS"],
                           "ehp":dd["等效HP不计防御"],"changed":chg,"raw":rr})
    target=max(1,round(len(ns)*.6))
    near=[r for r in result if len(r["names"])==target] or result
    near.sort(key=lambda r:(r["dps"]**.65*r["ehp"]**.35,r["names"]))
    return result,near[len(near)//2]
def build_route():
    st=State();st.grow(0)
    # Newbie set: explicit model baseline, not a new server grant.
    for r in S["c1"]["装备导入表"][1:9]:
        n=r[0]
        for sid in A.slots(n):
            e={"instance":f"{sid}:{n}","name":n,"slot":sid,"affixes":[],"rolls":0}
            st.gear[sid]=e;st.instances[e["instance"]]=e
    st.log("基线假设","起步制式一套",note="只作模型起点，不修改发放脚本")
    lastpost=None;optional_events=[]
    for c in range(1,11):
        st.c=c;st.gi=0
        inherited=snap(st,f"C{c:02d}入场继承","大陆入场")
        if lastpost:
            check("跨大陆永久与穿戴继承",all(inherited[k]==lastpost[k] for k in ("raw","gear","atlas","spent","neck")),str(c))
        st.grow(0)
        paid=snap(st,f"C{c:02d}本阶段既有付费/长期成长","阶段更新")
        ng=len(N["groups"][str(c)]);lastordinary=None;local=[inherited,paid]
        for gi,g in enumerate(N["groups"][str(c)]):
            st.gi=gi
            ent=snap(st,f"C{c:02d}G{gi+1:02d}入场","地图组入场")
            mons=[m for m in M if m["c"]==c and m["group_index"]==gi and m["role"]!="守关BOSS"]
            normal=[m for m in mons if m["role"]=="普通"];rare=[m for m in mons if m["role"]=="稀有"];boss=[m for m in mons if m["role"]=="地图BOSS"]
            ns=[n for m in normal for n in m["items"]]
            samples,chosen=ordinary_probe(st,ns)
            # This transition adds ONLY actual gear pieces from ordinary monsters.
            for m in normal:st.dead.add(m["id"]);st.log("普通来源可挑战",m["id"])
            for n in chosen["names"]:
                if st.stock[n]<1:st.acquire(n,reason="普通专属50-70%独立取得")
            st.wear_candidates(chosen["names"])
            normal60=snap(st,f"C{c:02d}G{gi+1:02d}普通专属{len(chosen['names'])}/{len(ns)}","普通专属换装")
            unchanged=all(normal60[k]==ent[k] for k in ("atlas","made","paid","quests","title","body","turn","fates","neck","skills"))
            check("普通50-70%不夹带永久成长",unchanged,normal60["id"])
            check("普通取得比例",.5<=len(chosen["names"])/len(ns)<=.7,normal60["id"])
            PROBES.append({"c":c,"gi":gi,"group":g,"entry":ent["id"],"after":normal60["id"],
                           "candidate_names":ns,"selected":chosen["names"],"changed":chosen["changed"],
                           "fraction":chosen["fraction"],
                           "gain_min":min(r["dps"] for r in samples)/ent["derived"]["技能效率DPS"],
                           "gain_median":statistics.median(r["dps"] for r in samples)/ent["derived"]["技能效率DPS"],
                           "gain_max":max(r["dps"] for r in samples)/ent["derived"]["技能效率DPS"]})
            # Optional rare/map-boss progression and deterministic crafts remain separate from ordinary benchmark.
            preboss={}
            for m in rare:st.dead.add(m["id"]);st.log("稀有来源可挑战",m["id"])
            if c==1 and gi>=1:st.fates=A.FATE_ORDER[:3]
            st.grow((gi+.5)/ng)
            for m in boss:
                bp=snap(st,m["name"]+"挑战前","地图BOSS挑战")
                preboss[m["id"]]=bp["id"]
                st.dead.add(m["id"]);st.log("地图BOSS条件击杀",m["id"],note="独立于大陆守关")
                # No guarantee of boss equipment worn; a comparison fast-lane snapshot is separate.
            fast=copy.deepcopy(st);fast.branch=f"C{c:02d}G{gi+1:02d}BOSS强装对照"
            fast.wear_candidates([n for m in boss for n in m["items"]])
            fastp=snap(fast,g+"BOSS装备快线","BOSS强装对照")
            optional_events.extend(fast.events[len(st.events):])
            st.finish_available()   # recipes may use materials/bases from map bosses; no gate materials
            # Small optional collections are never conditions for moving between groups.
            feasible=sorted([n for n in A.COL if A.META[n]["c"]==c and A.META[n]["gi"]<=gi and st.can(n)],
                            key=lambda n:(A.META[n]["gi"],n))
            limit=int(sum(A.META[n]["c"]==c for n in A.COL)*.12*(gi+1)/ng)
            for n in feasible:
                if sum(A.META[x]["c"]==c for x in st.atlas)>=limit:break
                st.register(n)
            done=snap(st,g+"阶段积累后","地图组完成")
            ref=ent if gi==0 else lastordinary
            GROUPS.append({"c":c,"gi":gi,"group":g,"entry":ent["id"],"ordinary":normal60["id"],
                           "done":done["id"],"boss_fast":fastp["id"],"calibration":ref["id"],
                           "preboss":preboss,"normal_pool":ns,"selected":chosen["names"]})
            lastordinary=normal60;local += [ent,normal60,done]
        st.grow(.9);st.finish_available()
        pre=snap(st,f"C{c:02d}守关前必做制作完成","守关准备")
        local.append(pre)
        remain=sorted([n for n in A.COL if A.META[n]["c"]==c and n not in st.atlas and st.can(n)],
                      key=lambda n:(A.META[n]["gi"],n))
        while remain and st.completion()["score"]<70:st.register(remain.pop(0))
        p70=snap(st,f"C{c:02d}约70%守关参考","守关70")
        p50=min(local,key=lambda p:abs(p["completion"]["score"]-50))
        rich=copy.deepcopy(st);rich.branch=f"C{c:02d}高完成度"
        for n in remain:
            if rich.completion()["score"]>=90:break
            rich.register(n)
        # 90 branch may choose more available ordinary/rare gear but never current gate drops.
        rich.wear_candidates([n for m in M if m["c"]==c and m["role"]!="守关BOSS" for n in m["items"]])
        rich.grow(1)
        p90=snap(rich,f"C{c:02d}高完成度参考","守关90")
        optional_events.extend(rich.events[len(st.events):])
        gate=next(m for m in M if m["c"]==c and m["role"]=="守关BOSS")
        check("守关前必做合成齐全",all(n in st.made for n,r in A.CR.items() if r["c"]==c),str(c))
        check("首次挑战未取得本守关装备",not any(e["name"] in gate["items"] for e in p70["gear"]),gate["name"])
        st.dead.add(gate["id"]);st.log("守关击杀放行",gate["id"],note="唯一跨大陆硬门槛；不查70%分数")
        st.finish_available()
        if c in (2,3,5,7,9):st.fates=A.FATE_ORDER[:min(8,len(st.fates)+1)]
        lastpost=snap(st,f"C{c:02d}守关后继承","守关后")
        CONT.append({"c":c,"entry":inherited["id"],"p50":p50["id"],"p70":p70["id"],"p90":p90["id"],"post":lastpost["id"],"gate":gate["id"]})
    EVENTS.extend(st.events+optional_events)

def exec_factor(points, rate, extra_time=0, extra_mult=0):
    points=max(0,min(100,points))
    if points<=0:return 1.
    prob=points/100
    dur=1+.2*max(0,points-1)+extra_time
    coverage=1-(1-prob)**max(1,rate*dur)
    return 1+coverage*(1+.2*points+extra_mult/100)
def attack_output(p, defense, exec_req, include_execution=True):
    r=p["raw"];d=p["derived"];at=d["期望攻击取值"]
    armor=max(.05,1-defense/max(1,at))
    # Armor hits ordinary damage, not flat cutting.
    ordinary=d["暴致命期望单刀"]*d["刀每秒"]*.95*.8
    cutting=r["固定切割"]*d["刀每秒"]*.95*.8
    f=exec_factor(d["处决总概率百分点"]-exec_req,d["刀每秒"]*.95,r["处决时间"],r["处决倍率"]) if include_execution else 1.
    return (ordinary*armor*f+cutting)*RULES["skill_efficiency"]
def defense_stats(p,req,interval=1.8,attackers=1):
    r=p["raw"];d=p["derived"]
    f=exec_factor(req-r["韧性"],attackers/interval)
    defense=(r["防御下限"]+r["防御上限"])/2
    return f,defense,d["有效吸收"]
def health_budget(p,ttk,role,c):
    hp=p["derived"]["HP"];heal=p["derived"]["总回复HPS"]
    if c==1:
        if role=="守关BOSS":
            # First-continent guardian keeps low ordinary hit pressure but tests missing toughness.
            return heal*.82+hp/(max(20,ttk)*5)
        return (heal*.22+hp/(max(10,ttk)*12))*RULES["c1_damage_multiplier"]
    if role=="守关BOSS":return heal*.85+hp/(max(20,ttk)*1.6)
    if role=="地图BOSS":return heal*.8+hp/(max(20,ttk)*2.0)
    if role=="稀有":return heal*.50+hp/(max(10,ttk)*6)
    # per-monster damage; 4 active attackers in a sustained swarm
    return heal*.14+hp/(max(5,ttk)*24)
def eval_survival(pp,dc,dcmax,req,interval,ttk):
    f,d,a=defense_stats(pp,req,interval)
    taken=max(1,(dc+dcmax)/2-d)*(1-a)/interval*f
    heal=pp["derived"]["总回复HPS"]
    hp=pp["derived"]["HP"]
    net=taken-heal
    survive=hp/net if net>0 else None
    deficit=max(0,min(100,req-pp["raw"]["韧性"]))
    probability=deficit/100
    event_multiplier=2+.2*deficit if probability else 1
    peak=max(1,dcmax-d)*(1-a)*event_multiplier
    ordinary_peak=max(1,dcmax-d)*(1-a)
    # Mean waiting time to a potentially lethal execution proc; not a claimed exact win probability.
    if ordinary_peak>=hp: survive=min(survive or interval,interval)
    elif probability and peak>=hp:
        wait=interval/probability
        survive=min(survive or wait,wait)
    return {"damage_in":taken,"heal_hps":heal,"survive_s":survive,
            "margin_hp":hp+(heal-taken)*ttk,"highest_single_hit":peak,
            "ordinary_single_hit":ordinary_peak,"lethal_proc_risk":bool(probability and peak>=hp),
            "approx_win":survive is None or survive>=ttk}
def preclear_possible(name,c,seen=()):
    if name in seen:return False
    if name in A.CR:
        rec=A.CR[name]
        return rec["c"]<=c and all(preclear_possible(n,c,seen+(name,)) for n in list(rec["bases"])+list(rec["materials"]))
    if name=="失色锻造石":return any(m["c"]<=c and m["role"]!="守关BOSS" for m in M)
    sources=N["item_sources"].get(name,N["material_sources"].get(name,[]))
    return any(s not in MI or (MI[s]["c"]<=c and (MI[s]["c"]<c or MI[s]["role"]!="守关BOSS")) for s in sources)
def run():
    build_route()
    P={p["id"]:p for p in PRO};GR={(g["c"],g["gi"]):g for g in GROUPS};CO={r["c"]:r for r in CONT}
    configs=[]
    for x in MAPIN["map_configs"]:
        c=x["c"];gi=N["groups"][str(c)].index(x["group"]);g=GR[c,gi];p=P[g["calibration"]]
        base_t=P[g["entry"]]["raw"]["韧性"]
        # C1 low attack, not paper HP. No artificial C1 toughness wall.
        if c==1:req=5*math.floor(max(0,base_t-10+5*gi)/5)
        else:
            req=5*math.floor((base_t-5+8*gi)/5)
        gate=next((MI[i] for i in x["residents"] if MI[i]["role"]=="守关BOSS"),None)
        exec_req=max(0,round(p["derived"]["处决总概率百分点"]-6,1))
        if gate:
            gp=P[CO[c]["p70"]]
            req=5*math.floor((gp["raw"]["韧性"]-5)/5)
            exec_req=max(0,round(gp["derived"]["处决总概率百分点"]-5,1))
        configs.append({**x,"韧性要求":max(0,req),"处决要求":exec_req,
                        "note":"地图共享；韧性不足只提高受处决概率/额外承伤，不自动造成眩晕或停手",
                        "status":"设计值，真实字段由平台映射"})
    CF={x["map_key"]:x for x in configs}
    PL=defaultdict(list)
    for x in MAPIN["placements"]:PL[x["monster"]].append(x["map_key"])
    monsters=[]; encounters=[];gatechecks=[]; groupsummary=[]
    source_appr={r[1]:r[8] for r in S["source2"]["地图与怪物"][4:] if r[1]}
    for m in M:
        c=m["c"];g=GR[c,m["group_index"]];role=m["role"];maps=PL[m["id"]]
        cf=max((CF[k] for k in maps),key=lambda q:q["韧性要求"])
        if role=="守关BOSS":p=P[CO[c]["p70"]];ttk=RULES["gate_seconds"][c-1]
        elif role=="地图BOSS":p=P[g["preboss"][m["id"]]];ttk=RULES["map_boss_seconds"]
        else:p=P[g["calibration"]];ttk=RULES["normal_seconds"] if role=="普通" else RULES["rare_seconds"]
        # ±15% role flavor; no per-continent HP multiplication.
        jitter=[.9,1,1.1,1.15,.95][int(hashlib.sha256(m["id"].encode()).hexdigest()[:3],16)%5]
        if role=="守关BOSS":jitter=1.
        tt=ttk*jitter
        defense=round_design(p["derived"]["期望攻击取值"]*RULES["roles"][role])
        # Ordinary-map HP excludes map execution from calibration; execution remains an extra player benefit.
        offense=attack_output(p,defense,cf["处决要求"],include_execution=(role in ("地图BOSS","守关BOSS")))
        hp=round_design(offense*tt)
        interval={"普通":1.6,"稀有":1.7,"地图BOSS":1.8,"守关BOSS":2.0}[role]
        actual_t=hp/max(1,attack_output(p,defense,cf["处决要求"]))
        incoming=health_budget(p,actual_t,role,c)
        # The survivable reference must not be killed by one ordinary hit before leech can act.
        hitcap={"普通":.08,"稀有":.15,"地图BOSS":.22,"守关BOSS":.32}[role]
        incoming=min(incoming,p["derived"]["HP"]*hitcap/interval)
        f,d,a=defense_stats(p,cf["韧性要求"],interval)
        mean=max(1,incoming*interval/max(.01,(1-a)*f)+d)
        dc=round_design(mean*.85);dcmax=round_design(mean*1.15)
        minlvl=20+(c-1)*30+m["group_index"]*3
        exp=round_design((60+40*c+15*m["group_index"])*({"普通":1,"稀有":3,"地图BOSS":12,"守关BOSS":30}[role]))
        row={**m,"HP":hp,"DC":dc,"DCMAX":dcmax,"AC":defense,"MAC":round_design(defense*.85),"Lvl":minlvl,
             "Exp":exp,"attack_interval_ms":int(interval*1000),"reference":p["id"],"target_ttk":tt,"design_dps":offense,
             "Appr":source_appr.get(m["id"]),"drop_probability":None,"maps":maps,
             "runtime_numeric_range":"64位值核对" if max(hp,dcmax,exp)>2147483647 else "32位有符号内",
             "note":"怪物设计属性；不把攻击间隔毫秒直接写成SPEED；无物品爆率"}
        monsters.append(row)
        for key in maps:
            q=CF[key]
            dps=attack_output(p,defense,q["处决要求"])
            t=hp/max(1,dps)
            survival=eval_survival(p,dc,dcmax,q["韧性要求"],interval,t)
            encounters.append({"monster":m["id"],"name":m["name"],"map":key,"role":role,"reference":p["id"],
                               "ttk":t,"toughness_gap":p["raw"]["韧性"]-q["韧性要求"],**survival})
        if role=="守关BOSS":
            for kind in ["p50","p70","p90"]:
                pp=P[CO[c][kind]];q=cf
                t=hp/attack_output(pp,defense,q["处决要求"])
                ev=eval_survival(pp,dc,dcmax,q["韧性要求"],interval,t)
                gatechecks.append({"c":c,"gate":m["name"],"case":kind,"profile":pp["id"],"completion":pp["completion"]["score"],
                                   "toughness_gap":pp["raw"]["韧性"]-q["韧性要求"],"ttk":t,
                                   "survival_seconds":ev["survive_s"],"win":ev["approx_win"],"HP":hp,
                                   "peak_hit_to_player":ev["highest_single_hit"],"player_hp":pp["derived"]["HP"],
                                   "execution_onehit_risk":ev["lethal_proc_risk"]})
            for deficit in [0,10,25]:
                pp=copy.deepcopy(p);pp["raw"]["韧性"]=cf["韧性要求"]-deficit
                t=hp/attack_output(pp,defense,cf["处决要求"])
                ev=eval_survival(pp,dc,dcmax,cf["韧性要求"],interval,t)
                gatechecks.append({"c":c,"gate":m["name"],"case":f"仅缺韧性{deficit}","profile":p["id"],"completion":p["completion"]["score"],
                                   "toughness_gap":-deficit,"ttk":t,"survival_seconds":ev["survive_s"],
                                   "win":ev["approx_win"],"HP":hp,
                                   "peak_hit_to_player":ev["highest_single_hit"],"player_hp":pp["derived"]["HP"],
                                   "execution_onehit_risk":ev["lethal_proc_risk"]})
    # Group transition checks: don't fake "hard without gear" if approved ordinary gear adds little.
    MM={m["id"]:m for m in monsters}
    for g,probe in zip(GROUPS,PROBES):
        c=g["c"];gi=g["gi"];p=P[g["entry"]];pa=P[g["ordinary"]]
        normals=[m for m in monsters if m["c"]==c and m["group_index"]==gi and m["role"]=="普通"]
        targethp=statistics.median(m["HP"] for m in normals)
        ac=statistics.median(m["AC"] for m in normals)
        base=attack_output(p,ac,0,False)
        if gi+1<len(N["groups"][str(c)]):
            nn=[m for m in monsters if m["c"]==c and m["group_index"]==gi+1 and m["role"]=="普通"]
            nhp=statistics.median(m["HP"] for m in nn);nac=statistics.median(m["AC"] for m in nn)
            naked=nhp/attack_output(p,nac,0,False);upgraded=nhp/attack_output(pa,nac,0,False)
            ratio=naked/max(.001,upgraded)
            statement="跳图压力明确" if ratio>=1.2 else "已持强装/普通提升有限；不强造额外门槛"
        else:naked=upgraded=ratio=None;statement="末组，转入守关70%基准"
        groupsummary.append({**g,"普通池数量":len(g["normal_pool"]),"取得种数":len(g["selected"]),
                             "普通换装DPS提升":pa["derived"]["技能效率DPS"]/p["derived"]["技能效率DPS"],
                             "本组入场普通TTK":targethp/max(1,base),"裸跳下一组TTK":naked,
                             "普通60后下一组TTK":upgraded,"裸跳相对压力":ratio,"结论":statement,
                             "随机组合收益范围":[probe["gain_min"],probe["gain_max"]]})
    # Source plan with no probability; somber only dismantling.
    droprows=[]
    for m in M:
        for name in m["items"]:
            droprows.append({"monster":m["id"],"c":m["c"],"pool":"自身专属","item":name,"quantity":1,"probability":None})
        if m["role"] in ("地图BOSS","守关BOSS"):
            # Only same-real-map normal monsters, not whole continent.
            commons={n for other in M if other["role"]=="普通" and set(PL[other["id"]])&set(PL[m["id"]]) for n in other["items"]}
            for name in sorted(commons):
                droprows.append({"monster":m["id"],"c":m["c"],"pool":"本图普通兼掉候选","item":name,"quantity":1,"probability":None})
        for mat,ids in N["material_sources"].items():
            if m["id"] not in ids or mat=="失色锻造石":continue
            cat=N["material_catalog"].get(mat,{}).get("类别","")
            q=1
            if "通用" in cat or mat in ["海蚀铁片","风暴石片","风蚀铁片","湖盐结晶","辉石碎晶","猩红矿渣","冻晶尘","霜脊铁","黄金叶脉","王城金屑"]:q={"普通":8,"稀有":15,"地图BOSS":30,"守关BOSS":40}[m["role"]]
            elif "证物" in cat or "征物" in cat:q=1
            elif "印记" in cat:q=1
            droprows.append({"monster":m["id"],"c":m["c"],"pool":"材料独立候选","item":mat,"quantity":q,"probability":None})
        if m["c"]>=2:droprows.append({"monster":m["id"],"c":m["c"],"pool":"六神器公共池","item":"引用既有6神器池（非新增物品）","quantity":1,"probability":None})
    # Add old set candidates without changing any rate; one roll yields one item from the indicated group.
    for m in M:
        if m["c"]<=2:
            offset=0 if m['c']==1 else 10
            ng=len(N['groups'][str(m['c'])]);j=m['group_index']
            low=offset+max(1,1+math.floor(j*10/ng))
            tier=offset+min(10,math.ceil((j+1)*10/ng))
            droprows.append({"monster":m["id"],"c":m["c"],"pool":"制式独立候选","item":f"引用制式第{low}-{tier}套池","quantity":1,"probability":None,"set_min":low,"set_max":tier})
    # Independent integrity checks.
    check("561怪唯一",len(monsters)==561 and len(set(m["id"] for m in monsters))==561)
    check("地图BOSS92",sum(m["role"]=="地图BOSS" for m in monsters)==92)
    check("每大陆唯一守关",all(sum(m["role"]=="守关BOSS" and m["c"]==c for m in monsters)==1 for c in range(1,11)))
    check("46组唯一",len(groupsummary)==46 and len(set((g["c"],g["gi"]) for g in groupsummary))==46)
    check("地图配置唯一",len(CF)==len(configs))
    check("所有落点共用地图配置",all(k in CF for m in monsters for k in m["maps"]))
    check("无失色直接掉落",not any(r["item"]=="失色锻造石" for r in droprows))
    check("所有概率留空",all(r["probability"] is None for r in droprows))
    check("所有怪物数值正数",all(m[k]>0 and isinstance(m[k],int) for m in monsters for k in ["HP","DC","DCMAX","AC","MAC","Lvl","Exp","attack_interval_ms"]))
    check("C1只调低攻击系数",RULES["c1_damage_multiplier"]<1 and "c1_hp_multiplier" not in RULES)
    for r in N["dependency_audit"]:
        check("递归首杀前存在可达来源",preclear_possible(r["name"],r["c"]),r["recipe"]+":"+r["name"])
    for g in groupsummary:
        check("普通换装恢复下一组时间粗校验",
              g["普通60后下一组TTK"] is None or 4<=g["普通60后下一组TTK"]<=16,
              g["group"])
    for e in encounters:
        pp=P[e["reference"]]
        check("基准人物可承受普通单击",e["ordinary_single_hit"]<pp["derived"]["HP"],e["monster"]+":"+e["map"])
    check("装备源引用当前补丁版",G==json.loads((B/"inputs/normalized_current.json").read_text())["gear"])

    result={"rules":RULES,"profiles":PRO,"sources":SOURCES,"events":EVENTS,"groups":groupsummary,
            "continent_refs":CONT,"probes":PROBES,"monsters":monsters,"maps":configs,"placements":MAPIN["placements"],
            "encounters":encounters,"gate_checks":gatechecks,"drop_content":droprows,"checks":CHECKS,
            "recipes":N["recipes"],"quests":N["quests"],"gear":G,"material_prices":N["material_prices"],
            "shared_gate_maps":MAPIN["shared_guard_maps"],
            "calibration_note":"设计定稿：普通装备分支负责稳定推进，实际主线持有BOSS/必做合成时允许提前越图。单一20%差异不再作为冻结条件。",
            "summary":{"profiles":len(PRO),"monsters":len(monsters),"maps":len(configs),"groups":len(groupsummary),
                       "ordinary_edges":sum(g["裸跳相对压力"] is not None for g in groupsummary),
                       "edges_clear":sum(g["裸跳相对压力"] is not None and g["裸跳相对压力"]>=1.2 for g in groupsummary),
                       "gate70_pass":sum(x["case"]=="p70" and x["win"] for x in gatechecks),
                       "weak25_fail":sum(x["case"]=="仅缺韧性25" and not x["win"] for x in gatechecks),
                       "shared_map_encounters_pass":sum(e["approx_win"] for e in encounters),
                       "checks":len(CHECKS),"check_failures":sum(not x["pass"] for x in CHECKS)}}
    (B/"results").mkdir(exist_ok=True)
    (B/"results/final.json").write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print(json.dumps(result["summary"],ensure_ascii=False,indent=2))
if __name__=="__main__":run()
