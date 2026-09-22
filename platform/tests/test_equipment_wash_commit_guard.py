import re
import unittest
from copy import deepcopy
from fractions import Fraction
from tests.test_equipment_wash_runtime_flow import programs
from tests.wash_runtime_model import ScriptModel, random_path


class WashCommitGuardTests(unittest.TestCase):
    def test_unimported_external_goto_is_not_silently_granted_by_model(self):
        m=ScriptModel({'main':'[@start]\n#IF\n#ACT\n#CALL [core.txt] @entry\n',
                       'core.txt':'[@entry]\n{\n#IF\n#ACT\nGOTO @sibling\n}\n[@sibling]\n{\n#IF\n#ACT\nMOV N$visited 1\n}\n'})
        with self.assertRaises(AssertionError):m.execute('main','start')

    def test_generated_call_graph_has_no_cycle_or_external_goto(self):
        texts=programs();core=texts['洗练词条随机核心.txt']
        self.assertNotIn('GOTO @',core)
        blocks=ScriptModel(texts).programs['洗练词条随机核心.txt']
        edges={label:re.findall(r'#CALL .*? @([^\s]+)', '\n'.join(lines)) for label,lines in blocks.items()}
        def visit(node,active):
            self.assertNotIn(node,active)
            for child in edges[node]:visit(child,active|{node})
        for node in edges:visit(node,set())

    def test_every_valid_category_and_equal_probability_for_all_ability_masks(self):
        expected=[43,44,45,46,47,48,49,50,0,0,51,52,53,54,55]
        for box in (27,28):
            for mask in range(8):
                valid=[i for i in range(3) if mask & (1<<i)]+list(range(3,15))
                n=len(valid)
                old_probability=Fraction(1,15)/(1-Fraction(15-n,15))
                for ordinal,category in enumerate(valid):
                    with self.subTest(box=box,mask=mask,category=category):
                        seen=[]
                        def chance(name,label,cmd,args):
                            if args==['1','1000']:return False
                            if label==f'XY_WASH_PICK_NORMAL_{box}':
                                seen.append(int(args[1]))
                                return int(args[1])==n-ordinal
                            return random_path(category=category)(name,label,cmd,args)
                        m=ScriptModel(programs(),chance=chance)
                        m.items[box].update({key:20 if mask&(1<<bit) else 0 for bit,key in enumerate(('HDC','HMC','HSC'))})
                        m.execute('洗练词条随机核心.txt',f'XY_WASH_PICK_{box}')
                        self.assertEqual(m.state['N$XY_WASH_PICK_LINE'],expected[category])
                        self.assertEqual(m.state['N$XY_WASH_PICK_NATIVE'],{8:0,9:21}.get(category,-1))
                        self.assertEqual(seen,list(range(n,n-ordinal-1,-1)))
                        probability=Fraction(1,seen[-1])
                        for count in seen[:-1]:probability*=Fraction(count-1,count)
                        self.assertEqual(probability,old_probability)

    def test_first_or_later_empty_result_preserves_money_and_entire_item(self):
        for failed_slot in (1,2,5):
            scripts=programs()
            scripts['洗练词条随机核心.txt']=f'''[@XY_WASH_PICK_27]
{{
#IF
#ACT
INC N$TEST_PICK_COUNT 1
#IF
EQUAL N$TEST_PICK_COUNT {failed_slot}
#ACT
BREAK
#IF
#ACT
MOV N$XY_WASH_PICK_LINE 43
MOV N$XY_WASH_PICK_VALUE 3
MOV N$XY_WASH_PICK_NATIVE -1
BREAK
}}
'''
            m=ScriptModel(scripts,chance=random_path(quality='仙级'))
            m.items[27].update(text='旧品质',color=99,stars=8,rows={7:(55,3,0)},native={0:7,21:4})
            before=deepcopy(m.items[27])
            m.execute('main','XYEW_WASH_EXEC')
            self.assertEqual(m.items[27],before)
            self.assertEqual(m.gold,10000)
            self.assertEqual(m.state['N$XY_WASH_BUSY_V2'],0)
            self.assertFalse(m.queue)
            self.assertFalse(any(len(e)==5 and (e[3]=='GAMEGOLD' or e[3].startswith('SETCUSTOMITEM') or e[3]=='SETNEWITEMVALUE') for e in m.events))

    def test_success_charges_after_all_picks_before_first_item_mutation(self):
        m=ScriptModel(programs(),chance=random_path(quality='圣级',category=8))
        m.execute('main','XYEW_WASH_EXEC')
        events=[e for e in m.events if len(e)==5]
        fees=[i for i,e in enumerate(events) if e[3]=='GAMEGOLD']
        picks=[i for i,e in enumerate(events) if e[3]=='#CALL' and e[4][-1]=='@XY_WASH_PICK_27']
        writes=[i for i,e in enumerate(events) if e[3].startswith('SETCUSTOMITEM') or e[3]=='SETNEWITEMVALUE']
        self.assertEqual(len(fees),1);self.assertEqual(len(picks),6)
        self.assertLess(max(picks),fees[0]);self.assertLess(fees[0],min(writes))
        self.assertEqual(m.gold,9900);self.assertGreater(m.items[27]['native'][0],0)

    def test_all_rolled_quality_row_counts_finish_without_timers(self):
        for quality,lo,hi in [('灵级',1,3),('上古',2,4),('传说',2,5)]:
            for count in range(lo,hi+1):
                m=ScriptModel(programs(),chance=random_path(quality=quality),
                    movr=lambda variable,low,high:count if variable=='N$XYEW_W_属性条数' else low)
                m.execute('main','XYEW_WASH_EXEC')
                self.assertEqual(len(m.items[27]['rows']),count)
                self.assertEqual(m.gold,9900);self.assertFalse(m.queue)
                self.assertEqual(m.state['N$XY_WASH_BUSY_V2'],0)


if __name__=='__main__':unittest.main()
