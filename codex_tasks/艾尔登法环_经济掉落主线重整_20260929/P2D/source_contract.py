"""Rebuild P2C reference profiles from named sources, never from unexplained residuals.
This is an accounting overlay, not a live game reward/fee writer.
"""
from __future__ import annotations
import copy
import legacy_math as L


def growth_names(c: int, level: int) -> list[str]:
    if type(c) is not int or not 1 <= c <= 10:
        raise ValueError('Invalid continent')
    if type(level) is not int or not 1 <= level <= 10:
        raise ValueError('A documented integer growth level is required')
    stems = ('圣律之剑', '黄金圣物') if c == 1 else ('圣律真言', '黄金之心')
    return [f'{stem}LV{level}' for stem in stems]


def rebuild_profile(p, old, sources, equipment, atlas, level, include_affixes=True):
    """Use declared worksheet level and current equipment; do not use p.raw/old.raw.
    Legacy equipment/growth/wash source blocks are replaced, not accumulated twice.
    External paid/fate inputs stay labelled external; their acquisition is not certified.
    """
    rows=[]
    for sid in old['sources']:
        s=sources[sid];cat=s['category']
        if cat in ('装备','成长装备','洗练'):
            continue
        stats = (atlas['pages'][s['key']] if cat=='地图整页' else
                 atlas['items'][s['key']] if cat=='单件图鉴' else s['stats'])
        rows.append({'category':cat,'key':s['key'],'origin_source_id':sid,
                     'origin':'current_atlas_projection' if cat in ('地图整页','单件图鉴') else 'V2.1/final.json/sources',
                     'stats':copy.deepcopy(stats)})
    for e in p['gear']:
        rows.append({'category':'装备','key':e['name'],'instance':e.get('instance'),
                     'origin':'R1/equipment','stats':L.stats_from_gear(equipment[e['name']])})
        if include_affixes and e.get('affixes'):
            stats={}
            for a in e['affixes']:
                mapped=L.stat_attr(a['attribute'],a['value'])
                if not mapped:raise ValueError('Unknown affix attribute '+str(a))
                for k,v in mapped.items():stats[k]=stats.get(k,0)+v
            rows.append({'category':'洗练_归档参考非主线扣费','key':e['name'],'instance':e.get('instance'),
                         'origin':'R1/fixed/profiles/gear/affixes','stats':stats})
    for name in growth_names(p['c'],level):
        rows.append({'category':'成长装备_当前逐级','key':name,'level':level,
                     'origin':'R1/equipment + 03_336配装复核/成长等级_情景',
                     'stats':L.stats_from_gear(equipment[name])})
    raw=L.sumstats(rows)
    return {'pid':p['id'],'level':level,'include_reference_affixes':bool(include_affixes),
            'raw':raw,'lines':rows,'runtime_verified':False}


def late_rune_candidate(triggers):
    """Static source-continent taper only, not conditional on individual player progress.
    Fourfold denominator is a design candidate. Earlier sources, all rewards, names,
    quantities and other materials/pools stay untouched. Caller must apply to P2C baseline.
    """
    out=copy.deepcopy(triggers)
    after={'小卢恩':4,'大卢恩':6}
    for t in out:
        if (t.get('category')=='材料独立候选' and not t.get('members') and
            t.get('item') in after and t['continent']>after[t['item']]):
            den=t['denominator']
            if type(den) is not int or den<=0:raise ValueError('Invalid denominator')
            if t.get('quantity') != 1:raise ValueError('Material must remain single unit')
            t['denominator']=den*4
    return out
