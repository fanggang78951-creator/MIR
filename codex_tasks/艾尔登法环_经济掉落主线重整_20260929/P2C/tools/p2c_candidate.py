"""One narrow economy experiment. This does not authorize a server deployment."""
from copy import deepcopy

def currency_candidate(triggers):
    out=deepcopy(triggers);diff=[]
    for t in out:
        if (t.get('item')=='黄金叶脉' and t.get('continent')==9
                and not t.get('members') and t.get('denominator',0)>1):
            old=t['denominator'];t['denominator']=old*2
            diff.append({'id':t['id'],'monster':t.get('monster_name'),
                'item':t['item'],'old_N':old,'new_N':t['denominator'],
                'reason':'候选：C9阶段现金富余集中；仅降低非必掉货币主材命中率，不改回收单价或NPC费。'})
    return out,diff
