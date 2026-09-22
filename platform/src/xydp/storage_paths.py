from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


USER_DATA_ENV = "XYDP_USER_DATA_ROOT"


def configure_platform_temp(
    platform_root: Path,
    *,
    env: dict[str, str] | None = None,
    create: bool = True,
) -> Path:
    runtime_temp = platform_root.resolve() / "runtime" / "temp"
    if create:
        runtime_temp.mkdir(parents=True, exist_ok=True)
    values = os.environ if env is None else env
    values["TEMP"] = str(runtime_temp)
    values["TMP"] = str(runtime_temp)
    tempfile.tempdir = str(runtime_temp)
    return runtime_temp


def workbench_user_data_root(
    platform_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    values = os.environ if env is None else env
    configured = values.get(USER_DATA_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return platform_root.resolve() / "玄渊界面施工台" / "user-data"


def workbench_pak_export_jobs_root(
    platform_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return workbench_user_data_root(platform_root, env=env) / "workspace" / "pak-export-jobs"
