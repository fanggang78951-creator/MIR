from pathlib import Path
import json,copy,statistics,math
import legacy_math as L
B=Path(__file__).resolve().parent
N=json.loads((B/'inputs/normalized_current.json').read_text());G=N['gear'];old=json.loads((B/'inputs/normalized.json').read_text())['gear']
x=json.loads((B/'inputs/equipment_comparison_original.json').read_text())
meta={n:{'c':m['c'],'role':m['role'],'gi':m['group_index']} for m in N['monsters'] for n in m['items']};meta.update({n:{'c':r['c'],'role':'合成','gi':0} for n,r in N['crafts'].items()})
def num(o,k):return float(o.get(k) or 0)
def rnd(x):return int(round(x)) if x<100 else int(round(x/5)*5)
def score(g,p):
 a=L.pair(g.get('攻击'))[1]
 return (p['raw_attack']+a)*(1+(p['attack_pct']+num(g,'攻击加成'))/100)*(1+(p['monster_pct']+num(g,'打怪伤害'))/100)*(1+(p['attack_damage']+num(g,'攻击伤害'))/100)*(1+p['crit_pct']/100*(1+(p['crit_damage']+num(g,'暴击伤害'))/100))*(1+p['lethal_pct']/100*(1+(p['lethal_damage']+num(g,'致命伤害'))/100))
R=[]
for z in x['crafted_comparisons']:
 n=z['name'];g=G[n];c=N['crafts'][n]['c'];p=x['benchmark_parameters'][str(c)]
 if z.get('kind')=='群攻生肖' or not z.get('base'):continue
 ref=copy.deepcopy(G[z['benchmark']]) if z['benchmark'] in G else copy.deepcopy(z['base'])
 synthetic=z['benchmark'] not in G
 # Synthetic grade benchmarks are openly labelled, never placed in drops or DB.
 if synthetic and c>=3:
  peers=[nm for nm,mm in meta.items() if mm['c']==c and mm['role']=='普通' and G[nm]['部位']==g['部位']]
  for k in ('攻击加成','魔法加成','道术加成','打怪伤害','暴击伤害','攻击伤害','致命伤害','HP'):
   ratios=[num(G[nm],k)/num(old[nm],k) for nm in peers if num(old[nm],k)>0]
   if ratios and num(ref,k):ref[k]=rnd(num(ref,k)*statistics.median(ratios))
 empty=score({},p);base=score(ref,p);den=base-empty
 if den<=0:continue
 if c>=3:
  for k in ('攻击','魔法','道术'):
   lo,hi=L.pair(ref.get(k));g[k]=f'{round(lo*1.5)}-{round(hi*1.5)}'
  seed=copy.deepcopy(old[n]);keys=[k for k in ('攻击加成','魔法加成','道术加成','打怪伤害','攻击伤害','暴击伤害','致命伤害') if num(seed,k)>0]
  lo,hi=1.,100.
  # Find a broad in-range single-item benefit; choose near2.3, not whole-character x2.3.
  for _ in range(20):
   f=(lo+hi)/2
   for k in keys:g[k]=rnd(num(seed,k)*f)
   q=(score(g,p)-empty)/den
   if q<2.3:lo=f
   else:hi=f
  # Retain approved lower bound; unmodified sufficient items do not get nerfed.
  for k in keys:g[k]=max(old[n].get(k) or 0,rnd(num(seed,k)*hi))
 q=(score(g,p)-empty)/den
 R.append({'name':n,'c':c,'part':g['部位'],'reference_name':z['benchmark'],'reference_type':'明确的同部位BOSS强度标尺（非实物）' if synthetic else '真实同部位BOSS（仅强度比较，配方来源另列）','reference':ref,'comparison_parameters':p,'empty':empty,'boss':base,'crafted':score(g,p),'marginal_ratio':q,'whole_ratio':score(g,p)/base,'attack_ratio':L.pair(g['攻击'])[1]/max(1,L.pair(ref['攻击'])[1]),'scope':'常规单刀边际贡献；不是总人物输出倍数。'})
(B/'inputs/normalized_current.json').write_text(json.dumps(N,ensure_ascii=False,separators=(',',':')))
(B/'results/craft_comparison.json').write_text(json.dumps(R,ensure_ascii=False,indent=2))
changes=[]
for n,g in G.items():
 for k,v in g.items():
  if old[n].get(k)!=v:
   mm=meta[n];changes.append({'name':n,'c':mm['c'],'group':N['groups'][str(mm['c'])][mm['gi']] if mm['role']!='合成' else 'NPC合成','role':mm['role'],'part':g['部位'],'field':k,'old':old[n].get(k),'new':v,'reason':'普通专属接棒调整' if mm['role']=='普通' else '普通调整后的必要保值联动'})
pat=json.loads((B/'results/equipment_patch.json').read_text());pat.update(changes=changes,changed_items=len({r['name'] for r in changes}));(B/'results/equipment_patch.json').write_text(json.dumps(pat,ensure_ascii=False,indent=2))
print('crafted comparison',len(R),'range',min(q['marginal_ratio'] for q in R),max(q['marginal_ratio'] for q in R))
