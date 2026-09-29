"""Sep29 contract layer over R1 canonical triggers; not a new TXT parser or engine.
Only emits a non-deployable structure candidate. Source ZIP and live server are never written.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path
from zipfile import ZipFile

def _integer(value):
    return type(value) is int and value > 0

def normalize_material_units(triggers, material_names):
    result=copy.deepcopy(triggers)
    for t in result:
        if not t.get("members") and t.get("item") in material_names:
            if not _integer(t.get("quantity")):
                raise ValueError(f"Invalid material quantity: {t.get('id')}")
            t["quantity"]=1
    return result

def validate_contract(triggers, material_names, standard_tiers, baseline=None):
    errors=[]; ids=set(); material_counts=Counter(); tier_counts=Counter()
    for t in triggers:
        tid=t.get("id")
        if not isinstance(tid,str) or not tid or tid in ids:
            errors.append(f"ID_INVALID:{tid}")
        ids.add(tid)
        mid=t.get("monster_id")
        if not isinstance(mid,str) or not mid:
            errors.append(f"MONSTER_ID_INVALID:{tid}")
        if not _integer(t.get("denominator")):
            errors.append(f"DENOMINATOR_INVALID:{tid}")
        if not _integer(t.get("quantity")):
            errors.append(f"QUANTITY_INVALID:{tid}")
        members=t.get("members",{})
        if not isinstance(members,dict):
            errors.append(f"MEMBERS_INVALID:{tid}"); continue
        if members:
            if any(not isinstance(n,str) or not n or not _integer(w) for n,w in members.items()):
                errors.append(f"WEIGHT_INVALID:{tid}")
            if t.get("quantity")!=1:
                errors.append(f"RANDOM_QUANTITY:{tid}")
            if set(members)&set(material_names):
                errors.append(f"MATERIAL_RANDOM:{tid}")
            for tier in {standard_tiers[n] for n in members if n in standard_tiers}:
                tier_counts[mid,tier]+=1
        else:
            item=t.get("item")
            if not isinstance(item,str) or not item:
                errors.append(f"ITEM_INVALID:{tid}"); continue
            if item in material_names:
                if t.get("quantity")!=1:
                    errors.append(f"MATERIAL_BATCH:{tid}")
                material_counts[mid,item]+=1
            if item in standard_tiers:
                tier_counts[mid,standard_tiers[item]]+=1
    errors += [f"MATERIAL_REPEAT:{mid}:{name}" for (mid,name),n in material_counts.items() if n>1]
    errors += [f"STANDARD_TIER_REPEAT:{mid}:{tier}" for (mid,tier),n in tier_counts.items() if n>1]
    if baseline is not None:
        original={t["id"]:t for t in baseline}
        if ids!=set(original):
            errors.append("SOURCE_IDS")
        for t in triggers:
            expected=copy.deepcopy(original.get(t["id"],{}))
            if expected and not expected.get("members") and expected.get("item") in material_names:
                expected["quantity"]=1
            if t!=expected:
                errors.append(f"SOURCE_DRIFT:{t['id']}")
    return errors

def expected_objects(triggers, multiplier):
    """One normal round in the archived multiplier model; no server-load claim."""
    m=Fraction(str(multiplier))
    if m<0:
        raise ValueError("Multiplier must not be negative")
    total=Fraction()
    for t in triggers:
        if not _integer(t["denominator"]) or not _integer(t["quantity"]):
            raise ValueError("Invalid numeric field")
        total+=min(Fraction(1),m/t["denominator"])*(1 if t["members"] else t["quantity"])
    return total

def _write(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")

def build(source_zip,out):
    out=Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be empty; refusing to overwrite")
    out.mkdir(parents=True,exist_ok=True)
    raw=Path(source_zip).read_bytes()
    with ZipFile(source_zip) as z:
        payload=z.read("复算证据/联调候选.json")
        fixed=z.read("复算证据/固定输入.json")
        source=json.loads(payload); inputs=json.loads(fixed)
    ts=source["triggers"]
    mats={t["item"] for t in ts if t["category"]=="材料独立候选"}|{"战灰"}
    tiers={n:s["id"] for s in inputs["sets"] for n in s["names"]}
    candidate=normalize_material_units(ts,mats)
    errors=validate_contract(candidate,mats,tiers,ts)
    if errors:
        raise ValueError(f"Contract failed: {errors[:20]}")
    changes=[{"id":b["id"],"monster_id":b["monster_id"],"monster":b["monster_name"],
              "continent":b["continent"],"material":b["item"],"old_quantity":b["quantity"],
              "candidate_quantity":a["quantity"],"denominator_unchanged":b["denominator"]}
             for b,a in zip(ts,candidate) if b!=a]
    old_dream={"普通":20000000,"稀有":5000000,"地图BOSS":200000,"守关BOSS":40000}
    drift=[{"id":t["id"],"monster":t["monster_name"],"R1_denominator":t["denominator"],
            "historical_role_denominator":old_dream[source["monsters"][t["monster_id"]]["role"]]}
           for t in ts if t["category"]=="六神器公共池" and
           t["denominator"]!=old_dream[source["monsters"][t["monster_id"]]["role"]]]
    ash=[t for t in candidate if t["item"]=="战灰"]
    assert len(ash)==10 and sorted(t["continent"] for t in ash)==list(range(1,11))
    assert [t["denominator"] for t in sorted(ash,key=lambda t:t["continent"])]==[598,745,587,745,330,407,254,311,1,1]
    frozen=[t for t in ts if t["category"]=="六神器公共池" or t["item"]=="战灰"]
    frozen_after=[t for t in candidate if t["category"]=="六神器公共池" or t["item"]=="战灰"]
    assert frozen==frozen_after
    report={"status":"STRUCTURE_ONLY_NOT_DEPLOYABLE","source_zip_sha256":hashlib.sha256(raw).hexdigest(),
            "candidate_source_member_sha256":hashlib.sha256(payload).hexdigest(),
            "fixed_source_member_sha256":hashlib.sha256(fixed).hexdigest(),
            "monsters":len(source["monsters"]),"triggers":len(ts),
            "material_triggers":sum(t["category"]=="材料独立候选" for t in ts),
            "quantity_changes":len(changes),"changed_fields":["quantity"],
            "name_denominator_weight_changes":0,"dream_pools_frozen":len(frozen)-10,
            "ash_triggers_frozen":10,"dream_R1_vs_historical_differences":len(drift),
            "before_contract_errors":len(validate_contract(ts,mats,tiers)),
            "candidate_contract_errors":len(errors),
            "pricing_rebalanced":False,"npc_demand_rebalanced":False,
            "engine_verified":False,"server_written":False}
    _write(out/"drop_structure_candidate.json",{"status":report["status"],"triggers":candidate})
    _write(out/"material_quantity_changes.json",changes)
    _write(out/"dream_version_differences.json",drift)
    _write(out/"P1_drop_result.json",report)
    return report

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-zip",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    print(json.dumps(build(args.source_zip,args.out),ensure_ascii=False,indent=2))
