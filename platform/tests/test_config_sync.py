from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from xydp.cli import _config_sync_change_summary, _config_sync_receipt_summary, _parser
from xydp.config_sync import ConfigSyncError, ConfigSyncPlan, ConfigSyncService, RegisteredDocument
from xydp.gui import PlatformApp
from xydp.installer import InstallPlan
from xydp.mingge import MingGeFileChange, MingGePlan, MingGeReceipt
from xydp.mingge_dual import DualInstallReceipt


class ConfigSyncTests(unittest.TestCase):
    def make_platform(self, root: Path) -> Path:
        documents = root / "所需材料表格汇总"
        documents.mkdir(parents=True)
        registry = {
            "schema_version": 1,
            "documents": [
                {"id": "rage", "file": "01_狂暴.xlsx", "consumer": "initial-camp"},
                {"id": "king_mode", "file": "14_国王模式配置.txt", "consumer": "king-mode"},
                {"id": "equipment_create", "file": "09_装备批量生成.xlsx", "consumer": "equipment"},
                {"id": "recycle_config", "file": "19_装备回收配置.xlsx", "consumer": "recycle-config"},
                {"id": "nmgf_sword", "file": "23_宁姆格福_圣律之剑.xlsx", "consumer": "growth-stage"},
                {"id": "nmgf_relic", "file": "24_宁姆格福_黄金圣物.xlsx", "consumer": "growth-stage"},
                {"id": "equipment_collection", "file": "33_装备收集图鉴.xlsx", "consumer": "equipment-collection"},
                {"id": "item_synthesis", "file": "34_通用物品合成.xlsx", "consumer": "item-synthesis"},
                {"id": "item_synthesis_npcs", "file": "35_合成NPC与配方分配.txt", "consumer": "item-synthesis"},
                {"id": "mingge_system", "file": "37_命格系统.xlsx", "consumer": "mingge-system"},
                {"id": "mingge_content", "file": "41_命格内容与多色属性.xlsx", "consumer": "mingge-content"},
            ],
        }
        (documents / "00_填写文档注册表.json").write_text(
            json.dumps(registry, ensure_ascii=False), encoding="utf-8"
        )
        (documents / "01_狂暴.xlsx").write_bytes(b"xlsx")
        (documents / "14_国王模式配置.txt").write_text("config", encoding="utf-8")
        (documents / "09_装备批量生成.xlsx").write_bytes(b"equipment")
        (documents / "19_装备回收配置.xlsx").write_bytes(b"recycle")
        (documents / "23_宁姆格福_圣律之剑.xlsx").write_bytes(b"sword")
        (documents / "24_宁姆格福_黄金圣物.xlsx").write_bytes(b"relic")
        (documents / "33_装备收集图鉴.xlsx").write_bytes(b"collection")
        (documents / "34_通用物品合成.xlsx").write_bytes(b"synthesis")
        (documents / "35_合成NPC与配方分配.txt").write_text("npc config", encoding="utf-8")
        shutil.copyfile(
            Path(r"E:\XuanYuanDevPlatform\所需材料表格汇总\37_命格系统.xlsx"),
            documents / "37_命格系统.xlsx",
        )
        (documents / "41_命格内容与多色属性.xlsx").write_bytes(b"mingge-content")
        return root

    def test_resolve_accepts_registered_filename_from_any_folder(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            source = root / "所需材料表格汇总" / "01_狂暴.xlsx"
            documents = service.resolve([source, source])
            self.assertEqual(len(documents), 1)
            self.assertEqual(documents[0].id, "rage")
            self.assertEqual(len(documents[0].sha256), 64)
            outside = root / "01_狂暴.xlsx"
            outside.write_bytes(b"xlsx")
            outside_documents = service.resolve([outside])
            self.assertEqual(outside_documents[0].id, "rage")
            self.assertEqual(Path(outside_documents[0].path), outside.resolve())

    def test_resolve_accepts_external_file_when_overview_binds_document_id(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-external-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            external = root / "用户目录" / "自定义命格.xlsx"
            external.parent.mkdir()
            external.write_bytes(b"external-mingge")

            documents = service.resolve([external], document_id="mingge_content")

            self.assertEqual(len(documents), 1)
            self.assertEqual(documents[0].id, "mingge_content")
            self.assertEqual(documents[0].filename, external.name)
            self.assertEqual(Path(documents[0].path), external.resolve())

    def test_external_binding_rejects_unknown_id_and_multiple_files(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-external-invalid-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            first = root / "one.xlsx"
            second = root / "two.xlsx"
            first.write_bytes(b"one")
            second.write_bytes(b"two")

            with self.assertRaisesRegex(ConfigSyncError, "未登记的功能编号"):
                service.resolve([first], document_id="missing")
            with self.assertRaisesRegex(ConfigSyncError, "只能绑定一个文件"):
                service.resolve([first, second], document_id="mingge_content")

    def test_incompatible_consumers_are_blocked_before_target_read(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-mixed-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            docs = root / "所需材料表格汇总"
            plan = service.preflight(
                root / "missing-server",
                [docs / "01_狂暴.xlsx", docs / "14_国王模式配置.txt"],
            )
            self.assertEqual(plan.route, "incompatible")
            self.assertTrue(any("不同安装核心" in item for item in plan.blockers))

    def test_specialist_document_is_recognized_and_redirected(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-specialist-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            plan = service.preflight(
                root / "missing-server",
                [root / "所需材料表格汇总" / "09_装备批量生成.xlsx"],
            )
            self.assertEqual(plan.route, "specialist")
            self.assertTrue(any("批量做装备" in item for item in plan.blockers))

    def test_recycle_document_uses_dedicated_route(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-recycle-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            plan = service.preflight(
                root / "missing-server",
                [root / "所需材料表格汇总" / "19_装备回收配置.xlsx"],
            )
            self.assertEqual(plan.route, "recycle-config")
            self.assertTrue(plan.blockers)

    def test_nmgf_growth_documents_share_one_dedicated_route(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-growth-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            docs = root / "所需材料表格汇总"
            plan = service.preflight(
                root / "missing-server",
                [docs / "23_宁姆格福_圣律之剑.xlsx", docs / "24_宁姆格福_黄金圣物.xlsx"],
            )
            self.assertEqual(plan.route, "growth-stage")
            self.assertTrue(plan.blockers)

    def test_equipment_collection_document_uses_dedicated_route(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-collection-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            plan = service.preflight(
                root / "missing-server",
                [root / "所需材料表格汇总" / "33_装备收集图鉴.xlsx"],
            )
            self.assertEqual(plan.route, "equipment-collection")
            self.assertTrue(plan.blockers)

    def test_item_synthesis_document_uses_dedicated_route(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-synthesis-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            plan = service.preflight(
                root / "missing-server",
                [root / "所需材料表格汇总" / "34_通用物品合成.xlsx"],
            )
            self.assertEqual(plan.route, "item-synthesis")
            self.assertTrue(plan.blockers)

    def test_item_synthesis_npc_config_alone_uses_same_dedicated_route(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-synthesis-npc-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            plan = service.preflight(
                root / "missing-server",
                [root / "所需材料表格汇总" / "35_合成NPC与配方分配.txt"],
            )
            self.assertEqual(plan.route, "item-synthesis")
            self.assertTrue(plan.blockers)

    def test_mingge_document_uses_dedicated_route(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-mingge-route-") as td:
            root = self.make_platform(Path(td))
            plan = ConfigSyncService(root).preflight(
                root / "missing-server",
                [root / "所需材料表格汇总" / "37_命格系统.xlsx"],
                root / "missing-client",
            )
            self.assertEqual(plan.route, "mingge-system")
            self.assertTrue(plan.blockers)

    def test_legacy_mingge_preflight_is_rollback_only_and_never_delegates(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-mingge-preflight-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            server = root / "server"
            client = root / "client"
            workbook = root / "所需材料表格汇总" / "37_命格系统.xlsx"
            change = MingGeFileChange(
                server / "target.txt", None, "after-hash", b"after", "server"
            )
            inner = MingGePlan(
                "plan-1", server.resolve(), client.resolve(), workbook.resolve(),
                "workbook-hash", -1, -1, "", ("inner blocker",),
                ("inner warning",), (change,),
            )
            service.mingge = Mock()
            service.mingge.preflight.return_value = inner

            plan = service.preflight(server, [workbook], client)

            self.assertEqual(plan.route, "mingge-system")
            self.assertIsNone(plan.inner_plan)
            self.assertTrue(any("只保留历史事务回滚" in item for item in plan.blockers))
            self.assertEqual(plan.changes, [])
            service.mingge.preflight.assert_not_called()

    def test_mingge_preflight_without_client_is_blocked_before_delegation(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-mingge-client-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            service.mingge = Mock()

            plan = service.preflight(
                root / "server",
                [root / "所需材料表格汇总" / "37_命格系统.xlsx"],
            )

            self.assertEqual(plan.route, "mingge-system")
            self.assertTrue(any("只保留历史事务回滚" in blocker for blocker in plan.blockers))
            self.assertIsNone(plan.inner_plan)
            service.mingge.preflight.assert_not_called()

    def test_legacy_mingge_install_is_blocked_after_outer_workbook_hash_guard(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-mingge-install-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            workbook = root / "所需材料表格汇总" / "37_命格系统.xlsx"
            document = service.resolve([workbook])[0]
            inner = MingGePlan(
                "plan-1", (root / "server").resolve(), (root / "client").resolve(),
                workbook.resolve(), document.sha256, -1, -1, "", (), (), (),
            )
            receipt = object()
            service.mingge = Mock()
            service.mingge.install.return_value = receipt
            plan = ConfigSyncPlan(
                server=str(root / "server"),
                client=str(root / "client"),
                route="mingge-system",
                documents=[document],
                inner_plan=inner,
            )

            with self.assertRaisesRegex(ConfigSyncError, "停止新安装"):
                service.install(plan)
            service.mingge.install.assert_not_called()

            workbook.write_bytes(b"changed")
            with self.assertRaisesRegex(ConfigSyncError, "预检后配置文件已变化"):
                service.install(plan)
            service.mingge.install.assert_not_called()

    def test_mingge_rollback_delegates_to_mingge_service_only(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-mingge-rollback-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            server = root / "server"
            service.mingge = Mock()
            service.mingge.rollback.return_value = "rolled-back"
            service.installer = Mock()

            result = service.rollback(server, "tx-1", "mingge-system")

            self.assertEqual(result, "rolled-back")
            service.mingge.rollback.assert_called_once_with(server, "tx-1")
            service.installer.rollback.assert_not_called()

    def test_config_sync_rollback_parser_accepts_mingge_route(self):
        try:
            args = _parser().parse_args([
                "config-sync-rollback",
                "--server", r"D:\Missing",
                "--transaction", "tx-1",
                "--route", "mingge-system",
                "--yes",
            ])
        except SystemExit:
            args = None

        self.assertIsNotNone(args)
        self.assertEqual(args.route, "mingge-system")

    def test_npc_bundle_cli_uses_current_formal_target_defaults(self):
        args = _parser().parse_args([
            "config-sync-bundle-preflight",
            "--source", r"C:\Users\Administrator\Downloads\npc.zip",
        ])

        self.assertEqual(args.server, Path(r"D:\MirServer"))
        self.assertEqual(args.client, Path(r"E:\11周年"))
        self.assertEqual(args.launcher, Path(r"D:\素材文件夹\LFM2[20260707]\登录器"))

    def test_npc_bundle_routes_are_available_for_install_and_rollback(self):
        install = _parser().parse_args([
            "config-sync-bundle-install",
            "--source", r"C:\Users\Administrator\Downloads\npc.zip",
            "--yes",
        ])
        rollback = _parser().parse_args([
            "config-sync-bundle-rollback",
            "--transaction", "tx-1",
            "--yes",
        ])
        generic = _parser().parse_args([
            "config-sync-rollback",
            "--server", r"D:\MirServer",
            "--transaction", "tx-1",
            "--route", "npc-bundle",
            "--yes",
        ])

        self.assertTrue(install.yes)
        self.assertTrue(rollback.yes)
        self.assertEqual(generic.route, "npc-bundle")

    def test_config_sync_change_summary_preserves_mingge_absolute_path(self):
        change = MingGeFileChange(
            Path(r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊命格\命格核心.txt"),
            None,
            "after-hash",
            b"after",
            "server",
        )

        summary = _config_sync_change_summary(change)

        self.assertEqual(summary["scope"], "server")
        self.assertEqual(summary["path"], str(change.path))

    def test_config_sync_receipt_summary_serializes_mingge_paths(self):
        receipt = MingGeReceipt(
            "tx-1",
            Path(r"E:\XuanYuanDevPlatform\backups\mingge-system\tx-1\receipt.json"),
            "installed-pending-game-verification",
            (Path(r"D:\MirServer\Mir200\Envir\QuestDiary\玄渊命格\命格核心.txt"),),
        )

        summary = _config_sync_receipt_summary(receipt)

        self.assertEqual(summary["receipt_path"], str(receipt.receipt_path))
        self.assertEqual(summary["affected_paths"], [str(receipt.affected_paths[0])])
        json.dumps(summary, ensure_ascii=False)

    def test_gui_config_sync_receipt_json_serializes_windows_paths(self):
        receipt = DualInstallReceipt(
            "20260909_102717_32db8ed0",
            "installed-pending-game-verification",
            Path(r"E:\XuanYuanDevPlatform\backups\mingge-content\20260909_102717_32db8ed0\receipt.json"),
            (Path(r"D:\MirServer\Mir200\Envir\CustomItemPropertyTextVarList.txt"),),
        )

        payload = json.loads(PlatformApp._config_sync_receipt_json(receipt))

        self.assertEqual(payload["receipt_path"], str(receipt.receipt_path))
        self.assertEqual(payload["affected_paths"], [str(receipt.affected_paths[0])])

    def test_install_rejects_document_changed_after_preflight(self):
        with tempfile.TemporaryDirectory(prefix="xydp-config-sync-hash-") as td:
            root = self.make_platform(Path(td))
            service = ConfigSyncService(root)
            path = root / "所需材料表格汇总" / "01_狂暴.xlsx"
            document = service.resolve([path])[0]
            path.write_bytes(b"changed")
            plan = ConfigSyncPlan(
                server=str(root / "server"), client=None, route="package-documents",
                documents=[document],
                inner_plan=InstallPlan(str(root / "server"), None, [], {}, {}, []),
            )
            with self.assertRaisesRegex(ConfigSyncError, "预检后配置文件已变化"):
                service.install(plan)


if __name__ == "__main__":
    unittest.main()
