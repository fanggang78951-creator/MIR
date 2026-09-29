import copy
import unittest
from fractions import Fraction
from drop_contract import normalize_material_units, validate_contract, expected_objects

def event(i, item="A", q=1, n=10, members=None, category="材料独立候选"):
    return {"id":i,"monster_id":"m","monster_name":"怪","continent":2,
            "category":category,"item":item,"quantity":q,"denominator":n,"members":members or {}}

class ContractTests(unittest.TestCase):
    mats={"A","B","C","D","战灰"}
    tiers={"剑":1,"衣":1,"盔":1,"新剑":2}
    def test_quantity_is_normalized_without_mutating_source(self):
        src=[event("a",q=40)]
        result=normalize_material_units(src,self.mats)
        self.assertEqual(result[0]["quantity"],1)
        self.assertEqual(src[0]["quantity"],40)
    def test_four_independent_materials_allowed(self):
        ts=[event(str(i),x,n=n) for i,(x,n) in enumerate(zip("ABCD",[10,20,30,40]))]
        self.assertEqual(validate_contract(ts,self.mats,self.tiers),[])
        self.assertEqual(expected_objects(ts,1),Fraction(5,24))
        self.assertEqual(len(normalize_material_units(ts,self.mats)),4)
    def test_batch_material_rejected(self):
        self.assertTrue(any("MATERIAL_BATCH" in s for s in validate_contract([event("a",q=3)],self.mats,self.tiers)))
    def test_material_duplicate_independent_rejected(self):
        self.assertTrue(any("MATERIAL_REPEAT" in s for s in validate_contract([event("a"),event("b")],self.mats,self.tiers)))
    def test_materials_not_merged_into_random(self):
        t=event("a",item="@pool",members={"A":1,"B":1})
        self.assertTrue(any("MATERIAL_RANDOM" in s for s in validate_contract([t],self.mats,self.tiers)))
    def test_weighted_standard_random_allowed(self):
        t=event("s",item="@pool",members={"剑":6,"衣":6,"新剑":3},category="制式装备候选池")
        self.assertEqual(validate_contract([t],self.mats,self.tiers),[])
        self.assertEqual(expected_objects([t],100),1)
    def test_same_tier_in_two_independent_pools_rejected(self):
        a=event("s1",item="@s1",members={"剑":1},category="制式装备候选池")
        b=event("s2",item="@s2",members={"衣":1},category="制式装备候选池")
        self.assertTrue(any("STANDARD_TIER_REPEAT" in s for s in validate_contract([a,b],self.mats,self.tiers)))
    def test_distinct_tiers_and_material_can_coexist(self):
        a=event("s1",item="@s1",members={"剑":1},category="制式装备候选池")
        b=event("s2",item="@s2",members={"新剑":1},category="制式装备候选池")
        self.assertEqual(validate_contract([a,b,event("a")],self.mats,self.tiers),[])
    def test_fractional_or_boolean_quantity_rejected(self):
        for q in [1.5,True,0,-1]:
            self.assertTrue(validate_contract([event("a",q=q)],self.mats,self.tiers))
    def test_nonpositive_denominator_rejected(self):
        self.assertTrue(validate_contract([event("a",n=0)],self.mats,self.tiers))
    def test_invalid_weights_rejected(self):
        for w in [0,-1,1.2,True]:
            t=event("s",item="@pool",members={"剑":w},category="制式装备候选池")
            self.assertTrue(validate_contract([t],self.mats,self.tiers))
    def test_dream_and_ash_unchanged(self):
        a=event("art",item="@dream",members={"神器":1},category="六神器公共池",n=200000)
        b=event("ash","战灰",n=745,category="战灰守关独立")
        src=[a,b]; out=normalize_material_units(src,self.mats)
        self.assertEqual(out,src)
        out[0]["denominator"]=400000
        self.assertTrue(any("SOURCE_DRIFT" in e for e in validate_contract(out,self.mats,self.tiers,src)))
    def test_missing_trigger_rejected_with_baseline(self):
        self.assertTrue(any("SOURCE_IDS" in e for e in validate_contract([],self.mats,self.tiers,[event("a")])))
    def test_idempotent_normalization(self):
        one=normalize_material_units([event("a",q=24)],self.mats)
        self.assertEqual(normalize_material_units(one,self.mats),one)
    def test_probability_clamps_but_does_not_multiply_quantity(self):
        self.assertEqual(expected_objects([event("a",n=5)],100),1)

if __name__ == "__main__":
    unittest.main(verbosity=2)
