import unittest
import re

from xydp.equipment_wash import (
    ATTACK_SPEED_BREAKTHROUGH_DENOMINATOR,
    NORMAL_CATEGORY_COUNT,
    ROUTE,
    parse_wash_affix_text,
    render_effect_core,
    render_random_core,
    render_direct_script,
)


SOURCE = """洗练可以洗出的属性包括
1，攻击/魔法/道术，数值为1至该装备最大攻击/魔法/道术的上限的一半。
2攻击速度+1
3攻击速度+2
4处决+1（处决概率加百分之一）
5处决+2
6处决时间+1
7处决伤害+1
8处决时间+2
9处决伤害+2
10韧性+10
11韧性+20
12，暴击+1
13暴击+2
14致命一击+1
15致命一击+2
16.攻击加成1-30
17攻击加成31-50
18吸血+1
19吸血+2
20最大爆率+1
21最大暴率+2
23最大爆率+3
24伤害系数+1
25伤害系数+2
26伤害系数+3
27伤害吸收上限+1
28伤害吸收上限+2
29.伤害吸收上限+3
30攻速突破+1
"""


class EquipmentWashImportTests(unittest.TestCase):
    def test_all_four_external_quality_entries_have_complete_loadable_bodies(self):
        for label, box, quality, color, stars in (
            ('仙级特殊', 27, '仙级', 242, 5),
            ('圣级特殊', 27, '圣级', 249, 6),
            ('天赐特殊', 28, '天赐', 31, 7),
            ('神佑特殊', 28, '神佑', 125, 8),
        ):
            with self.subTest(label=label):
                script = render_direct_script(label, box, quality, color, stars, '成功')
                match = re.search(rf'(?ms)^\[@{label}\]\n\{{\n(.*?)^\}}\s*$', script)
                self.assertIsNotNone(match, '外置入口必须能提取完整的CALL脚本体')
                body = match.group(1)
                self.assertTrue(body.startswith('#IF\n#ACT\n'))
                self.assertEqual(body.count(f'@XY_WASH_PICK_{box}'), stars)
                self.assertIn(f'ChangeItemUpgradeCount boxitem{box} = {stars}', body)
                self.assertTrue(body.rstrip().endswith('BREAK'))

    def test_parser_normalizes_affixes_and_exposes_locked_weights(self) -> None:
        catalog = parse_wash_affix_text(SOURCE)

        self.assertEqual(ROUTE, "equipment-wash-import")
        self.assertEqual(NORMAL_CATEGORY_COUNT, 15)
        self.assertEqual(ATTACK_SPEED_BREAKTHROUGH_DENOMINATOR, 1000)
        self.assertEqual(catalog.find("最大爆率").tiers, ((1, 40), (2, 40), (3, 20)))
        self.assertEqual(catalog.find("攻击速度").tiers, ((1, 80), (2, 20)))
        self.assertEqual(catalog.find("攻击加成").tiers, ((1, 30, 80), (31, 50, 20)))
        self.assertEqual(catalog.find("致命一击").native_new_item_index, 21)

    def test_rendered_cores_keep_the_engine_property_contract(self) -> None:
        catalog = parse_wash_affix_text(SOURCE)
        random_core = render_random_core(catalog)
        effect_core = render_effect_core()

        self.assertIn("RANDOMEX 1 1000", random_core)
        self.assertIn("RANDOMEX 40 100", random_core)
        self.assertIn("RANDOMEX 40 60", random_core)
        self.assertIn("MOVR N$XY_WASH_PICK_VALUE 1 <$STR(N$XY_WASH_PICK_MAX)>", random_core)
        self.assertIn("MOV N$XY_WASH_PICK_NATIVE 21", random_core)
        self.assertIn("LARGE <$BOXITEM[27].HDC> 1", random_core)
        self.assertNotIn("SMALL N$XY_WASH_PICK_MAX 2", random_core)
        self.assertIn("GetAllCustomItemValueByTextLine 60 -1 43", effect_core)
        self.assertIn("ChangeHumAbility 6 =", effect_core)
        self.assertIn("ChangeHumAbilityPercentage 5 =", effect_core)
        self.assertIn("GetAllCustomItemValueByTextLine 60 -1 55", effect_core)
        self.assertIn("INC N$XY_EXEC_Toughness", effect_core)

    def test_external_call_cores_wrap_each_target_label_in_a_script_block(self) -> None:
        catalog = parse_wash_affix_text(SOURCE)
        random_core = render_random_core(catalog)
        effect_core = render_effect_core()

        for label in (
            "XY_WASH_PICK_27",
            "XY_WASH_PICK_28",
        ):
            self.assertIn(f"[@{label}]\n{{", random_core)
        for label in (
            "XY_WASH_APPLY_ABIL",
            "XY_WASH_ADD_ATTACK",
            "XY_WASH_ADD_DROP_UI",
            "XY_WASH_ADD_SUSTAIN",
            "XY_WASH_ADD_TOUGHNESS",
            "XY_WASH_ADD_MONSTER_ABSORB",
        ):
            self.assertIn(f"[@{label}]\n{{", effect_core)


if __name__ == "__main__":
    unittest.main()
