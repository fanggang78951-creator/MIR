from __future__ import annotations

import hashlib
import ntpath
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class LoginFileEvidence:
    path: str
    exists: bool
    sha256: str | None
    mtime_ns: int | None


@dataclass(frozen=True)
class LoginIntegrationStatus:
    status: str
    next_step: str
    config_path: str
    dat_path: str
    launcher_path: str
    newest_dependency_path: str | None
    newest_dependency_mtime_ns: int | None
    launcher_mtime_ns: int | None
    evidence: tuple[LoginFileEvidence, ...]


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _file_evidence(path: Path) -> LoginFileEvidence:
    resolved = path.resolve()
    if not resolved.is_file():
        return LoginFileEvidence(str(resolved), False, None, None)
    stat = resolved.stat()
    return LoginFileEvidence(
        path=str(resolved),
        exists=True,
        sha256=_sha256_file(resolved),
        mtime_ns=stat.st_mtime_ns,
    )


def read_makegamelogin_config(config_path: Path) -> dict[str, str]:
    """Read MakeGameLogin key/value settings without rewriting the source file."""
    raw = Path(config_path).read_bytes()
    text: str | None = None
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    if text is None:
        assert last_error is not None
        raise last_error

    settings: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith((";", "#", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            settings[key] = value.strip()
    return settings


def _windows_absolute_key(value: str) -> str | None:
    candidate = value.strip().strip('"')
    if not ntpath.isabs(candidate):
        return None
    return ntpath.normcase(ntpath.normpath(candidate))


def verify_custom_monster_login(
    generator_dir: Path,
    dat_path: Path,
    launcher_path: Path,
    dependency_paths: Sequence[Path],
) -> LoginIntegrationStatus:
    """Return the read-only DAT/MakeGameLogin/launcher freshness state."""
    generator_dir = Path(generator_dir).resolve()
    config_path = (generator_dir / "Config.ini").resolve()
    dat_path = Path(dat_path).resolve()
    launcher_path = Path(launcher_path).resolve()
    dependencies = tuple(Path(item).resolve() for item in dependency_paths)
    evidence = tuple(
        _file_evidence(path)
        for path in (config_path, dat_path, launcher_path, *dependencies)
    )

    dependency_evidence = evidence[3:]
    existing_dependencies = tuple(item for item in dependency_evidence if item.mtime_ns is not None)
    newest_dependency = (
        max(existing_dependencies, key=lambda item: (int(item.mtime_ns or -1), item.path.casefold()))
        if existing_dependencies else None
    )

    def result(status: str, next_step: str) -> LoginIntegrationStatus:
        return LoginIntegrationStatus(
            status=status,
            next_step=next_step,
            config_path=str(config_path),
            dat_path=str(dat_path),
            launcher_path=str(launcher_path),
            newest_dependency_path=newest_dependency.path if newest_dependency else None,
            newest_dependency_mtime_ns=newest_dependency.mtime_ns if newest_dependency else None,
            launcher_mtime_ns=evidence[2].mtime_ns,
            evidence=evidence,
        )

    if not dat_path.is_file():
        return result("missing_dat", f"在M2怪物设置中生成自定义怪物DAT：{dat_path}")

    if not config_path.is_file():
        return result(
            "generator_not_configured",
            f"在MakeGameLogin集成配置中选择Config.ini并启用自定义怪物配置：{config_path}",
        )
    try:
        settings = read_makegamelogin_config(config_path)
    except (OSError, UnicodeError):
        return result(
            "generator_not_configured",
            f"在MakeGameLogin中重新保存可读取的集成配置：{config_path}",
        )
    configured_dat = _windows_absolute_key(settings.get("怪物配置文件", ""))
    requested_dat = _windows_absolute_key(str(dat_path))
    if settings.get("集成怪物配置", "").strip() != "1" or configured_dat != requested_dat:
        return result(
            "generator_not_configured",
            f"在MakeGameLogin集成配置中勾选集成怪物配置，并选择：{dat_path}",
        )

    missing_dependencies = [item.path for item in dependency_evidence if not item.exists]
    if missing_dependencies:
        return result(
            "launcher_stale",
            "先补齐登录器验收依赖，再重新生成登录器：" + "；".join(missing_dependencies),
        )
    if not launcher_path.is_file():
        return result("launcher_stale", f"使用MakeGameLogin重新生成登录器：{launcher_path}")

    launcher_mtime = launcher_path.stat().st_mtime_ns
    required_mtimes = [dat_path.stat().st_mtime_ns]
    required_mtimes.extend(int(item.mtime_ns) for item in dependency_evidence if item.mtime_ns is not None)
    if launcher_mtime <= max(required_mtimes):
        return result(
            "launcher_stale",
            "使用MakeGameLogin重新生成登录器，确保登录器晚于DAT、SmartMonster INI和EffectImageList。",
        )
    return result("ready", "登录器集成门禁已通过；继续进行单怪身体与五类动作验收。")
