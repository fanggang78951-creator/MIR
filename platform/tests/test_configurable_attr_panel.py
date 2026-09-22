import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from xydp.attribute_panel import AttributePanelError, compile_attribute_panel
from xydp.cli import _params
from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "packages" / "candidate" / "xy.ui.attr-overview"


class ConfigurableAttributePanelTests(unittest.TestCase):
    def test_cli_accepts_nested_json_parameter_value(self):
        params = _params([
            'panel_a={"title":"属性","namespace":"A","items":[{"label":"爆率","source":"N$XY_最终爆率"}]}'
        ])
        self.assertEqual(params["panel_a"]["title"], "属性")
        self.assertEqual(params["panel_a"]["items"][0]["source"], "N$XY_最终爆率")

    def test_compiles_arbitrary_numeric_attribute_bindings(self):
        compiled = compile_attribute_panel({
            "title": "战斗总览",
            "title_color": 250,
            "items": [
                {
                    "label": "暴击伤害", "source": "N$XY_最终爆伤", "offset": 100,
                    "prefix": "+", "suffix": "%", "color": 254, "clamp_min": 0,
                },
                {
                    "label": "固定切割", "source": "N$XY_固定切割", "offset": 0,
                    "prefix": "+", "suffix": "点", "color": 251,
                },
            ],
        })
        self.assertIn("MOV N$XY_UI_Value01 <$STR(N$XY_最终爆伤)>", compiled.setup)
        self.assertIn("DEC N$XY_UI_Value01 100", compiled.setup)
        self.assertIn("SMALL N$XY_UI_Value01 0", compiled.setup)
        self.assertIn("MOV N$XY_UI_Value02 <$STR(N$XY_固定切割)>", compiled.setup)
        self.assertIn(
            "MOV N$XY_UI_Value01 0\n#IF\n#ACT\nMOV N$XY_UI_Value02",
            compiled.setup,
        )
        self.assertEqual(
            compiled.tooltip,
            "250#战斗总览\\254#暴击伤害:+<$STR(N$XY_UI_Value01)>%\\251#固定切割:+<$STR(N$XY_UI_Value02)>点",
        )

    def test_namespace_and_divisor_create_isolated_display_variables(self):
        compiled = compile_attribute_panel({
            "title": "处决",
            "namespace": "C",
            "items": [
                {"label": "处决概率", "source": "N$XY_EXEC_ChanceBP", "divisor": 100, "suffix": "%"},
                {"label": "处决时间", "source": "N$XY_EXEC_PVEEquipDurationMs", "divisor": 1000, "suffix": "秒"},
            ],
        })
        self.assertIn("FORMULATION <$STR(N$XY_EXEC_ChanceBP)>/100 N$XY_UI_C_Value01", compiled.setup)
        self.assertIn("FORMULATION <$STR(N$XY_EXEC_PVEEquipDurationMs)>/1000 N$XY_UI_C_Value02", compiled.setup)
        self.assertIn("<$STR(N$XY_UI_C_Value01)>", compiled.tooltip)
        self.assertIn("<$STR(N$XY_UI_C_Value02)>", compiled.tooltip)

    def test_bind_type_reads_equipped_display_values_without_business_cache(self):
        compiled = compile_attribute_panel({
            "title": "装备显示",
            "namespace": "A",
            "items": [{
                "label": "神力倍攻", "source": "N$倍攻", "bind_type": 40,
                "prefix": "+", "suffix": "%", "clamp_min": 0,
            }],
        })
        self.assertIn("MOV N$XY_UI_A_Value01_BindPoint 0", compiled.setup)
        self.assertIn("MOV N$XY_UI_A_Value01_BindRate 0", compiled.setup)
        self.assertIn(
            "GetAllCustomItemValue 40 N$XY_UI_A_Value01_BindPoint N$XY_UI_A_Value01_BindRate",
            compiled.setup,
        )
        self.assertIn("MOV N$XY_UI_A_Value01 <$STR(N$XY_UI_A_Value01_BindPoint)>", compiled.setup)
        self.assertIn("INC N$XY_UI_A_Value01 <$STR(N$XY_UI_A_Value01_BindRate)>", compiled.setup)
        self.assertNotIn("MOV N$XY_UI_A_Value01 <$STR(N$倍攻)>", compiled.setup)

    def test_explicit_read_modes_and_equipment_and_title_additions_are_declarative(self):
        compiled = compile_attribute_panel({
            "title": "实效同源", "namespace": "B",
            "items": [
                {
                    "label": "神力倍攻", "source": "N$倍攻", "bind_type": 40,
                    "read_mode": "source", "offset": 100, "suffix": "%",
                    "clamp_min": 0,
                },
                {
                    "label": "首刀斩杀", "source": "N$XY_FirstKillRate", "bind_type": 46,
                    "read_mode": "zero", "suffix": "%", "equipment_additions": [
                        {"name": "测试鞋子", "amount": 10},
                        {"name": "尾刀盾牌", "amount": 50, "count": 1},
                    ], "title_additions": [
                        {"name": "赞助1档", "amount": 5},
                        {"name": "赞助2档", "amount": 6},
                    ]
                },
                {
                    "label": "鞭尸概率", "source": "N$XY_CorpseRate", "bind_type": 13,
                    "read_mode": "bind", "suffix": "%", "equipment_additions": [
                        {"name": "鞭尸灵玉", "amount": 100},
                    ],
                },
            ],
        })
        self.assertIn("MOV N$XY_UI_B_Value01 <$STR(N$倍攻)>", compiled.setup)
        self.assertIn("DEC N$XY_UI_B_Value01 100", compiled.setup)
        self.assertNotIn("GetAllCustomItemValue 40", compiled.setup)
        self.assertIn("MOV N$XY_UI_B_Value02 0", compiled.setup)
        self.assertIn("CHECKITEMW 测试鞋子 1\n#ACT\nINC N$XY_UI_B_Value02 10", compiled.setup)
        self.assertIn("CHECKITEMW 尾刀盾牌 1\n#ACT\nINC N$XY_UI_B_Value02 50", compiled.setup)
        self.assertIn("GetAllCustomItemValue 13 N$XY_UI_B_Value03_BindPoint", compiled.setup)
        self.assertIn("CHECKITEMW 鞭尸灵玉 1\n#ACT\nINC N$XY_UI_B_Value03 100", compiled.setup)
        self.assertIn("CHECKFENGHAO 赞助1档\n#ACT\nINC N$XY_UI_B_Value02 5", compiled.setup)
        self.assertIn("CHECKFENGHAO 赞助2档\n#ACT\nINC N$XY_UI_B_Value02 6", compiled.setup)
        self.assertEqual(compiled.normalized["items"][0]["read_mode"], "source")
        self.assertEqual(compiled.normalized["items"][1]["equipment_additions"][0]["count"], 1)
        self.assertEqual(compiled.normalized["items"][1]["title_additions"][1]["amount"], 6)

    def test_rejects_script_injection_and_bad_namespace_or_divisor(self):
        with self.assertRaises(AttributePanelError):
            compile_attribute_panel({
                "title": "属性", "items": [{"label": "爆率\\BREAK", "source": "N$XY_最终爆率"}],
            })
        with self.assertRaises(AttributePanelError):
            compile_attribute_panel({
                "title": "属性", "items": [{"label": "爆率", "source": "N$XY_最终爆率>\\DELBUTTON1"}],
            })
        with self.assertRaises(AttributePanelError):
            compile_attribute_panel({
                "title": "属性", "namespace": "A-B", "items": [{"label": "爆率", "source": "N$XY_最终爆率"}],
            })
        with self.assertRaises(AttributePanelError):
            compile_attribute_panel({
                "title": "属性", "items": [{"label": "爆率", "source": "N$XY_最终爆率", "divisor": 0}],
            })
        with self.assertRaises(AttributePanelError):
            compile_attribute_panel({
                "title": "属性", "items": [{"label": "爆率", "source": "N$XY_最终爆率", "bind_type": 256}],
            })

    def test_manifest_exposes_three_configurable_panels(self):
        manifest = json.loads((PACKAGE_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "2.0.9-candidate.1")
        for name in ("panel_a", "panel_b", "panel_c"):
            self.assertEqual(manifest["parameters"][name]["type"], "attribute_panel")
        rendered = next(item for item in manifest["operations"] if item["type"] == "render")
        self.assertTrue(rendered["target"].endswith("玄渊三属性按钮.txt"))
        damage_coefficient = manifest["parameters"]["panel_a"]["default"]["items"][1]
        toughness = manifest["parameters"]["panel_c"]["default"]["items"][0]
        execution = manifest["parameters"]["panel_c"]["default"]["items"][1]
        self.assertEqual([item["amount"] for item in damage_coefficient["title_additions"]], [5, 6, 10, 15])
        self.assertEqual([item["amount"] for item in toughness["title_additions"]], [20, 30, 40, 50])
        self.assertEqual([item["amount"] for item in execution["title_additions"]], [5, 6, 8, 10])

    def test_installer_renders_custom_panel_and_rejects_injection(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "server"
            envir = target / "Mir200/Envir"
            (envir / "MapQuest_Def").mkdir(parents=True)
            (envir / "Market_Def").mkdir(parents=True)
            (target / "Mir200/M2Server.exe").write_bytes(b"M2")
            (target / "Mir200/!setup.txt").write_bytes(b"[Setup]\r\nRevivalTime=60000\r\n")
            (envir / "MapInfo.txt").write_bytes(b"[0 test]\r\n")
            (envir / "MerChant.txt").write_bytes(b"")
            (envir / "MapQuest_Def/QManage.txt").write_bytes(
                "[@MAIN1]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
            )
            (envir / "Market_Def/QFunction-0.txt").write_bytes(
                "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030")
            )
            database = target / "Mud2/DB/ApexM2.DB"
            database.parent.mkdir(parents=True)
            rage_manifest = json.loads(
                (ROOT / "packages/candidate/xy.optional.rage.core/manifest.json").read_text(encoding="utf-8")
            )
            rage_values = next(
                item for item in rage_manifest["operations"] if item["type"] == "sqlite_upsert"
            )["values"]
            columns = ["Idx INTEGER", *(
                f'"{name}" {"TEXT" if name == "Name" else "INTEGER"}' for name in rage_values
            )]
            connection = sqlite3.connect(database)
            try:
                connection.execute(f'CREATE TABLE StdItems ({", ".join(columns)})')
                connection.commit()
            finally:
                connection.close()
            installer = Installer(PackageRepository(ROOT / "packages"), base / "backups")
            installer.repository.refresh()
            custom = {
                "panel_a": {
                    "title": "我的属性", "title_color": 253, "namespace": "A",
                    "items": [{
                        "label": "暴击伤害", "source": "N$XY_最终爆伤", "offset": 100,
                        "prefix": "+", "suffix": "%", "color": 254, "clamp_min": 0,
                    }],
                }
            }
            plan = installer.preflight(target, ["xy.ui.attr-overview"], custom)
            rendered = next(
                change.after.decode("gb18030")
                for change in plan.changes if change.relative_path.endswith("玄渊三属性按钮.txt")
            )
            self.assertIn("MOV N$XY_UI_A_Value01 <$STR(N$XY_最终爆伤)>", rendered)
            self.assertIn("#IF\r\n#ACT\r\nMOV N$XY_UI_A_Value01", rendered)
            self.assertIn("253#我的属性\\254#暴击伤害:+<$STR(N$XY_UI_A_Value01)>", rendered)

            with self.assertRaises(InstallError):
                installer.preflight(target, ["xy.ui.attr-overview"], {
                    "panel_a": {
                        "title": "属性", "namespace": "A",
                        "items": [{"label": "爆率\\BREAK", "source": "N$XY_最终爆率"}],
                    }
                })


if __name__ == "__main__":
    unittest.main()
