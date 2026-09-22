from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 1
DEFAULT_MIN_AGE_DAYS = 14

# These directories contain source-of-truth content, evidence, packages, client
# resources, workbooks, backups or released binaries.  They are never scanned
# for cleanup candidates.
HARD_PROTECTED_TOP_LEVEL = {
    ".git",
    "archive",
    "assets",
    "backups",
    "bin",
    "catalog",
    "docs",
    "Envir",
    "evidence",
    "knowledge",
    "labs",
    "library",
    "map-replication-projects",
    "migration",
    "outputs",
    "packages",
    "templates",
    "testbeds",
    "vendor",
    "wzl编辑",
    "测试后台监视",
    "所需材料表格汇总",
    "怪物库",
    "接口",
    "非常驻脚本",
    "NPC脚本",
    "做装备",
    "玄渊界面施工台",
}

# Build and tmp are shown one child at a time, but remain review-only and are
# never selected automatically.
REVIEW_ROOTS = {"build", "tmp"}
CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
CACHE_FILE_NAMES = {".coverage", ".DS_Store", "Thumbs.db"}
CACHE_SUFFIXES = {".pyc", ".pyo"}
QUARANTINE_RELATIVE = Path("backups") / "cleanup_quarantine"


@dataclass
class Candidate:
    candidate_id: str
    category: str
    relative_path: str
    kind: str
    bytes: int
    file_count: int
    newest_mtime_ns: int
    fingerprint: str
    default_selected: bool
    eligible: bool
    reason: str


@dataclass
class ScanResult:
    schema_version: int
    generated_at: str
    root: str
    min_age_days: int
    candidates: list[Candidate]
    protected_top_level: list[str]
    note: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["candidates"] = [asdict(item) for item in self.candidates]
        return data


class CleanerError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _norm_root(root: Path | str) -> Path:
    resolved = Path(root).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise CleanerError(f"平台根目录不存在：{resolved}")
    return resolved


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attrs & flag)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_metadata(path: Path) -> tuple[int, int, int, str, bool]:
    """Return bytes, file count, newest mtime, metadata digest, has reparse.

    Directory fingerprints intentionally hash names, sizes and mtimes instead of
    reading the full contents of large build directories.  The fingerprint is
    recomputed immediately before quarantine.
    """
    if _is_reparse(path):
        return 0, 0, 0, "", True
    if path.is_file():
        info = path.stat()
        token = f"F\0{path.name}\0{info.st_size}\0{info.st_mtime_ns}".encode("utf-8")
        return info.st_size, 1, info.st_mtime_ns, hashlib.sha256(token).hexdigest(), False

    total = 0
    count = 0
    newest = path.stat().st_mtime_ns
    digest = hashlib.sha256()
    has_reparse = False
    for current, dirs, files in os.walk(path, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in sorted(dirs, key=str.casefold):
            child = current_path / name
            if _is_reparse(child):
                has_reparse = True
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs
        for name in sorted(files, key=str.casefold):
            child = current_path / name
            if _is_reparse(child):
                has_reparse = True
                continue
            try:
                info = child.stat()
            except OSError:
                has_reparse = True
                continue
            rel = child.relative_to(path).as_posix()
            total += info.st_size
            count += 1
            newest = max(newest, info.st_mtime_ns)
            digest.update(f"{rel}\0{info.st_size}\0{info.st_mtime_ns}\n".encode("utf-8"))
    return total, count, newest, digest.hexdigest(), has_reparse


def _candidate(path: Path, root: Path, category: str, default: bool, reason: str) -> Candidate:
    size, count, newest, fingerprint, has_reparse = _tree_metadata(path)
    rel = path.relative_to(root).as_posix()
    candidate_id = hashlib.sha256(f"{category}\0{rel}".encode("utf-8")).hexdigest()[:16]
    eligible = not has_reparse
    if has_reparse:
        reason = f"{reason}；含链接或重解析点，禁止操作"
        default = False
    return Candidate(
        candidate_id=candidate_id,
        category=category,
        relative_path=rel,
        kind="directory" if path.is_dir() else "file",
        bytes=size,
        file_count=count,
        newest_mtime_ns=newest,
        fingerprint=fingerprint,
        default_selected=default and eligible,
        eligible=eligible,
        reason=reason,
    )


def _is_old_enough(mtime_ns: int, min_age_days: int) -> bool:
    if min_age_days <= 0:
        return True
    cutoff_ns = int(datetime.now().timestamp() * 1_000_000_000) - min_age_days * 86400 * 1_000_000_000
    return mtime_ns <= cutoff_ns


def _iter_cache_candidates(root: Path, min_age_days: int) -> Iterable[Candidate]:
    skip = {name.casefold() for name in HARD_PROTECTED_TOP_LEVEL | REVIEW_ROOTS}
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path == root:
            dirs[:] = [name for name in dirs if name.casefold() not in skip]

        cache_dirs: list[str] = []
        normal_dirs: list[str] = []
        for name in dirs:
            child = current_path / name
            if name.casefold() in skip:
                continue
            if name in CACHE_DIR_NAMES:
                cache_dirs.append(name)
            elif not _is_reparse(child):
                normal_dirs.append(name)
        dirs[:] = normal_dirs

        for name in sorted(cache_dirs, key=str.casefold):
            item = _candidate(
                current_path / name,
                root,
                "python_cache",
                default=True,
                reason="可再生的 Python/测试缓存；达到保留天数时才默认勾选",
            )
            item.default_selected = item.default_selected and _is_old_enough(item.newest_mtime_ns, min_age_days)
            yield item

        for name in sorted(files, key=str.casefold):
            child = current_path / name
            if name not in CACHE_FILE_NAMES and child.suffix.casefold() not in CACHE_SUFFIXES:
                continue
            item = _candidate(
                child,
                root,
                "cache_file",
                default=True,
                reason="可再生缓存文件；达到保留天数时才默认勾选",
            )
            item.default_selected = item.default_selected and _is_old_enough(item.newest_mtime_ns, min_age_days)
            yield item


def scan(root: Path | str, min_age_days: int = DEFAULT_MIN_AGE_DAYS) -> ScanResult:
    root_path = _norm_root(root)
    if min_age_days < 0:
        raise CleanerError("保留天数不能小于 0")

    candidates: list[Candidate] = []
    for review_root in sorted(REVIEW_ROOTS):
        parent = root_path / review_root
        if not parent.is_dir() or _is_reparse(parent):
            continue
        for child in sorted(parent.iterdir(), key=lambda p: p.name.casefold()):
            category = "build_review" if review_root == "build" else "tmp_review"
            reason = "构建中间/发布候选，必须逐项人工复核" if review_root == "build" else "临时施工资料可能含验收证据，必须逐项人工复核"
            candidates.append(_candidate(child, root_path, category, default=False, reason=reason))

    candidates.extend(_iter_cache_candidates(root_path, min_age_days))

    failed_tmp = root_path / "logs"
    if failed_tmp.is_dir():
        for child in sorted(failed_tmp.glob("*.xydp.tmp"), key=lambda p: p.name.casefold()):
            candidates.append(
                _candidate(
                    child,
                    root_path,
                    "failed_transaction_review",
                    default=False,
                    reason="失败事务残留；先核对对应事务和备份，默认不选",
                )
            )

    candidates.sort(key=lambda item: (item.category, item.relative_path.casefold()))
    return ScanResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now_iso(),
        root=str(root_path),
        min_age_days=min_age_days,
        candidates=candidates,
        protected_top_level=sorted(HARD_PROTECTED_TOP_LEVEL),
        note="只读扫描；构建目录、tmp、日志残留均不自动勾选。",
    )


def write_scan_report(result: ScanResult, destination: Path | str) -> Path:
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".writing")
    temporary.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return target


def _selected_candidates(result: ScanResult, candidate_ids: Iterable[str]) -> list[Candidate]:
    requested = set(candidate_ids)
    available = {item.candidate_id: item for item in result.candidates}
    unknown = requested - available.keys()
    if unknown:
        raise CleanerError(f"扫描计划中不存在这些项目：{', '.join(sorted(unknown))}")
    selected = [available[item_id] for item_id in requested]
    if not selected:
        raise CleanerError("没有勾选任何项目")
    blocked = [item.relative_path for item in selected if not item.eligible]
    if blocked:
        raise CleanerError("以下项目不可操作：" + "；".join(blocked))
    return sorted(selected, key=lambda item: item.relative_path.casefold())


def _revalidate(root: Path, item: Candidate) -> Path:
    path = (root / Path(item.relative_path)).resolve(strict=True)
    if not _within(path, root) or path == root:
        raise CleanerError(f"路径越界，已阻止：{item.relative_path}")
    top = path.relative_to(root).parts[0]
    if top in HARD_PROTECTED_TOP_LEVEL and item.category != "failed_transaction_review":
        raise CleanerError(f"命中硬保护目录，已阻止：{item.relative_path}")
    if item.category == "failed_transaction_review" and top != "logs":
        raise CleanerError(f"失败事务残留不在日志目录，已阻止：{item.relative_path}")
    size, count, newest, fingerprint, has_reparse = _tree_metadata(path)
    if has_reparse:
        raise CleanerError(f"发现链接或重解析点，已阻止：{item.relative_path}")
    actual = (size, count, newest, fingerprint)
    expected = (item.bytes, item.file_count, item.newest_mtime_ns, item.fingerprint)
    if actual != expected:
        raise CleanerError(f"扫描后内容已变化，请重新扫描：{item.relative_path}")
    return path


def quarantine(result: ScanResult, candidate_ids: Iterable[str]) -> Path:
    root = _norm_root(result.root)
    selected = _selected_candidates(result, candidate_ids)
    validated = [(item, _revalidate(root, item)) for item in selected]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    transaction_root = root / QUARANTINE_RELATIVE / stamp
    files_root = transaction_root / "files"
    files_root.mkdir(parents=True, exist_ok=False)
    receipt_path = transaction_root / "receipt.json"
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "operation": "quarantine",
        "created_at": _now_iso(),
        "root": str(root),
        "transaction_root": str(transaction_root),
        "status": "applying",
        "items": [
            {
                **asdict(item),
                "quarantine_relative_path": str((Path("files") / Path(item.relative_path)).as_posix()),
            }
            for item, _ in validated
        ],
        "note": "未永久删除；可使用本程序按本收据恢复。",
    }
    try:
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        shutil.rmtree(transaction_root, ignore_errors=True)
        raise CleanerError(f"无法先写入隔离收据，未移动任何文件：{exc}") from exc
    moved: list[tuple[Candidate, Path, Path]] = []
    try:
        for item, source in validated:
            destination = files_root / Path(item.relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise CleanerError(f"隔离目标已存在：{destination}")
            shutil.move(str(source), str(destination))
            moved.append((item, source, destination))
    except Exception as exc:
        rollback_errors: list[str] = []
        for _, source, destination in reversed(moved):
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
            except Exception as rollback_exc:  # pragma: no cover - catastrophic path
                rollback_errors.append(str(rollback_exc))
        if transaction_root.exists() and not rollback_errors:
            shutil.rmtree(transaction_root, ignore_errors=True)
        suffix = "" if not rollback_errors else "；回退异常：" + "；".join(rollback_errors)
        raise CleanerError(f"隔离失败，已回退：{exc}{suffix}") from exc

    receipt["status"] = "quarantined"
    receipt["completed_at"] = _now_iso()
    temporary_receipt = receipt_path.with_name("receipt.json.writing")
    try:
        temporary_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_receipt, receipt_path)
    except Exception as exc:
        rollback_errors: list[str] = []
        for _, source, destination in reversed(moved):
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
            except Exception as rollback_exc:  # pragma: no cover
                rollback_errors.append(str(rollback_exc))
        if not rollback_errors:
            shutil.rmtree(transaction_root, ignore_errors=True)
        suffix = "" if not rollback_errors else "；回退异常：" + "；".join(rollback_errors)
        raise CleanerError(f"完成收据写入失败，已回退：{exc}{suffix}") from exc
    return receipt_path


def restore(receipt_path: Path | str) -> Path:
    receipt_file = Path(receipt_path).expanduser().resolve(strict=True)
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    if receipt.get("operation") != "quarantine" or receipt.get("status") != "quarantined":
        raise CleanerError("收据不是可恢复的隔离记录")
    root = _norm_root(receipt["root"])
    transaction_root = Path(receipt["transaction_root"]).resolve(strict=True)
    quarantine_root = (root / QUARANTINE_RELATIVE).resolve()
    if not _within(transaction_root, quarantine_root):
        raise CleanerError("隔离收据路径越界，已阻止")

    prepared: list[tuple[Path, Path, dict]] = []
    for item in receipt.get("items", []):
        source = (transaction_root / item["quarantine_relative_path"]).resolve(strict=True)
        destination = (root / Path(item["relative_path"])).resolve()
        if not _within(source, transaction_root) or not _within(destination, root):
            raise CleanerError(f"恢复路径越界，已阻止：{item.get('relative_path')}")
        if destination.exists():
            raise CleanerError(f"原位置已有同名内容，禁止覆盖：{destination}")
        size, count, newest, fingerprint, has_reparse = _tree_metadata(source)
        if has_reparse or (size, count, newest, fingerprint) != (
            item["bytes"], item["file_count"], item["newest_mtime_ns"], item["fingerprint"]
        ):
            raise CleanerError(f"隔离内容已变化，禁止恢复：{item['relative_path']}")
        prepared.append((source, destination, item))

    moved: list[tuple[Path, Path]] = []
    try:
        for source, destination, _ in prepared:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append((source, destination))
    except Exception as exc:
        rollback_errors: list[str] = []
        for source, destination in reversed(moved):
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
            except Exception as rollback_exc:  # pragma: no cover
                rollback_errors.append(str(rollback_exc))
        suffix = "" if not rollback_errors else "；回退异常：" + "；".join(rollback_errors)
        raise CleanerError(f"恢复失败，已回退：{exc}{suffix}") from exc

    restored_receipt = dict(receipt)
    restored_receipt["status"] = "restored"
    restored_receipt["restored_at"] = _now_iso()
    restored_path = receipt_file.with_name("receipt.restored.json")
    restored_path.write_text(json.dumps(restored_receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    receipt_file.write_text(json.dumps(restored_receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return restored_path


def human_size(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{amount:.2f} TB"
