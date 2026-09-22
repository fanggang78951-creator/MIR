import unittest
from xydp.equipment_wash import parse_wash_affix_text


class WashLocationTests(unittest.TestCase):
    def test_error_includes_file_and_line(self):
        with self.assertRaisesRegex(ValueError, r'填写/洗练属性.txt.*第3行'):
            parse_wash_affix_text('; 注释\n\n韧性=错误', source_name='填写/洗练属性.txt')


if __name__ == '__main__': unittest.main()
