import shutil
import tempfile
import unittest
from pathlib import Path

from tests.test_equipment_wash_import import SOURCE
from xydp.equipment_wash import EquipmentWashImportService, MAIN_RELATIVE, RANDOM_CORE_RELATIVE, parse_wash_affix_text, render_random_core

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'tests/fixtures/equipment_wash_current'


class ExistingWashRegressionTests(unittest.TestCase):
    def test_txt_numeric_changes_reach_the_generated_random_core(self):
        old = render_random_core(parse_wash_affix_text(SOURCE))
        new = render_random_core(parse_wash_affix_text(SOURCE.replace('韧性+20', '韧性+25')))
        self.assertNotEqual(old, new, 'TXT数值变化不能被仅检查属性名的解析器忽略')
        self.assertIn('MOV N$XY_WASH_PICK_VALUE 25', new)

    def test_unknown_numeric_syntax_does_not_silently_use_fixed_values(self):
        with self.assertRaisesRegex(ValueError, 'TXT|韧性|数值'):
            parse_wash_affix_text(SOURCE.replace('韧性+20', '韧性=未知'))

    def test_marker_is_not_proof_that_main_script_is_owned(self):
        with tempfile.TemporaryDirectory() as td:
            server = Path(td) / 'server'
            shutil.copytree(SNAPSHOT, server)
            main = server / MAIN_RELATIVE
            main.write_bytes(main.read_bytes() + b'\r\n; unexpected user edit\r\n')
            plan = EquipmentWashImportService(ROOT).preflight(server, ROOT / '所需材料表格汇总/洗练属性.txt')
            self.assertTrue(any('未知手改' in b and '装备洗练-' in b for b in plan.blockers), plan.blockers)

    def test_generated_comment_is_not_proof_that_random_core_is_owned(self):
        with tempfile.TemporaryDirectory() as td:
            server = Path(td) / 'server'
            shutil.copytree(SNAPSHOT, server)
            core = server / RANDOM_CORE_RELATIVE
            core.write_bytes(core.read_bytes().replace(b'RANDOMEX 1 1000', b'RANDOMEX 1 2'))
            plan = EquipmentWashImportService(ROOT).preflight(server, ROOT / '所需材料表格汇总/洗练属性.txt')
            self.assertTrue(any('未知手改' in b and '随机核心' in b for b in plan.blockers), plan.blockers)
