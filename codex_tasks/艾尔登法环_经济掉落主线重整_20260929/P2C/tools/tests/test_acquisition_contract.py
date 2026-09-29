import unittest
from acquisition_contract import required_for_player

class AcquisitionContract(unittest.TestCase):
    def test_peer_cannot_force_previously_seen_item_to_be_refarmed(self):
        self.assertEqual(required_for_player({}, {'A':1}, {'A':1}, {}, [{'A':1},{}]), {})
    def test_past_seen_items_need_not_be_held(self):
        self.assertEqual(required_for_player({}, {'A':1}, {'A':1}, {}), {})
    def test_one_missing_item_required(self):
        self.assertEqual(required_for_player({}, {'A':1}, {}, {}), {'A':1})
    def test_prefix_still_protects_current_recipe_and_worn_items(self):
        self.assertEqual(required_for_player({'A':3}, {'A':1}, {'A':10}, {'A':1}), {'A':3})
    def test_cumulative_goal_only_requires_unseen_remainder(self):
        self.assertEqual(required_for_player({}, {'A':5}, {'A':3}, {'A':1}), {'A':3})
    def test_independent_goals_do_not_merge_materials(self):
        self.assertEqual(required_for_player({}, {'A':1,'B':1}, {'A':1}, {}), {'B':1})
    def test_preserves_inputs(self):
        prefix={'A':2};goals={'B':1};seen={};stock={}
        required_for_player(prefix,goals,seen,stock)
        self.assertEqual((prefix,goals,seen,stock),({'A':2},{'B':1},{},{}))

if __name__=='__main__':unittest.main()
