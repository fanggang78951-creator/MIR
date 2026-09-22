from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


PLATFORM_ROOT = Path(r"E:\XuanYuanDevPlatform")
TOOL_PATH = PLATFORM_ROOT / "tools" / "deploy_star_monster13_smartmonster.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_tool():
    spec = importlib.util.spec_from_file_location("deploy_star_monster13_smartmonster", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载工具：{TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StarMonster13SmartMonsterTest(unittest.TestCase):
    def test_preflight_relocates_action_and_effect_refs_without_touching_db_or_mongen(self) -> None:
        """防止只重写ActionFile而遗漏祖玛力士的EffectFile，导致攻击动作仍指向供体旧编号。"""
        module = load_tool()
        simulation_root = PLATFORM_ROOT / "怪物库" / "simulation"
        simulation_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="star13-test-", dir=simulation_root) as temporary:
            root = Path(temporary)
            server = root / "server"
            envir = server / "Mir200" / "Envir"
            db_path = server / "Mud2" / "DB" / "ApexM2.DB"
            target_data = root / "client" / "data"
            candidate_root = root / "candidate"
            report_root = root / "reports"
            backup_root = root / "backups"
            db_path.parent.mkdir(parents=True)
            envir.mkdir(parents=True)
            target_data.mkdir(parents=True)

            connection = sqlite3.connect(db_path)
            connection.execute("CREATE TABLE Monster (Name TEXT, Race INTEGER, RaceImg INTEGER, Appr INTEGER)")
            connection.execute(
                "INSERT INTO Monster (Name, Race, RaceImg, Appr) VALUES (?, ?, ?, ?)",
                ("星辰怪13", 156, 156, 1123),
            )
            connection.commit()
            connection.close()
            (envir / "MonGen.txt").write_bytes("0105 12 25 星辰怪13 1 1 600 0 151\r\n".encode("gb18030"))
            effect_entries = [f"Existing{i}.wzl" for i in range(13)] + ["XY_StarMon10.wzl"]
            (envir / "EffectImageList.txt").write_bytes(("\r\n".join(effect_entries) + "\r\n").encode("gb18030"))

            db_before = sha256(db_path)
            mon_gen_before = sha256(envir / "MonGen.txt")
            args = argparse.Namespace(
                apply=False,
                rollback=None,
                yes=False,
                donor_server=Path(r"D:\MirServer10"),
                donor_client=Path(r"E:\星辰剑歌"),
                server_root=server,
                target_data=target_data,
                candidate_root=candidate_root,
                backup_root=backup_root,
                report_root=report_root,
                skip_process_check=True,
            )

            plan = module.preflight(args)

            self.assertEqual(plan["status"], "ready-to-apply")
            self.assertEqual(plan["source"]["zero_based_action_file"], 78)
            self.assertEqual(plan["source"]["resolved_resource"], "Mon7.wzl")
            self.assertEqual(plan["effect_list"]["target_index"], 14)
            self.assertEqual(plan["candidate"]["rewrite"]["rewritten_occurrences"], 13)
            self.assertEqual(
                plan["candidate"]["rewrite"]["rewritten_resource_keys"],
                {"ActionFile": 12, "EffectFile": 1},
            )
            self.assertEqual(plan["candidate"]["action_frames"]["total_verified_play_frames"], 224)
            candidate_ini = Path(plan["candidate"]["candidate_files"]["ini"]["path"]).read_bytes().decode("gb18030")
            self.assertEqual(candidate_ini.count("ActionFile=14"), 12)
            self.assertEqual(candidate_ini.count("EffectFile=14"), 1)
            self.assertNotIn("ActionFile=78", candidate_ini)
            self.assertNotIn("EffectFile=78", candidate_ini)
            self.assertEqual(sha256(db_path), db_before)
            self.assertEqual(sha256(envir / "MonGen.txt"), mon_gen_before)


if __name__ == "__main__":
    unittest.main()
