"""Recheck the packaged player data. No third-party dependency or server access."""
from pathlib import Path
from collections import defaultdict,Counter
import json,math,sys
BASE=Path(__file__).resolve().parent
D=json.loads((BASE/"40组半急速人物_完整数据.json").read_text(encoding="utf-8"))
P=D["profiles"];check=[]
def require(name,condition):
    check.append({"name":name,"pass":bool(condition)})
require("40 unique profiles",len(P)==40 and len({p["id"] for p in P})==40)
for p in P:
    total=defaultdict(float)
    for source in p["sources"]:
        for key,value in source["stats"].items():total[key]+=value
    for key,value in p["raw"].items():
        require(p["id"]+" source "+key,math.isclose(total[key],value,abs_tol=1e-7,rel_tol=1e-10))
    require(p["id"]+" rainbow",all(f["quality"]==5 for f in p["meta"]["fates"]))
    slots=[g["slot"] for g in p["meta"]["gear"]]
    require(p["id"]+" slots unique",len(slots)==len(set(slots)))
    raw=p["raw"];derived=p["derived"]
    require(p["id"]+" attack formula",math.isclose(
        derived["面板攻击上限"],raw["攻击上限"]*(1+raw["攻击加成"]/100),rel_tol=1e-10))
    require(p["id"]+" hp formula",math.isclose(
        derived["HP"],raw["HP"]*(1+raw["HP百分比"]/100),rel_tol=1e-10))
    material=Counter();gold=yuan=0
    for payment in p["payments"]:
        if payment["route"]=="自产":
            gold+=payment["gold"];yuan+=payment["yuan"];material.update(payment["mats"])
    require(p["id"]+" gold ledger",math.isclose(gold,p["gold_total"]))
    require(p["id"]+" yuan ledger",math.isclose(yuan,p["yuan_total"]))
    for key in set(material)|set(p["required_materials"]):
        require(p["id"]+" material "+key,math.isclose(material[key],p["required_materials"].get(key,0)))
    require(p["id"]+" finite derived",all(math.isfinite(v) for v in derived.values()))
fail=[r for r in check if not r["pass"]]
report={"checks":len(check),"failures":len(fail),"failed_items":fail,
        "note":"Core reproducibility check only; full recorded tests and Excel formula checks are separate."}
(BASE/"可重复核心核验.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False))
if fail:sys.exit(1)
