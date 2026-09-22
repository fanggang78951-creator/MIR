import unittest
from pathlib import Path
from xydp.equipment_wash import render_main_script,render_random_core,render_direct_script,parse_wash_affix_text,DIRECT_SPECS
from tests.wash_runtime_model import ScriptModel,random_path

ROOT=Path(__file__).resolve().parents[1]
BUSY='N$XY_WASH_BUSY_V2'
OLD_BUSY='N$XYEW_W_洗练CD'
OPEN_BUSY='N$XYEW_O_开光锁'

def programs():
    template=(ROOT/'packages/verified/xy.optional.equipment-wash-opening/payload/server/npc/装备洗练.txt').read_text(encoding='utf-8').format_map({})
    catalog=parse_wash_affix_text((ROOT/'所需材料表格汇总/洗练属性.txt').read_text(encoding='utf-8-sig'))
    result={'main':render_main_script(template),'洗练词条随机核心.txt':render_random_core(catalog)}
    result['open']=(ROOT/'packages/verified/xy.optional.equipment-wash-opening/payload/server/npc/装备开光.txt').read_text(encoding='utf-8').format_map({})
    for filename,*args in DIRECT_SPECS: result[filename]=render_direct_script(*args)
    return result


class RuntimeModelContractTests(unittest.TestCase):
    def test_goto_returns_and_flat_if_is_not_nested(self):
        model=ScriptModel({'main':'[@a]\n#ACT\nGOTO @b\nMOV N$after 1\nBREAK\n[@b]\n#IF\nEQUAL 0 1\n#ACT\nMOV N$bad 1\n#IF\n#ACT\nMOV N$inner 1\nRETURN\nMOV N$bad2 1\n'})
        model.execute('main','a')
        self.assertEqual(model.state,{'N$inner':1,'N$after':1})


class WashRuntimeFlowTests(unittest.TestCase):
    def model(self,**kwargs): return ScriptModel(programs(),chance=random_path(**kwargs))

    def test_real_random_selector_reaches_each_normal_category_in_both_boxes(self):
        expected=[43,44,45,46,47,48,49,50,0,0,51,52,53,54,55]
        for box in (27,28):
            for category,line in enumerate(expected):
                with self.subTest(box=box,category=category):
                    m=self.model(category=category);m.execute('洗练词条随机核心.txt',f'XY_WASH_PICK_{box}')
                    self.assertEqual(m.state.get('N$XY_WASH_PICK_LINE'),line)
                    self.assertGreater(m.state.get('N$XY_WASH_PICK_VALUE',0),0)
                    self.assertEqual(m.state.get('N$XY_WASH_PICK_NATIVE'),{8:0,9:21}.get(category,-1))

    def test_special_roll_and_next_normal_roll_reset_picker_state(self):
        m=self.model(breakthrough=True);m.state['N$XY_WASH_PICK_NATIVE']=21
        m.execute('洗练词条随机核心.txt','XY_WASH_PICK_27')
        self.assertEqual([m.state.get('N$XY_WASH_PICK_'+x) for x in ('LINE','VALUE','NATIVE')],[40,1,-1])
        m.chance=random_path(category=1);m.execute('洗练词条随机核心.txt','XY_WASH_PICK_28')
        self.assertEqual(m.state['N$XY_WASH_PICK_LINE'],44)

    def test_full_button_first_and_second_click_write_before_success(self):
        m=self.model()
        for click in range(2):
            start=len(m.events);m.execute('main','XYEW_WASH_EXEC');m.drain()
            self.assertEqual(m.gold,10000-(click+1)*100)
            self.assertEqual(set(m.items[27]['rows']),{0})
            self.assertEqual(m.state.get(BUSY,0),0)
            events=m.events[start:]
            success=[i for i,e in enumerate(events) if len(e)==5 and e[3]=='SENDMSG' and '成功' in ' '.join(e[4])]
            commits=[i for i,e in enumerate(events) if len(e)==4 and e[1]=='snapshot' and e[3]['rows']]
            self.assertEqual(len(success),1)
            self.assertTrue(commits and max(commits)<success[0],'success must follow final item refresh')
        self.assertFalse(m.queue)

    def test_busy_operation_blocks_and_sequential_clicks_are_synchronous(self):
        m=self.model();m.state[BUSY]=1
        m.execute('main','XYEW_WASH_EXEC')
        self.assertEqual(m.gold,10000);self.assertFalse(m.queue)
        m.state[BUSY]=0
        for expected_gold in (9900,9800):
            m.execute('main','XYEW_WASH_EXEC')
            self.assertEqual(m.gold,expected_gold)
            self.assertEqual(m.state[BUSY],0);self.assertFalse(m.queue)

    def test_legacy_stuck_cd_is_preserved_and_does_not_block_new_wash(self):
        m=self.model();m.state[OLD_BUSY]=1;m.state['N$UNRELATED_BUSY']=1
        for _ in range(2):m.execute('main','XYEW_WASH_EXEC');m.drain()
        self.assertEqual(m.gold,9800);self.assertEqual(m.state[OLD_BUSY],1)
        self.assertEqual(m.state['N$UNRELATED_BUSY'],1)
        self.assertEqual(m.state.get(BUSY),0)

    def test_commit_zero_one_seven_eight_rows_releases_but_only_valid_result_refreshes(self):
        for count in (0,1,7,8):
            with self.subTest(count=count):
                m=self.model();m.state[BUSY]=1;m.state[OLD_BUSY]=1
                m.state['N$XYEW_W_洗练星星']=count;m.state['N$XY_WASH_EXPECTED']=count
                for i in range(count):m.state.update({f'N$XY_WASH_LINE{i}':43,f'N$XY_WASH_VALUE{i}':3,f'N$XY_WASH_NATIVE{i}':-1})
                m.execute('main','洗练给予属性')
                self.assertEqual(m.state.get(BUSY),0)
                self.assertEqual(m.items[27]['stars'],count)
                self.assertEqual(set(m.items[27]['rows']),set(range(count)))
                self.assertEqual(any(e[1]=='snapshot' for e in m.events),count>0)
                success=[e for e in m.events if len(e)==5 and e[3]=='SENDMSG' and '成功' in ' '.join(e[4])]
                self.assertEqual(len(success),int(count>0))

    def test_all_direct_entries_really_pick_every_slot_and_finish(self):
        for filename,label,box,quality,color,stars,message in DIRECT_SPECS:
            for category in (0,8,9):
                with self.subTest(entry=filename,category=category):
                    m=self.model(category=category);m.state[BUSY]=1;m.state[OLD_BUSY]=1;m.state[OPEN_BUSY]=1
                    m.execute(filename,label)
                    calls=[e for e in m.events if len(e)==5 and e[3]=='#CALL' and e[4][-1]==f'@XY_WASH_PICK_{box}']
                    self.assertEqual(len(calls),stars)
                    self.assertEqual(m.items[box]['stars'],stars)
                    self.assertTrue(any(e[1]=='snapshot' for e in m.events))
                    if category==0:self.assertEqual(set(m.items[box]['rows']),set(range(stars)))
                    else:self.assertGreater(m.items[box]['native'].get({8:0,9:21}[category],0),0)
                    self.assertEqual(m.state[OLD_BUSY],1)
                    self.assertEqual(m.state[BUSY],0 if box==27 else 1)
                    self.assertEqual(m.state[OPEN_BUSY],0 if box==28 else 1)

    def test_empty_item_and_insufficient_gold_do_not_lock_or_charge(self):
        for empty,gold in ((True,10000),(False,99)):
            m=self.model();m.gold=gold
            if empty:m.items[27]['NAME']=''
            m.execute('main','XYEW_WASH_EXEC');m.drain()
            self.assertEqual(m.gold,gold);self.assertEqual(m.state.get(BUSY,0),0)
            self.assertFalse(m.queue)

    def test_normal_dispatch_does_not_execute_unselected_nested_conditions(self):
        for category,expected in ((1,44),(3,46),(14,55)):
            m=self.model(category=category)
            m.execute('洗练词条随机核心.txt','XY_WASH_PICK_NORMAL_27')
            self.assertEqual(m.state.get('N$XY_WASH_PICK_LINE'),expected)

    def test_low_attack_magic_tao_are_excluded_without_recursive_imports(self):
        for box in (27,28):
            m=ScriptModel(programs(),chance=lambda name,label,cmd,args: cmd!='RANDOM' and args!=['1','1000'])
            m.items[box].update(HDC=0,HMC=1,HSC=0)
            m.execute('洗练词条随机核心.txt',f'XY_WASH_PICK_{box}')
            self.assertEqual(m.state['N$XY_WASH_PICK_LINE'],46)
            self.assertFalse(any(len(e)==5 and e[3]=='GOTO' for e in m.events))
            self.assertLess(m.steps,400)

    def test_numeric_tiers_are_executed_including_last_fallback(self):
        for category,values in ((3,(1,2)),(7,(10,20)),(12,(1,2,3)),(13,(1,2,3)),(14,(1,2,3))):
            for tier,value in enumerate(values):
                m=self.model(category=category,tier=tier)
                m.execute('洗练词条随机核心.txt','XY_WASH_PICK_27')
                self.assertEqual(m.state.get('N$XY_WASH_PICK_VALUE'),value)

    def test_full_button_direct_and_unopened_quality_paths_release_only_new_lock(self):
        for quality,stars,rows in (('仙级',5,5),('圣级',6,6),('天赐',7,0),('神佑',8,0)):
            with self.subTest(quality=quality):
                m=self.model(quality=quality);m.state[OLD_BUSY]=1
                m.execute('main','XYEW_WASH_EXEC');m.drain()
                self.assertEqual(m.gold,9900)
                self.assertEqual(m.items[27]['stars'],stars)
                self.assertEqual(len(m.items[27]['rows']),rows)
                self.assertEqual(m.state.get(BUSY),0)
                self.assertEqual(m.state[OLD_BUSY],1)
                snapshots=[i for i,e in enumerate(m.events) if len(e)==4 and e[1]=='snapshot' and e[3]['stars']==stars]
                notices=[i for i,e in enumerate(m.events) if len(e)==5 and e[3]=='MESSAGEBOX' and quality in str(m.value(' '.join(e[4])))]
                self.assertEqual(len(notices),1)
                self.assertTrue(snapshots and max(snapshots)<notices[0])

    def test_empty_picker_result_cannot_destroy_commit_item_or_claim_success(self):
        m=self.model();m.state[BUSY]=1
        m.items[27]['rows']={0:(55,3,0)};m.items[27]['stars']=4
        m.execute('main','洗练给予属性')
        self.assertEqual(m.state[BUSY],0)
        self.assertEqual(m.items[27]['rows'],{0:(55,3,0)})
        self.assertEqual(m.items[27]['stars'],4)
        notices=[e for e in m.events if len(e)==5 and e[3] in ('MESSAGEBOX','SENDMSG')]
        self.assertTrue(any('失败' in ' '.join(e[4]) for e in notices))
        self.assertFalse(any('成功' in ' '.join(e[4]) for e in notices))

    def test_native_only_result_is_valid_even_without_text_line(self):
        for category,native in ((8,0),(9,21)):
            m=self.model(category=category)
            m.execute('main','XYEW_WASH_EXEC');m.drain()
            self.assertEqual(m.items[27]['rows'],{})
            self.assertGreater(m.items[27]['native'].get(native,0),0)
            self.assertEqual(m.state.get(BUSY),0)
            self.assertTrue(any(len(e)==5 and e[3]=='SENDMSG' and '成功' in ' '.join(e[4]) for e in m.events))

    def test_box28_real_entry_acquires_and_releases_only_its_own_lock(self):
        for quality,stars in (('神佑',8),('天赐',7)):
            m=self.model();m.state[BUSY]=1;m.state[OLD_BUSY]=1
            for _ in range(2):
                m.items[28]['text']=f'[装备品质:{quality}未开光]'
                start=len(m.events);m.execute('open','XYEW_OPEN_EXEC');m.drain()
                self.assertEqual(m.items[28]['stars'],stars)
                self.assertEqual(m.state[OPEN_BUSY],0)
                self.assertEqual(m.state[BUSY],1);self.assertEqual(m.state[OLD_BUSY],1)
                changes=[e[4] for e in m.events[start:] if len(e)==5 and e[3]=='MOV' and e[4][0]==OPEN_BUSY]
                self.assertEqual(changes,[(OPEN_BUSY,'1'),(OPEN_BUSY,'0')])
