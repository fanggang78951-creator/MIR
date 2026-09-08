"""Pure functions; probabilities are capped before the single additional corpse roll."""
def effective_p(denominator: int, multiplier: float) -> float:
 if denominator < 1 or multiplier < 0: raise ValueError('invalid probability input')
 return min(1.0,multiplier/denominator)
def expected_per_kill(denominator: int,multiplier:float,quantity:int=1,whip:float=0)->float:
 if quantity<1 or not 0<=whip<=1: raise ValueError('invalid quantity or corpse chance')
 return effective_p(denominator,multiplier)*quantity*(1+whip)
def pool_amounts(denominator,multiplier,whip,weights):
 total=sum(weights.values())
 if total<=0:raise ValueError('empty weights')
 return {name:expected_per_kill(denominator,multiplier,1,whip)*w/total for name,w in weights.items()}
def recyclable_surplus(produced,retained,consumed):return max(0,produced-retained-consumed)
