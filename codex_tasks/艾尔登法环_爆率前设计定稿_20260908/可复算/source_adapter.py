
"""Conditional acquisition ledger, no drop probabilities or time-to-acquire claims."""
from pathlib import Path
from collections import Counter,defaultdict
import json,math,copy,re,random,hashlib
from legacy_math import ATTRS,stat_attr,stats_from_gear,derive,pair
ROOT=Path(__file__).resolve().parent
N=json.loads((ROOT/'inputs/normalized_current.json').read_text());S=json.loads((ROOT/'inputs/snapshot_all.json').read_text())
J=json.loads((ROOT/'inputs/combat.json').read_text());O=json.loads((ROOT/'inputs/source_inputs.json').read_text())
G=N['gear'];M=N['monsters'];MI={m['id']:m for m in M};CR=N['crafts'];RE={r['id']:r for r in N['recipes']}
COL={r[2]:r for r in J['collection_rows']}
PAGES={(r[0],r[1]):r for r in S['npc']['08_地图整页图鉴'][4:] if r[0]}
PAGEITEMS=defaultdict(set)
for n,r in COL.items():PAGEITEMS[(r[0],r[1])].add(n)
META={}
for m in M:
 for n in m['items']:META[n]={'c':m['c'],'gi':m['group_index'],'role':m['role'],'source':m['id']}
for tag,c in [('c1',1),('c2sets',2)]:
 for i,r in enumerate(S[tag]['装备导入表'][1:]):
  if r[0] and r[0] not in META:META[r[0]]={'c':c,'gi':min(len(N['groups'][str(c)])-1,int((i//8)/10*len(N['groups'][str(c)]))),'role':'制式','source':tag}
for n,r in CR.items():META[n]={'c':r['c'],'gi':0,'role':'合成','source':r['id']}
SLOTMAP={r[0]:r[1] for r in S['c310']['部位说明'][1:] if r[0]}
BOX={r[0]:69+int(r[2]) for r in O['nonmonster']['slot_plan']}
def slots(n):
 part=G[n]['部位']
 if part=='灵玉':return []
 if part=='时装首饰盒':return [BOX[n]]
 v=SLOTMAP.get(part)
 if isinstance(v,(int,float)):return [int(v)]
 return [int(x) for x in str(v).split('/')] if v and '/' in str(v) else []
def stable(s):return int.from_bytes(hashlib.sha256(str(s).encode()).digest()[:8],'big')
def clean(st):return {k:float(v) for k,v in st.items() if v and k in ATTRS}
def sumstats(src):
 a={k:0. for k in ATTRS}
 for r in src:
  for k,v in r.items():
   if k in a:a[k]+=float(v or 0)
 return a
def merit(n):
 g=G[n];r=stats_from_gear(g)
 return pair(g.get('攻击'))[1]+4*r.get('攻击加成',0)+6*r.get('打怪伤害',0)+3*r.get('攻击伤害',0)+.00015*r.get('HP',0)+8*r.get('韧性',0)+22*r.get('对怪伤害吸收',0)+40*r.get('伤害吸收上限',0)+30*r.get('吸血',0)+80*r.get('攻速突破',0)+8*r.get('攻击速度',0)
FATES={}
for r in S['fate']['命格定义'][1:]:
 if r[0]:FATES[int(r[0])]={'name':r[2],'stats':{}}
for r in S['fate']['命格属性'][1:]:
 if r[0]:
  for k,v in stat_attr(r[2],r[3]).items():FATES[int(r[0])]['stats'][k]=FATES[int(r[0])]['stats'].get(k,0)+v
FATE_ORDER=[1087,1088,1091,1081,1085,1083,1090,1093]
BODY_MAX=[0,50,80,110,140,170,195,220,240,255]
TITLE={int(r[0][1:]):r for r in S['npc']['01_贯穿称号'][4:] if r[0]}
IND={r[0]:r for r in S['npc']['02_独立称号'][4:] if r[0]}
RB={int(r[0]):r for r in S['npc']['03_二十转奖励'][4:] if r[0]}
BODY={int(r[0]):r for r in S['econ']['10_神印255档'][4:] if r[0]}
RECYCLE={r[6]:int(r[8]) for r in S['econ']['07_专属分解明细'][4:] if r[0] and isinstance(r[8],(int,float))}
AOE={r[2]:{'interval':r[6],'coefficient':r[7],'range':r[5]} for r in S['npc']['05_群攻生肖'][4:] if r[0]}
SKILL_C={'攻杀剑术':1,'基本剑术':2,'半月弯刀':2,'烈火剑法':3,'施毒术':4}
SKILL_UNLOCK={'攻杀剑术':'开天斩','基本剑术':'逐日剑法','半月弯刀':'双龙斩','烈火剑法':'十步一杀','施毒术':'群体施毒术'}
WEIGHTS={'title':20,'collection':50,'equipment':20,'craft':10}
PROFILES=[];BANK={};EVENTS=[];PREMON={};GROUPREF=[];CONTREF=[];CHECKS=[]
class State:
 def __init__(self):
  self.c=1;self.gi=0;self.dead=set();self.atlas=set();self.paid=set();self.made=set();self.quests=set()
  self.title=0;self.body=0;self.turn=0;self.holy=1;self.neck=0;self.trials=0;self.fates=FATE_ORDER[:2]
  self.stock=Counter();self.material=Counter();self.spent=Counter();self.gear={};self.instances={}
  self.skills={n:0 for n in SKILL_C};self.last=None;self.branch='主线';self.events=[]
 def log(self,kind,name,qty=1,**more):
  row={'c':self.c,'gi':self.gi,'branch':self.branch,'kind':kind,'name':name,'qty':qty,**more}
  self.events.append(row)
 def source(self,n):
  if n in G and META[n]['role']=='制式':
   mm=META[n];return next((m['id'] for m in M if m['id'] in self.dead and m['c']==mm['c'] and m['group_index']>=mm['gi']),None)
  ss=N['item_sources'].get(n,N['material_sources'].get(n,[]))
  live=[s for s in ss if s in self.dead]
  if live:return max(live,key=lambda s:(MI[s]['c'],MI[s]['group_index'],s))
  return next((s for s in ss if str(s).startswith('SHOP:')),None)
 def can(self,n,seen=()):
  if n in seen:return False
  if n in CR:return CR[n]['c']<=self.c and all(self.can(x,seen+(n,)) for x in list(CR[n]['bases'])+list(CR[n]['materials']))
  if n=='失色锻造石':return any(self.source(x) for x in RECYCLE if x in G)
  return bool(self.source(n))
 def currency(self,r,count=1):
  self.spent['金币']+=r['gold']*count;self.spent['元宝']+=r['yuan']*count
  self.log('货币支出',r['id'],count,gold=r['gold']*count,yuan=r['yuan']*count)
 def mat(self,n,q,reason):
  need=max(0,q-self.material[n])
  if need:
   if n=='失色锻造石':
    opts=[x for x in RECYCLE if x in META and META[x]['role']=='普通' and self.source(x)]
    if not opts:opts=[x for x in RECYCLE if x in META and self.source(x)]
    if not opts:raise ValueError(('no somber',self.c,reason))
    item=max(opts,key=lambda x:(META[x]['c'],META[x]['gi'],-merit(x)))
    count=math.ceil(need/RECYCLE[item]);self.material[n]+=count*RECYCLE[item]
    self.log('条件取得并分解',item,count,source=self.source(item),output=n,output_qty=count*RECYCLE[item],unit=RECYCLE[item])
   else:
    source=self.source(n)
    if source is None:raise ValueError(('unavailable',n,reason,self.c))
    self.material[n]+=need;self.log('条件取得材料',n,need,source=source)
  self.material[n]-=q;self.spent[n]+=q;self.log('消耗材料',n,q,reason=reason)
 def acquire(self,n,q=1,reason='换装',seen=()):
  if n in seen:raise ValueError('cycle')
  for _ in range(int(q)):
   if n in CR:
    r=CR[n]
    for b,k in r['bases'].items():
     if self.stock[b]<k:self.acquire(b,k-self.stock[b],'合成基础件',seen+(n,))
     self.stock[b]-=k;self.log('消耗装备',b,k,reason=r['id'])
    for b,k in r['materials'].items():self.mat(b,k,r['id'])
    self.currency(r);self.made.add(n);source=r['id']
   else:
    source=self.source(n)
    if not source:raise ValueError(('gear unavailable',n,self.c,reason))
   self.stock[n]+=1;self.log('制作成品' if n in CR else '条件取得装备',n,1,source=source,reason=reason)
 def register(self,n):
  if n in self.atlas:return
  if self.stock[n]<1:self.acquire(n,reason='图鉴专用实物')
  self.stock[n]-=1;self.atlas.add(n);self.log('登记图鉴',n,1)
 def wear_candidates(self,names):
  for n in sorted(set(names),key=lambda n:(merit(n),n)):
   for sid in slots(n):
    old=self.gear.get(sid)
    if n in AOE:
     if old and old['name'] in AOE and AOE[old['name']]['interval']<=AOE[n]['interval']:continue
    elif old and (old['name'] in AOE or merit(old['name'])>=merit(n)):continue
    key=f'{sid}:{n}'
    if key not in self.instances:
     if self.stock[n]<1:self.acquire(n,reason='穿戴实物')
     self.stock[n]-=1;self.instances[key]={'instance':key,'name':n,'slot':sid,'affixes':[],'rolls':0}
    self.gear[sid]=self.instances[key]
    self.log('换装',n,slot=sid,instance=key,replaced=old['instance'] if old else None)
 def recipe(self,r):
  if r['id'] in self.paid:return
  for n,q in r['materials'].items():self.mat(n,q,r['id'])
  self.currency(r);self.paid.add(r['id']);self.log('领取奖励',r['id'])
 def finish_available(self):
  for n,r in CR.items():
   if n not in self.made and r['c']<=self.c and self.can(n):self.acquire(n,reason='必做合成')
  self.wear_candidates([n for n in self.made if self.stock[n]>0 or any(e['name']==n for e in self.gear.values())])
  for r in RE.values():
   if r['type'] in ('独立称号','转生') and r['c']<=self.c and r['id'] not in self.paid and all(self.can(n) for n in r['materials']):
    self.recipe(r)
    if r['type']=='转生':self.turn=max(self.turn,int(re.search(r'第(\d+)转',r['output']).group(1)))
  for q in N['quests']:
   if q['id'] in self.quests or q['c']>self.c:continue
   if q['c']==self.c and N['groups'][str(self.c)].index(q['group'])>self.gi:continue
   if q['postclear'] and not any(m['id'] in self.dead and m['role']=='守关BOSS' and m['c']==q['c'] for m in M):continue
   if all(self.can(n) for n in q['materials']):
    for n,v in q['materials'].items():self.mat(n,v,q['id'])
    self.quests.add(q['id']);self.log('领取任务',q['id'])
 def grow(self,p):
  if self.title<self.c:
   r=RE[f'C{self.c:02d}-LONGTITLE']
   if self.c<=2:
    self.title=self.c;self.log('灵符既有路径',r['id'],note='不把缺价0解释为免费')
   elif p>=.4 and all(self.can(n) for n in r['materials']):
    self.recipe(r);self.title=self.c
  if self.c==2 and self.holy==1:self.holy=2;self.log('成长装备进阶','圣律真言+黄金之心',note='各280；原功能/灵符路线继承')
  if self.c>=2 and self.can('野兽骨片'):
   end=BODY_MAX[self.c-2]+int((BODY_MAX[self.c-1]-BODY_MAX[self.c-2])*min(.9,p))
   for lev in range(self.body+1,end+1):
    r=BODY[lev];self.mat('野兽骨片',r[3],f'神印{lev}');self.spent['金币']+=r[4];self.spent['元宝']+=r[5];self.log('神印升级',str(lev),gold=r[4],yuan=r[5])
   self.body=max(self.body,end)
  if self.c>=2 and self.neck<8:
   r=next(x for x in RE.values() if 'LUCK' in x['id']);target=90 if self.c==2 and p<.5 else 350
   while self.neck<8 and self.trials<target and all(self.can(n) for n in r['materials']):
    self.trials+=1;self.currency(r)
    for n,v in r['materials'].items():self.mat(n,v,r['id'])
    if random.Random(stable('neck'+str(self.trials))).random()<(.024 if self.trials<=250 else .2):self.neck+=1
    self.log('人物幸运','项链',trial=self.trials,luck=self.neck)
  if self.can('技能残页'):
   for n,c in SKILL_C.items():
    end=9 if self.c>c else min(9,int(9*p)) if self.c==c else 0
    for lev in range(self.skills[n]+1,end+1):
     self.mat('技能残页',10*lev,f'{n}+{lev}');self.spent['元宝']+=1000000*lev
     self.log('技能强化',n,lev,pages=10*lev,yuan=1000000*lev,unlock=SKILL_UNLOCK[n] if lev==9 else None)
    self.skills[n]=max(self.skills[n],end)
  if self.c>=2:
   targets=sorted(self.gear.values(),key=lambda e:merit(e['name']),reverse=True)[:max(2,self.c-1)]
   for e in targets:
    target_rolls=3 if self.c<4 else 5 if self.c<7 else 8
    if e['rolls']>=target_rolls:continue
    n=e['name'];r=RE[f'C{max(2,META[n]["c"]):02d}-WASH']
    if not e.get('backup'):self.acquire(n,reason='洗练轮换备用件');self.stock[n]-=1;e['backup']=True
    best=e['affixes'];bestscore=sum(a['value'] for a in best if a['attribute'] not in ('魔法','道术'))
    for k in range(e['rolls'],target_rolls):
     self.currency(r)
     for mat,v in r['materials'].items():self.mat(mat,v,r['id'])
     aff=roll(n,random.Random(stable(e['instance']+str(k))))
     score=sum(a['value'] for a in aff if a['attribute'] not in ('魔法','道术'))
     if score>bestscore:best,bestscore=aff,score
     self.log('洗练轮换',n,instance_family=e['instance'],attempt=k+1,result=aff,note='两份独立实物轮换，无锁条')
    e['affixes']=best;e['rolls']=target_rolls
 def sources(self):
  rows=[]
  def add(cat,key,st):rows.append({'category':cat,'key':str(key),'stats':clean(st)})
  q=self.body//25;add('基础','自然底板',{'攻击下限':7+2*q,'攻击上限':13+5*q,'HP':1000+400*q,'MP':200+100*q})
  add('付费','赞助',{'处决概率':10,'韧性':50,'爆率':600,'最大爆率':10,'伤害系数':10})
  add('付费','狂暴',dict(mainflat(50),HP=10000,暴击几率=10))
  add('付费','捐献',dict(mainflat(99),爆率=100,最大爆率=5,暴击几率=10))
  add('成长装备','圣律',dict(mainflat(50 if self.holy==1 else 280),**({'固定切割':5000} if self.holy==1 else {'鞭尸':10})))
  add('成长装备','黄金',dict(mainflat(50 if self.holy==1 else 280),**({'每秒回血':2000} if self.holy==1 else {'首刀斩杀':10})))
  if self.title:
   r=TITLE[self.title];add('贯穿称号',r[2],dict(mainflat(r[3]),HP=r[4],MP=r[5],爆率=r[6]))
  q=self.body*(self.body+1)/2;add('神印',self.body,dict(mainflat(q),HP=q*100))
  add('转生',self.turn,{'神力增量':sum(r[7] for k,r in RB.items() if k<=self.turn)})
  for key,r in IND.items():
   if key in self.paid:
    c=int(r[1][1:]);st=dict(mainflat(r[3]),HP=r[4],神力增量=r[5],处决概率=r[6],韧性=r[7])
    if c>=3:st['攻速突破']=1
    if c in (3,5):st['伤害吸收上限']=1 if c==3 else 2
    add('独立称号',key,st)
  for n in sorted(self.atlas):r=COL[n];add('单件图鉴',n,dict(mainflat(r[8]),HP=r[9]))
  for key,ns in PAGEITEMS.items():
   if ns<=self.atlas:
    r=PAGES[key];add('地图整页','/'.join(key),{'韧性':r[3],'处决概率':r[4],'神力增量':r[5]})
  for q in N['quests']:
   if q['id'] in self.quests:add('任务',q['id'],sumstats([stat_attr(k,v) for k,v in q['stats'].items()]))
  for r in S['npc']['09_大陆全收集'][4:]:
   if r[0] and {n for n,x in COL.items() if x[0]==r[0]}<=self.atlas:add('大陆全收集',r[0],{'暴击几率':r[4]})
  assert len(set(self.fates))==len(self.fates)
  for f in self.fates:add('命格',f,FATES[f]['stats'])
  add('幸运','人物永久',{'武器幸运':7,'项链幸运':self.neck})
  for sid,e in sorted(self.gear.items()):
   add('装备',e['instance'],stats_from_gear(G[e['name']]))
   add('洗练',e['instance'],sumstats([stat_attr(a['attribute'],a['value']) for a in e['affixes']]))
  return rows
 def completion(self):
  ns={n for n,r in COL.items() if int(r[0][1:])==self.c};keys=[k for k in PAGEITEMS if int(k[0][1:])==self.c]
  singles=len(ns&self.atlas)/len(ns);pages=sum(PAGEITEMS[k]<=self.atlas for k in keys)/len(keys)
  target={}
  for n,mm in META.items():
   if mm['c']==self.c:
    for sid in slots(n):target[sid]=max(target.get(sid,0),merit(n))
  eq=sum(min(1,(merit(self.gear[sid]['name'])/v if v>0 else 1)) if sid in self.gear else 0 for sid,v in target.items())/len(target)
  crafts={n for n,r in CR.items() if r['c']==self.c}
  ratios={'title':float(self.title>=self.c),'collection':.7*singles+.3*pages,'equipment':eq,'craft':len(crafts&self.made)/len(crafts)}
  return {**ratios,'score':sum(WEIGHTS[k]*v for k,v in ratios.items()),'single_collection':singles,'page_collection':pages}
def mainflat(v):return {k:v for k in ('攻击下限','攻击上限','魔法下限','魔法上限','道术下限','道术上限')}
def roll(n,rng):
 pool=[r for r in O['wash_pool'][1:] if r[1] not in ('攻击','魔法','道术') or pair(G[n].get(r[1]))[1]>=2];ret=[]
 for _ in range(rng.choices(range(1,9),[.34,.26,.18,.1,.06,.03,.02,.01])[0]):
  r=rng.choices(pool,[x[3] for x in pool])[0];a=r[1]
  if a in ('攻击','魔法','道术'):v=rng.randint(1,int(pair(G[n].get(a))[1]//2))
  elif a=='攻击加成':lo,hi=pair(r[2]);v=rng.randint(int(lo),int(hi))
  else:v=float(re.findall(r'\d+(?:\.\d+)?',str(r[2]))[0])
  ret.append({'attribute':a,'value':v})
 return ret
def snap(st,label):
 refs=[];ss=st.sources()
 for row in ss:
  k='S'+hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16];BANK[k]=row;refs.append(k)
 raw=sumstats([r['stats'] for r in ss]);iid=f'P{len(PROFILES)+1:04d}'
 p={'id':iid,'parent':st.last,'c':st.c,'gi':st.gi,'branch':st.branch,'label':label,'raw':raw,'derived':derive(raw,skill=1),
    'sources':refs,'gear':copy.deepcopy(list(st.gear.values())),'atlas':sorted(st.atlas),'made':sorted(st.made),'quests':sorted(st.quests),
    'title':st.title,'body':st.body,'turn':st.turn,'fates':list(st.fates),'skills':dict(st.skills),'neck':st.neck,'luck_trials':st.trials,
    'dead':sorted(st.dead),'spent':dict(st.spent),'event_count':len(st.events),'completion':st.completion(),
    'aoe':next(({'name':e['name'],**AOE[e['name']]} for e in st.gear.values() if e['name'] in AOE),None)}
 PROFILES.append(p);st.last=iid;return p
def run():
 st=State();st.grow(0);post=None;side_events=[]
 for c in range(1,11):
  print('continent',c,flush=True);st.c=c;st.gi=0
  entry=snap(st,f'C{c:02d}入场')
  if post:CHECKS.append({'type':'跨大陆完全继承','c':c,'pass':all(entry[k]==post[k] for k in ['raw','gear','atlas','spent','skills'])})
  local=[entry];ng=len(N['groups'][str(c)])
  for gi,g in enumerate(N['groups'][str(c)]):
   st.gi=gi;en=snap(st,f'C{c:02d}G{gi+1:02d}入场')
   mm=[m for m in M if m['c']==c and m['group_index']==gi and m['role']!='守关BOSS']
   normal=[m for m in mm if m['role']=='普通'];rare=[m for m in mm if m['role']=='稀有'];boss=[m for m in mm if m['role']=='地图BOSS']
   for m in normal+rare:PREMON[m['id']]=en['id'];st.dead.add(m['id']);st.log('击杀来源',m['id'])
   names=[n for m in normal+rare for n in m['items']]
   names += [n for n,x in META.items() if x['role']=='制式' and x['c']==c and x['gi']==gi]
   st.wear_candidates(names)
   if c==1 and gi>=1:st.fates=FATE_ORDER[:3]
   st.grow((gi+.5)/ng);mid=snap(st,f'C{c:02d}G{gi+1:02d}积累后')
   for m in boss:
    b=snap(st,m['name']+'首杀前');PREMON[m['id']]=b['id'];st.dead.add(m['id']);st.log('击杀地图BOSS',m['id'])
    st.wear_candidates(m['items']);st.finish_available()
   # Main path carries only registered entries, not imaginary 85% previous-continent completion.
   feasible=sorted([n for n in COL if META[n]['c']==c and META[n]['gi']<=gi and st.can(n)],key=lambda n:(META[n]['gi'],n))
   count=int(sum(META[n]['c']==c for n in COL)*.18*(gi+1)/ng)
   for n in feasible:
    if sum(META[x]['c']==c for x in st.atlas)>=count:break
    st.register(n)
   done=snap(st,f'C{c:02d}G{gi+1:02d}地图组完成');local += [en,mid,done]
   GROUPREF.append({'c':c,'gi':gi,'group':g,'entry':en['id'],'mid':mid['id'],'done':done['id']})
  st.finish_available();st.grow(.9)
  local.append(snap(st,f'C{c:02d}首杀前制作完成'))
  remaining=sorted([n for n in COL if META[n]['c']==c and n not in st.atlas and st.can(n)],key=lambda n:(META[n]['gi'],n))
  while remaining and st.completion()['score']<70:st.register(remaining.pop(0))
  p70=snap(st,f'C{c:02d}守关准备');p50=min(local,key=lambda p:abs(p['completion']['score']-50))
  rich=copy.deepcopy(st);rich.branch=f'C{c:02d}高完成度分支'
  for n in remaining:
   if rich.completion()['score']>=90:break
   rich.register(n)
  rich.grow(1);p90=snap(rich,f'C{c:02d}高完成度');side_events += rich.events[len(st.events):]
  gate=next(m for m in M if m['c']==c and m['role']=='守关BOSS');PREMON[gate['id']]=p70['id']
  CHECKS.append({'type':'必做合成全部在当前守关前','c':c,'pass':all(n in st.made for n,r in CR.items() if r['c']==c)})
  st.dead.add(gate['id']);st.log('守关击杀',gate['id'],note='唯一跨大陆硬条件，无完成度传送检查')
  if c in (2,3,5,7,9):st.fates=FATE_ORDER[:min(8,len(st.fates)+1)]
  post=snap(st,f'C{c:02d}守关后_不赠指定掉落')
  CONTREF.append({'c':c,'entry':entry['id'],'p50':p50['id'],'p70':p70['id'],'p90':p90['id'],'post':post['id']})
 out={'profiles':PROFILES,'sources':BANK,'events':st.events+side_events,'map_group_refs':GROUPREF,'continent_refs':CONTREF,
      'monster_reference':PREMON,'checks':CHECKS,'item_meta':META,'completion_weights':WEIGHTS,'collection_rows':list(COL.values()),
      'note':'有明确来源的条件取得路径和耗材需求；不证明无掉率条件下的获取耗时'}
 (ROOT/'results/route.json').write_text(json.dumps(out,ensure_ascii=False,separators=(',',':')))
 print(json.dumps({'profiles':len(PROFILES),'sources':len(BANK),'events':len(out['events']),'checks':CHECKS,'scores':[[PROFILES[int(r[k][1:])-1]['completion']['score'] for k in ['p50','p70','p90']] for r in CONTREF]},ensure_ascii=False,indent=2))
if __name__=='__main__':run()
