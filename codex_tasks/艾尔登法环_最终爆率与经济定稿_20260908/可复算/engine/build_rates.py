"""Final drop/economy design. No server, network, or repository writes.
Sources: inputs.json frozen from the approved pre-drop design archive.
Rates below are new planner decisions; no old hourly budgets are treated as facts.
"""
from pathlib import Path
from collections import defaultdict,Counter
import json,math,hashlib,statistics
import numpy as np
from scipy.optimize import linprog
from scipy.stats import gamma
from drop_math import effective_p,expected_per_kill
B=Path(__file__).resolve().parent
O=B.parent/'output';O.mkdir(exist_ok=True)
I=json.loads((B/'inputs.json').read_text(encoding='utf-8'))
M={r['id']:r for r in I['monsters']};P={r['id']:r for r in I['profiles']}
G={(g['c'],g['gi']):g for g in I['groups']}
NAMES={r['name']:r['id'] for r in I['monsters']}
PRICE={r['名称']:r for r in I['material_prices']};RC=I['somber_values']
COLLECT={n for n,r in I['materials'].items() if '收藏' in str(r) or r.get('类别')=='大陆收藏材料'}
COLLECT.update(['西境风痕碑拓','月潮忆珀','湖心月谱残章','熔原罪火残章','永霜朝圣痕','穹霜碑珀','古坛鎏叶髓','穹律鎏痕拓片'])
COM={int(r['大陆ID'][-2:]):n for n,r in PRICE.items() if r.get('计入货币产出模型')=='是'}
ROLE_SHARE={'普通':.72,'稀有':.18,'地图BOSS':.10}
SPAWN={'普通':(12,600),'稀有':(2,600),'地图BOSS':(1,1800),'守关BOSS':(1,7200)}
# Allocation references, NOT mandatory completion clocks or a recharge-time conversion.
HREF={c:h for c,h in enumerate([6,12,20,22,24,22,26,30,34,40],1)}
TAU={c:h for c,h in enumerate([.40,.55,.70,.80,.90,1.0,1.10,1.20,1.35,1.5],1)}
SET_BY_ID={int(r['id']):r for r in I['sets']}
SET_PRICE={n:(r['gold'],r['yuan']) for r in I['sets'] for n in r['names']}
DREAM=[r['item'] for r in I['high_value'] if r['type']=='追梦神器']
CHANGES=[];WARN=[];CHECK=[]
def check(name,ok,detail=''):
 CHECK.append({'check':name,'pass':bool(ok),'detail':detail})
def den_round(x):
 if x<=1:return 1
 e=10**math.floor(math.log10(x)); options=[1,1.2,1.5,1.8,2,2.5,3,4,5,6,8,10]
 return max(1,int(round(min(options,key=lambda z:abs(math.log((z*e)/x)))*e)))
def nice_qty(x):
 x=max(1,math.ceil(x))
 if x<=10:return x
 step=5 if x<=50 else 10 if x<=200 else 25 if x<=1000 else 100
 return int(math.ceil(x/step)*step)
# Stage requirements from actual pre-gate acquisition/spending events, not obsolete blanket budgets.
REQ={};EQ={};GROUP_REQ={};GROUP_EQ={};SIDE=[]
for c in range(1,11):
 es=[e for e in I['events'] if e['c']==c and e['branch']=='主线']
 stop=next(i for i,e in enumerate(es) if e['kind']=='守关击杀放行')
 rr=Counter();ee=Counter()
 for e in es[:stop]:
  key=(c,e['gi']);GROUP_REQ.setdefault(key,Counter());GROUP_EQ.setdefault(key,Counter())
  if e['kind']=='消耗材料':
   rr[e['name']]+=float(e['qty']);GROUP_REQ[key][e['name']]+=float(e['qty'])
  elif e['kind']=='货币支出':
   for nm,f in [('金币','gold'),('元宝','yuan')]:rr[nm]+=e[f];GROUP_REQ[key][nm]+=e[f]
  elif e['kind']=='条件取得装备':
   if e['name'] in RC or e['name'] in SET_PRICE:
    ee[e['name']]+=float(e['qty']);GROUP_EQ[key][e['name']]+=float(e['qty'])
 REQ[c]=rr;EQ[c]=ee
 for e in es[stop+1:]:
  if e['kind'] in ('消耗材料','货币支出','条件取得装备'):SIDE.append(e)
# Derive fixed baseline service rates from approved TTK. No second skill multiplier.
ENC=defaultdict(list)
for e in I['encounters']:ENC[e['monster']].append(e['ttk'])
SERVICE={};GROUP_STATS=[]
for key,g in G.items():
 c,gi=key;pi=P[g['entry']];po=P[g['ordinary']];pd=P[g['done']]
 mult=statistics.mean(p['derived']['有效爆率_主换算'] for p in (pi,po,pd))
 whip=min(1,max(0,statistics.mean(p['raw'].get('鞭尸',0) for p in (pi,po,pd))/100))
 members=[m for m in M.values() if (m['c'],m['group_index'])==key]
 for role in ('普通','稀有','地图BOSS','守关BOSS'):
  ms=[m for m in members if m['role']==role]
  for m in ms:
   ttk=statistics.mean(ENC[m['id']]) if ENC[m['id']] else m['target_ttk']
   spawn_n,respawn=SPAWN[role];cap=spawn_n*3600/respawn
   k=0 if role=='守关BOSS' else min(cap,3600*ROLE_SHARE[role]/len(ms)/max(ttk,.5))
   SERVICE[m['id']]={'monster':m['id'],'name':m['name'],'c':c,'gi':gi,'role':role,'ttk':ttk,'kills_h':k,'spawn_n':spawn_n,'respawn_s':respawn,'supply_cap_h':cap,'multiplier':mult,'whip':whip,'profile':g['entry']}
 GROUP_STATS.append({'c':c,'gi':gi,'group':g['group'],'M':mult,'whip':whip,'reference_hours':HREF[c]/len([x for x in G if x[0]==c]),**{r:sum(SERVICE[m['id']]['kills_h'] for m in members if m['role']==r) for r in ROLE_SHARE}})
# Trigger grouping: each RANDOM pool appears once, with explicit candidate weights.
buckets={}
for a in I['drop_content']:
 mid=a['monster'];pool=a['pool']
 grp='兼掉普通' if pool=='本图普通兼掉候选' else '制式池' if pool=='制式独立候选' else '六神器池' if pool=='六神器公共池' else a['item']
 key=(mid,pool,grp)
 if key not in buckets:buckets[key]={'monster':mid,'pool':pool,'item':a['item'],'q':int(a['quantity']),'members':{},'input_relation_count':0}
 b=buckets[key];b['input_relation_count']+=1
 if pool=='本图普通兼掉候选':b['members'][a['item']]=1
 elif pool=='制式独立候选':
  for si in range(a['set_min'],a['set_max']+1):
   for n in SET_BY_ID[si]['names']:b['members'][n]=1
 elif pool=='六神器公共池':b['members']={n:1 for n in DREAM}
# Restore existing named title items omitted in the previous candidate view. No new title identity or stats.
for r in I['high_value']:
 if r['type']=='称号卷' and r['source'] in NAMES:
  mid=NAMES[r['source']];key=(mid,'称号卷',r['item'])
  buckets[key]={'monster':mid,'pool':'称号卷','item':r['item'],'q':1,'members':{},'input_relation_count':0}
  CHANGES.append({'type':'补回既有候选','monster':mid,'item':r['item'],'before':'此前5400关系未包含','after':'按既有25称号回收/来源注册加入','reason':'未新建称号；原物品名称部署前与本机最新版逐字映射'})
TR=list(buckets.values())
# Material aggregate targets: reserve consumption first, sell only COM surplus; model no rare-item income.
MAT_CONFIG={}
for c in range(1,11):
 materials=sorted({t['item'] for t in TR if M[t['monster']]['c']==c and t['pool']=='材料独立候选' and M[t['monster']]['role']!='守关BOSS'})
 for name in materials:
  ts=[t for t in TR if M[t['monster']]['c']==c and t['pool']=='材料独立候选' and t['item']==name and M[t['monster']]['role']!='守关BOSS']
  demand=REQ[c].get(name,0);need_rate=demand*1.20/HREF[c]
  if name==COM.get(c):
   pr=PRICE[name];needed=max(REQ[c]['金币']/(1.5*pr['基础金币']),REQ[c]['元宝']/(1.5*pr['基础元宝']))
   need_rate=(demand+1.15*needed)/HREF[c]
  if name in COLLECT:
   # Optional collection: ~one per 80 hours of current-continent farming, excluded from required progression.
   need_rate=1/80
  elif demand==0:
   need_rate=.35 if any('BOSS' in M[t['monster']]['role'] for t in ts) else 1.5
   if name=='技能残页':need_rate=max(5,450/HREF[c])
   if name in ('小卢恩','大卢恩'):need_rate=max(need_rate,2 if name=='小卢恩' else .5)
   if name=='黄金树芽':need_rate=max(need_rate,2)
  group_count=len([k for k in G if k[0]==c])
  base_capacity=sum(SERVICE[t['monster']]['kills_h']*t['q']*(1+SERVICE[t['monster']]['whip']) for t in ts)/group_count
  # Raise stacks only when the required production cannot be delivered at a moderate trigger frequency.
  scale=max(1,math.ceil(need_rate/max(base_capacity*.25,1e-9)))
  for t in ts:
   if scale>1:
    old=t['q'];t['q']=nice_qty(old*scale)
    CHANGES.append({'type':'叠加数量','monster':t['monster'],'item':name,'before':old,'after':t['q'],'reason':'长期消耗供给；提高每次叠加量，避免把所有候选改为高频地面散件'})
  weighted_cap=sum(SERVICE[t['monster']]['kills_h']*t['q']*(1+SERVICE[t['monster']]['whip'])*({'普通':1,'稀有':1.6,'地图BOSS':3}[M[t['monster']]['role']]) for t in ts)
  alpha=need_rate*group_count/max(weighted_cap,1e-9)
  MAT_CONFIG[(c,name)]={'desired_h':need_rate,'demand':demand,'alpha':alpha,'qty_scale':scale}
# One numeric base denominator for every real trigger.
for j,t in enumerate(TR,1):
 m=M[t['monster']];s=SERVICE[m['id']];c=m['c'];g=G[(c,m['group_index'])];mult=s['multiplier'];role=m['role']
 if t['pool']=='自身专属':
  if role=='普通':
   n=len(g['normal_pool']);k=len(g['selected']);coupon=n*sum(1/i for i in range(n-k+1,n+1))
   nr=sum(x['kills_h'] for x in SERVICE.values() if x['c']==c and x['gi']==m['group_index'] and x['role']=='普通')
   prob=min(.15,coupon/max(1,nr*TAU[c]*(1+s['whip'])))
  elif role=='稀有':prob=[.10,.08,.065,.06,.055,.05,.045,.04,.035,.032][c-1]
  elif role=='地图BOSS':prob=.40/len(m['items'])
  else:prob=.90/len(m['items'])
 elif t['pool']=='本图普通兼掉候选':prob=.40
 elif t['pool']=='制式独立候选':prob={'普通':.012,'稀有':.025,'地图BOSS':.08,'守关BOSS':.20}[role]
 elif t['pool']=='六神器公共池':prob={'普通':1/180000,'稀有':1/45000,'地图BOSS':1/1800,'守关BOSS':1/350}[role]
 elif t['pool']=='称号卷':prob=.08 if role=='守关BOSS' else .06 if role=='地图BOSS' else .025
 else:
  name=t['item']
  if role=='守关BOSS':
   prob=1 if name not in COLLECT else 1/250
  else:prob=min(.65,MAT_CONFIG[(c,name)]['alpha']*{'普通':1,'稀有':1.6,'地图BOSS':3}[role])
 t['denominator']=1 if (t['pool']=='材料独立候选' and role=='守关BOSS' and t['item'] not in COLLECT) else den_round(mult/max(prob,1e-12))
 if t['pool']=='六神器公共池':
  # One global base pool: higher native-tier denominators must not reward C10 farming C2.
  t['denominator']={'普通':20000000,'稀有':5000000,'地图BOSS':200000,'守关BOSS':40000}[role]
 t['id']=f'D{j:05d}';t['c']=c;t['gi']=m['group_index'];t['role']=role;t['name']=m['name'];t['M']=mult;t['whip']=s['whip']
 t['p_effective']=effective_p(t['denominator'],mult)
 t['expected_per_kill']=expected_per_kill(t['denominator'],mult,t['q'],s['whip'])
 t['expected_h']=s['kills_h']*t['expected_per_kill']
 t['expected_pool_event_h']=s['kills_h']*expected_per_kill(t['denominator'],mult,1,s['whip'])
# Cap standard-gear currency share relative to native common materials, without changing recycle prices.
for key,g in G.items():
 c,gi=key
 if c>2:continue
 ts=[t for t in TR if t['c']==c and t['gi']==gi and t['role']!='守关BOSS']
 cm=COM[c];pr=PRICE[cm]
 material_q=sum(t['expected_h'] for t in ts if t['pool']=='材料独立候选' and t['item']==cm)
 c_gold=material_q*pr['基础金币']*1.5;c_yuan=material_q*pr['基础元宝']*1.5
 set_ts=[t for t in ts if t['pool']=='制式独立候选']
 sg=sy=0
 for t in set_ts:
  total=sum(t['members'].values())
  sg+=t['expected_h']*sum(SET_PRICE[n][0]*w for n,w in t['members'].items())/total*1.5
  sy+=t['expected_h']*sum(SET_PRICE[n][1]*w for n,w in t['members'].items())/total*1.5
 factor=max(1,sg/max(c_gold*.20,1),sy/max(c_yuan*.20,1))
 for t in set_ts:
  if factor<=1:continue
  old=t['denominator'];t['denominator']=den_round(old*factor)
  ss=SERVICE[t['monster']];t['p_effective']=effective_p(t['denominator'],t['M'])
  t['expected_per_kill']=expected_per_kill(t['denominator'],t['M'],t['q'],t['whip'])
  t['expected_h']=ss['kills_h']*t['expected_per_kill'];t['expected_pool_event_h']=t['expected_h']/t['q']
  CHANGES.append({'type':'制式池频率控制','monster':t['monster'],'item':t['item'],'before':old,'after':t['denominator'],'reason':'制式装备辅助货币供给；防止旧高回收价使C2产币反超C3'})

# Revenue/resources for an hour in a group; old maps use a bounded speed uplift and current character multiplier.
BY_MON=defaultdict(list)
for t in TR:BY_MON[t['monster']].append(t)
GROUP_MIDS={key:[m['id'] for m in M.values() if (m['c'],m['group_index'])==key and m['role']!='守关BOSS'] for key in G}
CF={r['c']:r for r in I['continent_refs']}
def farm_rate(key,current_c=None,speed_factor=1.,loot_factor=1.,competition=1.):
 c,gi=key;resources=Counter();quant=Counter();kills=Counter()
 current_c=current_c or c
 for mid in GROUP_MIDS[key]:
  s=SERVICE[mid];k=s['kills_h'];mult=s['multiplier'];whip=s['whip']
  if current_c>c:
   p=P[CF[current_c]['p70']];mult=p['derived']['有效爆率_主换算'];whip=min(1,max(0,p['raw'].get('鞭尸',0)/100))
   old=P[G[key]['entry']]['derived']['技能效率DPS'];new=p['derived']['技能效率DPS']
   k=min(s['supply_cap_h'],k*min(6,max(1,new/max(old,1))))
  k=min(s['supply_cap_h']*competition,k*speed_factor)
  kills[s['role']]+=k
  for t in BY_MON[mid]:
   amount=k*expected_per_kill(t['denominator'],mult*loot_factor,t['q'],whip)
   if t['members']:
    total=sum(t['members'].values());products={n:amount*w/total for n,w in t['members'].items()}
   else:products={t['item']:amount}
   for name,v in products.items():
    quant[name]+=v
    if name in RC:resources['EQ:'+name]+=v;resources['失色锻造石']+=v*RC[name]
    elif name in SET_PRICE:
     resources['EQ:'+name]+=v;gold,yuan=SET_PRICE[name];resources['金币']+=v*gold*1.5;resources['元宝']+=v*yuan*1.5
    elif name in COM.values():
     resources[name]+=v;r=PRICE[name];resources['金币']+=v*r['基础金币']*1.5;resources['元宝']+=v*r['基础元宝']*1.5
    elif t['pool'] not in ('六神器公共池','称号卷') and name not in COLLECT:
     resources[name]+=v
 return resources,quant,kills
BASE={key:farm_rate(key) for key in G}
# Per-map first ordinary distinct items; Poisson approximation to independent name arrivals.
rng=np.random.default_rng(20260908);ACQUISITION=[]
for key,g in G.items():
 q=BASE[key][1];pool=g['normal_pool'];k=len(g['selected']);rates=np.array([q[n] for n in pool])
 times=rng.exponential(1/rates,size=(10000,len(rates)));kth=np.partition(times,k-1,axis=1)[:,k-1]
 ACQUISITION.append({'c':key[0],'gi':key[1],'group':g['group'],'n':len(pool),'k':k,'mean_h':float(kth.mean()),'p50_h':float(np.quantile(kth,.5)),'p90_h':float(np.quantile(kth,.9)),'ordinary_rates':dict(zip(pool,rates.tolist()))})
# Fit resource production against real retained inputs. Currency and somber use gross-minus-reserve accounting.
STAGES=[];FARMS=[];BALANCES=[];BINDINGS=[];stash=Counter();unused_eq=Counter()
for c in range(1,11):
 needed=Counter(REQ[c]);eq=EQ[c]
 for name,n in eq.items():
  if name in RC:needed['失色锻造石']+=n*RC[name]
  elif name in SET_PRICE:
   a,b=SET_PRICE[name];needed['金币']+=n*a*1.5;needed['元宝']+=n*b*1.5
 for name,n in REQ[c].items():
  if name in COM.values():
   needed['金币']+=n*PRICE[name]['基础金币']*1.5;needed['元宝']+=n*PRICE[name]['基础元宝']*1.5
 # Named pieces cannot be claimed both as saved duplicates and dismantled currency. Piece buffers are not carried.
 for name,n in eq.items():needed['EQ:'+name]=float(gamma.ppf(.85,n))
 current_keys=[k for k in G if k[0]==c]
 old_required=set()
 for name,n in eq.items():
  if not any(name in BASE[k][1] for k in current_keys):
   old_required.update(k for k in G if k[0]<c and BASE[k][1].get(name,0)>0)
 for name,n in REQ[c].items():
  if name not in ('金币','元宝','失色锻造石') and stash[name]<n and not any(BASE[k][0].get(name,0)>0 for k in current_keys):
   old_required.update(k for k in G if k[0]<c and BASE[k][0].get(name,0)>0)
 keys=sorted(set(current_keys)|old_required);vectors=[farm_rate(k,c)[0] for k in keys]
 resources=[n for n,v in needed.items() if v>0]
 A=[];bv=[];valid=[];missing=[]
 for n in resources:
  demand=needed[n];stock=0 if n.startswith('EQ:') or n in COM.values() else stash[n]
  net=max(0,demand-stock)
  if net==0:continue
  if max(v.get(n,0) for v in vectors)<=0:
   missing.append({'c':c,'resource':n,'need':net,'reason':'not obtainable from pre-gate farming entries; explicit source needed'})
   continue
  scale=max(1,net);A.append([-v.get(n,0)/scale for v in vectors]);bv.append(-net/scale);valid.append((n,net,scale))
 if missing:WARN.extend(missing)
 bounds=[]
 for k in keys:
  a=next(a for a in ACQUISITION if (a['c'],a['gi'])==k)
  bounds.append((a['mean_h'] if k[0]==c else 0,None))
 result=linprog([1 if k[0]==c else 1.12 for k in keys],A_ub=np.array(A),b_ub=np.array(bv),bounds=bounds,method='highs')
 if not result.success:raise RuntimeError((c,result.message))
 # Round farm sessions upward to 15-minute units; retain resource precision in calculations.
 hours=[math.ceil(max(0,x)*4-1e-9)/4 if x>1e-7 else 0 for x in result.x]
 produced=Counter();qproduced=Counter();total_kills=Counter()
 for k,h in zip(keys,hours):
  if h<=0:continue
  r,q,ks=farm_rate(k,c)
  for n,v in r.items():produced[n]+=v*h
  for n,v in q.items():qproduced[n]+=v*h
  for n,v in ks.items():total_kills[n]+=v*h
  FARMS.append({'stage':c,'farm_c':k[0],'gi':k[1],'group':G[k]['group'],'hours':h,'backfarm':k[0]<c,'gold_gross_h':r['金币'],'yuan_gross_h':r['元宝'],'somber_gross_h':r['失色锻造石']})
 for n,net,scale in valid:
  ratio=produced[n]/max(net,1e-12)
  if ratio<1.10:BINDINGS.append({'c':c,'resource':n,'coverage':ratio})
  check(f'C{c}:{n}:供给',produced[n]+1e-5*scale>=net, f'{produced[n]:.4g}/{net:.4g}')
 # Resource balances; pending EQ safety quantities are inspection constraints, not physical extra spends.
 reserve_somber=sum(n*RC.get(name,0) for name,n in eq.items())
 reserve_gold=sum(n*PRICE[name]['基础金币']*1.5 for name,n in REQ[c].items() if name in COM.values())+sum(n*SET_PRICE[name][0]*1.5 for name,n in eq.items() if name in SET_PRICE)
 reserve_yuan=sum(n*PRICE[name]['基础元宝']*1.5 for name,n in REQ[c].items() if name in COM.values())+sum(n*SET_PRICE[name][1]*1.5 for name,n in eq.items() if name in SET_PRICE)
 for n in sorted(set(produced)|set(needed)|set(stash)):
  if n.startswith('EQ:'):continue
  before=stash[n]
  consumption=needed.get(n,0)
  if n in COM.values():
   # All after-use COM units are monetized in the currency entries; do not carry them as material too.
   after=0
  else:after=before+produced[n]-consumption;stash[n]=max(0,after)
  if consumption or (produced[n]>0 and n in ('金币','元宝','失色锻造石')):
   BALANCES.append({'c':c,'resource':n,'opening':before,'produced':produced[n],'need_including_reserve':consumption,'ending':after,'actual_spend':REQ[c].get(n,0),'note':('COM余量已计货币，不再留作实体库存' if n in COM.values() else '金币元宝扣除留用主材机会成本；失色扣除不拆的专属等价量' if n in ('金币','元宝','失色锻造石') else '非主材剩余存仓，不计货币收入')})
 total=sum(hours);native=sum(h for k,h in zip(keys,hours) if k[0]==c);back=total-native
 # Approximate joint required-item tail on the planned mixture. Not a guarantee, not a target clock.
 wait=[]
 for name,n in eq.items():
  lam=qproduced[name]/max(total,1e-12)
  if lam>0:wait.append(rng.gamma(max(1,int(math.ceil(n))),1/lam,size=4000))
 tails=np.max(np.array(wait),axis=0) if wait else np.zeros(4000)
 STAGES.append({'c':c,'reference_hours':HREF[c],'native_h':native,'backfarm_h':back,'plan_h':total,'eq_tail_p50_h':float(np.quantile(tails,.5)),'eq_tail_p90_h':float(np.quantile(tails,.9)),
 'gold_spend':REQ[c]['金币'],'yuan_spend':REQ[c]['元宝'],'somber_spend':REQ[c]['失色锻造石'],'gold_gross':produced['金币'],'yuan_gross':produced['元宝'],'somber_gross':produced['失色锻造石'],
 'gold_net_h':(produced['金币']-reserve_gold)/max(total,1e-12),'yuan_net_h':(produced['元宝']-reserve_yuan)/max(total,1e-12),'somber_net_h':(produced['失色锻造石']-reserve_somber)/max(total,1e-12),
 'normal_kills_h':total_kills['普通']/max(total,1e-12),'rare_kills_h':total_kills['稀有']/max(total,1e-12),'boss_kills_h':total_kills['地图BOSS']/max(total,1e-12),
 'M_entry':P[CF[c]['entry']]['derived']['有效爆率_主换算'],'M_gate':P[CF[c]['p70']]['derived']['有效爆率_主换算'],'missing':len(missing)})
# Collect mature current-continent production, separate from advancement net income.
MATURE=[]
for c in range(1,11):
 keys=[k for k in G if k[0]==c];r=Counter();qq=Counter();kk=Counter()
 for k in keys:
  rv,qv,kv=BASE[k]
  for n,v in rv.items():r[n]+=v/len(keys)
  for n,v in qv.items():qq[n]+=v/len(keys)
  for n,v in kv.items():kk[n]+=v/len(keys)
 MATURE.append({'c':c,'gold_h':r['金币'],'yuan_h':r['元宝'],'somber_h':r['失色锻造石'],'COM_h':r[COM[c]],'normal_h':kk['普通'],'rare_h':kk['稀有'],'boss_h':kk['地图BOSS'],'dream_any_h':sum(qq[n] for n in DREAM),**{'M':statistics.mean(SERVICE[mid]['multiplier'] for k in keys for mid in GROUP_MIDS[k])}})
# Stress old-map farming using a mature C10 character; probability capped before corpse reroll.
STRESS=[]
for k in G:
 for scenario,speed,loot,competition in [('基础',1,1,1),('效率70%',.7,1,1),('效率130%',1.3,1,1),('抢怪可用50%',1,1,.5),('爆率80%',1,.8,1),('爆率120%',1,1.2,1),('C10回刷',1,1,1)]:
  r,q,ks=farm_rate(k,10 if scenario=='C10回刷' else k[0],speed,loot,competition)
  STRESS.append({'c':k[0],'gi':k[1],'scenario':scenario,'gold_h':r['金币'],'yuan_h':r['元宝'],'somber_h':r['失色锻造石'],'kills_h':sum(ks.values()),'dream_h':sum(q[n] for n in DREAM)})
# Core validation.
check('561 monster identities',len(M)==561)
check('619 exclusives preserved',len(RC)==619)
check('46 groups',len(G)==46)
check('10 gate identities',sum(m['role']=='守关BOSS' for m in M.values())==10)
check('525 single six-artifact triggers',sum(t['pool']=='六神器公共池' for t in TR)==525)
check('one distinct dream pool per monster',len({t['monster'] for t in TR if t['pool']=='六神器公共池'})==525)
check('no direct somber',not any(t['item']=='失色锻造石' for t in TR))
check('no first-continent dream',not any(t['c']==1 and t['pool']=='六神器公共池' for t in TR))
check('25 titles restored',sum(t['pool']=='称号卷' for t in TR)==25)
check('title scrolls remain rare',all(t['denominator']>1 and t['p_effective']<.12 for t in TR if t['pool']=='称号卷'))
check('names unique for monster files',len(NAMES)==561)
check('no missing pre-gate supply',not WARN,str(WARN[:10]))
for t in TR:
 check(t['id']+':positive_integer',isinstance(t['denominator'],int) and t['denominator']>=1 and isinstance(t['q'],int) and t['q']>=1)
 if t['members']:check(t['id']+':pool_conservation',sum(t['members'].values())>0)
# Excluded budgets to make scope explicit.
BUDGETS=[]
for r in I['recipes']:
 rule='已含条件路线/按实际事件计量'
 if 'ASH' in r['id']:rule='PVP旁账，不计主线产消'
 elif 'FATE' in r['id']:rule='满充值命格走既有灵符入口；不把符文/元宝重复算入半急速；零充路线另列'
 elif r['gold']==0 and r['yuan']==0 and not r['materials']:rule='既有脚本/灵符价格保留；0不是免费，不虚构兑换关系'
 BUDGETS.append({'id':r['id'],'c':r['c'],'npc':r['npc'],'output':r['output'],'gold':r['gold'],'yuan':r['yuan'],'count':r['budget_count'],'scope':rule})
DATA={'version':'1.0','date':'2026-09-08','source_sha256':I['source_sha256'],
 'assumptions':{'skill_in_ttk':2,'leech_model_only':1.3,'recycle_currency':1.5,'corpse':'one additional independent roll at whip probability; expectation (1+w), no repeated multiplication','cap':'p=min(1,M/N)','spawn':SPAWN,'role_time_shares':ROLE_SHARE,'farm_scope':'one self-farming payer; no market purchases/no daily extra boss gifts; no guaranteed realtime duration','hours_reference_only':HREF,'named_item_safety':.85},
 'triggers':TR,'services':list(SERVICE.values()),'groups':GROUP_STATS,'acquisition':ACQUISITION,'stages':STAGES,'farm_plan':FARMS,'balances':BALANCES,'mature':MATURE,'stress':STRESS,'bindings':BINDINGS,'changes':CHANGES,'warnings':WARN,'checks':CHECK,'recipe_scope':BUDGETS,
 'requirements':{c:dict(x) for c,x in REQ.items()},'equipment_requirements':{c:dict(x) for c,x in EQ.items()},'side_events':SIDE,
 'summary':{'triggers':len(TR),'source_relations':len(I['drop_content']),'normal_pickup_groups':len(ACQUISITION),'plan_hours':sum(s['plan_h'] for s in STAGES),'checks':len(CHECK),'failed':sum(not x['pass'] for x in CHECK),'qty_changes':sum(x['type']=='叠加数量' for x in CHANGES)}}
(O/'results.json').write_text(json.dumps(DATA,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
(O/'核验'/'model_validation.json').write_text(json.dumps({'summary':DATA['summary'],'warnings':WARN,'failed':[x for x in CHECK if not x['pass']]},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(DATA['summary'],ensure_ascii=False,indent=2))
print('missing',WARN)
for s in STAGES:print('C',s['c'],'hours',s['plan_h'],'back',s['backfarm_h'],'goldnet/h',round(s['gold_net_h']),'yuan',round(s['yuan_net_h']),'somber',round(s['somber_net_h']))
