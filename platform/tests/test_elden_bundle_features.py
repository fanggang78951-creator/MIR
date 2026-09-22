from __future__ import annotations

import unittest
import hashlib
import inspect
from pathlib import Path
from unittest import mock

import xydp.elden_bundle_features as features
from xydp.elden_bundle_features import (
    EldenBundleFeatureError,
    compile_rebirth_power_hook,
    compile_rebirth_segment,
    compile_seal_npc,
    compile_combined_title_synthesis,
    compile_opening_variant,
    compile_soul_task,
    compile_task_execution_hook,
    compile_task_toughness_hook,
    compile_title_chain,
    compile_wash_variant,
    load_config_rows,
    load_synthesis_workbooks,
    load_soul_tasks,
    load_wash_open_costs,
    load_war_ash_costs,
    load_v21_progression,
)


ROOT = Path(r"D:\codex临时工作区\elden-npc-v21") / (
    "艾尔登法环_全NPC平台填写_V2.1_20260920-normalized"
)


class EldenBundleProgressionTests(unittest.TestCase):
    def test_war_ash_preflight_reuses_the_current_managed_wash_pipeline(self):
        source = inspect.getsource(features.EldenBundleFeatureService.preflight_progression)

        self.assertIn(
            "render_elden_war_ash_core(\n                _managed_body_or_text(wash_template),",
            source,
        )

    def test_v21_progression_has_255_seals_100_main_titles_12_independent_and_20_rebirths(self):
        data = load_v21_progression(ROOT)

        self.assertEqual(len(data.seal_rows), 255)
        self.assertEqual([len(item.rows) for item in data.seal_npcs], [255, 50, 80, 110, 140, 170, 195, 220, 240, 255])
        self.assertEqual(len(data.main_title_rows), 100)
        self.assertEqual([int(row["档位/等级"]) for row in data.main_title_rows], list(range(1, 101)))
        self.assertEqual(sum(len(chain.rows) for chain in data.independent_titles), 12)
        self.assertEqual(len(data.rebirth_rows), 20)
        self.assertEqual([int(row["档位/等级"]) for row in data.rebirth_rows], list(range(1, 21)))

    def test_seal_compiler_caps_each_npc_but_uses_one_persistent_level(self):
        data = load_v21_progression(ROOT)
        script = compile_seal_npc(data.seal_rows, 50, "神印修行·宁姆格福")

        self.assertIn("CHECKVAR HUMAN XY_SEAL_BASE_LEVEL = 49", script)
        self.assertIn("CALCVAR HUMAN XY_SEAL_BASE_LEVEL = 50", script)
        self.assertNotIn("CALCVAR HUMAN XY_SEAL_BASE_LEVEL = 51", script)
        self.assertIn("本处可修行的最高阶段为50档", script)

    def test_main_title_compiler_enforces_cross_continent_previous_title(self):
        data = load_v21_progression(ROOT)
        all_names = [str(row["称号名称"]) for row in data.main_title_rows]
        c2 = data.main_titles[1]
        script = compile_title_chain(c2.rows, all_names, "EL_MAIN_C02", c2.npc_name)

        self.assertIn(f"CHECKFENGHAO {all_names[9]}", script)
        self.assertIn(f"GIVEFENGHAO {all_names[10]} 1", script)
        self.assertIn(f"RECYCFENGHAO {all_names[9]}", script)
        self.assertNotIn("[@XY_TITLE_ADVANCE_MAIN]", script)

    def test_rebirth_segments_only_serve_their_five_native_levels(self):
        data = load_v21_progression(ROOT)
        titles = [str(row["称号名称"]) for row in data.rebirth_rows]
        segment = compile_rebirth_segment(data.rebirths[2].rows, titles, "EL_REBIRTH_C08", data.rebirths[2].npc_name)
        hook = compile_rebirth_power_hook(data.rebirth_rows, "N$XY_RT_Power")

        self.assertIn("CHECKRENEWLEVEL = 10", segment)
        self.assertIn("CHECKRENEWLEVEL = 14", segment)
        self.assertNotIn("CHECKRENEWLEVEL = 15\n#ACT\nGOTO @EL_REBIRTH_C08_VIEW_16", segment)
        self.assertIn("CHECKRENEWLEVEL > 19", hook)
        self.assertIn("INC N$XY_RT_Power", hook)

    def test_each_catchup_seal_is_an_exact_prefix_of_the_global_255_rows(self):
        data = load_v21_progression(ROOT)
        comparable = ("档位/等级", "攻击", "魔法", "道术", "HP", "材料A", "材料A数量", "货币A", "货币A数量")
        for spec in data.seal_npcs[1:]:
            for expected, actual in zip(data.seal_rows, spec.rows):
                self.assertEqual(
                    tuple(expected.get(key) for key in comparable),
                    tuple(actual.get(key) for key in comparable),
                )

    def test_legacy_takeover_allowlist_is_full_file_exact(self):
        legacy = b"historical-verified-npc"
        with mock.patch.object(features, "LEGACY_ACCEPTED_NPC_SHA256", {hashlib.sha256(legacy).hexdigest()}):
            features._validate_existing_npc(legacy, set())
            with self.assertRaises(EldenBundleFeatureError):
                features._validate_existing_npc(legacy + b"!", set())

    def test_v21_synthesis_keeps_all_16_npcs_and_38_recipes(self):
        workbooks = load_synthesis_workbooks(ROOT)
        self.assertEqual(len(workbooks), 16)
        self.assertEqual(sum(len(workbook.recipes) for _, workbook in workbooks), 38)
        self.assertTrue(all((workbook.settings.x, workbook.settings.y) == (0, 0) for _, workbook in workbooks))

    def test_shared_scavenger_npc_exposes_title_and_synthesis_from_one_main(self):
        combined = compile_combined_title_synthesis(
            "[@Main]\n#IF\n#ACT\nGOTO @EL_IND_C01_VIEW_1\n",
            "[@Main]\n#IF\n#ACT\nGOTO @XY_SYN_PAGE_1\n",
        )
        self.assertEqual(combined.count("[@Main]"), 1)
        self.assertIn("<称号晋升/@EL_IND_C01_TITLE>", combined)
        self.assertIn("<物品合成/@EL_IND_C01_SYNTH>", combined)
        self.assertIn("[@EL_IND_C01_TITLE]", combined)
        self.assertIn("[@EL_IND_C01_SYNTH]", combined)

    def test_economy_ledger_drives_nine_wash_and_opening_costs(self):
        wash, opening = load_wash_open_costs(ROOT)
        self.assertEqual(len(wash), 9)
        self.assertEqual(len(opening), 9)
        self.assertEqual((wash[0].material_amount, wash[0].yuanbao), (1, 1200))
        self.assertEqual((wash[-1].material_amount, wash[-1].yuanbao), (5, 32000))
        self.assertEqual((opening[0].material_amount, opening[0].yuanbao), (6, 6000))
        self.assertEqual((opening[-1].material_amount, opening[-1].yuanbao), (100, 160000))

    def test_economy_ledger_drives_three_native_currency_war_ash_operations(self):
        normal, rare, clear = load_war_ash_costs(ROOT)
        self.assertEqual((normal.gold, normal.yuanbao), (0, 15000))
        self.assertEqual(normal.materials, (("风暴石片", 20), ("失色锻造石", 3)))
        self.assertEqual((rare.gold, rare.yuanbao), (0, 50000))
        self.assertEqual(len(rare.materials), 4)
        self.assertEqual((clear.gold, clear.yuanbao), (100000, 0))
        self.assertEqual(clear.materials, (("失色锻造石", 2),))

    def test_wash_and_opening_variants_are_atomic_and_keep_first_opening_free(self):
        wash_template = Path(
            r"D:\MirServer\Mir200\Envir\Market_Def\玄渊实验室\装备洗练-XY_NMGF_MAIN.txt"
        ).read_bytes().decode("gb18030")
        opening_template = Path(
            r"D:\MirServer\Mir200\Envir\Market_Def\玄渊实验室\装备开光-XY_NMGF_MAIN.txt"
        ).read_bytes().decode("gb18030")
        wash = compile_wash_variant(wash_template, 3, 11000)
        opening = compile_opening_variant(opening_template, 40, 55000)
        self.assertEqual(wash.count("CHECKITEM 失色锻造石 3"), 2)
        self.assertEqual(wash.count("CHECKGAMEGOLD > 10999"), 2)
        self.assertEqual(wash.count("TAKE 失色锻造石 3"), 1)
        self.assertEqual(wash.count("GAMEGOLD - 11000"), 1)
        self.assertIn("首次开光：免费", opening)
        self.assertEqual(opening.count("CHECKITEM 失色锻造石 40"), 1)
        self.assertEqual(opening.count("CHECKGAMEGOLD > 54999"), 1)
        self.assertEqual(opening.count("TAKE 失色锻造石 40"), 1)
        self.assertEqual(opening.count("GAMEGOLD - 55000"), 1)
        managed_wash = features._managed_npc("wash-c07", wash).decode("gb18030")
        managed_opening = features._managed_npc("opening-c07", opening).decode("gb18030")
        self.assertEqual(compile_wash_variant(managed_wash, 3, 11000), wash)
        self.assertEqual(compile_opening_variant(managed_opening, 40, 55000), opening)

    def test_eight_soul_tasks_come_from_the_economy_ledger(self):
        tasks = load_soul_tasks(ROOT)
        self.assertEqual(len(tasks), 8)
        self.assertEqual([len(task.materials) for task in tasks], [4, 4, 5, 4, 4, 4, 4, 5])
        self.assertEqual(tasks[3].map_code, "XX346")
        self.assertEqual(tasks[-1].map_code, "XX144")
        self.assertEqual(tasks[-1].execution_percent, 2)

    def test_c2_soul_task_is_single_use_atomic_and_refreshes_the_panel(self):
        task = load_soul_tasks(ROOT)[3]
        script = compile_soul_task(task)
        self.assertIn(f"CHECKVAR HUMAN {task.variable} = 1", script)
        self.assertIn("CHECKITEM 看门犬石心 2", script)
        self.assertIn("TAKE 看门犬石心 2", script)
        self.assertIn(f"CALCVAR HUMAN {task.variable} = 1", script)
        self.assertIn(f"SAVEVAR HUMAN {task.variable}", script)
        self.assertLess(script.index("CHECKITEM 看门犬石心 2"), script.index("TAKE 看门犬石心 2"))
        self.assertIn("@XY_UI_STATUS_REFRESH", script)
        self.assertIn(f"CHECKVAR HUMAN {task.variable} = 1", compile_task_toughness_hook(load_soul_tasks(ROOT)))
        self.assertIn("INC N$XY_EXEC_ChanceBP 200", compile_task_execution_hook(load_soul_tasks(ROOT), "N$XY_EXEC_ChanceBP"))
        self.assertIn("INC N$XY_UI_C_Value02 2", compile_task_execution_hook(load_soul_tasks(ROOT), "N$XY_UI_C_Value02"))


if __name__ == "__main__":
    unittest.main()
