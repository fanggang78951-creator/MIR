from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from xydp.monster_login_integration import LoginIntegrationStatus


PLATFORM_ROOT = Path(__file__).resolve().parents[1]


class MonsterGuiDefaultPathTests(unittest.TestCase):
    def test_monster_library_defaults_follow_current_e_drive_layout(self) -> None:
        source = (PLATFORM_ROOT / "src" / "xydp" / "gui.py").read_text(encoding="utf-8")

        expected_defaults = (
            r'E:\MirServer明月\Mud2\DB\ApexM2.DB',
            r'E:\明月客户端\data',
            r'E:\明月沉默\mycm\data',
            r'E:\MirServer明月\登录器\pak.txt',
        )
        for expected in expected_defaults:
            with self.subTest(expected=expected):
                self.assertIn(expected, source)

        self.assertIn(
            'workbench_pak_export_jobs_root(self.platform_root)',
            source,
        )
        self.assertNotIn('os.environ.get("APPDATA"', source)


class MonsterGuiV3ContractTests(unittest.TestCase):
    def test_gui_uses_engine_rule_scan_language_not_appr_only_language(self) -> None:
        import inspect

        from xydp.gui import PlatformApp

        source = inspect.getsource(PlatformApp._build_monster_library) + inspect.getsource(PlatformApp.monster_scan)
        self.assertIn("按引擎规则扫描供体并重建V3怪物库", source)
        self.assertIn("SmartMonster", source)
        self.assertNotIn("Appr//10+1", source)

    def test_gui_v3_row_keeps_closure_independent_from_preview(self) -> None:
        import json
        from types import SimpleNamespace

        from xydp.gui import PlatformApp

        record = SimpleNamespace(
            monster_id=17,
            monster_name="测试Smart怪",
            engine_mode="smartmonster",
            appearance_id=13,
            closure_status="ready_verified",
            resource_manifest_json=json.dumps([{"entry": "A.wzl"}, {"entry": "B.wzl"}]),
            login_policy="custom_monster_dat_required",
            preview_path=None,
            status="ready",
            skip_reason=None,
        )
        self.assertEqual(
            PlatformApp.MONSTER_TREE_COLUMN_TITLES,
            ("预览", "库编号", "怪物名称", "引擎模式", "Appr", "闭包状态", "依赖数量", "登录器要求", "说明"),
        )
        row = PlatformApp._monster_tree_row(record)
        self.assertEqual(row[:8], ("待桥接", 17, "测试Smart怪", "SmartMonster", 13, "已验证", 2, "待生成DAT/登录器"))

    @staticmethod
    def _status(status: str) -> LoginIntegrationStatus:
        return LoginIntegrationStatus(
            status=status,
            next_step=f"NEXT:{status}",
            config_path=r"C:\generator\Config.ini",
            dat_path=r"C:\server\Mir200\自定义怪物.dat",
            launcher_path=r"C:\client\传奇登陆器.exe",
            newest_dependency_path=None,
            newest_dependency_mtime_ns=None,
            launcher_mtime_ns=None,
            evidence=(),
        )

    @staticmethod
    def _smart_plan() -> SimpleNamespace:
        server = Path(r"C:\server")
        client_data = Path(r"C:\client\data")
        return SimpleNamespace(
            server_root=server,
            client_data=client_data,
            selected_ids=(17, 18),
            monster_names=("测试Smart怪甲", "测试Smart怪乙"),
            library_numbers=(),
            changes=[SimpleNamespace(scope="client", kind="copy")],
            blockers=[],
            warnings=[],
            skipped=[],
            generator_login_dir=Path(r"C:\generator"),
            generator_rules_added=(),
            generated_files_after={
                str(server / "Mir200" / "Envir" / "SmartMonster" / "测试Smart怪甲.ini"): b"A",
                str(server / "Mir200" / "Envir" / "SmartMonster" / "测试Smart怪乙.ini"): b"B",
                str(server / "Mir200" / "Envir" / "EffectImageList.txt"): b"E",
            },
            engine_assignments=(
                {"monster_id": 17, "target_index": 30},
                {"monster_id": 17, "target_index": 31},
                {"monster_id": 18, "target_index": 31},
            ),
            requires_custom_monster_dat=True,
            requires_login_regeneration=True,
            custom_monster_dat_path=str(server / "Mir200" / "自定义怪物.dat"),
            client_integration_status="awaiting-client-integration",
            inserted_names=("测试Smart怪甲", "测试Smart怪乙"),
            updated_names=(),
            appearance_changed_names=(),
            unchanged_names=(),
            auto_reselected=(),
            name_color_assignments=(),
        )

    def test_smartmonster_summary_reaches_both_flows_at_all_three_stages(self) -> None:
        from xydp.gui import PlatformApp

        plan = self._smart_plan()
        receipt = SimpleNamespace(
            transaction_id="TX-8-FIX-1",
            monster_names=plan.monster_names,
            library_numbers=plan.library_numbers,
        )

        def assert_summary(message: str) -> None:
            self.assertIn("INI数：2", message)
            self.assertIn("依赖映射：3", message)
            self.assertIn("目标EffectImageList条目：2", message)
            self.assertIn("真实登录状态：launcher_stale", message)

        with (
            patch("xydp.gui.default_generator_login_dir", return_value=plan.generator_login_dir),
            patch("xydp.gui.verify_custom_monster_login", return_value=self._status("launcher_stale")),
            patch("xydp.gui.MonsterLibraryService.plan_summary", return_value={}),
            patch("xydp.gui.messagebox.showinfo") as showinfo,
            patch("xydp.gui.messagebox.showerror"),
        ):
            direct_preflight = SimpleNamespace(
                monster_tree=SimpleNamespace(selection=lambda: ("17", "18")),
                monster_server_var=SimpleNamespace(get=lambda: str(plan.server_root)),
                monster_client_var=SimpleNamespace(get=lambda: str(plan.client_data)),
                monster_library=SimpleNamespace(preflight=lambda *args, **kwargs: plan),
                current_monster_plan=None,
                monster_report=object(),
                _write=lambda *args: None,
            )
            PlatformApp.monster_preflight(direct_preflight)
            assert_summary(showinfo.call_args.args[1])

        with (
            patch("xydp.gui.verify_custom_monster_login", return_value=self._status("launcher_stale")),
            patch("xydp.gui.messagebox.askyesno", return_value=True) as askyesno,
            patch("xydp.gui.messagebox.showinfo") as showinfo,
            patch("xydp.gui.messagebox.showerror"),
        ):
            direct_install = SimpleNamespace(
                current_monster_plan=plan,
                monster_library=SimpleNamespace(install=lambda current: receipt),
                monster_transaction_var=SimpleNamespace(set=lambda value: None),
                _prepare_monster_login_generator=PlatformApp._prepare_monster_login_generator,
            )
            PlatformApp.monster_install(direct_install)
            assert_summary(askyesno.call_args.args[1])
            assert_summary(showinfo.call_args.args[1])

        with (
            patch("xydp.gui.default_generator_login_dir", return_value=plan.generator_login_dir),
            patch("xydp.gui.verify_custom_monster_login", return_value=self._status("launcher_stale")),
            patch("xydp.gui.messagebox.showinfo") as showinfo,
            patch("xydp.gui.messagebox.showerror"),
        ):
            workbook_preflight = SimpleNamespace(
                monster_server_var=SimpleNamespace(get=lambda: str(plan.server_root)),
                monster_client_var=SimpleNamespace(get=lambda: str(plan.client_data)),
                monster_workbook_var=SimpleNamespace(get=lambda: r"C:\workbook.xlsx"),
                monster_workbook=SimpleNamespace(
                    preflight=lambda *args, **kwargs: plan,
                    plan_summary=lambda current: {},
                ),
                current_monster_workbook_plan=None,
                monster_report=object(),
                _write=lambda *args: None,
            )
            self.assertTrue(PlatformApp.monster_workbook_preflight(workbook_preflight))
            assert_summary(showinfo.call_args.args[1])

        with (
            patch("xydp.gui.verify_custom_monster_login", return_value=self._status("launcher_stale")),
            patch("xydp.gui.messagebox.askyesno", return_value=True) as askyesno,
            patch("xydp.gui.messagebox.showinfo") as showinfo,
            patch("xydp.gui.messagebox.showerror"),
        ):
            workbook_install = SimpleNamespace(
                current_monster_workbook_plan=plan,
                monster_workbook_preflight=lambda show_success=False: True,
                monster_workbook=SimpleNamespace(install=lambda current: receipt),
                monster_transaction_var=SimpleNamespace(set=lambda value: None),
                _prepare_monster_login_generator=PlatformApp._prepare_monster_login_generator,
            )
            PlatformApp.monster_workbook_install(workbook_install)
            assert_summary(askyesno.call_args.args[1])
            assert_summary(showinfo.call_args.args[1])

    def test_prepare_login_message_uses_each_real_status_branch(self) -> None:
        from xydp.gui import PlatformApp

        plan = self._smart_plan()
        expectations = {
            "missing_dat": "生成自定义怪物DAT",
            "generator_not_configured": "配置自定义怪物",
            "launcher_stale": "重新生成登录器",
            "ready": "继续进行单怪身体与五类动作验收",
        }
        for status, expected in expectations.items():
            with self.subTest(status=status), patch(
                "xydp.gui.verify_custom_monster_login",
                return_value=self._status(status),
            ) as verify:
                message = PlatformApp._prepare_monster_login_generator(plan)
                verify.assert_called_once()
                self.assertIn(expected, message)
                self.assertIn(f"真实登录状态：{status}", message)
                if status == "ready":
                    self.assertNotIn("待生成", message)
                    self.assertNotIn("请手动打开", message)
                    self.assertNotIn("MakeGameLogin.exe", message)

    def test_standard_appr_summary_never_claims_custom_dat_is_required(self) -> None:
        from xydp.gui import PlatformApp

        plan = SimpleNamespace(
            requires_custom_monster_dat=False,
            requires_login_regeneration=False,
            changes=[],
            generator_login_dir=None,
            generator_rules_added=(),
        )
        self.assertEqual(PlatformApp._monster_engine_summary_text(plan), "")
        self.assertNotIn("待生成DAT/登录器", PlatformApp._prepare_monster_login_generator(plan))


if __name__ == "__main__":
    unittest.main()
