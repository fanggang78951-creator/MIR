from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from xydp.installer import Installer
from xydp.repository import PackageRepository
from xydp.user_documents import DOCUMENTS, package_operation_source
from xydp.validator import PackageValidationError, validate_package


class UserDocumentRegistryTests(unittest.TestCase):
    def test_current_platform_documents_exist(self):
        root = Path(r"E:\XuanYuanDevPlatform")
        for name in DOCUMENTS.values():
            with self.subTest(name=name):
                self.assertTrue((root / "所需材料表格汇总" / name).is_file())

    def test_missing_central_document_falls_back_to_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fallback = root / "packages/candidate/xy.demo/payload/default.txt"
            fallback.parent.mkdir(parents=True)
            fallback.write_text("default", encoding="utf-8")
            self.assertEqual(
                package_operation_source(root, fallback, "15_首爆奖励配置.txt"),
                fallback,
            )

    def test_mingge_document_matches_code_and_json_registry(self):
        root = Path(r"E:\XuanYuanDevPlatform")
        registry = json.loads(
            (root / "所需材料表格汇总" / "00_填写文档注册表.json").read_text(
                encoding="utf-8-sig"
            )
        )
        records = [
            item for item in registry["documents"]
            if item.get("id") == "mingge_system"
        ]

        self.assertEqual(
            (DOCUMENTS.get("mingge_system"), records),
            (
                "37_命格系统.xlsx",
                [{
                    "id": "mingge_system",
                    "file": "37_命格系统.xlsx",
                    "consumer": "mingge-system-legacy-rollback",
                    "legacy": None,
                }],
            ),
        )
        self.assertTrue((root / "所需材料表格汇总" / "37_命格系统.xlsx").is_file())


class UserDocumentPackageTests(unittest.TestCase):
    def make_target(self, root: Path) -> None:
        envir = root / "Mir200/Envir"
        (root / "Mir200").mkdir(parents=True)
        (root / "Mir200/M2Server.exe").write_bytes(b"M2")
        (envir / "Market_Def").mkdir(parents=True)
        (envir / "MapInfo.txt").write_text("[0 盟重]\r\n", encoding="gb18030")
        (envir / "Market_Def/QFunction-0.txt").write_text(
            "[@PlayLogin]\r\n#IF\r\n#ACT\r\n", encoding="gb18030"
        )

    def make_package(self, root: Path, user_document: str = "15_首爆奖励配置.txt") -> Path:
        package = root / "packages/candidate/xy.optional.user-doc-demo"
        (package / "payload").mkdir(parents=True)
        (package / "payload/default.txt").write_text("来源=包内默认\n", encoding="utf-8")
        data = {
            "schema_version": 1,
            "id": "xy.optional.user-doc-demo",
            "version": "1.0.0",
            "display_name": "填写文档演示",
            "status": "candidate",
            "engine": "LFM2",
            "residency": "optional",
            "bundle": None,
            "dependencies": [],
            "parameters": {},
            "claims": {"labels": [], "variables": [], "maps": [], "npcs": []},
            "operations": [{
                "type": "render",
                "source": "payload/default.txt",
                "user_document": user_document,
                "target": "Mir200/Envir/QuestDiary/玄渊配置/填写文档演示.txt",
                "source_encoding": "utf-8",
                "target_encoding": "gb18030",
                "newline": "\r\n",
            }],
            "preflight_checks": [],
            "post_checks": [],
            "evidence": ["static:test"],
        }
        (package / "manifest.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        return package

    def test_preflight_prefers_central_document_without_writing_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "server"
            self.make_target(target)
            self.make_package(root)
            central = root / "所需材料表格汇总/15_首爆奖励配置.txt"
            central.parent.mkdir(parents=True)
            central.write_text("来源=中文母版\n", encoding="utf-8")
            repository = PackageRepository(root / "packages")
            repository.refresh()
            plan = Installer(repository, root / "backups").preflight(
                target, ["xy.optional.user-doc-demo"], {}
            )
            output = target / "Mir200/Envir/QuestDiary/玄渊配置/填写文档演示.txt"
            self.assertFalse(output.exists())
            self.assertEqual(plan.changes[0].after.decode("gb18030"), "来源=中文母版\r\n")

    def test_validator_rejects_nested_user_document_path(self):
        with tempfile.TemporaryDirectory() as td:
            package = self.make_package(Path(td), "子目录/配置.txt")
            with self.assertRaisesRegex(PackageValidationError, "单个文件名"):
                validate_package(package)


if __name__ == "__main__":
    unittest.main()
