import json
import tempfile
import unittest
from pathlib import Path

from xydp.validator import PackageValidationError, validate_package


class EventHookValidationTests(unittest.TestCase):
    def make_package(self, root: Path, content: str) -> Path:
        package = root / "xy.event-hook-test"
        package.mkdir(parents=True)
        manifest = {
            "schema_version": 1,
            "id": "xy.event-hook-test",
            "version": "1.0.0",
            "display_name": "事件钩子校验测试",
            "status": "candidate",
            "engine": "LFM2",
            "bundle": None,
            "dependencies": [],
            "parameters": {},
            "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
            "operations": [{
                "type": "event_hook",
                "target": "Mir200/Envir/Market_Def/QFunction-0.txt",
                "label": "TakeOnEx",
                "content": content,
            }],
            "preflight_checks": [],
            "post_checks": [],
            "evidence": [],
        }
        (package / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return package

    def test_rejects_delaygoto_outside_action_section(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_package(Path(temporary), "DELAYGOTO 1 @XY_Test")
            with self.assertRaisesRegex(PackageValidationError, "DELAYGOTO 必须位于"):
                validate_package(package)

    def test_accepts_delaygoto_inside_action_section(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_package(Path(temporary), "#IF\n#ACT\nDELAYGOTO 1 @XY_Test")
            manifest = validate_package(package)
            self.assertEqual(manifest.id, "xy.event-hook-test")


if __name__ == "__main__":
    unittest.main()
