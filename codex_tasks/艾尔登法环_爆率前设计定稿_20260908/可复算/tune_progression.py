"""Finite coarse tuning on a clearly labelled no-strong-equipment comparison.
No target-player buffs. Every improvement is written back to named gear cells.
"""
from pathlib import Path
from itertools import combinations
import json,copy,math,statistics
import build as T
B=Path(__file__).resolve().parent
R=json.loads((B/'inputs/baseline_results.json').read_text());P={x['id']:x for x in R['profiles']}
original=json.loads((B/'inputs/normalized.json').read_text())['gear']
patched_seed=copy.deepcopy(T.G);gear=[];aud=[]
def rnd(v):
 v=float(v);unit=1 if v<100 else 5 if v<500 else 10 if v<2000 else 50 if v<10000 else 100 if v<100000 else 1000
 return int(round(v/unit)*unit)
def boost(n,f):
 seed=patched_seed[n];g=T.G[n]
 if n=='拾骨弯刀':return
 # Do not multiply rare affixes. Mainhand flat values remain at the manually set modest scale.
 for k in ('攻击加成','魔法加成','道术加成','打怪伤害','攻击伤害','暴击伤害','致命伤害'):
  if seed.get(k):g[k]=rnd(float(seed[k])*f)
 if seed.get('HP'):g['HP']=rnd(float(seed['HP'])*math.sqrt(f))
 # Defense grows with actual defensive parts, not a second damage reduction system.
 for k in ('防御','魔御'):
  lo,hi=T.L.pair(seed.get(k))
  if hi:g[k]=f'{rnd(lo*math.sqrt(f))}-{rnd(hi*math.sqrt(f))}'
def probes(raw,gg,ns):
 d=T.approx(raw);out=[];k=max(1,round(len(ns)*.6))
 for sub in combinations(ns,k):
  rr,gear2,ch=T.replace_options(raw,gg,sub);d2=T.approx(rr)
  a=d2['技能效率DPS']/d['技能效率DPS'];b=d2['等效HP不计防御']/d['等效HP不计防御']
  out.append({'offense':a,'survival':b,'score':a**.65*b**.35,'raw':rr,'gear':gear2,'chosen':list(sub),'changes':ch})
 out.sort(key=lambda x:(x['score'],x['chosen']));return out,out[len(out)//2]
for g in R['groups']:
 p=P[g['entry']];raw=dict(p['raw'])
 for e in p['gear']:
  for k,v in T.gear_delta(e).items():
   # Snapshot raw came from original equipment, not the patched values.
   pass
 # Use original gear for removing the old reference's gear sources.
 for e in p['gear']:
  dd=T.L.stats_from_gear(original[e['name']])
  for x in e.get('affixes',[]):
   for k,v in T.L.stat_attr(x['attribute'],x['value']).items():dd[k]=dd.get(k,0)+v
  for k,v in dd.items():raw[k]-=v
 for e in gear:
  for k,v in T.gear_delta(e).items():raw[k]+=v
 if g['c']==1 and g['gi']==0:
  names=[row[0] for row in T.S['c1']['装备导入表'][1:9]]
  raw,gear,_=T.replace_options(raw,gear,names)
 # At continent boundary carry normal equipment actually selected, do not award all old normal loot.
 ns=g['normal_pool'];before,chosen=probes(raw,gear,ns);f=1.
 if g['c']>=3:
  # Target a broad noticeable ~15-25% offense or defensive substitute; not a mandatory exact gap, not exact per-hit equilibrium.
  for f in [1+x*.1 for x in range(151)]:
   for n in ns:boost(n,f)
   vals,chosen=probes(raw,gear,ns)
   if chosen['score']>=1.10:break
  else:raise RuntimeError('No finite progression solution '+g['group'])
 else:vals=before
 ep=T.approx(raw);ap=T.approx(chosen['raw'])
 aud.append({'c':g['c'],'gi':g['gi'],'group':g['group'],'pool':ns,'selected':chosen['chosen'],'ratio':len(chosen['chosen'])/len(ns),'patch_weight':f,
             'offense':chosen['offense'],'survival':chosen['survival'],'combat_index':chosen['score'],
             'minimum_combination_index':min(x['score'] for x in vals),'maximum_combination_index':max(x['score'] for x in vals),
             'entry_raw':raw,'entry_gear':copy.deepcopy(gear),'after_raw':chosen['raw'],'after_gear':chosen['gear'],
             'entry_dps':ep['技能效率DPS'],'after_dps':ap['技能效率DPS'],'entry_ehp':ep['等效HP不计防御'],'after_ehp':ap['等效HP不计防御'],
             'note':'普通装备分支的隔离比较；不包含BOSS/合成。角色非装备来源按已确认阶段继承；取得不是图鉴登记。'})
 gear=copy.deepcopy(chosen['gear'])
# Keep rarer same-group pieces attractive using common-stat floors; preserve every rare mechanic and original slot.
linked=[]
COMMON=['攻击加成','魔法加成','道术加成','打怪伤害','攻击伤害','暴击伤害','致命伤害','HP']
for m in T.M:
 if m['c']<3 or m['role'] not in ('稀有','地图BOSS','守关BOSS'):continue
 for n in m['items']:
  g=T.G[n];part=g['部位']
  same=[T.G[nn] for mm in T.M if mm['c']==m['c'] and mm['group_index']==m['group_index'] and mm['role']=='普通' for nn in mm['items'] if T.G[nn]['部位']==part]
  if not same:continue
  rank=1.12 if m['role']=='稀有' else 1.28 if m['role']=='地图BOSS' else 1.4
  for k in COMMON:
   maximum=max(float(x.get(k) or 0) for x in same)
   # Do not add entirely new off-role stats to rare item; existing design signature remains.
   if maximum and g.get(k):
    nv=max(float(g[k]),rnd(maximum*rank))
    if nv!=g[k]:linked.append({'name':n,'field':k,'old':g[k],'new':nv,'reason':'同图普通增强后的稀有档保值补差'});g[k]=nv
# Crafted pieces linked to a *real* same-slot boss or explicitly a same-slot rare/normal benchmark, no fabricated drops.
craft_aud=[]
for n,rec in T.A.CR.items():
 if rec['c']<3 or n in T.A.AOE:continue
 g=T.G[n];part=g['部位'];c=rec['c']
 candidates=[(nn,T.G[nn],mm['role']) for mm in T.M if mm['c']==c and mm['role']=='地图BOSS' for nn in mm['items'] if T.G[nn]['部位']==part]
 if not candidates:
  candidates=[(nn,T.G[nn],mm['role']) for mm in T.M if mm['c']==c and mm['role']!='守关BOSS' for nn in mm['items'] if T.G[nn]['部位']==part]
 if not candidates:continue  # independent zodiac/box products keep approved values
 refname,ref,role=max(candidates,key=lambda x:T.A.merit(x[0]))
 for k in COMMON:
  if ref.get(k) and g.get(k):
   floor=rnd(float(ref[k])* (1.1 if k=='HP' else 1.25))
   if floor>g[k]:linked.append({'name':n,'field':k,'old':g[k],'new':floor,'reason':'维护必做合成相对同部位掉落的优势'});g[k]=floor
 craft_aud.append({'craft':n,'c':c,'reference':refname,'reference_role':role,'note':'仅普通乘区必要补差；攻击基值与稀有词条仍保留原合成设计'})
changes=[]
for n,g in T.G.items():
 for k,v in g.items():
  if original[n].get(k)!=v:
   meta=T.A.META[n]
   changes.append({'name':n,'c':meta['c'],'group':T.N['groups'][str(meta['c'])][meta['gi']] if meta['role']!='合成' else 'NPC合成','role':meta['role'],'part':g['部位'],'field':k,'old':original[n].get(k),'new':v,'reason':'普通专属接棒调整' if meta['role']=='普通' else '普通调整后的必要保值联动'})
T.N['gear']=T.G
(B/'inputs/normalized_current.json').write_text(json.dumps(T.N,ensure_ascii=False,separators=(',',':')))
(B/'results/equipment_patch.json').write_text(json.dumps({'changes':changes,'linked_adjustments':linked,'crafted_references':craft_aud,'changed_items':len({x['name'] for x in changes})},ensure_ascii=False,indent=2))
(B/'results/ordinary_route.json').write_text(json.dumps(aud,ensure_ascii=False,separators=(',',':')))
print(json.dumps({'items':len({x['name'] for x in changes}),'fields':len(changes),'roles':{role:len({x['name'] for x in changes if x['role']==role}) for role in {x['role'] for x in changes}},'group_max_weight':max(x['patch_weight'] for x in aud),'combat_min':min(x['combat_index'] for x in aud if x['c']>=3)},ensure_ascii=False))
