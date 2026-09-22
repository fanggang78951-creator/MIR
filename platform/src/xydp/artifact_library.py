from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(f".{destination.name}.xydp-copying")
    if temp.exists():
        temp.chmod(stat.S_IREAD | stat.S_IWRITE)
        temp.unlink()
    shutil.copyfile(source, temp)
    temp.chmod(stat.S_IREAD | stat.S_IWRITE)
    if destination.exists():
        destination.chmod(stat.S_IREAD | stat.S_IWRITE)
    os.replace(temp, destination)
    shutil.copystat(source, destination)


@dataclass(frozen=True)
class ReviewDecision:
    status: str
    reason: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewReport:
    total_files: int
    counts: dict[str, int]
    report_path: str


@dataclass(frozen=True)
class ExtractionReport:
    total_source_files: int
    copied_files: int
    unchanged_files: int
    verified_files: int
    conflicts: int
    duplicate_groups: int
    skipped_links: int
    catalog_path: str


class ArtifactLibrary:
    """只读提取成果源，并在平台内建立逐文件哈希目录。"""

    VALID_REVIEW_STATUSES = {"verified", "candidate", "deprecated", "reference"}

    def __init__(self, platform_root: Path):
        self.platform_root = Path(platform_root)
        self.library_root = self.platform_root / "library"
        self.catalog_root = self.platform_root / "catalog"

    def review_deepseek(
        self, deepseek_root: Path, decisions: Mapping[str, ReviewDecision] | None = None
    ) -> ReviewReport:
        deepseek_root = Path(deepseek_root).resolve()
        decisions = {key.replace("\\", "/"): value for key, value in (decisions or {}).items()}
        if not deepseek_root.is_dir():
            raise FileNotFoundError(deepseek_root)
        items: list[dict[str, object]] = []
        counts = {status: 0 for status in sorted(self.VALID_REVIEW_STATUSES)}
        for source in sorted(deepseek_root.rglob("*"), key=lambda item: str(item).casefold()):
            if not source.is_file() or source.is_symlink():
                continue
            relative = source.relative_to(deepseek_root).as_posix()
            decision = decisions.get(relative)
            if decision is None:
                status, reason = self._default_review(relative)
                evidence: tuple[str, ...] = ()
            else:
                status, reason, evidence = decision.status, decision.reason, decision.evidence
            if status not in self.VALID_REVIEW_STATUSES:
                raise ValueError(f"DeepSeek 审核状态无效: {status} ({relative})")
            digest = _sha256(source)
            destination = self.library_root / "reviewed" / "deepseek" / status / Path(relative)
            if not destination.exists() or _sha256(destination) != digest:
                _atomic_copy(source, destination)
            copied_digest = _sha256(destination)
            if copied_digest != digest:
                raise IOError(f"DeepSeek 审核副本哈希不一致: {relative}")
            counts[status] += 1
            items.append(
                {
                    "relative_path": relative,
                    "status": status,
                    "reason": reason,
                    "evidence": list(evidence),
                    "sha256": digest,
                    "reviewed_copy": str(destination),
                }
            )
        report_path = self.catalog_root / "deepseek_review.json"
        _write_json(
            report_path,
            {
                "schema_version": 1,
                "source": str(deepseek_root),
                "reviewed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "counts": counts,
                "items": items,
            },
        )
        return ReviewReport(len(items), counts, str(report_path))

    @staticmethod
    def _default_review(relative: str) -> tuple[str, str]:
        top = relative.split("/", 1)[0]
        if top == "04_已采纳归档":
            return "verified", "已采纳归档；保留为已审核知识成果"
        if top == "05_废弃与错误输出":
            return "deprecated", "来源目录明确标记为废弃或错误，不得成为正式母版"
        if top == "00_说明":
            return "reference", "管理说明，仅作来源边界参考"
        return "candidate", "DeepSeek 默认仅为候选，尚无足够交叉证据晋级"

    def extract(self, sources: Mapping[str, Path]) -> ExtractionReport:
        review_statuses = self._load_deepseek_review()
        run_id = time.strftime("%Y%m%d_%H%M%S")
        records: list[dict[str, object]] = []
        copied = unchanged = verified = skipped_links = 0
        for source_id, root_value in sources.items():
            root = Path(root_value).resolve()
            if not root.is_dir():
                raise FileNotFoundError(root)
            destination_root = self.library_root / "sources" / source_id
            for source in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
                if not source.is_file():
                    continue
                if source.is_symlink():
                    skipped_links += 1
                    continue
                relative = source.relative_to(root)
                digest = _sha256(source)
                destination = destination_root / relative
                if destination.exists():
                    destination_digest = _sha256(destination)
                    if destination_digest == digest:
                        unchanged += 1
                    else:
                        history = self.library_root / "history" / run_id / source_id / relative
                        _atomic_copy(destination, history)
                        _atomic_copy(source, destination)
                        copied += 1
                else:
                    _atomic_copy(source, destination)
                    copied += 1
                if _sha256(destination) != digest:
                    raise IOError(f"提取后哈希不一致: {source}")
                verified += 1
                relative_posix = relative.as_posix()
                trust_status, priority = self._trust(source_id, relative_posix, review_statuses)
                stat = source.stat()
                records.append(
                    {
                        "source_id": source_id,
                        "source_path": str(source),
                        "relative_path": relative_posix,
                        "library_path": str(destination),
                        "logical_key": source.name.casefold(),
                        "sha256": digest,
                        "bytes": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "trust_status": trust_status,
                        "priority": priority,
                    }
                )
        conflicts, duplicate_groups = self._resolve(records)
        catalog_path = self.catalog_root / "artifacts.json"
        summary = {
            "total_source_files": len(records),
            "copied_files": copied,
            "unchanged_files": unchanged,
            "verified_files": verified,
            "conflicts": len(conflicts),
            "duplicate_groups": duplicate_groups,
            "skipped_links": skipped_links,
        }
        _write_json(
            catalog_path,
            {
                "schema_version": 1,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "precedence": "普通交班记录 > 旧 AI_Handoff；DeepSeek 按人工审核状态单独定级",
                "sources": {key: str(Path(value).resolve()) for key, value in sources.items()},
                "summary": summary,
                "artifacts": records,
                "conflicts": conflicts,
            },
        )
        review_path = self.catalog_root / "deepseek_review.json"
        _write_json(
            self.platform_root / "migration" / "full_extraction_latest.json",
            {
                "schema_version": 1,
                "status": "completed",
                "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source_policy": "copy_only_no_delete",
                "precedence": "普通交班记录 > 旧 AI_Handoff；DeepSeek 按审核状态单独定级",
                "sources": {key: str(Path(value).resolve()) for key, value in sources.items()},
                "summary": summary,
                "catalog": str(catalog_path),
                "catalog_sha256": _sha256(catalog_path),
                "deepseek_review": str(review_path) if review_path.exists() else None,
                "deepseek_review_sha256": _sha256(review_path) if review_path.exists() else None,
            },
        )
        return ExtractionReport(
            total_source_files=len(records),
            copied_files=copied,
            unchanged_files=unchanged,
            verified_files=verified,
            conflicts=len(conflicts),
            duplicate_groups=duplicate_groups,
            skipped_links=skipped_links,
            catalog_path=str(catalog_path),
        )

    def _load_deepseek_review(self) -> dict[str, str]:
        path = self.catalog_root / "deepseek_review.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(item["relative_path"]): str(item["status"]) for item in data.get("items", [])}

    @staticmethod
    def _trust(source_id: str, relative: str, reviews: Mapping[str, str]) -> tuple[str, int]:
        if source_id == "codex_handover":
            marker = "deepseek专用/"
            if relative.startswith(marker):
                status = reviews.get(relative[len(marker):], "candidate")
                return status, {"verified": 110, "candidate": 40, "reference": 20, "deprecated": 0}[status]
            return "authoritative", 100
        if source_id == "legacy_ai_handoff":
            return "legacy", 50
        return "unranked", 10

    @staticmethod
    def _resolve(records: list[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
        grouped: dict[str, list[dict[str, object]]] = {}
        for record in records:
            grouped.setdefault(str(record["logical_key"]), []).append(record)
        conflicts: list[dict[str, object]] = []
        duplicate_groups = 0
        for logical_key, variants in sorted(grouped.items()):
            hashes = {str(item["sha256"]) for item in variants}
            if len(variants) > 1 and len(hashes) == 1:
                duplicate_groups += 1
            if len(hashes) <= 1:
                continue
            selected = sorted(
                variants,
                key=lambda item: (
                    -int(item["priority"]),
                    -int(item["mtime_ns"]),
                    str(item["relative_path"]).casefold(),
                ),
            )[0]
            conflicts.append(
                {
                    "logical_key": logical_key,
                    "selected_source": selected["source_id"],
                    "selected_relative_path": selected["relative_path"],
                    "selected_sha256": selected["sha256"],
                    "resolution": "按审核状态与来源优先级选择；全部变体均保留",
                    "variants": [
                        {
                            "source_id": item["source_id"],
                            "relative_path": item["relative_path"],
                            "sha256": item["sha256"],
                            "trust_status": item["trust_status"],
                            "priority": item["priority"],
                        }
                        for item in variants
                    ],
                }
            )
        return conflicts, duplicate_groups
