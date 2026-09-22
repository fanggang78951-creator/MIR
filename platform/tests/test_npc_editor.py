from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xydp.installer import Installer
from xydp.npc_editor import KingModeNpcConfig, NpcDraft, NpcEditorError, create_package, direct_install, direct_preflight, king_mode_preflight, scan_npc_appearances, validate_draft
from xydp.repository import PackageRepository
from xydp.validator import validate_package


class NpcEditorTests(unittest.TestCase):
    def test_scan_wzx_indexes_without_trusting_wzl_count(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = bytearray(48 + 4 * 4)
            raw[44:48] = (4).to_bytes(4, "little")
            raw[48:52] = (0).to_bytes(4, "little")
            raw[52:56] = (100).to_bytes(4, "little")
            raw[56:60] = (0).to_bytes(4, "little")
            raw[60:64] = (200).to_bytes(4, "little")
            (root / "Npc.wzx").write_bytes(raw)
            rows = scan_npc_appearances(root)
            self.assertEqual([row["index"] for row in rows], [0, 1, 2, 3])
            self.assertEqual([row["empty"] for row in rows], [True, False, True, False])

    def test_validate_draft_requires_main_and_say(self):
        with self.assertRaises(NpcEditorError):
            validate_draft(NpcDraft(script_text="[@Main]\n"))
        checked = validate_draft(NpcDraft(script_path="玄渊NPC/测试NPC", map_code="jinjiedi", script_text="[@Main]\n#SAY\n测试\\\n<关闭/@exit>\n"))
        self.assertEqual(checked.script_path, "玄渊NPC/测试NPC")

    def test_validate_draft_blocks_config_reads_in_npc_context(self):
        with self.assertRaisesRegex(NpcEditorError, "ReadConfigFileItem"):
            validate_draft(NpcDraft(script_text="[@Main]\n#SAY\n测试\\\n<按钮/@X>\n\n[@X]\n#IF\nReadConfigFileItem x y z N$X\n"))

    def test_create_candidate_package_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            draft = NpcDraft(
                package_id="xy.npc.test-dialogue",
                display_name="测试NPC",
                script_path="玄渊NPC/测试NPC",
                map_code="jinjiedi",
                x=106,
                y=99,
                visible_name="测试NPC",
                appearance=9,
                patch_library="Npc",
                patch_index=9,
                patch_status="reuse-installed",
                script_text="[@Main]\n#SAY\n测试对话\\\n<关闭/@exit>\n",
            )
            package_root = create_package(draft, root)
            package = validate_package(package_root)
            self.assertEqual(package.id, "xy.npc.test-dialogue")
            self.assertEqual(package.status, "candidate")
            self.assertIn("unique_line", {operation["type"] for operation in package.operations})
            self.assertTrue((package_root / "payload/client_patch.json").is_file())

    def test_direct_import_writes_server_and_rolls_back_byte_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); server = root / "server"; envir = server / "Mir200/Envir"
            envir.mkdir(parents=True)
            (server / "Mir200/M2Server.exe").write_bytes(b"M2")
            (envir / "MapInfo.txt").write_bytes("[0 jinjiedi]\r\n".encode("gb18030"))
            draft = NpcDraft(
                package_id="xy.npc.direct-test",
                script_path="玄渊NPC/直接NPC",
                map_code="jinjiedi",
                script_text="[@Main]\n#SAY\n直接导入测试\\\n<关闭/@exit>\n",
                patch_status="reuse-installed",
            )
            plan = direct_preflight(draft, server)
            self.assertFalse(plan.blockers)
            self.assertEqual(len(plan.changes), 2)
            installer = Installer(PackageRepository(root / "packages"), root / "backups")
            before = {path.relative_to(server): path.read_bytes() for path in server.rglob("*") if path.is_file()}
            receipt = direct_install(plan, installer)
            script = envir / "Market_Def/玄渊NPC/直接NPC-jinjiedi.txt"
            self.assertTrue(script.exists())
            self.assertIn("直接导入测试", script.read_text(encoding="gb18030"))
            self.assertIn("直接NPC\tjinjiedi", (envir / "MerChant.txt").read_text(encoding="gb18030"))
            installer.rollback(server, receipt.transaction_id)
            after = {path.relative_to(server): path.read_bytes() for path in server.rglob("*") if path.is_file() and ".xydp" not in path.parts}
            self.assertEqual(after, before)

    def test_direct_import_blocks_existing_script_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); server = root / "server"; envir = server / "Mir200/Envir"
            (envir / "Market_Def/玄渊NPC").mkdir(parents=True)
            (server / "Mir200/M2Server.exe").write_bytes(b"M2")
            (envir / "MapInfo.txt").write_bytes("[0 jinjiedi]\r\n".encode("gb18030"))
            (envir / "Market_Def/玄渊NPC/直接NPC-jinjiedi.txt").write_bytes("[@Main]\r\n#SAY\r\n旧内容\r\n".encode("gb18030"))
            draft = NpcDraft(script_path="玄渊NPC/直接NPC", map_code="jinjiedi", script_text="[@Main]\n#SAY\n新内容\\\n<关闭/@exit>\n")
            plan = direct_preflight(draft, server)
            self.assertTrue(any("内容不同" in item for item in plan.blockers))

    def test_king_mode_npc_preflight_uses_xygdzy_and_gate_coordinates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); server = root / "server"; envir = server / "Mir200/Envir"
            (envir / "Market_Def").mkdir(parents=True)
            (envir / "MapQuest_Def").mkdir(parents=True)
            (server / "Mir200/M2Server.exe").write_bytes(b"M2")
            (envir / "MapInfo.txt").write_bytes("[vx605|XYGDZY 古代庄园]\r\n".encode("gb18030"))
            (envir / "Market_Def/QFunction-0.txt").write_bytes("[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            (envir / "MapQuest_Def/QManage.txt").write_bytes("[@Login]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            (envir / "QuestDiary/游戏登陆").mkdir(parents=True)
            (envir / "QuestDiary/游戏登陆/登陆脚本.txt").write_bytes("[@登陆设置]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            plan = king_mode_preflight(KingModeNpcConfig(), server)
            self.assertFalse(plan.blockers, plan.blockers)
            self.assertEqual(plan.drafts[0].map_code, "XYGDZY")
            self.assertEqual([(item.x, item.y) for item in plan.drafts], [(20, 50), (95, 50), (58, 50), (58, 55)])
            self.assertTrue(any(item.relative_path.endswith("QFunction-0.txt") for item in plan.changes))
            self.assertTrue(any(item.relative_path.endswith("QManage.txt") for item in plan.changes))
            scripts = "\n".join(item.script_text for item in plan.drafts)
            self.assertIn("SETONTIMEREX 9 1000", scripts)
            self.assertIn("POWERRATE 200 0 0 1 0", scripts)
            self.assertIn("ChangeHumAbilityEX 5 + 1", scripts)
            self.assertNotIn("ReadConfigFileItem", scripts.split("恶魔契约")[0])
            qfunction = next(item for item in plan.changes if item.relative_path.endswith("QFunction-0.txt"))
            qfunction_text = qfunction.after.decode("gb18030", errors="replace")
            self.assertIn("@XY_KING_ATTACK_GUARD", qfunction_text)
            self.assertIn("@XY_KING_PLAY_DIE", qfunction_text)
            self.assertIn("@XY_KING_REVIVAL", qfunction_text)

    def test_king_mode_npc_batch_install_is_idempotent_for_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); server = root / "server"; envir = server / "Mir200/Envir"
            (envir / "Market_Def").mkdir(parents=True)
            (envir / "MapQuest_Def").mkdir(parents=True)
            (server / "Mir200/M2Server.exe").write_bytes(b"M2")
            (envir / "MapInfo.txt").write_bytes("[XYGDZY]\r\n".encode("gb18030"))
            (envir / "Market_Def/QFunction-0.txt").write_bytes("[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            (envir / "MapQuest_Def/QManage.txt").write_bytes("[@Login]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            (envir / "QuestDiary/游戏登陆").mkdir(parents=True)
            (envir / "QuestDiary/游戏登陆/登陆脚本.txt").write_bytes("[@登陆设置]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            plan = king_mode_preflight(KingModeNpcConfig(), server)
            installer = Installer(PackageRepository(root / "packages"), root / "backups")
            direct_install(plan, installer)
            second = king_mode_preflight(KingModeNpcConfig(), server)
            self.assertFalse(second.blockers, second.blockers)
            self.assertEqual(len(second.drafts), 4)

    def test_king_mode_contract_seeds_core_and_login_hook(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); server = root / "server"; envir = server / "Mir200/Envir"
            (envir / "Market_Def").mkdir(parents=True)
            (envir / "MapQuest_Def").mkdir(parents=True)
            (envir / "QuestDiary/游戏登陆").mkdir(parents=True)
            (server / "Mir200/M2Server.exe").write_bytes(b"M2")
            (envir / "MapInfo.txt").write_bytes("[XYGDZY]\r\n".encode("gb18030"))
            (envir / "Market_Def/QFunction-0.txt").write_bytes("[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            (envir / "MapQuest_Def/QManage.txt").write_bytes("[@Login]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            (envir / "QuestDiary/游戏登陆/登陆脚本.txt").write_bytes("[@登陆设置]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            plan = king_mode_preflight(KingModeNpcConfig(), server)
            self.assertFalse(plan.blockers, plan.blockers)
            paths = {item.relative_path for item in plan.changes}
            self.assertIn("Mir200/Envir/MerChant.txt", paths)
            self.assertIn("Mir200/Envir/QuestDiary/玄渊功能/国王模式/国王模式核心.txt", paths)
            self.assertIn("Mir200/Envir/QuestDiary/玄渊配置/国王模式配置.txt", paths)
            self.assertIn("Mir200/Envir/QuestDiary/游戏登陆/登陆脚本.txt", paths)
            self.assertIn("Mir200/Envir/MapQuest_Def/QManage.txt", paths)
            login_change = next(item for item in plan.changes if item.relative_path.endswith("登陆脚本.txt"))
            self.assertIn("XY_KING_MEDITATE", login_change.after.decode("gb18030"))
            installer = Installer(PackageRepository(root / "packages"), root / "backups")
            before = {path.relative_to(server): path.read_bytes() for path in server.rglob("*") if path.is_file()}
            receipt = direct_install(plan, installer)
            self.assertTrue((envir / "QuestDiary/玄渊功能/国王模式/国王模式核心.txt").is_file())
            self.assertIn("XY_KING_MEDITATE", (envir / "QuestDiary/游戏登陆/登陆脚本.txt").read_text(encoding="gb18030"))
            installer.rollback(server, receipt.transaction_id)
            after = {path.relative_to(server): path.read_bytes() for path in server.rglob("*") if path.is_file() and ".xydp" not in path.parts}
            self.assertEqual(after, before)

    def test_king_mode_contract_blocks_missing_login_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); server = root / "server"; envir = server / "Mir200/Envir"
            (envir / "Market_Def").mkdir(parents=True)
            (envir / "MapQuest_Def").mkdir(parents=True)
            (server / "Mir200/M2Server.exe").write_bytes(b"M2")
            (envir / "MapInfo.txt").write_bytes("[XYGDZY]\r\n".encode("gb18030"))
            (envir / "Market_Def/QFunction-0.txt").write_bytes("[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            (envir / "MapQuest_Def/QManage.txt").write_bytes("[@Login]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            plan = king_mode_preflight(KingModeNpcConfig(), server)
            self.assertTrue(any("登陆脚本" in item for item in plan.blockers))


if __name__ == "__main__":
    unittest.main()
