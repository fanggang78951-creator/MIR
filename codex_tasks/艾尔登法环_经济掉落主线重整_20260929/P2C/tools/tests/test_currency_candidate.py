import unittest
from p2c_candidate import currency_candidate

def trig(tid,item,c,N):
 return {'id':tid,'item':item,'continent':c,'denominator':N,'quantity':1,'members':{}}
class CandidateContract(unittest.TestCase):
 def test_only_c9_non_guaranteed_currency_is_reduced(self):
  rows=[trig('a','黄金叶脉',9,100),trig('b','黄金叶脉',9,1),trig('c','海蚀铁片',1,100),trig('d','战灰',9,1)]
  out,diff=currency_candidate(rows)
  self.assertEqual([t['denominator'] for t in out],[200,1,100,1]);self.assertEqual(len(diff),1)
  self.assertEqual(rows[0]['denominator'],100)
 def test_pool_and_weight_never_changed(self):
  row={**trig('art','@artifact',9,444444),'members':{'神器甲':2,'神器乙':1}}
  self.assertEqual(currency_candidate([row])[0],[row])
 def test_same_name_in_other_continent_is_not_implicitly_changed(self):
  row=trig('x','黄金叶脉',8,100)
  self.assertEqual(currency_candidate([row])[0],[row])
if __name__=='__main__':unittest.main()
