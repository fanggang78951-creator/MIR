from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xydp.cli import _parser
from xydp.config_sync import ConfigSyncPlan, ConfigSyncService
from xydp.gui import PlatformApp, TAB_TITLES
from xydp.mingge_dual import (
    CONTENT_ROUTE,
    NPC_ROUTE,
    DualInstallPlan,
)


def _platform(root: Path) -> Path:
    documents = root / "所需材料表格汇总"
    documents.mkdir(parents=True)
    registry = {
        "schema_version": 1,
        "documents": [
            {"id": "mingge_system", "file": "37_命格系统.xlsx", "consumer": "mingge-system"},
            {"id": "mingge_npc", "file": "40_命格NPC规则.xlsx", "consumer": "mingge-npc"},
            {"id": "mingge_content", "file": "41_命格内容与多色属性.xlsx", "consumer": "mingge-content"},
        ],
    }
    (documents / "00_填写文档注册表.json").write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    for name in ("37_命格系统.xlsx", "40_命格NPC规则.xlsx", "41_命格内容与多色属性.xlsx"):
        (documents / name).write_bytes(name.encode("utf-8"))
    (root / "packages").mkdir()
    return root


class MinggeDualConfigSyncTests(unittest.TestCase):
    def test_new_workbooks_route_to_independent_services_without_client(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xydp-mingge-dual-routes-") as td:
            root = _platform(Path(td))
            service = ConfigSyncService(root)
            service.mingge_npc = Mock()
            service.mingge_content = Mock()
            server = root / "server"
            for filename, route, attr in (
                ("40_命格NPC规则.xlsx", NPC_ROUTE, "mingge_npc"),
                ("41_命格内容与多色属性.xlsx", CONTENT_ROUTE, "mingge_content"),
            ):
                inner = DualInstallPlan(route, "package", "plan", server.resolve(), (root / "所需材料表格汇总" / filename).resolve(), "hash", (), (), ("warning",))
                getattr(service, attr).preflight.return_value = inner

                plan = service.preflight(server, [root / "所需材料表格汇总" / filename])

                self.assertEqual(plan.route, route)
                self.assertIs(plan.inner_plan, inner)
                self.assertEqual(plan.warnings, ["warning"])
                getattr(service, attr).preflight.assert_called_once_with(server, (root / "所需材料表格汇总" / filename).resolve())

    def test_legacy_combined_route_blocks_new_install_but_keeps_rollback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xydp-mingge-legacy-route-") as td:
            root = _platform(Path(td))
            service = ConfigSyncService(root)
            service.mingge = Mock()

            plan = service.preflight(root / "server", [root / "所需材料表格汇总" / "37_命格系统.xlsx"])

            self.assertEqual(plan.route, "mingge-system")
            self.assertTrue(any("旧版" in item and "回滚" in item for item in plan.blockers))
            service.mingge.preflight.assert_not_called()

            service.mingge.rollback.return_value = "legacy-rolled-back"
            self.assertEqual(service.rollback(root / "server", "tx-old", "mingge-system"), "legacy-rolled-back")

    def test_install_and_rollback_dispatch_to_only_selected_subpackage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xydp-mingge-dual-dispatch-") as td:
            root = _platform(Path(td))
            service = ConfigSyncService(root)
            service.mingge_npc = Mock()
            service.mingge_content = Mock()
            for route, attr, filename in (
                (NPC_ROUTE, "mingge_npc", "40_命格NPC规则.xlsx"),
                (CONTENT_ROUTE, "mingge_content", "41_命格内容与多色属性.xlsx"),
            ):
                document = service.resolve([root / "所需材料表格汇总" / filename])[0]
                inner = DualInstallPlan(route, "package", "plan", (root / "server").resolve(), Path(document.path), document.sha256, (), (), ())
                receipt = object()
                getattr(service, attr).install.return_value = receipt
                plan = ConfigSyncPlan(str(root / "server"), None, route, [document], inner_plan=inner)

                self.assertIs(service.install(plan), receipt)
                getattr(service, attr).install.assert_called_once_with(inner)
                getattr(service, attr).rollback.return_value = SimpleNamespace(transaction_id="tx-1")
                self.assertEqual(service.rollback(root / "server", "tx-1", route), "tx-1")

    def test_cli_rollback_accepts_both_new_routes(self) -> None:
        for route in (NPC_ROUTE, CONTENT_ROUTE):
            args = _parser().parse_args([
                "config-sync-rollback", "--server", r"D:\Missing", "--transaction", "tx-1",
                "--route", route, "--yes",
            ])
            self.assertEqual(args.route, route)


class MinggeDualGuiTests(unittest.TestCase):
    def test_platform_uses_single_mingge_tab_name(self) -> None:
        self.assertIn("命格", TAB_TITLES)
        self.assertNotIn("命格原生多色", TAB_TITLES)

    def test_each_install_button_runs_fresh_preflight(self) -> None:
        for method_name, preflight_name in (
            ("mingge_npc_install", "mingge_npc_preflight"),
            ("mingge_content_install", "mingge_content_preflight"),
        ):
            calls: list[bool] = []

            def preflight(*, show_success: bool = True):
                calls.append(show_success)
                return SimpleNamespace(blockers=())

            app = SimpleNamespace(**{preflight_name: preflight})
            with patch("xydp.gui.messagebox.askyesno", return_value=False) as askyesno:
                getattr(PlatformApp, method_name)(app)
            self.assertEqual(calls, [False])
            askyesno.assert_called_once()


if __name__ == "__main__":
    unittest.main()
