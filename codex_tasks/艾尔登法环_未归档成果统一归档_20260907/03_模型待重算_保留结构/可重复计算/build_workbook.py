
from __future__ import annotations
import json,math,hashlib
from pathlib import Path
from collections import defaultdict,Counter
from artifact_tool import Workbook,SpreadsheetFile

BASE=Path(__file__).resolve().parent
D=json.loads((BASE/"40组半急速人物_完整数据.json").read_text(encoding="utf-8"))
PS=D["profiles"]; AF=D["attributes"]
def xl(n):
    out=""
    while n:
        n,r=divmod(n-1,26);out=chr(65+r)+out
    return out
TITLE={"fill":"#17365D","font":{"bold":True,"color":"#FFFFFF","size":16},
       "vertical_alignment":"center"}
SUB={"fill":"#EAF0F6","font":{"color":"#38516B","size":10},
     "wrap_text":True,"vertical_alignment":"center"}
HEAD={"fill":"#2D567C","font":{"bold":True,"color":"#FFFFFF","size":10},
      "wrap_text":True,"vertical_alignment":"center"}
BODY={"font":{"size":10},"vertical_alignment":"center"}
wb=Workbook.create()
wb.worksheets.add('00_结果导览')
def sheet(name,title,subtitle,headers,rows,widths=None,freeze=3):
    s=wb.worksheets.get_item(name) if name=="00_结果导览" else wb.worksheets.add(name)
    end=xl(len(headers))
    s.merge_cells(f"A1:{end}1");s.get_range("A1").values=[[title]]
    s.get_range(f"A1:{end}1").format=TITLE;s.get_range("A1").format.row_height=29
    s.merge_cells(f"A2:{end}2");s.get_range("A2").values=[[subtitle]]
    s.get_range(f"A2:{end}2").format=SUB;s.get_range("A2").format.row_height=43
    s.get_range(f"A4:{end}4").values=[headers];s.get_range(f"A4:{end}4").format=HEAD
    s.get_range(f"A4:{end}4").format.row_height=42
    if rows:
        s.get_range(f"A5:{end}{4+len(rows)}").values=rows
        s.get_range(f"A5:{end}{4+len(rows)}").format=BODY
        # Large audit ranges use frozen headers; avoid redundant Excel table objects.
    s.freeze_panes.freeze_rows(4)
    if freeze:s.freeze_panes.freeze_columns(freeze)
    s.get_range(f"A:{end}").format.column_width=14
    if widths:
        for i,w in enumerate(widths,1):
            s.get_range(f"{xl(i)}:{xl(i)}").format.column_width=w
    s.show_grid_lines=False
    return s

# Input parameter cells deliberately kept editable and separately labeled as assumptions.
param_list=[
 ("命中率",.95,"比率","A10"),
 ("有效输出时间",.8,"比率","A10"),
 ("攻击伤害每点换算",.01,"每点增幅","A11"),
 ("人物爆率每点主换算",1.,"倍","A13"),
 ("人物爆率小单位对照",.01,"倍","A13"),
 ("暴击基础总倍率",2.,"倍","A12"),
 ("致命基础总倍率",2.,"倍","A12"),
 ("吸收基础上限",.60,"比率","项目规则"),
 ("数学防除零吸收限",.99,"比率","不是引擎硬上限"),
 ("普通攻速上限",20,"点","项目规则"),
 ("突破技术上限",30,"点","项目规则"),
 ("生效攻速技术上限",50,"点","项目规则"),
 ("低攻速间隔截距",570.111430,"毫秒","原端拟合"),
 ("低攻速间隔斜率",11.295503,"毫秒/点","原端拟合"),
 ("攻速0刀速",1.75,"刀/秒","原端实测"),
 ("攻速10刀速",2.20,"刀/秒","原端实测"),
 ("攻速20刀速",2.90,"刀/秒","原端实测"),
 ("攻速30刀速",4.30,"刀/秒","原端实测"),
 ("攻速40刀速",8.50,"刀/秒","原端实测"),
 ("攻速50刀速",14.30,"刀/秒","原端实测"),
 ("固定最大攻击幸运阈值",12,"点","项目规则"),
 ("幸运额外奖励阈值",15,"点","项目规则"),
 ("幸运额外伤害系数",15,"百分点","项目规则"),
 ("幸运额外处决",5,"百分点","项目规则"),
 ("处决基础持续",1.,"秒","PVE应用为假设A14"),
 ("处决每档持续增长",.2,"秒/百分点","A14"),
 ("处决基础总倍率",2.,"倍","A14"),
 ("处决每档倍率增长",.2,"倍/百分点","A14"),
 ("回收货币总倍率",1.5,"倍","只作总预算，不叠第二遍命格"),
]
param=sheet("13_参数与假设","计算参数｜蓝色数值为可替换假设或既有规则",
"修改参数只重算派生值，不自动重新选择装备或模拟洗练。重新选配须运行build_profiles.py。",
["参数","数值","单位","来源等级"],[list(r) for r in param_list],[32,19,21,65],1)
pref={r[0]:f"'13_参数与假设'!$B${5+i}" for i,r in enumerate(param_list)}
param.get_range(f"B5:B{4+len(param_list)}").format.font.color="#1663A6"
offset=38
param.get_range(f"A{offset}:E{offset}").values=[["ID","对象","模型处理","依据与状态","敏感性/边界"]]
param.get_range(f"A{offset}:E{offset}").format=HEAD
param.get_range(f"A{offset+1}:E{offset+len(D['assumptions'])}").values=D["assumptions"]
param.get_range(f"A{offset+1}:E{offset+len(D['assumptions'])}").format=BODY
param.get_range(f"A{offset+1}:E{offset+len(D['assumptions'])}").format.wrap_text=True
param.get_range(f"A{offset+1}:E{offset+len(D['assumptions'])}").format.row_height=73
param.get_range("C:E").format.column_width=47

source_rows=[];blocks={}
for p in PS:
    start=len(source_rows)+5
    cats={}
    for s in p["sources"]:
        if s["category"] not in cats: cats[s["category"]]={"stats":Counter(),"count":0,"provenance":set(),"status":set()}
        cat=cats[s["category"]];cat["stats"].update(s["stats"]);cat["count"]+=1
        cat["provenance"].add(s["source"]);cat["status"].add(s["status"])
    for category,cat in cats.items():
        source_rows.append([p["id"],p["continent"],p["phase"],category,f"本类{cat['count']}项（逐项见完整JSON）",
                            "；".join(sorted(cat["provenance"])),"；".join(sorted(cat["status"])),
                            "由同包逐项数据聚合，便于核对"]+[cat["stats"].get(a,None) for a in AF])
    blocks[p["id"]]=(start,4+len(source_rows))
src=sheet("02_属性来源","来源分类账｜3,374条逐项来源见完整数据JSON",
"由完整JSON按人物和来源类别聚合，逐项未丢弃。空值按0；百分比输入为百分点，神力为增量。最终汇总使用SUM公式。",
["人物ID","大陆","状态","来源分类","来源名称","来源文件/依据","证据性质","备注"]+AF,
source_rows,[13,18,17,18,31,24,20,45]+[13]*len(AF))
src.get_range(f"I5:{xl(8+len(AF))}{4+len(source_rows)}").format.number_format='#,##0.####'

raw_rows=[[p["id"],p["continent"],p["phase"]]+[None]*len(AF) for p in PS]
rawsh=sheet("01_属性汇总","40组人物｜同类属性源加算",
"本页全部属性用SUM引用02_属性来源；还没有将独立乘区连乘。HP、攻击等最终面板见03_战斗派生。",
["人物ID","大陆","状态"]+AF,raw_rows,[13,18,17]+[14]*len(AF))
raw_form=[];rm={a:xl(4+i) for i,a in enumerate(AF)}
for p in PS:
    lo,hi=blocks[p["id"]]
    raw_form.append([f"=SUM('02_属性来源'!{xl(9+j)}{lo}:{xl(9+j)}{hi})" for j in range(len(AF))])
rawsh.get_range(f"D5:{xl(3+len(AF))}44").formulas=raw_form
rawsh.get_range(f"D5:{xl(3+len(AF))}44").format.number_format='#,##0.####'

deriv_keys=[
"面板攻击下限","面板攻击上限","面板魔法下限","面板魔法上限","面板道术下限","面板道术上限",
"HP","MP","期望攻击取值","有效幸运","幸运额外伤害系数",
"有效攻速点","刀每秒","普通单刀","暴致命期望单刀","普攻站桩DPS",
"技能系数","技能站桩DPS","群攻单目标DPS","有效常规DPS",
"有效吸收","等效HP不计防御","吸血理论上限每秒","含固定回复上限每秒",
"有效爆率_主换算","有效爆率_小单位对照","鞭尸期望倍数","货币回收倍率",
"处决总概率百分点","首刀","尾刀","暴击期望乘区","致命期望乘区","群攻间隔"]
dmap={a:xl(4+j) for j,a in enumerate(deriv_keys)}
der_rows=[[p["id"],p["continent"],p["phase"]]+[None]*len(deriv_keys) for p in PS]
der=sheet("03_战斗派生","最终面板与理论输出｜不含怪物防御、回血或处决",
"常规DPS已含一次命中和有效时间折损；群攻仅按一个目标。回血列是木桩理论上限，不是实际杀怪续航承诺。爆率主换算与小单位对照同时保留。",
["人物ID","大陆","状态"]+deriv_keys,der_rows,[13,18,17]+[19]*len(deriv_keys))
matrix=[]
for idx,p in enumerate(PS,5):
    R=lambda k:f"'01_属性汇总'!{rm[k]}{idx}"
    C=lambda k:f"{dmap[k]}{idx}"
    P=lambda k:pref[k]
    formulas={}
    for typ in ["攻击","魔法","道术"]:
        for end in ["下限","上限"]:
            formulas["面板"+typ+end]=f"{R(typ+end)}*(1+{R(typ+'加成')}/100)"
    formulas["HP"]=f"{R('HP')}*(1+{R('HP百分比')}/100)"
    formulas["MP"]=R("MP")
    formulas["有效幸运"]=f"{R('武器幸运')}+{R('项链幸运')}"
    formulas["幸运额外伤害系数"]=f"IF({C('有效幸运')}>={P('幸运额外奖励阈值')},{P('幸运额外伤害系数')},0)"
    formulas["期望攻击取值"]=f"{C('面板攻击下限')}+({C('面板攻击上限')}-{C('面板攻击下限')})*IF({C('有效幸运')}>={P('固定最大攻击幸运阈值')},1,0.5+0.5*MAX(0,{C('有效幸运')})/{P('固定最大攻击幸运阈值')})"
    formulas["有效攻速点"]=f"MIN({P('生效攻速技术上限')},MAX(0,MIN({R('攻击速度')},{P('普通攻速上限')}+MIN({P('突破技术上限')},{R('攻速突破')}))))"
    # Individual measured anchors; 41-49 interpolation is explicitly a model assumption.
    S=C("有效攻速点")
    speed=f"IF({S}<=40,1000/({P('低攻速间隔截距')}-{P('低攻速间隔斜率')}*{S}),1/(1/{P('攻速40刀速')}+({S}-40)/10*(1/{P('攻速50刀速')}-1/{P('攻速40刀速')})))"
    for anchor in [50,40,30,20,10,0]:
        speed=f"IF({S}={anchor},{P('攻速'+str(anchor)+'刀速')},{speed})"
    formulas["刀每秒"]=speed
    formulas["暴击期望乘区"]=f"1+MIN(1,MAX(0,{R('暴击几率')}/100))*({P('暴击基础总倍率')}+{R('暴击伤害')}/100-1)"
    formulas["致命期望乘区"]=f"1+MIN(1,MAX(0,{R('致命几率')}/100))*({P('致命基础总倍率')}+{R('致命伤害')}/100-1)"
    formulas["普通单刀"]=f"{C('期望攻击取值')}*(1+{R('伤害系数')}/100+{C('幸运额外伤害系数')}/100)*(1+{R('打怪伤害')}/100)*(1+{R('神力增量')})*(1+{R('攻击伤害')}*{P('攻击伤害每点换算')})"
    formulas["暴致命期望单刀"]=f"{C('普通单刀')}*{C('暴击期望乘区')}*{C('致命期望乘区')}"
    formulas["普攻站桩DPS"]=f"({C('暴致命期望单刀')}+{R('固定切割')})*{C('刀每秒')}*{P('命中率')}"
    formulas["技能站桩DPS"]=f"({C('暴致命期望单刀')}*{C('技能系数')}+{R('固定切割')})*{C('刀每秒')}*{P('命中率')}"
    formulas["群攻单目标DPS"]=f"IF({C('群攻间隔')}>0,{C('期望攻击取值')}*{P('命中率')}/MAX(0.0001,{C('群攻间隔')}),0)"
    formulas["有效常规DPS"]=f"({C('技能站桩DPS')}+{C('群攻单目标DPS')})*{P('有效输出时间')}"
    formulas["有效吸收"]=f"MAX(0,MIN({P('数学防除零吸收限')},{R('对怪伤害吸收')}/100,{P('吸收基础上限')}+{R('伤害吸收上限')}/100))"
    formulas["等效HP不计防御"]=f"{C('HP')}/(1-{C('有效吸收')})"
    formulas["吸血理论上限每秒"]=f"{C('暴致命期望单刀')}*{C('技能系数')}*{C('刀每秒')}*{P('命中率')}*{P('有效输出时间')}*MAX(0,{R('吸血')}/100)"
    formulas["含固定回复上限每秒"]=f"{C('吸血理论上限每秒')}+{R('每秒回血')}"
    formulas["有效爆率_主换算"]=f"(1+{R('爆率')}/100+{R('人物爆率')}*{P('人物爆率每点主换算')})*(1+{R('最大爆率')}/100)"
    formulas["有效爆率_小单位对照"]=f"(1+{R('爆率')}/100+{R('人物爆率')}*{P('人物爆率小单位对照')})*(1+{R('最大爆率')}/100)"
    formulas["鞭尸期望倍数"]=f"1+MIN(1,MAX(0,{R('鞭尸')}/100))"
    formulas["货币回收倍率"]=P("回收货币总倍率")
    formulas["处决总概率百分点"]=f"{R('处决概率')}+IF({C('有效幸运')}>={P('幸运额外奖励阈值')},{P('幸运额外处决')},0)"
    formulas["首刀"]=R("首刀斩杀");formulas["尾刀"]=R("尾刀斩杀")
    row=[]
    for k in deriv_keys:
        if k=="技能系数":row.append(None)
        elif k=="群攻间隔":row.append(None)
        else:row.append("="+formulas[k])
    matrix.append(row)
der.get_range(f"D5:{xl(3+len(deriv_keys))}44").formulas=matrix
for i,p in enumerate(PS,5):
    der.get_range(f"{dmap['技能系数']}{i}").values=[[p["meta"]["skills"]]]
    der.get_range(f"{dmap['群攻间隔']}{i}").values=[[p["aoe_interval"]]]
der.get_range(f"D5:{xl(3+len(deriv_keys))}44").format.number_format='#,##0.00'
der.get_range(f"{dmap['有效吸收']}5:{dmap['有效吸收']}44").format.number_format='0.0%'
for k in ["有效爆率_主换算","有效爆率_小单位对照","鞭尸期望倍数","货币回收倍率"]:
    der.get_range(f"{dmap[k]}5:{dmap[k]}44").format.number_format='0.00"x"'

erows=[]
for p in PS:
    for threshold in [0,10,20,30]:
        erows.append([p["id"],p["continent"],p["phase"],threshold]+[None]*6+
                     ["PVE抵扣规则＋持续/倍率映射假设；非地图实测"])
execs=sheet("04_处决条件计算","处决窗口条件表｜160个抵扣情景",
"先输出无处决常规DPS，再独立观察地图要求为0/10/20/30时的长战窗口。首刀、尾刀、低血量目标、怪物回复需后续逐刀计算，不能直接套长战值。",
["人物ID","大陆","状态","地图处决要求pp","有效处决概率","持续秒","处决总倍率","窗口内有效刀数","近似覆盖率","条件长战DPS","适用边界"],
erows,[13,18,17,19,19,15,17,19,17,23,64])
for j,p in enumerate(PS):
    base=5+j
    rr=lambda k:f"'01_属性汇总'!{rm[k]}{base}"
    dd=lambda k:f"'03_战斗派生'!{dmap[k]}{base}"
    for t in range(4):
        row=5+j*4+t
        fs=[
        f"=MIN(1,MAX(0,({dd('处决总概率百分点')}-D{row})/100))",
        f"=IF(E{row}>0,{pref['处决基础持续']}+{pref['处决每档持续增长']}*MAX(0,E{row}*100-1)+{rr('处决时间')},0)",
        f"=IF(E{row}>0,{pref['处决基础总倍率']}+{pref['处决每档倍率增长']}*MAX(0,E{row}*100-1)+{rr('处决倍率')}/100,1)",
        f"=MAX(0,INT(F{row}*{dd('刀每秒')}*{pref['命中率']}))",
        f"=IF(E{row}>0,1-(1-E{row})^H{row},0)",
        f"=(({dd('暴致命期望单刀')}*{dd('技能系数')}*(1+I{row}*(G{row}-1))+{rr('固定切割')})*{dd('刀每秒')}*{pref['命中率']}+{dd('群攻单目标DPS')})*{pref['有效输出时间']}"
        ]
        execs.get_range(f"E{row}:J{row}").formulas=[fs]
execs.get_range("E5:E164").format.number_format='0.0%'
execs.get_range("I5:I164").format.number_format='0.0%'
execs.get_range("J5:J164").format.number_format='#,##0'

gear=[];aff=[];fates=[];grow=[];collection=[];needs=[];payrows=[];flags=[]
def mats_text(d):return "；".join(f"{k}×{v:g}" if isinstance(v,(float,int)) else f"{k}×{v}" for k,v in d.items())
for p in PS:
    m=p["meta"]
    for g in m["gear"]:
        cat=D["catalog"][g["name"]]
        gear.append([p["id"],p["continent"],p["phase"],g["slot"],g["instance"],g["name"],g["part"],
             g["origin_c"],g["type"],g["source"],cat.get("攻击"),cat.get("HP"),len(g["affixes"]),
             "是" if g["opened"] else "否",g["weapon_luck"],g["neck_luck"],g["neck_tries"],
             "洗练绑定装备；项链幸运绑定人物永久进度；武器幸运成本忽略"])
    for a in m["affixes"]:
        aff.append([p["id"],p["continent"],p["phase"],a["slot"],a["instance"],a["name"],a["line"],
                    a["key"],a["value"],a["pool_index"],"仅装备原始基础值决定主属性范围"])
    for f in m["fates"]:
        fates.append([p["id"],p["continent"],p["phase"],f["slot"],f["id"],f["name"],
                      "彩色",mats_text(f["stats"]),"明确的代表组合，不等于100次必出指定名称"])
    grow.append([p["id"],p["continent"],p["phase"],m["equivalent_level"],m["title_c"],m["fate_count"],
                m["body"],m["rebirth"],m["sword_phase"],m["sword_level"],m["relic_level"],
                len(m["atlas"]),len(m["completed_pages"]),len(m["completed_continents"]),len(m["material_atlas"]),
                m["ordinary_rolls"],m["open_rolls"],m["equipped_count"],p["gold_total"],p["yuan_total"],
                "C0—C2仅已支持/明确假设的灵符路径；C3后新增成长自产"])
    aset=set(m["atlas"])
    groups=defaultdict(list)
    for row in D["meta"]["collection_single"] if "collection_single" in D["meta"] else []: pass
    # Per-group membership is provided by original input snapshot, not inferred from percentages.
    inp=json.loads((BASE/"source_inputs.json").read_text(encoding="utf-8")) if False else None
    for name,num in sorted(p["required_materials"].items()):
        needs.append([p["id"],p["continent"],p["phase"],"材料",name,num,
                      "从C0至当前检查点累计需求；未扣自身未来产出，不代表已有库存"])
    needs.append([p["id"],p["continent"],p["phase"],"装备实物",
                   f"共{len(p['required_gear_drops'])}个精确名称（明细见JSON）",
                   sum(p["required_gear_drops"].values()),
                   "含穿戴、重复试洗、图鉴登记与合成前置；完整数据未省略"])
    agg={}
    for pay in p["payments"]:
        key=(pay["c"],"本大陆动作汇总",pay["route"],"逐操作及每次费用见完整JSON/payments")
        if key not in agg:agg[key]={"gold":0.,"yuan":0.,"mats":Counter(),"n":0}
        a=agg[key];a["gold"]+=pay["gold"];a["yuan"]+=pay["yuan"];a["mats"].update(pay["mats"]);a["n"]+=1
    for (c,op,route,note),a in agg.items():
        payrows.append([p["id"],p["continent"],p["phase"],c,op,route,a["n"],a["gold"],a["yuan"],mats_text(a["mats"]),note])
    for flag in p["flags"]:flags.append([p["id"],p["continent"],p["phase"],flag,"模型已保留该情景；不隐性裁剪或改写原值"])

sheet("05_逐件穿戴","1,151条穿戴明细｜部位互斥与物理副本",
"物理槽70—75为时装首饰盒；普通首饰盒30—35不混用。马牌/军鼓由成长装备单独发放；灵玉位保守预留给命格接口。",
["人物ID","大陆","状态","物理槽","实物副本ID","装备名称","部位","产出大陆","来源层级","来源编号",
 "原始攻击","原始HP","洗练条数","已开光","武器幸运","项链幸运","本件项链尝试数","说明"],
gear,[13,18,17,12,16,32,19,13,18,14,18,19,12,12,13,13,20,48])
sheet("06_逐条洗练","逐条洗练结果｜固定随机种子可重现",
"这是一次符合概率池的具体配装样本，不是全体玩家平均或最优解。两份自产同名装备轮换试洗；没有锁单条或结果回滚。",
["人物ID","大陆","状态","槽位","副本ID","装备名称","第几条","属性","数值","原池行号","范围规则"],
aff,[13,18,17,11,13,30,12,20,16,14,43])
sheet("07_已开槽全彩","命格逐槽清单｜品质全彩≠指定极品必得",
"实际解锁脚本阈值未知；本批使用明确阶段假设。中后期新开槽的100次保底只保证彩色，不保证本表指定组合，组合获取需另作概率校准。",
["人物ID","大陆","状态","逻辑槽","命格ID","命格名称","品质","具体属性","边界"],
fates,[13,18,17,12,15,26,12,63,60])
sheet("08_成长进度","成长、图鉴与累计投入｜自产约束而非时间保证",
"进入档继承上一大陆毕业档；C2额外灵符解锁单列。127条旧预算不是自动全收集；本页成本由实际采用动作累计。缺失灵符分项不填假价。",
["人物ID","大陆","状态","等效等级","称号阶段","全彩槽位","神印档","转生","剑/圣物阶段","剑等级","圣物等级",
 "单件图鉴数","整页完成数","大陆全收集数","材料图鉴数","累计普通洗练","累计有效开光","穿戴件数",
 "累计自产金币","累计自产元宝","范围"],
grow,[13,18,17,13,13,13,12,12,18,12,12,15,15,17,16,18,18,14,23,23,61])
# Build per-group exact collection audit.
inp=json.loads((BASE/"source_inputs.json").read_text(encoding="utf-8"))
group_items=defaultdict(list)
for r in inp["nonmonster"]["collection_single"]:
    group_items[(r[0],r[1])].append(r[2])
for p in PS:
    done=set(p["meta"]["atlas"]);donepg=set(p["meta"]["completed_pages"])
    for c in range(1,p["c"]+1):
        cid=f"C{c:02}";gg=[(g,names) for (cc,g),names in group_items.items() if cc==cid]
        chosen=[n for g,names in gg for n in names if n in done]
        required=sum(len(names) for _,names in gg)
        full=[g for g,names in gg if g in donepg]
        collection.append([p["id"],p["continent"],p["phase"],cid,f"{len(gg)}组",required,len(chosen),
                           f"{len(full)}/{len(gg)}组","；".join(full),
                           "；".join(g for g,_ in gg if g not in donepg)])
sheet("09_图鉴核对","按实际登记名称触发奖励｜不是完成率乘全奖励",
"只有全页所需名称确实登记齐全才发整页奖。主情景不会把100%全图鉴暴击、韧性等上限奖励预先给普通进度。",
["人物ID","大陆","状态","图鉴大陆","地图组","要求件数","已登记数","整页奖生效","已完成地图组","未完成地图组"],
collection,[13,18,17,13,23,14,14,16,72,65])
sheet("10_自产需求","所有自产材料与装备的累计要求",
"每组是从开局到该状态的累计账。不同组不能相加。这里只证明取得这些东西能形成面板，不证明既定时间内掉够；后续561怪爆率负责供给。",
["人物ID","大陆","状态","类型","名称","累计数量","解释"],needs,[13,18,17,15,32,18,92])
sheet("11_支付分类账","操作支付路线｜灵符与自产分开",
"按同一人物、执行大陆、支付路径汇总。0游戏货币的灵符行不代表免费，未知灵符分项价格没有伪造。不可把全部40组费用相加。",
["人物ID","大陆","状态","执行大陆","操作","路线","操作记录数","自产金币","自产元宝","材料合计","依据/备注"],
payrows,[13,18,17,14,42,13,16,22,22,80,70])
sens=sheet("12_敏感性对照","400组单变量对照｜重点看结论是否依赖未知系数",
"只改变指定条件，不暗改原件。C2神印255和未灵符升满二阶段成长装备是对照，不是本批已实现功能。+突破压力不代表实际取得概率。",
["人物ID","大陆","状态","改变条件","攻击上限","HP","有效常规DPS","相对主情景","爆率倍数","刀每秒","解释"],
D.get("sensitivity",[]),[13,18,17,28,20,22,24,17,17,17,58])
sens.get_range(f"E5:G{4+len(D.get('sensitivity',[]))}").format.number_format='#,##0'
sens.get_range(f"H5:H{4+len(D.get('sensitivity',[]))}").format.number_format='0.00"x"'
riskrows=[
["F01","爆率不是补差得到","本批464件后续专属＋38合成无原生爆率词条；实际由称号、命格、洗练聚合。中间大陆不强行等于旧锚值。",
 "先用实际结果定掉率；若要修改装备投放，应另出明确修改表。"],
["F02","攻击加成跨位累计很高","C10半急速毕业原始攻击上限391721，攻击加成941%；最终攻击上限4077815.61。不是将每件百分比连乘。",
 "后续怪物按完整角色计算，旧单件/简化S0不能直接比。"],
["F03","压力档不是绝对上限","本批不预装用户修改后的6追梦和16称号卷；极端是已知来源高投入对照。",
 "不宣称一套数据穷尽所有构筑；未知原件后续加入同结构。"],
["F04","命格全彩不等于保底特定名称","主情景选定均衡彩色组合用于战斗代表；100次仅保证某彩色。",
 "实际支付次数需要进一步按候选池和保留策略计算；本批不推免费取得时长。"],
["F05","场景DPS不是净伤害","表中有效常规DPS不含怪物防御/回复、地图处决抵扣或首尾斩杀。",
 "怪物HP与低刀数目标后续逐刀反算；条件处决DPS在04单列。"],
["F06","吸血理论上限高","有些组合理论木桩回血很高；真实有效伤害、尾刀、过杀和控制断档影响回血。",
 "不能拿持续木桩回血直接断言怪群无威胁。"],
["F07","自给是数量约束，不是生产验收","每组都有实物与材料需求账，但本轮没定最终爆率，未证明12小时或某个时长内完成。",
 "严禁恢复21765灵符≈12小时或480/528小时硬线。"],
["F08","输入未被修改，GitHub未写","本批只创建角色方案、公式表和校验。",
 "后续根据用户统一归档指令再写仓库。"]
]
risk=sheet("14_边界与发现","本轮发现与解释边界","不能把文件通过校验等同游戏平衡通过；把来源事实、推定参数和情景结果分开。",
["编号","问题","解释","处理"],riskrows,[12,27,76,68],1)
risk.get_range("A5:D12").format.wrap_text=True;risk.get_range("A5:D12").format.row_height=62
if flags:
    risk.get_range("A16:E16").values=[["人物ID","大陆","状态","触发提醒","解释"]]
    risk.get_range("A16:E16").format=HEAD
    risk.get_range(f"A17:E{16+len(flags)}").values=flags
    risk.get_range(f"A17:E{16+len(flags)}").format=BODY
sourcerows=[[s["id"],s["name"],s["role"],s["sha256"],s["path"]] for s in D["sources"]]
ver=sheet("15_输入与校验","来源与新运行校验","原件SHA256记录用于追溯；本轮不上传GitHub、不修改来源表。项链幸运按人物永久进度修正；游戏货币×100、失色×10仅改变数值尺度。",
["ID","来源文件","使用范围","SHA256","本地输入路径"],sourcerows,[12,54,54,76,90],1)
ver.get_range("A20:D20").values=[["校验","结果","范围","备注"]];ver.get_range("A20:D20").format=HEAD
ver.get_range("A21:D26").values=[
["模型新运行断言","见数值与结构校验.json","来源/槽位/支付/图鉴/幸运/随机范围/40组继承","每项明细见数值与结构校验.json；逐项来源在完整JSON"],
["失败",0,"上述模型断言","本表不是进服测试"],
["Excel公式对照","导出前执行","40组×45源属性＋33派生字段＋处决160场景","另存工作簿核验.json"],
["GitHub写入","未执行","用户暂缓归档","只读输入"],
["服务器变更","未执行","没有写正式库、脚本、客户端","模型文件不能直接当服务端导入表"],
["最终爆率与产消","本批未执行","只输出后续需要的物料/装备量","561TXT随后完成"]
]

# Front-page executive view added last; reordered during export if API allows.
cover=sheet("00_结果导览","半急速人物属性｜40组计算结果 V1.1",
"满充值、前两大陆使用既有灵符路径；装备材料自产。下面是半急速毕业样本，不含怪物防御/处决的有效常规DPS。其他30档及来源明细在各页。",
["大陆","全彩槽","神印","转生","面板攻击上限","HP","常规DPS","推算爆率倍数","旧阶段目标","压力DPS比","状态"],
[[p["continent"],None,None,None,None,None,None,None,None,None,"离线模型"] for p in PS if p["id"].endswith("-G")],
[19,10,10,10,22,22,24,20,19,17,15],1)
anchors=[12,16,22,30,40,52,65,78,90,100]
for c in range(1,11):
    idx=5+(c-1)*4+2;rr=4+c;stressidx=idx+1
    pp=PS[(c-1)*4+2]
    cover.get_range(f"B{rr}:J{rr}").formulas=[[
        f"='08_成长进度'!F{idx}",f"='08_成长进度'!G{idx}",f"='08_成长进度'!H{idx}",
        f"='03_战斗派生'!{dmap['面板攻击上限']}{idx}",
        f"='03_战斗派生'!{dmap['HP']}{idx}",
        f"='03_战斗派生'!{dmap['有效常规DPS']}{idx}",
        f"='03_战斗派生'!{dmap['有效爆率_主换算']}{idx}",
        None,
        f"='03_战斗派生'!{dmap['有效常规DPS']}{stressidx}/'03_战斗派生'!{dmap['有效常规DPS']}{idx}"]]
    cover.get_range(f"I{rr}").values=[[anchors[c-1]]]
cover.get_range("E5:G14").format.number_format='#,##0'
cover.get_range("H5:J14").format.number_format='0.00"x"'
cover.merge_cells("A17:K18");cover.get_range("A17").values=[[
"本批是完整来源汇总与可复算情景，不是40个实服账号。命格开槽、部分付费路径和引擎单位采用明示假设；120/150/200倍只是压力情景，不是硬上限。"
]]
cover.get_range("A17:K18").format=SUB;cover.get_range("A17:K18").format.row_height=27
cover.merge_cells("A20:K21");cover.get_range("A20").values=[[
"已算出：40组面板、3,374条来源、1,151条穿戴、逐条洗练、累计自产需求、400条敏感性。未做：561怪最终爆率、怪物HP/攻击、真实时间闭环及GitHub归档。"
]]
cover.get_range("A20:K21").format={"fill":"#FFF2CC","font":{"color":"#704F00","bold":True,"size":10},"wrap_text":True}
cover.get_range("A20:K21").format.vertical_alignment="center"
cover.get_range("A20:K21").format.row_height=32
# Keep summary as the initially selected tab when supported.
try:
    cover.position=0
except Exception:pass

OUT=BASE/"艾尔登法环_40组半急速人物属性_V1.1.xlsx"
SpreadsheetFile.export_xlsx(wb).save(str(OUT))
# Return live workbook and maps for independent numerical verification/rendering.
(BASE/"workbook_maps.json").write_text(json.dumps({"raw_fields":AF,"raw_map":rm,"derived_keys":deriv_keys,"derived_map":dmap,"source_blocks":blocks,"parameter_refs":pref},ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"output":str(OUT),"bytes":OUT.stat().st_size,"sheets":len(wb.worksheets.items),
                  "source_rows":len(source_rows),"gear_rows":len(gear),"affix_rows":len(aff),
                  "payment_aggregate_rows":len(payrows),"needs_rows":len(needs)},ensure_ascii=False))
