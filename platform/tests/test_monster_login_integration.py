from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from xydp.monster_library import MonsterLibraryPlan, MonsterLibraryService
from xydp.monster_login_integration import (
    read_makegamelogin_config,
    verify_custom_monster_login,
)


class MonsterLoginIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.generator = self.root / "generator"
        self.generator.mkdir()
        self.server = self.root / "server"
        self.client = self.root / "client" / "data"
        self.client.mkdir(parents=True)
        self.dat = self.server / "Mir200" / "自定义怪物.dat"
        self.dat.parent.mkdir(parents=True)
        self.launcher = self.client.parent / "传奇登陆器.exe"
        self.ini = self.server / "Mir200" / "Envir" / "SmartMonster" / "测试怪.ini"
        self.effect_list = self.server / "Mir200" / "Envir" / "EffectImageList.txt"
        self.ini.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_with_mtime(path: Path, data: bytes, mtime_ns: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, ns=(mtime_ns, mtime_ns))

    def _write_config(self, *, enabled: str = "1", dat_path: str | None = None) -> bytes:
        text = (
            "[Setup]\r\n"
            f"集成怪物配置={enabled}\r\n"
            f"怪物配置文件={dat_path or self.dat.resolve()}\r\n"
        )
        raw = text.encode("gb18030")
        (self.generator / "Config.ini").write_bytes(raw)
        return raw

    def _write_ready_files(self) -> None:
        self._write_with_mtime(self.dat, b"dat", 100_000_000_000)
        self._write_with_mtime(self.ini, b"ini", 110_000_000_000)
        self._write_with_mtime(self.effect_list, b"effect", 120_000_000_000)
        self._write_with_mtime(self.launcher, b"launcher", 130_000_000_000)
        self._write_config()

    def _verify(self, dependencies: tuple[Path, ...] | None = None):
        return verify_custom_monster_login(
            self.generator,
            self.dat,
            self.launcher,
            dependencies if dependencies is not None else (self.ini, self.effect_list),
        )

    def _plan(self, *, smartmonster: bool) -> MonsterLibraryPlan:
        return MonsterLibraryPlan(
            server_root=self.server.resolve(),
            client_data=self.client.resolve(),
            selected_ids=(1,),
            monster_names=("测试怪",),
            library_numbers=(),
            changes=[],
            blockers=[],
            warnings=[],
            skipped=[],
            requires_custom_monster_dat=smartmonster,
            requires_login_regeneration=smartmonster,
        )

    def test_config_requires_enabled_flag_and_exact_dat_path(self) -> None:
        self._write_ready_files()
        self.assertEqual(self._verify().status, "ready")

        self._write_config(enabled="0")
        disabled = self._verify()
        self.assertEqual(disabled.status, "generator_not_configured")
        self.assertIn("集成怪物配置", disabled.next_step)

        self._write_config(dat_path=str(self.server / "Mir200" / "别的怪物.dat"))
        wrong_path = self._verify()
        self.assertEqual(wrong_path.status, "generator_not_configured")
        self.assertIn(str(self.dat.resolve()), wrong_path.next_step)

    def test_launcher_must_be_newer_than_dat_ini_and_effect_list(self) -> None:
        self._write_ready_files()
        ready = self._verify()
        self.assertEqual(ready.status, "ready")
        self.assertEqual(ready.newest_dependency_path, str(self.effect_list.resolve()))

        self._write_with_mtime(self.launcher, b"launcher", 119_000_000_000)
        stale = self._verify()
        self.assertEqual(stale.status, "launcher_stale")
        self.assertIn("重新生成登录器", stale.next_step)

    def test_equal_launcher_timestamp_is_stale(self) -> None:
        self._write_ready_files()
        self._write_with_mtime(self.launcher, b"launcher", 120_000_000_000)
        self.assertEqual(self._verify().status, "launcher_stale")

    def test_gb18030_config_is_read_without_reencoding(self) -> None:
        before = self._write_config()
        before_hash = hashlib.sha256(before).hexdigest()

        settings = read_makegamelogin_config(self.generator / "Config.ini")

        after = (self.generator / "Config.ini").read_bytes()
        self.assertEqual(settings["集成怪物配置"], "1")
        self.assertEqual(settings["怪物配置文件"], str(self.dat.resolve()))
        self.assertEqual(hashlib.sha256(after).hexdigest(), before_hash)
        self.assertEqual(after, before)

    def test_windows_dat_path_comparison_is_case_insensitive(self) -> None:
        self._write_ready_files()
        self._write_config(dat_path=str(self.dat.resolve()).swapcase())
        self.assertEqual(self._verify().status, "ready")

    def test_missing_config_launcher_and_dependency_have_deterministic_statuses(self) -> None:
        self._write_with_mtime(self.dat, b"dat", 100_000_000_000)
        missing_config = self._verify()
        self.assertEqual(missing_config.status, "generator_not_configured")
        self.assertIn("Config.ini", missing_config.next_step)

        self._write_config()
        self._write_with_mtime(self.ini, b"ini", 110_000_000_000)
        self._write_with_mtime(self.effect_list, b"effect", 120_000_000_000)
        missing_launcher = self._verify()
        self.assertEqual(missing_launcher.status, "launcher_stale")
        self.assertIn(str(self.launcher.resolve()), missing_launcher.next_step)

        self._write_with_mtime(self.launcher, b"launcher", 130_000_000_000)
        self.effect_list.unlink()
        missing_dependency = self._verify()
        self.assertEqual(missing_dependency.status, "launcher_stale")
        self.assertIn(str(self.effect_list.resolve()), missing_dependency.next_step)

    def test_missing_dat_is_reported_before_generator_configuration(self) -> None:
        result = self._verify()
        self.assertEqual(result.status, "missing_dat")
        self.assertIn(str(self.dat.resolve()), result.next_step)

    def test_status_contains_hash_and_mtime_evidence_without_writes(self) -> None:
        self._write_ready_files()
        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (self.generator / "Config.ini", self.dat, self.launcher, self.ini, self.effect_list)
        }

        status = self._verify()

        by_path = {item.path: item for item in status.evidence}
        self.assertEqual(status.status, "ready")
        self.assertEqual(by_path[str(self.dat.resolve())].sha256, hashlib.sha256(b"dat").hexdigest().upper())
        self.assertEqual(by_path[str(self.launcher.resolve())].mtime_ns, 130_000_000_000)
        for path, expected in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), expected)

    def test_standard_appr_plan_does_not_require_custom_dat(self) -> None:
        plan = self._plan(smartmonster=False)
        summary = MonsterLibraryService.plan_summary(plan)
        payload = MonsterLibraryService._receipt_payload(
            plan, "20260824_030000_1234abcd", [], status="deployed", completed=[]
        )

        self.assertFalse(summary["requires_custom_monster_dat"])
        self.assertFalse(summary["requires_login_regeneration"])
        self.assertEqual(summary["custom_monster_dat_path"], str(self.dat.resolve()))
        self.assertEqual(summary["client_integration_status"], "not-required")
        self.assertEqual(payload["status"], "deployed")
        self.assertEqual(payload["client_integration_status"], "not-required")

    def test_smartmonster_receipt_is_awaiting_client_integration(self) -> None:
        plan = self._plan(smartmonster=True)
        summary = MonsterLibraryService.plan_summary(plan)
        payload = MonsterLibraryService._receipt_payload(
            plan, "20260824_030000_1234abcd", [], status="deployed", completed=[]
        )

        self.assertEqual(summary["custom_monster_dat_path"], str(self.dat.resolve()))
        self.assertEqual(summary["client_integration_status"], "awaiting-client-integration")
        self.assertEqual(payload["status"], "deployed-awaiting-client-integration")
        self.assertEqual(payload["custom_monster_dat_path"], str(self.dat.resolve()))
        self.assertEqual(payload["client_integration_status"], "awaiting-client-integration")

    def test_smartmonster_in_progress_manifest_keeps_recovery_status(self) -> None:
        plan = self._plan(smartmonster=True)
        payload = MonsterLibraryService._receipt_payload(
            plan, "20260824_030000_1234abcd", [], status="in-progress", completed=[]
        )
        self.assertEqual(payload["schema_version"], 4)
        self.assertEqual(payload["status"], "in-progress")
        self.assertEqual(payload["recovery_state"], {"completed_indices": []})


if __name__ == "__main__":
    unittest.main()
