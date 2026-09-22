from pathlib import Path
import tempfile
import unittest

from xydp.storage_paths import (
    configure_platform_temp,
    workbench_pak_export_jobs_root,
    workbench_user_data_root,
)


class StoragePathTests(unittest.TestCase):
    def test_workbench_data_defaults_to_platform_e_drive_tree(self) -> None:
        platform_root = Path(r"E:\XuanYuanDevPlatform")

        user_data = workbench_user_data_root(platform_root, env={})

        self.assertEqual(
            user_data,
            platform_root / "玄渊界面施工台" / "user-data",
        )
        self.assertEqual(
            workbench_pak_export_jobs_root(platform_root, env={}),
            user_data / "workspace" / "pak-export-jobs",
        )

    def test_explicit_user_data_override_wins(self) -> None:
        platform_root = Path(r"E:\XuanYuanDevPlatform")
        override = Path(r"F:\玄渊数据")

        self.assertEqual(
            workbench_user_data_root(
                platform_root,
                env={"XYDP_USER_DATA_ROOT": str(override)},
            ),
            override,
        )

    def test_runtime_temp_is_kept_inside_platform_root(self) -> None:
        platform_root = Path(r"E:\XuanYuanDevPlatform")
        env: dict[str, str] = {}
        previous = tempfile.tempdir
        try:
            runtime_temp = configure_platform_temp(platform_root, env=env, create=False)
            self.assertEqual(runtime_temp, platform_root / "runtime" / "temp")
            self.assertEqual(env["TEMP"], str(runtime_temp))
            self.assertEqual(env["TMP"], str(runtime_temp))
            self.assertEqual(tempfile.tempdir, str(runtime_temp))
        finally:
            tempfile.tempdir = previous

    def test_build_script_redirects_build_cache_to_platform_runtime(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("$env:TEMP = $BuildTemp", source)
        self.assertIn("$env:TMP = $BuildTemp", source)
        self.assertIn("$env:PYINSTALLER_CONFIG_DIR = $PyInstallerConfig", source)


if __name__ == "__main__":
    unittest.main()
