import json
import contextlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path

from xydp.artifact_library import ArtifactLibrary, ReviewDecision
from xydp.cli import main


class ArtifactLibraryTests(unittest.TestCase):
    def test_extracts_every_file_and_codex_wins_conflicting_basename(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex = root / "codex"
            legacy = root / "legacy"
            platform = root / "platform"
            (codex / "rules").mkdir(parents=True)
            (legacy / "skills").mkdir(parents=True)
            (codex / "rules" / "same.txt").write_text("交班正式版", encoding="utf-8")
            (legacy / "skills" / "same.txt").write_text("旧版", encoding="utf-8")
            (legacy / "skills" / "only.txt").write_text("唯一成果", encoding="utf-8")

            report = ArtifactLibrary(platform).extract(
                {"codex_handover": codex, "legacy_ai_handoff": legacy}
            )

            self.assertEqual(report.total_source_files, 3)
            self.assertEqual(report.verified_files, 3)
            self.assertEqual(
                (platform / "library/sources/codex_handover/rules/same.txt").read_text(encoding="utf-8"),
                "交班正式版",
            )
            catalog = json.loads((platform / "catalog/artifacts.json").read_text(encoding="utf-8"))
            conflict = next(item for item in catalog["conflicts"] if item["logical_key"] == "same.txt")
            self.assertEqual(conflict["selected_source"], "codex_handover")
            self.assertEqual(len(conflict["variants"]), 2)
            migration = json.loads((platform / "migration/full_extraction_latest.json").read_text(encoding="utf-8"))
            self.assertEqual(migration["status"], "completed")
            self.assertEqual(migration["summary"]["verified_files"], 3)

    def test_second_extraction_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            (source / "one.txt").write_text("one", encoding="utf-8")
            library = ArtifactLibrary(root / "platform")

            first = library.extract({"codex_handover": source})
            second = library.extract({"codex_handover": source})

            self.assertEqual(first.copied_files, 1)
            self.assertEqual(second.copied_files, 0)
            self.assertEqual(second.unchanged_files, 1)

    def test_extracts_read_only_binary_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            binary = source / "frame.bin"
            binary.write_bytes(b"\x00\x01\x02")
            os.chmod(binary, stat.S_IREAD)
            try:
                report = ArtifactLibrary(root / "platform").extract({"legacy_ai_handoff": source})
                self.assertEqual(report.verified_files, 1)
                self.assertEqual((root / "platform/library/sources/legacy_ai_handoff/frame.bin").read_bytes(), b"\x00\x01\x02")
            finally:
                os.chmod(binary, stat.S_IWRITE)

    def test_replaces_stale_read_only_archive_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            (source / "frame.bin").write_bytes(b"new")
            stale = root / "platform/library/sources/legacy_ai_handoff/frame.bin"
            stale.parent.mkdir(parents=True)
            stale.write_bytes(b"old")
            os.chmod(stale, stat.S_IREAD)

            report = ArtifactLibrary(root / "platform").extract({"legacy_ai_handoff": source})

            self.assertEqual(report.copied_files, 1)
            self.assertEqual(stale.read_bytes(), b"new")

    def test_deepseek_review_routes_verified_candidate_and_deprecated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            deepseek = root / "deepseek"
            (deepseek / "03_待GPT审核").mkdir(parents=True)
            (deepseek / "05_废弃与错误输出").mkdir(parents=True)
            (deepseek / "04_已采纳归档").mkdir(parents=True)
            (deepseek / "03_待GPT审核" / "XY-SKILL-005.md").write_text("已验证组合", encoding="utf-8")
            (deepseek / "03_待GPT审核" / "XY-SKILL-006.md").write_text("仍待确认", encoding="utf-8")
            (deepseek / "05_废弃与错误输出" / "XY-SKILL-002.md").write_text("错误路线", encoding="utf-8")
            (deepseek / "04_已采纳归档" / "XY-SKILL-003.md").write_text("已采纳", encoding="utf-8")
            decisions = {
                "03_待GPT审核/XY-SKILL-005.md": ReviewDecision(
                    status="verified", reason="由旧施工日志和测试记录交叉佐证"
                ),
                "03_待GPT审核/XY-SKILL-006.md": ReviewDecision(
                    status="candidate", reason="与部分验证记录冲突，等待游戏验收"
                ),
            }

            report = ArtifactLibrary(root / "platform").review_deepseek(deepseek, decisions)

            self.assertEqual(report.counts["verified"], 2)
            self.assertEqual(report.counts["candidate"], 1)
            self.assertEqual(report.counts["deprecated"], 1)
            self.assertTrue((root / "platform/library/reviewed/deepseek/verified/03_待GPT审核/XY-SKILL-005.md").is_file())
            self.assertTrue((root / "platform/library/reviewed/deepseek/deprecated/05_废弃与错误输出/XY-SKILL-002.md").is_file())
            review = json.loads((root / "platform/catalog/deepseek_review.json").read_text(encoding="utf-8"))
            self.assertEqual(len(review["items"]), 4)

    def test_cli_extract_library_requires_confirmation_and_uses_review_decisions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex = root / "codex"
            legacy = root / "legacy"
            deepseek = codex / "deepseek专用"
            deepseek.mkdir(parents=True)
            legacy.mkdir()
            (deepseek / "skill.md").write_text("技能", encoding="utf-8")
            (legacy / "old.txt").write_text("旧成果", encoding="utf-8")
            decisions = root / "decisions.json"
            decisions.write_text(
                json.dumps({"skill.md": {"status": "verified", "reason": "交叉验证"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            args = [
                "--root", str(root / "platform"), "extract-library",
                "--codex", str(codex), "--legacy", str(legacy),
                "--deepseek", str(deepseek), "--decisions", str(decisions),
            ]
            with self.assertRaisesRegex(SystemExit, "--yes"):
                main(args)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(args + ["--yes"])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["review"]["counts"]["verified"], 1)
            self.assertEqual(result["extraction"]["total_source_files"], 2)


if __name__ == "__main__":
    unittest.main()
