"""Per-player acquisition needs; never let another simulation's missing item affect this one."""
from collections import Counter

def required_for_player(prefix, goals, seen, stock, cohort_seen=None):
    """Keep recipe/wear needs; add only this player's unseen cumulative acquisition remainder.
    cohort_seen is retained solely to prove isolation against the earlier interface.
    A previously seen item need not still be held unless required by the current prefix.
    """
    req=Counter(prefix)
    for name,qty in goals.items():
        missing=max(0,qty-seen.get(name,0))
        if missing:
            req[name]=max(req[name],stock.get(name,0)+missing)
    return dict(+req)
