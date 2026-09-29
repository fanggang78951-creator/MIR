"""Small, explicit candidates following P2A single-item conversion; no deployment output."""
from copy import deepcopy
from collections import Counter
from decimal import Decimal,ROUND_HALF_UP

def candidate(source):
 out=deepcopy(source);changes=[]
 divisors={'大卢恩':20,'巨人熔火卢恩':20,'黄金律法卢恩':17,
           '西境战旗印':2,'沉湖王印':3,'深湖压舱印':3,'满月王室印':3,
           '红狮战印':5,'圣雪誓印':4,'巨人火印':4,'黄金律印':7,'艾尔登王印':13}
 def reduced(mat,q):
  return max(1,int((Decimal(str(q))/Decimal(divisors[mat])).quantize(Decimal(1),rounding=ROUND_HALF_UP)))
 for op in out['operations']:
  if not op.get('candidate_materials') or op['historical_stage']<3:continue
  for mat in divisors:
   if mat in op['candidate_materials']:
    old=op['candidate_materials'][mat];new=reduced(mat,old)
    op['candidate_materials'][mat]=new
    changes.append({'id':op['id'],'item':mat,'old_quantity':old,'new_quantity':new,
                    'basis':'核对R1本阶段地图BOSS原单次批量，改单件后同步缩小既有操作用量；这是候选而非数量精确等价，不加新材料或改合成关系',
                    'source_batch_divisor':divisors[mat],'candidate_not_approved_target':True,'actually_changed':old!=new})
 for tx in out['repriced_reference_transactions']:
  if tx['c']<3:continue
  for mat in divisors:
   if mat in tx['materials']:
    old=tx['materials'][mat];new=reduced(mat,old);tx['materials'][mat]=new
    out['revised_reference_materials'][mat]+=new-old
 out['P2B_quantity_changes']=changes
 return out

def reduce_clear_surplus(out):
 """Documented candidate: reduce two global skill-material rates, no sources removed."""
 result=deepcopy(out);changes=[]
 factors={'野兽骨片':8,'技能残页':12}
 for t in result['triggers_trial']:
  if not t.get('members') and t['item'] in factors:
   old=t['denominator'];t['denominator']=old*factors[t['item']]
   changes.append({'id':t['id'],'monster':t['monster_name'],'material':t['item'],'old_N':old,'new_N':t['denominator'],
                   'basis':'P2A使用量已压缩、但基础分母仍旧值；本轮候选先减少广泛富余，保留所有大陆来源，须随机路径复核',
                   'design_choice_factor':factors[t['item']]})
 result['P2B_drop_changes']=changes
 return result
