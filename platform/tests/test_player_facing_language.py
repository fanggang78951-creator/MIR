from __future__ import annotations

import json
import unittest
from pathlib import Path


FORBIDDEN_PLAYER_WORDING = (
    "保护性停止",
    "本次没有执行",
    "未执行升级",
    "强化未执行",
    "脚本遗留",
    "M2未识别",
    "查看最新日志",
    "当前阶段或资源已经变化",
    "当前称号阶段或资源不满足",
)


def _visible_lines(text: str):
    for line in text.replace("\\n", "\n").splitlines():
        if "MESSAGEBOX" in line or "SENDMSG" in line:
            yield line


class PlayerFacingLanguageTests(unittest.TestCase):
    def test_manual_never_claims_thumbnail_equals_complete_patch(self):
        root = Path(__file__).resolve().parents[1]
        manual = root / "bin" / "玄渊成果平台使用手册" / "Codex维护记录" / "生成工具" / "build_illustrated_manual.py"

        self.assertIn("缩略图仅用于预览，不能证明补丁完整", manual.read_text(encoding="utf-8"))

    def test_interface_marks_star13_game_verified_and_v3_as_default_future_route(self):
        root = Path(__file__).resolve().parents[1]
        interface = root / "接口" / "30_星辰怪首饰店一键生成接口.txt"
        text = interface.read_text(encoding="utf-8")

        self.assertIn("星辰怪13已完成身体及站立、行走、攻击、受击、死亡五类动作游戏验收", text)
        self.assertIn("后续怪物默认走通用V3", text)

    def test_v3_documentation_rejects_obsolete_executable_monster_workflow(self):
        root = Path(__file__).resolve().parents[1]
        documents = {
            "README": (root / "README.md").read_text(encoding="utf-8"),
            "接口": (root / "接口" / "30_星辰怪首饰店一键生成接口.txt").read_text(encoding="utf-8"),
            "手册源": (root / "bin" / "玄渊成果平台使用手册" / "Codex维护记录" / "生成工具" / "build_illustrated_manual.py").read_text(encoding="utf-8"),
        }
        forbidden = {
            "README": ("monster-library-apply", "monster-workbook-apply", "新增MonGen刷怪行"),
            "接口": (
                "D:\\XuanYuanDevPlatform\\tools\\",
                "--apply",
                "正式写入",
                "MonGen刷新",
                "import_star_monster_visual_pack.py",
                "当前有效门禁",
                "待生成新登录器和游戏验收",
                "当前只允许验收星辰怪13",
                "当前接口暂停正式生成",
            ),
            "手册源": ("自动打开生成器", "只点生成登录器"),
        }

        for document, phrases in forbidden.items():
            for phrase in phrases:
                self.assertNotIn(phrase, documents[document], f"{document}仍暴露废止流程：{phrase}")

        legacy_d_tool_sample = "D:\\XuanYuanDevPlatform\\tools\\legacy-monster-tool.py"
        self.assertIn(forbidden["接口"][0], legacy_d_tool_sample)

    def test_platform_scripts_do_not_expose_developer_wording(self):
        root = Path(__file__).resolve().parents[1]
        violations: list[str] = []

        for path in (root / "src" / "xydp").glob("*.py"):
            for line in _visible_lines(path.read_text(encoding="utf-8")):
                for wording in FORBIDDEN_PLAYER_WORDING:
                    if wording in line:
                        violations.append(f"{path}: {wording}")

        for path in (root / "packages").rglob("*.txt"):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="gb18030")
            for line in _visible_lines(text):
                for wording in FORBIDDEN_PLAYER_WORDING:
                    if wording in line:
                        violations.append(f"{path}: {wording}")

        for path in (root / "packages").rglob("manifest.json"):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            for operation in manifest.get("operations", []):
                for value in operation.values():
                    if not isinstance(value, str):
                        continue
                    for line in _visible_lines(value):
                        for wording in FORBIDDEN_PLAYER_WORDING:
                            if wording in line:
                                violations.append(f"{path}: {wording}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
