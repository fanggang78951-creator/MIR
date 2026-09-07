"""Seal design decisions and independently check source boundaries; not engine validation."""
from pathlib import Path
from collections import Counter
import copy,json,math,hashlib,re
B=Path(__file__).resolve().parent
R=json.loads((B/'results/final.json').read_text());N=json.loads((B/'inputs/normalized_current.json').read_text());OLD=json.loads((B/'inputs/normalized.json').read_text());S=json.loads((B/'inputs/snapshot_all.json').read_text())
patch=json.loads((B/'results/equipment_patch.json').read_text());ordinary=json.loads((B/'results/ordinary_route.json').read_text());crafted=json.loads((B/'results/craft_comparison.json').read_text())
checks=[]
def ck(n,p,d=''):
 checks.append({'check':n,'pass':bool(p),'detail':d})
P={p['id']:p for p in R['profiles']};M={m['id']:m for m in R['monsters']}
META={name:{'c':m['c'],'role':m['role'],'gi':m['group_index']} for m in R['monsters'] for name in m['items']}
for name,rec in N['crafts'].items():META[name]={'c':rec['c'],'role':'合成','gi':0}
for tag,c in [('c1',1),('c2sets',2)]:
 for row in S[tag]['装备导入表'][1:]:
  if row and row[0] not in META:META[row[0]]={'c':c,'role':'制式','gi':0}
allowed={'攻击','魔法','道术','攻击加成','魔法加成','道术加成','打怪伤害','暴击伤害','攻击伤害','致命伤害','HP','防御','魔御','攻击速度'}
ck('装备总数不变',len(R['gear'])==len(OLD['gear'])==817)
ck('物品集合不增删',set(R['gear'])==set(OLD['gear']))
for name,g in R['gear'].items():
 old=OLD['gear'][name];mm=META[name]
 ck('名称部位资源号不变',all(g.get(k)==old.get(k) for k in ['名称','部位','来源编号']),name)
 if mm['c']<=2:ck('C1/C2与既有前期合成全部冻结',g==old,name)
 for k in g:
  if g[k]!=old.get(k):ck('只改授权普通战斗字段',mm['c']>=3 and k in allowed,name+':'+k)
for a in ordinary:
 ck('普通专属样本50%-70%',.5<=a['ratio']<=.7,a['group'])
 if a['c']>=3:ck('普通分支有可感知换装收益',a['combat_index']>=1.09,a['group'])
 # raw-after minus raw-before contains gear only: reconstruction from named gear in ordinary json.
for k in ['monsters','groups','recipes','crafts','quests','item_sources','material_sources']:
 if k!='monsters':ck('结构/来源/成本不乱改',N[k]==OLD[k],k)
ck('561身份原样',[(m['id'],m['name'],m['role'],m['group'],m['loc']) for m in R['monsters']]==[(m['id'],m['name'],m['role'],m['group'],m['loc']) for m in OLD['monsters']])
for c in range(1,11):ck('每大陆1守关',sum(m['c']==c and m['role']=='守关BOSS' for m in R['monsters'])==1,str(c))
ck('地图BOSS92',sum(m['role']=='地图BOSS' for m in R['monsters'])==92)
for m in R['monsters']:
 ck('怪物攻击上下限',0<m['DC']<=m['DCMAX'],m['name'])
 ck('怪物关键数字可精确保存',all(isinstance(m[k],int) and 0<m[k]<2**53 for k in ['HP','DC','DCMAX','AC','MAC','Exp','Lvl','attack_interval_ms']),m['name'])
ck('同图统一配置',len({x['map_key'] for x in R['maps']})==len(R['maps'])==171)
for e in R['encounters']:ck('落点使用同一地图键',e['map'] in {m['map_key'] for m in R['maps']},e['monster'])
ck('守关70预算可过',all(x['win'] for x in R['gate_checks'] if x['case']=='p70'))
ck('缺25韧性存在实质风险',all(not x['win'] for x in R['gate_checks'] if x['case']=='仅缺韧性25'))
ck('技能粗系数明确',R['rules']['skill_efficiency']==2 and R['rules']['leech_skill_factor']==1.3)
for p in R['profiles']:
 ck('命格不重复',len(p['fates'])==len(set(p['fates'])),p['id'])
 ck('洗练最多8条',all(len(e.get('affixes',[]))<=8 for e in p['gear']),p['id'])
 ck('技能只乘一次',math.isclose(p['derived']['技能效率DPS'],p['derived']['纯属性DPS']*2,rel_tol=1e-12),p['id'])
 ck('吸血只按1.3',math.isclose(p['derived']['吸血HPS'],p['derived']['吸血理论上限每秒']*1.3,rel_tol=1e-12),p['id'])
 if p['parent'] and P[p['parent']]['neck']==8:ck('幸运永久不回退',p['neck']==8,p['id'])
for x in crafted:ck('合成常规边际2-3倍',2<=x['marginal_ratio']<=3,x['name'])
ck('33属性合成均比较',len(crafted)==33)
ck('物品概率全空',all(x['probability'] is None for x in R['drop_content']))
ck('失色无直接掉落',not any(x['item']=='失色锻造石' for x in R['drop_content']))
coverage=set()
for x in R['drop_content']:
 if x['pool']=='制式独立候选':coverage.update(range(x['set_min'],x['set_max']+1))
ck('20套制式来源覆盖',coverage==set(range(1,21)))
# Explanations for strong route: separate and explicit, not failed 20% tests masked as pass.
for g in R['groups']:
 if g['gi']==len(N['groups'][str(g['c'])])-1:continue
 en=P[g['entry']];rows=[e for e in en['gear'] if META[e['name']]['role'] in ('合成','地图BOSS','守关BOSS')]
 g['strong_items']=sorted(set(e['name'] for e in rows))
 g['design_decision']='强装/必做合成分支，允许提前推进；不要求凑50%-70%普通件' if rows else '普通换装分支，按普通专项对照推进；C1/C2已冻结'
R['ordinary_ladder']=ordinary;R['crafted_comparisons']=crafted;R['equipment_changes']=patch['changes'];R['equipment_meta']=META
R['status']='爆率前设计定稿；非服务器部署回执'
R['calibration_note']='按普通支线与强装主线分别定值；没有新增20%硬门槛。C1/C2、命格属性、身份与概率保护。'
R['remaining_design_task']='仅物品触发爆率与产出时间/供需速度反算；引擎字段映射、资源显示和进服校准属于实施验收。'
R['summary'].pop('edges_clear',None)
R['summary'].update({'ordinary_items_changed':len({x['name'] for x in patch['changes'] if x['role']=='普通'}),'linked_items_changed':len({x['name'] for x in patch['changes'] if x['role']!='普通'}),'gear_items_changed':len({x['name'] for x in patch['changes']}),'gear_fields_changed':len(patch['changes']), 'ordinary_ladder_groups':sum(x['c']>=3 for x in ordinary),'ordinary_ladder_offense_range':[min(x['offense'] for x in ordinary if x['c']>=3),max(x['offense'] for x in ordinary if x['c']>=3)]})
R['closure_checks']=checks
failed=[x for x in checks if not x['pass']]
report={'checks':len(checks),'failures':len(failed),'failed':failed,'counts_by_kind':dict(Counter(x['check'] for x in checks)),'scope':'数据身份、字段白名单、近似设计指标、来源和导出前结构；不是游戏内试验'}
(B/'results/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
(B/'results/design_final.json').write_text(json.dumps(R,ensure_ascii=False,separators=(',',':')))
print(json.dumps({'summary':R['summary'],'validation':report},ensure_ascii=False,indent=2))
if failed:raise SystemExit(1)
