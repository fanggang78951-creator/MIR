from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from xydp.installer import InstallError, Installer
from xydp.repository import PackageRepository
from xydp.validator import validate_package


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ID = "xy.optional.skill-upgrade.warrior.gongsha-kaitian"
PACKAGE_ROOT = PLATFORM_ROOT / "packages/verified" / PACKAGE_ID


class SkillUpgradePackageTests(unittest.TestCase):
    def make_fixture(self, base: Path) -> tuple[Path, Path, dict[str, bytes]]:
        server = base / "server"
        client = base / "client_data"
        envir = server / "Mir200/Envir"
        (envir / "Market_Def").mkdir(parents=True)
        (envir / "MapQuest_Def").mkdir(parents=True)
        (server / "Mir200/M2Server.exe").write_bytes(b"M2")
        (envir / "MapInfo.txt").write_bytes("[0 盟重]\r\n".encode("gb18030"))
        qfunction = envir / "Market_Def/QFunction-0.txt"
        qmanage = envir / "MapQuest_Def/QManage.txt"
        qfunction.write_bytes("[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
        qmanage.write_bytes("[@MAIN1]\r\n#IF\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))

        database = server / "Mud2/DB/ApexM2.DB"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "CREATE TABLE Magic ("
                "MagID INTEGER NOT NULL, MagName TEXT NOT NULL, Job INTEGER NOT NULL, "
                "CanUpgrade INTEGER NOT NULL, MaxUpgradeLv INTEGER NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO Magic VALUES (?, ?, ?, ?, ?)",
                [
                    (7, "攻杀剑术", 0, 0, 0),
                    (7, "英雄攻杀剑术", 0, 0, 0),
                    (7, "怒之攻杀剑术", 0, 0, 0),
                ],
            )
            connection.commit()
        finally:
            connection.close()

        client.mkdir(parents=True)
        skill_desc = client / "SkillUpgradeDesc.Dat"
        skill_desc.write_bytes("; 技能强化说明\r\n".encode("gb18030"))
        before = {
            "database": database.read_bytes(),
            "qfunction": qfunction.read_bytes(),
            "qmanage": qmanage.read_bytes(),
            "skill_desc": skill_desc.read_bytes(),
        }
        return server, client, before

    @staticmethod
    def read_magic(database: Path) -> list[tuple]:
        connection = sqlite3.connect(database)
        try:
            return connection.execute(
                "SELECT MagID, MagName, Job, CanUpgrade, MaxUpgradeLv FROM Magic ORDER BY rowid"
            ).fetchall()
        finally:
            connection.close()

    def test_manifest_is_verified_optional_and_contains_no_test_npc(self):
        manifest = validate_package(PACKAGE_ROOT)
        self.assertEqual(manifest.id, PACKAGE_ID)
        self.assertEqual(manifest.status, "verified")
        self.assertEqual(manifest.residency, "optional")
        self.assertEqual(manifest.bundle, "skill-upgrade")
        self.assertEqual(len(manifest.operations), 6)
        manifest_text = (PACKAGE_ROOT / "manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("MerChant", manifest_text)
        self.assertNotIn("测试NPC", manifest_text)
        self.assertNotIn("玄渊实验室", manifest_text)
        self.assertNotIn("基本剑术", manifest_text)
        self.assertIn('"type": "sqlite_magic_skill_update"', manifest_text)

    def test_exact_game_accepted_costs_and_unlock_contract_are_preserved(self):
        manifest = validate_package(PACKAGE_ROOT)
        qfunction = next(
            item["content"]
            for item in manifest.operations
            if item["type"] == "managed_block" and item["target"].endswith("QFunction-0.txt")
        )
        for level in range(1, 10):
            self.assertIn(f"CHECKITEM 金刚石 {level}", qfunction)
            self.assertIn(f"CHECKITEM 血剑碎片 {level}", qfunction)
            self.assertIn(f"GAMEGOLD - {level * 10}", qfunction)
            self.assertIn(f"GAMEDIAMOND - {level}", qfunction)
            self.assertIn(f"SKILLLEVEL 攻杀剑术 = {level} 1", qfunction)
        self.assertIn("ADDSKILL 开天斩 3", qfunction)
        self.assertIn("CHECKSKILL 攻杀剑术 = 3 0", qfunction)

    def test_isolated_install_is_idempotent_and_rollback_is_byte_exact(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            server, client, before = self.make_fixture(base)
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")

            plan = installer.preflight(server, [PACKAGE_ID], {}, client_root=client)
            self.assertEqual(len(plan.changes), 5)
            self.assertEqual(plan.candidate_packages, [])
            receipt = installer.install(plan)

            database = server / "Mud2/DB/ApexM2.DB"
            self.assertEqual(
                self.read_magic(database),
                [
                    (7, "攻杀剑术", 0, 1, 9),
                    (7, "英雄攻杀剑术", 0, 0, 0),
                    (7, "怒之攻杀剑术", 0, 0, 0),
                ],
            )
            qfunction = (server / "Mir200/Envir/Market_Def/QFunction-0.txt").read_text(
                encoding="gb18030"
            )
            qmanage = (server / "Mir200/Envir/MapQuest_Def/QManage.txt").read_text(
                encoding="gb18030"
            )
            login_path = server / "Mir200/Envir/QuestDiary/玄渊功能/技能强化/攻杀开天登录补写.txt"
            skill_desc = (client / "SkillUpgradeDesc.Dat").read_text(encoding="gb18030")
            self.assertEqual(qfunction.count("[@SkillLevelEx7]"), 1)
            self.assertEqual(qfunction.count("XYDP-BEGIN " + PACKAGE_ID), 1)
            self.assertEqual(qmanage.count("@XY_WSU_LOGIN_BACKFILL"), 1)
            self.assertTrue(login_path.is_file())
            self.assertIn("强化9；达到强化9后领悟3级开天斩", skill_desc)
            self.assertEqual(
                installer.preflight(server, [PACKAGE_ID], {}, client_root=client).changes,
                [],
            )

            installer.rollback(server, receipt.transaction_id)
            self.assertEqual(database.read_bytes(), before["database"])
            self.assertEqual(
                (server / "Mir200/Envir/Market_Def/QFunction-0.txt").read_bytes(),
                before["qfunction"],
            )
            self.assertEqual(
                (server / "Mir200/Envir/MapQuest_Def/QManage.txt").read_bytes(),
                before["qmanage"],
            )
            self.assertEqual((client / "SkillUpgradeDesc.Dat").read_bytes(), before["skill_desc"])
            self.assertFalse(login_path.exists())

    def test_existing_skill_event_conflict_blocks_before_database_change(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            server, client, before = self.make_fixture(base)
            qfunction = server / "Mir200/Envir/Market_Def/QFunction-0.txt"
            qfunction.write_bytes("[@SkillLevelEx7]\r\n#ACT\r\nBREAK\r\n".encode("gb18030"))
            database = server / "Mud2/DB/ApexM2.DB"
            database_before = database.read_bytes()
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")

            with self.assertRaisesRegex(InstallError, "标签占用冲突: SkillLevelEx7"):
                installer.preflight(server, [PACKAGE_ID], {}, client_root=client)

            self.assertEqual(database.read_bytes(), database_before)
            self.assertEqual(self.read_magic(database)[0], (7, "攻杀剑术", 0, 0, 0))

    def test_client_data_root_is_required(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            server, _, _ = self.make_fixture(base)
            repository = PackageRepository(PLATFORM_ROOT / "packages")
            repository.refresh()
            installer = Installer(repository, base / "backups")

            with self.assertRaisesRegex(InstallError, "需要客户端根目录"):
                installer.preflight(server, [PACKAGE_ID], {})

    def test_optional_registry_links_to_formal_package(self):
        registry = json.loads(
            (PLATFORM_ROOT / "非常驻脚本/registry.json").read_text(encoding="utf-8")
        )
        record = next(
            item for item in registry["records"]
            if item["script_id"] == "XY-SKILL-030_攻杀开天技能强化_V1"
        )
        self.assertEqual(record["status"], "packaged")
        self.assertEqual(record["package_id"], PACKAGE_ID)
        self.assertEqual(record["version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
