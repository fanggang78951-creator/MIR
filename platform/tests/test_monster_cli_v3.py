from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from xydp.cli import _parser, main


@dataclass(frozen=True)
class _ScanResult:
    status: str = "ok"


class MonsterCliV3Tests(unittest.TestCase):
    def test_cli_scan_accepts_and_passes_optional_donor_server_root(self) -> None:
        paths = [Path(f"C:/fixture/{name}") for name in ("ApexM2.DB", "wzl", "pak", "pak.txt", "server", "client", "donor")]
        argv = [
            "monster-library-scan",
            "--donor-db", str(paths[0]),
            "--donor-wzl-data", str(paths[1]),
            "--donor-pak-data", str(paths[2]),
            "--donor-pak-rules", str(paths[3]),
            "--server", str(paths[4]),
            "--client-data", str(paths[5]),
            "--donor-server-root", str(paths[6]),
        ]
        with patch("xydp.cli.MonsterLibraryService") as service_type, redirect_stdout(io.StringIO()):
            service_type.return_value.scan.return_value = _ScanResult()
            code = main(argv)
        self.assertEqual(code, 0)
        call = service_type.return_value.scan.call_args
        self.assertEqual(call.kwargs["donor_server_root"], paths[6])
        self.assertTrue(call.kwargs["materialize"])

    def test_cli_login_verify_emits_read_only_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            server = root / "server"
            client = root / "client"
            generator = root / "generator"
            dat_path = server / "Mir200" / "自定义怪物.dat"
            launcher = client / "传奇登陆器.exe"
            dependency = server / "Mir200" / "Envir" / "SmartMonster" / "测试怪.ini"
            for path in (dat_path, launcher, dependency):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(path.name.encode("utf-8"))
            generator.mkdir(parents=True)
            config = generator / "Config.ini"
            config.write_text(
                f"集成怪物配置=1\r\n怪物配置文件={dat_path.resolve()}\r\n",
                encoding="utf-8-sig",
            )
            os.utime(dat_path, ns=(1_000_000_000, 1_000_000_000))
            os.utime(dependency, ns=(2_000_000_000, 2_000_000_000))
            os.utime(launcher, ns=(3_000_000_000, 3_000_000_000))
            watched = (config, dat_path, launcher, dependency)
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in watched}

            output = io.StringIO()
            with redirect_stdout(output):
                code = main([
                    "monster-login-verify",
                    "--server", str(server),
                    "--client", str(client),
                    "--generator-login-dir", str(generator),
                    "--dependency", str(dependency),
                ])

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(Path(payload["dat_path"]), dat_path.resolve())
            self.assertEqual(Path(payload["launcher_path"]), launcher.resolve())
            self.assertEqual(len(payload["evidence"]), 4)
            self.assertEqual(
                {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in watched},
                before,
            )

    def test_cli_login_verify_exposes_no_apply_or_generation_options(self) -> None:
        parser = _parser()
        for forbidden in ("--apply", "--yes", "--generate"):
            with self.subTest(forbidden=forbidden), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["monster-login-verify", forbidden])

    def test_cli_login_verify_does_not_initialize_unrelated_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            server = root / "server"
            client = root / "client"
            generator = root / "generator"
            dat_path = server / "Mir200" / "自定义怪物.dat"
            launcher = client / "传奇登陆器.exe"
            dat_path.parent.mkdir(parents=True)
            launcher.parent.mkdir(parents=True)
            generator.mkdir(parents=True)
            dat_path.write_bytes(b"DAT")
            launcher.write_bytes(b"LAUNCHER")
            (generator / "Config.ini").write_text(
                f"集成怪物配置=1\r\n怪物配置文件={dat_path.resolve()}\r\n",
                encoding="utf-8-sig",
            )
            os.utime(dat_path, ns=(1_000_000_000, 1_000_000_000))
            os.utime(launcher, ns=(2_000_000_000, 2_000_000_000))

            output = io.StringIO()
            with (
                patch("xydp.cli.PackageRepository", side_effect=RuntimeError("UNRELATED_REPO")),
                redirect_stdout(output),
            ):
                code = main([
                    "monster-login-verify",
                    "--server", str(server),
                    "--client", str(client),
                    "--generator-login-dir", str(generator),
                ])

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "ready")


if __name__ == "__main__":
    unittest.main()
