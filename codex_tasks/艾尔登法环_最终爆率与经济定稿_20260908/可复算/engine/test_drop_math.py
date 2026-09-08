import unittest
from drop_math import effective_p, expected_per_kill, pool_amounts, recyclable_surplus
class MathTests(unittest.TestCase):
 def test_cap(self): self.assertEqual(effective_p(50,100),1.0)
 def test_base(self): self.assertAlmostEqual(effective_p(600,12),.02)
 def test_whip_once(self): self.assertAlmostEqual(expected_per_kill(600,12,8,.1),.176)
 def test_single_choice_pool(self):
  r=pool_amounts(100,10,.1,{'A':1,'B':1,'C':1})
  self.assertAlmostEqual(sum(r.values()),.11)
 def test_no_double_count(self): self.assertEqual(recyclable_surplus(10,4,3),3)
 def test_shortage(self): self.assertEqual(recyclable_surplus(2,4,3),0)
 def test_invalid(self):
  with self.assertRaises(ValueError):effective_p(0,12)
if __name__=='__main__':unittest.main()
