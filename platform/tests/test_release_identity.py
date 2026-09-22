import unittest
import tempfile
from pathlib import Path
import sys
from xydp.release_identity import source_identity, runtime_identity
from xydp.release_identity import code_fingerprint

class ReleaseIdentityTests(unittest.TestCase):
    def test_build_location_does_not_change_execution_fingerprint(self):
        text = 'def value():\n    return 17\n'
        self.assertEqual(code_fingerprint(compile(text, 'C:/build/a.py', 'exec')), code_fingerprint(compile(text, 'E:/release/a.py', 'exec')))

    def test_changed_nested_function_is_detected(self):
        self.assertNotEqual(code_fingerprint(compile('def value():\n return 17', '', 'exec')), code_fingerprint(compile('def value():\n return 18', '', 'exec')))

    def test_source_fingerprint_does_not_inherit_checker_future_flags(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'xydp').mkdir()
            source = root/'xydp/plain.py'
            source.write_text('answer: int = 42\n', encoding='utf-8')
            expected = code_fingerprint(compile(source.read_bytes(), str(source), 'exec', dont_inherit=True))
            self.assertEqual(source_identity(root)['xydp.plain'], expected)

    def test_source_identity_includes_only_reviewed_equipment_graphics_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'xydp').mkdir()
            (root/'xyequip/equipment_graphics').mkdir(parents=True)
            (root/'xydp/plain.py').write_text('answer = 42\n', encoding='utf-8')
            (root/'xydp/__init__.py').write_text('ignored = True\n', encoding='utf-8')
            (root/'xyequip/equipment_graphics/__init__.py').write_text('answer = 1\n', encoding='utf-8')
            (root/'xyequip/equipment_graphics/codec.py').write_text('answer = 2\n', encoding='utf-8')
            (root/'xyequip/equipment_graphics/foo').mkdir()
            (root/'xyequip/equipment_graphics/foo/__init__.py').write_text('answer = 3\n', encoding='utf-8')
            identity = source_identity(root)
            self.assertEqual({'xydp.plain', 'xyequip.equipment_graphics', 'xyequip.equipment_graphics.codec', 'xyequip.equipment_graphics.foo'}, set(identity))

    def test_runtime_identity_allows_reviewed_package_and_rejects_other_xyequip_modules(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = root/'xyequip/equipment_graphics'
            package.mkdir(parents=True)
            (root/'xyequip/__init__.py').write_text('', encoding='utf-8')
            (package/'__init__.py').write_text('answer = 1\n', encoding='utf-8')
            (package/'codec.py').write_text('answer = 2\n', encoding='utf-8')
            previous = {name: module for name, module in sys.modules.items() if name == 'xyequip' or name.startswith('xyequip.')}
            for name in previous:
                del sys.modules[name]
            sys.path.insert(0, str(root))
            try:
                identity = runtime_identity(['xyequip.equipment_graphics', 'xyequip.equipment_graphics.codec'])
                self.assertEqual(set(identity), {'xyequip.equipment_graphics', 'xyequip.equipment_graphics.codec'})
                with self.assertRaises(ValueError):
                    runtime_identity(['xyequip.other'])
            finally:
                sys.path.remove(str(root))
                for name in list(sys.modules):
                    if name == 'xyequip' or name.startswith('xyequip.'):
                        del sys.modules[name]
                sys.modules.update(previous)

if __name__ == '__main__': unittest.main()
