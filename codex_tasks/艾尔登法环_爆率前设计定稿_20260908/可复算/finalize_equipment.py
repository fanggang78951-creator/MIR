"""Conservative ordinary-gear progression patch; frozen input remains unchanged."""
from pathlib import Path
import json,copy,math,hashlib
B=Path(__file__).resolve().parent
N=json.loads((B/'inputs/normalized.json').read_text())
ORIG=copy.deepcopy(N['gear'])
def pair(x):
 if not x:return [0,0]
 if isinstance(x,(int,float)):return [x,x]
 return list(map(float,str(x).split('-')))
def nice(x,step=1): return int(round(float(x)/step)*step)
def val(g,k):return float(g.get(k) or 0)
# Mainhand flat ceilings: first C3 weapon stays the user's cross-continent anchor.
weapon_targets={3:[560,650,730,810,900,980],4:[780,870,990,1110,1230,1340],5:[1050,1180,1330,1500,1660,1840],6:[1580,1840,2160],7:[1970,2380,2800],8:[2780,3160,3550,3970],9:[3400,3930,4500,5110,5710],10:[4820,5480,6180,6820,7520]}
speed_floor={3:23,4:25,5:26,6:27,7:28,8:29,9:30,10:31}
changes=[]; decisions=[]
for m in N['monsters']:
 if m['c']<3 or m['role']!='普通':continue
 c=m['c'];j=m['group_index'];ng=len(N['groups'][str(c)]);t=j/max(1,ng-1)
 for name in m['items']:
  old=ORIG[name];g=N['gear'][name];part=g['部位']
  if name=='拾骨弯刀':
   decisions.append({'name':name,'decision':'保留C3首图主手跨大陆参照；后续用同组其他部位补位，不强迫淘汰C1/C2强装'})
   continue
  offense=part in ('武器','项链','手镯','戒指','勋章')
  if part=='武器':
   oldlo,oldhi=pair(g['攻击']);baseline=weapon_targets[c][j]
   # Existing high-flat versus high-percent weapon routes are preserved.
   local=[ORIG[n] for mm in N['monsters'] if mm['c']==c and mm['role']=='普通' for n in mm['items'] if ORIG[n]['部位']=='武器']
   highpct=val(old,'攻击加成')>(min(val(x,'攻击加成') for x in local)+max(val(x,'攻击加成') for x in local))/2
   upper=max(oldhi,nice(baseline*(.94 if highpct else 1.04),10))
   for k in ('攻击','魔法','道术'):
    lo,hi=pair(old.get(k));g[k]=f'{nice(upper*(lo/max(1,hi)),10)}-{int(upper)}'
   for k in ('攻击加成','魔法加成','道术加成'):
    g[k]=nice(val(old,k)*(1.04+.12*t),1 if c<=5 else 5)
   for k in ('打怪伤害','暴击伤害','攻击伤害'):
    if val(old,k):g[k]=nice(val(old,k)*(1.08+.18*t),1)
   g['攻击速度']=min(32,max(val(old,'攻击速度'),speed_floor[c]+nice(t*3)))
   policy='普通主手保持高基础/高加成两路线；补足普通攻速，不投放突破/处决/最大爆率'
  else:
   flat=1.04+.36*t
   for k in ('攻击','魔法','道术'):
    lo,hi=pair(old.get(k))
    if hi:g[k]=f'{nice(lo*flat,1 if hi<200 else 5)}-{nice(hi*flat,1 if hi<200 else 5)}'
   for k in ('攻击加成','魔法加成','道术加成'):
    g[k]=nice(val(old,k)*(1.12+.32*t)+(2 if offense else 1)+t*(2+(c-3)*.4))
   for k in ('打怪伤害','暴击伤害','攻击伤害'):
    if val(old,k):g[k]=nice(val(old,k)*(1.12+.28*t)+t*(2 if k!='暴击伤害' else 3))
   # Defense parts improve actual durability instead of getting every damage multiplier.
   hp_factor=(1.18+.44*t) if part=='衣服' else (1.32+.68*t) if not offense else (1.12+.40*t)
   if val(old,'HP'):g['HP']=nice(val(old,'HP')*hp_factor,100 if val(old,'HP')<100000 else 1000)
   for k in ('防御','魔御'):
    lo,hi=pair(old.get(k))
    if hi:g[k]=f'{nice(lo*(1.1+.30*t))}-{nice(hi*(1.1+.30*t))}'
   policy='输出部位增强原有乘区；防具提高HP/攻防；不新增吸收上限或稀有词条'
  decisions.append({'name':name,'c':c,'group':m['group'],'part':part,'decision':policy})
  for k in old:
   if g.get(k)!=old[k]:changes.append({'name':name,'c':c,'group':m['group'],'role':'普通','part':part,'field':k,'old':old[k],'new':g[k],'reason':policy})
# Keep rarity identity: never silently boost rare/boss/crafted pieces.
(B/'results').mkdir(exist_ok=True)
(B/'results/equipment_patch.json').write_text(json.dumps({'changes':changes,'decisions':decisions,'changed_items':len(set(x['name'] for x in changes)),'allowed_roles':['普通'],'source_sha256':hashlib.sha256((B/'inputs/normalized.json').read_bytes()).hexdigest()},ensure_ascii=False,indent=2))
(B/'inputs/normalized_current.json').write_text(json.dumps(N,ensure_ascii=False,separators=(',',':')))
print(json.dumps({'items':len(set(x['name'] for x in changes)),'cells':len(changes)},ensure_ascii=False))
