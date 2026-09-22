"""命格 XLSX 的只读数据模型与严格解析器。"""

from __future__ import annotations

import json
import msvcrt
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Sequence


QUALITIES = ("绿", "橙", "红", "彩")
QUALITY_ORDER = {quality: index for index, quality in enumerate(QUALITIES)}
ENABLED_RULE_SEMANTICS = (
    ("彩", "累计阈值"),
    ("彩", "周期彩色判定"),
    ("红", "累计阈值"),
    ("红", "概率"),
    ("橙", "概率"),
    ("绿", "绿色兜底"),
)
SHEETS: dict[str, tuple[str, ...]] = {
    "系统设置": ("配置项", "配置值", "说明"),
    "槽位开放": ("槽位号", "显示名称", "启用", "条件类型", "条件键", "条件值", "永久开放"),
    "词条定义": ("词条ID", "槽位号", "词条名称", "启用", "显示顺序"),
    "品质属性": ("词条ID", "品质", "属性键", "数值", "单位", "显示顺序", "悬浮文案"),
    "品质规则": ("规则ID", "优先级", "目标品质", "触发类型", "累计阈值", "周期", "概率分母", "命中后重置项", "启用"),
    "洗练消耗": ("模式", "消耗类型", "准确名称", "数量", "启用"),
    "品质样式": ("品质", "字体", "字号", "加粗", "画布高度", "左右留白", "描边颜色", "描边宽度", "主色或渐变色"),
}
SETTING_KEYS = ("NPC", "脚本目录", "地图", "坐标", "外观", "装备", "装备位", "槽位数", "红保底", "彩保底", "十连进度", "数据版本")
DEFAULT_MINGGE_TEMPLATE_DIR = Path(
    r"E:\XuanYuanDevPlatform\wzl编辑\workspace\mingge-template"
)
MINGGE_PROVIDER_TIMEOUT_SECONDS = 120
MINGGE_PROVIDER_NAME = "xuanyuan-wzl"
MINGGE_PROVIDER_PROTOCOL = "wzl-provider/1"
LEGACY_CUSTOM_TEXT_HASH = "11501580D6AF2E0150E0B88B9C26527C37551488775CA5FFBA73D320528289FD"
LEGACY_DIALOG_WZL_HASH = "393D736C2CD0709D17131B295F962AC87C0BCD1C8BCA986C27A39D1AE47FC294"
LEGACY_DIALOG_WZX_HASH = "A8DED087C587F9DEE50EF70950DD6D21B4008FFE624581CD30263729A0CBF9F5"
LEGACY_LABEL_WZL_HASH = "9BDDFFEA8AE6EEBFC5A392FEBAA0FD93DA4B88924E83AC445744C79D54EE66D4"
LEGACY_LABEL_WZX_HASH = "B07B5F48068D97F5A647EC2DE3C420819C06F248DEC0497BCB6110ED49BB815C"
LEGACY_SCRIPT_HASHES = {
    "Mir200/Envir/Market_Def/玄渊命格/龙魂觉醒-3.txt": "1EAB9650A748525E2E7D85E289898D867C23E15DC8D0B32862055519B49B6ABE",
    "Mir200/Envir/QuestDiary/玄渊命格/彩色显示.txt": "9B7CD82E28EBB6B9D6DF4E56A3B8CFE5F91EC099DD3217AFA8CE98216D8FDE72",
    "Mir200/Envir/QuestDiary/玄渊命格/命格测试配置.txt": "59F94FDB3E3A3A661445624AE5A6924F85073C2B00C99DABD7640A509DF2D1EF",
}
LEGACY_MERCHANT_LINE = "玄渊命格\\龙魂觉醒 3 320 339 龙魂觉醒 0 220 0"
MINGGE_TARGET_ITEM_NAME = "鞭尸灵玉"
MINGGE_TARGET_ITEM_STD_MODE = 90
MINGGE_TARGET_EQUIP_SLOT = 17


class MingGeError(ValueError):
    """命格表格不符合平台数据契约。"""


class MingGeResourceError(MingGeError):
    """命格客户端资源无法通过正式 Provider 安全构建。"""


@dataclass(frozen=True)
class MingGeSettings:
    npc_name: str; script_dir: str; map_id: str; npc_x: int; npc_y: int; npc_appearance: int; target_item_name: str; equip_slot: int; slot_count: int; red_pity: int; color_pity: int; batch_progress: int; data_version: int


@dataclass(frozen=True)
class MingGeAffix:
    affix_id: str; slot: int; name: str; enabled: bool; order: int


@dataclass(frozen=True)
class MingGeQualityAttribute:
    affix_id: str; quality: str; property_key: str; value: int; unit: str; order: int; hover_text: str


@dataclass(frozen=True)
class MingGeSlotRule:
    slot: int; display_name: str; enabled: bool; condition_type: str; condition_key: str; condition_value: str; permanent: bool


@dataclass(frozen=True)
class MingGeQualityRule:
    rule_id: str; priority: int; quality: str; trigger_type: str; threshold: int; cycle: int; denominator: int; reset_fields: tuple[str, ...]; enabled: bool


@dataclass(frozen=True)
class MingGeCost:
    mode: str; cost_type: str; exact_name: str; amount: int; enabled: bool


@dataclass(frozen=True)
class MingGeQualityStyle:
    quality: str; font_name: str; font_size: int; bold: bool; canvas_height: int; horizontal_padding: int; outline_color: str; outline_width: int; colors: tuple[str, ...]


@dataclass(frozen=True)
class QualityProgress:
    red: int; color: int; tenth: int


@dataclass(frozen=True)
class QualityResult:
    quality: str; progress: QualityProgress; matched_rule_id: str


@dataclass(frozen=True)
class MingGeWorkbook:
    settings: MingGeSettings; slots: tuple[MingGeSlotRule, ...]; affixes: tuple[MingGeAffix, ...]; attributes: tuple[MingGeQualityAttribute, ...]; quality_rules: tuple[MingGeQualityRule, ...]; costs: tuple[MingGeCost, ...]; styles: tuple[MingGeQualityStyle, ...]


@dataclass(frozen=True)
class PropertyBinding:
    key: str
    binding: int
    display: str
    unit: str
    minimum: int
    maximum: int


@dataclass(frozen=True)
class MingGeLabelFrame:
    slot: int
    quality: str
    frame_id: int
    hover_text: str


@dataclass(frozen=True)
class CompiledMingGePayload:
    files: dict[PurePosixPath, bytes]
    npc_text: str
    custom_property_lines: tuple[str, ...]


@dataclass(frozen=True)
class MingGeLibrary:
    wzl_path: Path
    wzx_path: Path
    wzl_hash: str
    wzx_hash: str
    config_hash: str
    mapping: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class MingGeFileChange:
    path: Path
    before_hash: str | None
    after_hash: str
    after_bytes: bytes
    scope: str


@dataclass(frozen=True)
class MingGePlan:
    plan_id: str
    server: Path
    client: Path
    workbook: Path
    workbook_hash: str
    resource_index: int
    custom_text_base: int
    resource_name: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    changes: tuple[MingGeFileChange, ...]


@dataclass(frozen=True)
class MingGeReceipt:
    transaction_id: str
    receipt_path: Path
    status: str
    affected_paths: tuple[Path, ...]


def _resource_sha256(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise MingGeResourceError(f"资源无法读取: {path}") from exc


@contextmanager
def _mingge_output_lock(lock_path: Path):
    """用 Windows 字节锁串行化同一内容寻址 stem 的跨进程发布。"""
    lock_path = Path(lock_path)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b", buffering=0) as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError as exc:
        raise MingGeResourceError(f"命格资源输出锁失败: {lock_path}") from exc


def _unlink_published_hash(path: Path, expected_hash: str) -> None:
    """只清理仍保持本轮发布字节的文件，避免误删并发替换结果。"""
    try:
        if path.is_file() and sha256(path.read_bytes()).hexdigest() == expected_hash:
            path.unlink()
    except OSError:
        return


def _png_size(path: Path) -> tuple[int, int]:
    try:
        header = path.read_bytes()[:24]
    except OSError as exc:
        raise MingGeResourceError(f"PNG无法读取: {path}") from exc
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise MingGeResourceError(f"命格帧不是有效PNG: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise MingGeResourceError(f"命格帧尺寸非法: {path}")
    return width, height


def _provider_process(
    provider_path: Path,
    arguments: Sequence[str],
    request: dict[str, object] | None = None,
) -> dict[str, object]:
    command = (str(provider_path), *arguments)
    try:
        result = subprocess.run(
            command,
            input=(
                json.dumps(request, ensure_ascii=False, separators=(",", ":"))
                if request is not None
                else None
            ),
            capture_output=True,
            check=False,
            encoding="utf-8",
            timeout=MINGGE_PROVIDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise MingGeResourceError("WZL Provider调用超时") from exc
    except UnicodeDecodeError as exc:
        raise MingGeResourceError("WZL Provider返回非法UTF-8") from exc
    except OSError as exc:
        raise MingGeResourceError(f"WZL Provider无法启动: {provider_path}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit={result.returncode}"
        raise MingGeResourceError(f"WZL Provider失败: {detail}")
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MingGeResourceError("WZL Provider返回非JSON") from exc
    if not isinstance(payload, dict):
        raise MingGeResourceError("WZL Provider响应必须是JSON对象")
    return payload


def _provider_metadata(provider_path: Path) -> dict[str, object]:
    payload = _provider_process(provider_path, ("meta", "version"))
    if (
        payload.get("schemaVersion") != 1
        or payload.get("provider") != MINGGE_PROVIDER_NAME
        or payload.get("protocol") != MINGGE_PROVIDER_PROTOCOL
        or not isinstance(payload.get("providerVersion"), str)
        or not payload["providerVersion"]
    ):
        raise MingGeResourceError("WZL Provider版本协议不匹配")
    return payload


def _provider_data(
    payload: dict[str, object],
    *,
    metadata: dict[str, object],
    request_id: str,
    command: str,
) -> dict[str, object]:
    if (
        payload.get("schemaVersion") != 1
        or payload.get("provider") != metadata["provider"]
        or payload.get("protocol") != metadata["protocol"]
        or payload.get("providerVersion") != metadata["providerVersion"]
        or payload.get("requestId") != request_id
        or payload.get("command") != command
        or payload.get("ok") is not True
        or not isinstance(payload.get("data"), dict)
    ):
        raise MingGeResourceError(f"WZL Provider {command}响应协议不匹配")
    return payload["data"]  # type: ignore[return-value]


def _inspect_mingge_library(
    provider_path: Path,
    wzl_path: Path,
    wzx_path: Path,
    frame_paths: Sequence[Path],
    metadata: dict[str, object],
    frame_hashes: Sequence[str],
) -> None:
    request_id = f"mingge-inspect-{uuid.uuid4().hex}"
    request = {
        "schemaVersion": 1,
        "requestId": request_id,
        "command": "inspect",
        "arguments": {
            "wzl": str(wzl_path),
            "wzx": str(wzx_path),
            "selection": {"ids": list(range(len(frame_paths)))},
        },
        "policy": {"allowedWriteRoots": []},
    }
    data = _provider_data(
        _provider_process(provider_path, ("run", "--request", "-"), request),
        metadata=metadata,
        request_id=request_id,
        command="inspect",
    )
    entries = data.get("entries")
    if data.get("count") != len(frame_paths) or not isinstance(entries, list) or len(entries) != len(frame_paths):
        raise MingGeResourceError("WZL Provider inspect帧数不匹配")
    for target_id, (frame_path, expected_hash, entry) in enumerate(
        zip(frame_paths, frame_hashes, entries, strict=True)
    ):
        if not isinstance(entry, dict):
            raise MingGeResourceError("WZL Provider inspect映射格式错误")
        width, height = _png_size(frame_path)
        if (
            entry.get("image_id") != target_id
            or entry.get("frame_type") != 6
            or entry.get("width") != width
            or entry.get("height") != height
            or entry.get("x") != 0
            or entry.get("y") != 0
            or str(entry.get("sha256", "")).casefold() != expected_hash.casefold()
        ):
            raise MingGeResourceError(f"WZL Provider inspect第{target_id}帧不匹配")


def build_mingge_library(
    frames,
    output_dir: Path,
    provider_path: Path,
    *,
    workbook_path: Path,
    template_dir: Path = DEFAULT_MINGGE_TEMPLATE_DIR,
) -> MingGeLibrary:
    """通过正式 Provider 构建未部署、内容寻址的命格 WZL/WZX。"""
    ordered_frames = tuple(sorted(tuple(frames), key=lambda frame: frame.frame_id))
    if not ordered_frames or tuple(frame.frame_id for frame in ordered_frames) != tuple(range(len(ordered_frames))):
        raise MingGeResourceError("命格帧frame_id必须从0开始连续")
    output_dir = Path(output_dir).resolve()
    provider_path = Path(provider_path).resolve()
    workbook_path = Path(workbook_path).resolve()
    template_dir = Path(template_dir).resolve()
    template_wzl = template_dir / "Template.wzl"
    template_wzx = template_dir / "Template.wzx"
    if not provider_path.is_file():
        raise MingGeResourceError(f"WZL Provider不存在: {provider_path}")
    if not workbook_path.is_file():
        raise MingGeResourceError(f"命格配置表不存在: {workbook_path}")
    if not template_wzl.is_file() or not template_wzx.is_file():
        raise MingGeResourceError(f"命格模板必须成对存在: {template_dir}")

    metadata = _provider_metadata(provider_path)
    workbook_hash = _resource_sha256(workbook_path)
    original_template_hashes = (
        _resource_sha256(template_wzl),
        _resource_sha256(template_wzx),
    )
    original_frame_paths: list[Path] = []
    original_frame_hashes: list[str] = []
    for frame in ordered_frames:
        png_path = Path(frame.png_path).resolve()
        actual_hash = _resource_sha256(png_path)
        if str(frame.sha256).casefold() != actual_hash.casefold():
            raise MingGeResourceError(f"命格帧SHA-256不匹配: {png_path}")
        _png_size(png_path)
        original_frame_paths.append(png_path)
        original_frame_hashes.append(actual_hash)

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = output_dir / f".mingge-snapshot-{uuid.uuid4().hex}"
    staged_paths: tuple[Path, Path] | tuple[()] = ()
    try:
        snapshot_template_dir = snapshot_dir / "template"
        snapshot_frame_dir = snapshot_dir / "frames"
        snapshot_template_dir.mkdir(parents=True)
        snapshot_frame_dir.mkdir()
        snapshot_wzl = snapshot_template_dir / "Template.wzl"
        snapshot_wzx = snapshot_template_dir / "Template.wzx"
        shutil.copyfile(template_wzl, snapshot_wzl)
        shutil.copyfile(template_wzx, snapshot_wzx)
        snapshot_frame_paths = tuple(
            snapshot_frame_dir / f"{frame.frame_id:03}.png" for frame in ordered_frames
        )
        for source, target in zip(original_frame_paths, snapshot_frame_paths, strict=True):
            shutil.copyfile(source, target)

        snapshot_template_hashes = (
            _resource_sha256(snapshot_wzl),
            _resource_sha256(snapshot_wzx),
        )
        snapshot_frame_hashes = tuple(
            _resource_sha256(path) for path in snapshot_frame_paths
        )
        if snapshot_template_hashes != original_template_hashes:
            raise MingGeResourceError("命格模板snapshot与原始输入不一致")
        if snapshot_frame_hashes != tuple(original_frame_hashes):
            raise MingGeResourceError("命格PNG snapshot与原始输入不一致")

        frame_config = [
            {
                "frame_id": frame.frame_id,
                "line_no": frame.line_no,
                "label": frame.label,
                "hover_text": frame.hover_text,
                "png_sha256": snapshot_hash,
            }
            for frame, snapshot_hash in zip(
                ordered_frames, snapshot_frame_hashes, strict=True
            )
        ]
        config = {
            "workbook_sha256": workbook_hash,
            "frames": frame_config,
            "template": {
                "wzl_sha256": snapshot_template_hashes[0],
                "wzx_sha256": snapshot_template_hashes[1],
            },
            "provider": {
                "provider": metadata["provider"],
                "protocol": metadata["protocol"],
                "providerVersion": metadata["providerVersion"],
            },
        }
        config_hash = sha256(
            json.dumps(
                config,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        stem = f"XY_MingGeLabels_{config_hash[:8]}"
        final_wzl = output_dir / f"{stem}.wzl"
        final_wzx = output_dir / f"{stem}.wzx"

        token = uuid.uuid4().hex
        staged_wzl = output_dir / f".{stem}.{token}.staged.wzl"
        staged_wzx = output_dir / f".{stem}.{token}.staged.wzx"
        staged_paths = (staged_wzl, staged_wzx)
        request_id = f"mingge-build-{uuid.uuid4().hex}"
        request = {
            "schemaVersion": 1,
            "requestId": request_id,
            "command": "build-image-library",
            "arguments": {
                "templateWzl": str(snapshot_wzl),
                "templateWzx": str(snapshot_wzx),
                "images": [
                    {
                        "path": str(path),
                        "sourceId": frame.frame_id,
                        "x": 0,
                        "y": 0,
                    }
                    for frame, path in zip(
                        ordered_frames, snapshot_frame_paths, strict=True
                    )
                ],
                "outputWzl": str(staged_wzl),
                "outputWzx": str(staged_wzx),
            },
            "policy": {"allowedWriteRoots": [str(output_dir)]},
        }
        data = _provider_data(
            _provider_process(provider_path, ("run", "--request", "-"), request),
            metadata=metadata,
            request_id=request_id,
            command="build-image-library",
        )
        mapping = data.get("mapping")
        if data.get("count") != len(ordered_frames) or data.get("readback_ok") is not True:
            raise MingGeResourceError("WZL Provider构建帧数或readback_ok不匹配")
        if not isinstance(mapping, list) or len(mapping) != len(ordered_frames):
            raise MingGeResourceError("WZL Provider构建mapping不匹配")
        for target_id, (frame, snapshot_path, expected_hash, item) in enumerate(
            zip(
                ordered_frames,
                snapshot_frame_paths,
                snapshot_frame_hashes,
                mapping,
                strict=True,
            )
        ):
            width, height = _png_size(snapshot_path)
            if not isinstance(item, dict) or (
                item.get("source_id") != frame.frame_id
                or item.get("target_id") != target_id
                or str(item.get("source_path", "")).casefold()
                != str(snapshot_path).casefold()
                or item.get("width") != width
                or item.get("height") != height
                or item.get("x") != 0
                or item.get("y") != 0
                or str(item.get("source_sha256", "")).casefold()
                != expected_hash.casefold()
                or not isinstance(item.get("frame_sha256"), str)
                or not item["frame_sha256"]
            ):
                raise MingGeResourceError(f"WZL Provider第{target_id}帧mapping不匹配")
        if not staged_wzl.is_file() or not staged_wzx.is_file():
            raise MingGeResourceError("WZL Provider未生成完整资源对")
        staged_hashes = (_resource_sha256(staged_wzl), _resource_sha256(staged_wzx))
        output_pair = data.get("output_pair")
        if not isinstance(output_pair, dict) or (
            str(output_pair.get("wzl", "")).casefold() != str(staged_wzl).casefold()
            or str(output_pair.get("wzx", "")).casefold() != str(staged_wzx).casefold()
            or str(output_pair.get("wzlSha256", "")).casefold()
            != staged_hashes[0].casefold()
            or str(output_pair.get("wzxSha256", "")).casefold()
            != staged_hashes[1].casefold()
        ):
            raise MingGeResourceError("WZL Provider输出pair哈希不匹配")
        if str(data.get("output_wzl", "")).casefold() != str(staged_wzl).casefold() or str(
            data.get("output_wzx", "")
        ).casefold() != str(staged_wzx).casefold():
            raise MingGeResourceError("WZL Provider输出pair路径不匹配")
        provider_frame_hashes = tuple(str(item["frame_sha256"]) for item in mapping)
        _inspect_mingge_library(
            provider_path,
            staged_wzl,
            staged_wzx,
            snapshot_frame_paths,
            metadata,
            provider_frame_hashes,
        )
        if snapshot_template_hashes != (
            _resource_sha256(snapshot_wzl),
            _resource_sha256(snapshot_wzx),
        ):
            raise MingGeResourceError("命格模板snapshot在构建期间发生变化")
        if snapshot_frame_hashes != tuple(
            _resource_sha256(path) for path in snapshot_frame_paths
        ):
            raise MingGeResourceError("命格PNG snapshot在构建期间发生变化")
        if original_template_hashes != (
            _resource_sha256(template_wzl),
            _resource_sha256(template_wzx),
        ):
            raise MingGeResourceError("命格模板在构建期间发生变化")
        for path, expected_hash in zip(
            original_frame_paths, original_frame_hashes, strict=True
        ):
            if _resource_sha256(path) != expected_hash:
                raise MingGeResourceError(f"命格PNG在构建期间发生变化: {path}")

        lock_path = output_dir / f".{stem}.lock"
        with _mingge_output_lock(lock_path):
            published: list[tuple[Path, str]] = []
            try:
                if final_wzl.exists() and final_wzx.exists():
                    if (
                        _resource_sha256(final_wzl) != staged_hashes[0]
                        or _resource_sha256(final_wzx) != staged_hashes[1]
                    ):
                        raise MingGeResourceError(
                            "已存在的内容寻址资源与验证结果不匹配，禁止覆盖"
                        )
                    _inspect_mingge_library(
                        provider_path,
                        final_wzl,
                        final_wzx,
                        snapshot_frame_paths,
                        metadata,
                        provider_frame_hashes,
                    )
                else:
                    if final_wzl.exists() or final_wzx.exists():
                        raise MingGeResourceError("发布前检测到单边资源，禁止覆盖")
                    os.replace(staged_wzl, final_wzl)
                    published.append((final_wzl, staged_hashes[0]))
                    os.replace(staged_wzx, final_wzx)
                    published.append((final_wzx, staged_hashes[1]))
                    _inspect_mingge_library(
                        provider_path,
                        final_wzl,
                        final_wzx,
                        snapshot_frame_paths,
                        metadata,
                        provider_frame_hashes,
                    )
            except Exception:
                for path, expected_hash in published:
                    _unlink_published_hash(path, expected_hash)
                raise
        normalized_mapping = []
        for item, original_path in zip(mapping, original_frame_paths, strict=True):
            normalized = dict(item)
            normalized["source_path"] = str(original_path)
            normalized_mapping.append(normalized)
        return MingGeLibrary(
            final_wzl,
            final_wzx,
            staged_hashes[0],
            staged_hashes[1],
            config_hash,
            tuple(normalized_mapping),
        )
    except Exception as exc:
        if isinstance(exc, MingGeResourceError):
            raise
        raise MingGeResourceError(f"命格资源对发布失败: {exc}") from exc
    finally:
        for path in staged_paths:
            if path.exists():
                path.unlink()
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)


def _text(value: object, label: str, row: int) -> str:
    result = "" if value is None else str(value).strip()
    if not result: raise MingGeError(f"第{row}行{label}不能为空")
    return result


def _integer(value: object, label: str, row: int, minimum: int = 0) -> int:
    if isinstance(value, bool): raise MingGeError(f"第{row}行{label}必须是大于等于{minimum}的整数")
    if isinstance(value, float) and value.is_integer(): value = int(value)
    if not isinstance(value, int) or value < minimum: raise MingGeError(f"第{row}行{label}必须是大于等于{minimum}的整数")
    return value


def _positive(value: object, label: str, row: int) -> int:
    if isinstance(value, bool): raise MingGeError(f"第{row}行{label}必须是正整数")
    if isinstance(value, float) and value.is_integer(): value = int(value)
    if not isinstance(value, int) or value <= 0: raise MingGeError(f"第{row}行{label}必须是正整数")
    return value


def _bool(value: object, label: str, row: int) -> bool:
    value = _text(value, label, row)
    if value not in {"是", "否"}: raise MingGeError(f"第{row}行{label}只允许填“是”或“否”")
    return value == "是"


def _table_rows(sheet, headers: Sequence[str]) -> Iterable[tuple[int, tuple[object, ...]]]:
    actual = tuple(cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1)))
    if actual != tuple(headers): raise MingGeError(f"{sheet.title}表头不匹配")
    for number, values in enumerate(sheet.iter_rows(min_row=2, max_col=len(headers), values_only=True), 2):
        if any(value is not None and str(value).strip() for value in values): yield number, tuple(values)


def _unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value.casefold() in seen: raise MingGeError(f"{label}重复: {value}")
        seen.add(value.casefold())


def _settings(rows: Iterable[tuple[int, tuple[object, ...]]]) -> MingGeSettings:
    entries: dict[str, tuple[int, object]] = {}
    for row, values in rows:
        key = _text(values[0], "配置项", row)
        if key in entries: raise MingGeError(f"配置项重复: {key}")
        entries[key] = (row, values[1])
    missing = [key for key in SETTING_KEYS if key not in entries]
    if missing: raise MingGeError(f"系统设置缺少配置项: {', '.join(missing)}")
    if any(key not in SETTING_KEYS for key in entries): raise MingGeError("系统设置包含未知配置项")
    def text(key: str) -> str: return _text(entries[key][1], key, entries[key][0])
    def positive(key: str) -> int: return _positive(entries[key][1], key, entries[key][0])
    coordinates = text("坐标").split("/")
    if len(coordinates) != 2: raise MingGeError("坐标必须为X/Y")
    try: x, y = (int(value.strip()) for value in coordinates)
    except ValueError as exc: raise MingGeError("坐标必须为X/Y整数") from exc
    if x < 0 or y < 0: raise MingGeError("坐标必须为非负整数")
    result = MingGeSettings(text("NPC"), text("脚本目录"), text("地图"), x, y, positive("外观"), text("装备"), positive("装备位"), positive("槽位数"), positive("红保底"), positive("彩保底"), positive("十连进度"), positive("数据版本"))
    if result.slot_count != 8: raise MingGeError("槽位数必须为8")
    return result


def _slots(rows: Iterable[tuple[int, tuple[object, ...]]]) -> tuple[MingGeSlotRule, ...]:
    result = []
    for row, values in rows:
        slot = _positive(values[0], "槽位号", row)
        if not 1 <= slot <= 8: raise MingGeError(f"第{row}行槽位号必须是1～8的整数")
        result.append(MingGeSlotRule(slot, _text(values[1], "显示名称", row), _bool(values[2], "启用", row), _text(values[3], "条件类型", row), _text(values[4], "条件键", row), _text(values[5], "条件值", row), _bool(values[6], "永久开放", row)))
    if len(result) != 8 or {item.slot for item in result} != set(range(1, 9)): raise MingGeError("槽位开放必须完整定义1～8槽位")
    return tuple(sorted(result, key=lambda item: item.slot))


def _affixes(rows: Iterable[tuple[int, tuple[object, ...]]]) -> tuple[MingGeAffix, ...]:
    result = []
    for row, values in rows:
        slot = _positive(values[1], "槽位号", row)
        if not 1 <= slot <= 8: raise MingGeError(f"第{row}行槽位号必须是1～8的整数")
        result.append(MingGeAffix(_text(values[0], "词条ID", row), slot, _text(values[2], "词条名称", row), _bool(values[3], "启用", row), _positive(values[4], "显示顺序", row)))
    _unique((item.affix_id for item in result), "词条ID")
    if len(result) != 8 or {item.slot for item in result} != set(range(1, 9)): raise MingGeError("词条定义必须完整覆盖1～8槽位")
    return tuple(sorted(result, key=lambda item: item.order))


def _attributes(rows: Iterable[tuple[int, tuple[object, ...]]], affixes: Sequence[MingGeAffix]) -> tuple[MingGeQualityAttribute, ...]:
    coverage = {item.affix_id.casefold(): set() for item in affixes}; result = []
    for row, values in rows:
        affix_id = _text(values[0], "词条ID", row); key = affix_id.casefold(); quality = _text(values[1], "品质", row)
        if key not in coverage: raise MingGeError(f"第{row}行品质属性引用未知词条ID: {affix_id}")
        if quality not in QUALITIES: raise MingGeError(f"第{row}行品质必须为: {'、'.join(QUALITIES)}")
        if quality in coverage[key]: raise MingGeError(f"第{row}行词条品质重复: {affix_id}/{quality}")
        coverage[key].add(quality)
        result.append(MingGeQualityAttribute(affix_id, quality, _text(values[2], "属性键", row), _integer(values[3], "数值", row), "" if values[4] is None else str(values[4]).strip(), _positive(values[5], "显示顺序", row), _text(values[6], "悬浮文案", row)))
    if any(values != set(QUALITIES) for values in coverage.values()): raise MingGeError("每个词条的品质必须完整覆盖：绿、橙、红、彩")
    return tuple(sorted(result, key=lambda item: (item.affix_id, item.order)))


def _rules(rows: Iterable[tuple[int, tuple[object, ...]]]) -> tuple[MingGeQualityRule, ...]:
    result = []; green_fallbacks = 0
    for row, values in rows:
        quality = _text(values[2], "目标品质", row); trigger = _text(values[3], "触发类型", row)
        if quality not in QUALITIES: raise MingGeError(f"第{row}行目标品质必须为: {'、'.join(QUALITIES)}")
        threshold = 0 if values[4] is None or not str(values[4]).strip() else _integer(values[4], "累计阈值", row)
        cycle = 0 if values[5] is None or not str(values[5]).strip() else _integer(values[5], "周期", row)
        denominator = 0 if values[6] is None or not str(values[6]).strip() else _integer(values[6], "概率分母", row)
        if trigger == "累计阈值":
            if threshold <= 0:
                raise MingGeError(f"第{row}行累计阈值规则的累计阈值必须是正整数")
        elif trigger == "周期彩色判定":
            if quality != "彩" or cycle <= 0 or denominator <= 0:
                raise MingGeError(f"第{row}行周期彩色判定规则的周期和概率分母必须是正整数")
        elif trigger == "概率":
            if denominator <= 0:
                raise MingGeError(f"第{row}行概率规则的概率分母必须是正整数")
        elif trigger == "绿色兜底":
            if quality != "绿":
                raise MingGeError(f"第{row}行绿色兜底规则的目标品质必须为绿")
        else:
            raise MingGeError(f"第{row}行触发类型未知: {trigger}")
        reset_fields = tuple(part.strip() for part in str(values[7] or "").replace("、", ",").replace("，", ",").split(",") if part.strip())
        rule = MingGeQualityRule(_text(values[0], "规则ID", row), _positive(values[1], "优先级", row), quality, trigger, threshold, cycle, denominator, reset_fields, _bool(values[8], "启用", row))
        green_fallbacks += int(rule.enabled and rule.quality == "绿" and rule.trigger_type == "绿色兜底")
        result.append(rule)
    _unique((item.rule_id for item in result), "规则ID")
    if green_fallbacks != 1: raise MingGeError("绿色兜底规则必须恰好有一条")
    enabled = tuple(sorted((item for item in result if item.enabled), key=lambda item: item.priority))
    if len(enabled) != len(ENABLED_RULE_SEMANTICS):
        raise MingGeError("启用品质规则必须恰好包含六条")
    if tuple(item.priority for item in enabled) != tuple(range(1, 7)):
        raise MingGeError("启用品质规则优先级必须唯一且连续为1～6")
    if tuple((item.quality, item.trigger_type) for item in enabled) != ENABLED_RULE_SEMANTICS:
        raise MingGeError("启用品质规则优先级语义必须依次为彩累计、周期彩、红累计、自然红、自然橙、绿色兜底")
    return tuple(sorted(result, key=lambda item: item.priority))


def _costs(rows: Iterable[tuple[int, tuple[object, ...]]]) -> tuple[MingGeCost, ...]:
    result = tuple(MingGeCost(_text(v[0], "模式", row), _text(v[1], "消耗类型", row), _text(v[2], "准确名称", row), _positive(v[3], "消耗数量", row), _bool(v[4], "启用", row)) for row, v in rows)
    _unique((item.mode for item in result), "洗练模式")
    return result


def _styles(rows: Iterable[tuple[int, tuple[object, ...]]]) -> tuple[MingGeQualityStyle, ...]:
    result = []
    for row, values in rows:
        quality = _text(values[0], "品质", row)
        if quality not in QUALITIES: raise MingGeError(f"第{row}行品质必须为: {'、'.join(QUALITIES)}")
        colors = tuple(part.strip() for part in _text(values[8], "主色或渐变色", row).split("→") if part.strip())
        result.append(MingGeQualityStyle(quality, _text(values[1], "字体", row), _positive(values[2], "字号", row), _bool(values[3], "加粗", row), _positive(values[4], "画布高度", row), _integer(values[5], "左右留白", row), _text(values[6], "描边颜色", row), _integer(values[7], "描边宽度", row), colors))
    if len(result) != len(QUALITIES) or {item.quality for item in result} != set(QUALITIES): raise MingGeError("品质样式必须完整覆盖：绿、橙、红、彩")
    return tuple(sorted(result, key=lambda item: QUALITIES.index(item.quality)))


def read_mingge_workbook(path: Path) -> MingGeWorkbook:
    """严格读取七张命格数据表，不从服务端或脚本推测默认值。"""
    try:
        from openpyxl import load_workbook
    except ImportError as exc: raise MingGeError("当前平台缺少XLSX读取组件 openpyxl") from exc
    path = Path(path)
    if not path.is_file(): raise MingGeError(f"命格配置表不存在: {path}")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        for name in SHEETS:
            if name not in workbook.sheetnames: raise MingGeError(f"缺少工作表：{name}")
        if len(workbook.sheetnames) != len(SHEETS): raise MingGeError("命格配置表必须恰好包含七张工作表")
        data = {name: tuple(_table_rows(workbook[name], headers)) for name, headers in SHEETS.items()}
    finally: workbook.close()
    settings = _settings(data["系统设置"]); slots = _slots(data["槽位开放"]); affixes = _affixes(data["词条定义"])
    return MingGeWorkbook(settings, slots, affixes, _attributes(data["品质属性"], affixes), _rules(data["品质规则"]), _costs(data["洗练消耗"]), _styles(data["品质样式"]))


def _apply_resets(progress: QualityProgress, fields: Sequence[str]) -> QualityProgress:
    values = {"red": progress.red, "color": progress.color, "tenth": progress.tenth}
    names = {
        "红色进度": "red", "彩色进度": "color", "十连进度": "tenth",
        "red": "red", "color": "color", "tenth": "tenth",
    }
    for field in fields:
        target = names.get(field)
        if target is not None:
            values[target] = 0
    return QualityProgress(**values)


def _result(quality: str, progress: QualityProgress, rule: MingGeQualityRule) -> QualityResult:
    return QualityResult(quality, _apply_resets(progress, rule.reset_fields), rule.rule_id)


def resolve_quality(
    progress: QualityProgress,
    attempts: int,
    rules: tuple[MingGeQualityRule, ...],
    hit: Callable[[int], bool],
) -> QualityResult:
    """按彩、红、橙、绿的固定优先级计算一次或批量洗练的品质。"""
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts <= 0:
        raise MingGeError("洗练次数必须是正整数")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (progress.red, progress.color, progress.tenth)):
        raise MingGeError("品质进度必须是非负整数")
    next_progress = QualityProgress(progress.red + attempts, progress.color + attempts, progress.tenth + attempts)
    enabled = tuple(sorted((rule for rule in rules if rule.enabled), key=lambda rule: rule.priority))
    green_fallbacks = tuple(
        rule
        for rule in enabled
        if rule.quality == "绿" and rule.trigger_type == "绿色兜底"
    )
    if len(green_fallbacks) != 1:
        raise MingGeError("绿色兜底规则必须恰好有一条")

    def first(quality: str, predicate: Callable[[MingGeQualityRule], bool]) -> MingGeQualityRule | None:
        return next((rule for rule in enabled if rule.quality == quality and predicate(rule)), None)

    color_pity = first("彩", lambda rule: rule.trigger_type == "累计阈值" and rule.threshold > 0 and next_progress.color >= rule.threshold)
    if color_pity is not None:
        return _result("彩", next_progress, color_pity)

    color_cycle = first("彩", lambda rule: rule.trigger_type in {"周期", "周期彩色判定"} and rule.cycle > 0 and next_progress.tenth % rule.cycle == 0 and rule.denominator > 0 and hit(rule.denominator))
    if color_cycle is not None:
        return _result("彩", next_progress, color_cycle)

    red_pity = first("红", lambda rule: rule.trigger_type == "累计阈值" and rule.threshold > 0 and next_progress.red >= rule.threshold)
    if red_pity is not None:
        return _result("红", next_progress, red_pity)

    for quality in ("红", "橙"):
        natural = first(quality, lambda rule: rule.trigger_type not in {"累计阈值", "绿色兜底"} and rule.denominator > 0 and hit(rule.denominator))
        if natural is not None:
            return _result(quality, next_progress, natural)

    return _result("绿", next_progress, green_fallbacks[0])


def _registry_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MingGeError(f"属性白名单{label}必须是整数")
    return value


def load_property_registry(path: Path) -> dict[str, PropertyBinding]:
    """读取不可推断的属性白名单；表格属性必须逐项命中它。"""
    path = Path(path)
    if not path.is_file():
        raise MingGeError(f"属性白名单不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MingGeError(f"属性白名单无法读取: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise MingGeError("属性白名单schema_version必须为1")
    properties = data.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise MingGeError("属性白名单properties不能为空")
    result: dict[str, PropertyBinding] = {}
    bindings: set[int] = set()
    for key, raw in properties.items():
        if not isinstance(key, str) or not key or not isinstance(raw, dict):
            raise MingGeError("属性白名单条目格式错误")
        required = {"binding", "display", "unit", "min", "max"}
        if set(raw) != required:
            raise MingGeError(f"属性白名单{key}字段不匹配")
        binding = _registry_integer(raw["binding"], f"{key}.binding")
        minimum = _registry_integer(raw["min"], f"{key}.min")
        maximum = _registry_integer(raw["max"], f"{key}.max")
        if binding <= 0 or minimum < 0 or maximum < minimum:
            raise MingGeError(f"属性白名单{key}范围非法")
        if binding in bindings:
            raise MingGeError(f"属性白名单binding重复: {binding}")
        if not isinstance(raw["display"], str) or not raw["display"]:
            raise MingGeError(f"属性白名单{key}.display不能为空")
        if not isinstance(raw["unit"], str):
            raise MingGeError(f"属性白名单{key}.unit必须是字符串")
        result[key] = PropertyBinding(
            key, binding, raw["display"], raw["unit"], minimum, maximum
        )
        bindings.add(binding)
    return result


def label_line(custom_text_base: int, slot: int, quality: str, slot_count: int) -> int:
    if (
        isinstance(custom_text_base, bool)
        or not isinstance(custom_text_base, int)
        or custom_text_base <= 0
        or isinstance(slot_count, bool)
        or not isinstance(slot_count, int)
        or slot_count <= 0
        or not 1 <= slot <= slot_count
        or quality not in QUALITY_ORDER
    ):
        raise MingGeError("命格显示行参数非法")
    return custom_text_base + QUALITY_ORDER[quality] * slot_count + slot - 1


def custom_text_line(resource_index: int, frame: MingGeLabelFrame) -> str:
    return (
        f"<PlayImg:{resource_index}:{frame.frame_id}:1:100:0:0:1:"
        f"{frame.hover_text}>"
    )


def _template_root() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "candidate"
        / "xy.optional.mingge-system"
        / "payload"
        / "server"
        / "templates"
    )


def _render_template(
    name: str,
    values: dict[str, str],
    template_root: Path | None = None,
) -> str:
    path = (Path(template_root).resolve() if template_root is not None else _template_root()) / name
    if not path.is_file():
        raise MingGeError(f"服务端模板不存在: {path}")
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"@@{key}@@", value)
    if "@@" in text:
        raise MingGeError(f"服务端模板存在未替换标记: {name}")
    return text


def _server_bytes(text: str) -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return (normalized.replace("\n", "\r\n") + "\r\n").encode("gb18030")


def _wrap_questdiary_call_target(text: str, entry_label: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    expected_first_line = f"[{entry_label}]"
    first_line, separator, remainder = normalized.partition("\n")
    if first_line != expected_first_line or not separator:
        raise MingGeError(f"QuestDiary入口标签不匹配: {entry_label}")
    return f"{first_line}\n{{\n{remainder}\n}}"


def _validated_attribute_rows(
    book: MingGeWorkbook, registry: dict[str, PropertyBinding]
) -> tuple[tuple[int, MingGeQualityAttribute, PropertyBinding], ...]:
    slots = {affix.affix_id.casefold(): affix.slot for affix in book.affixes}
    signatures: dict[str, tuple[str, str]] = {}
    rows = []
    for attribute in book.attributes:
        binding = registry.get(attribute.property_key)
        if binding is None:
            raise MingGeError(f"blocker: 未知属性键: {attribute.property_key}")
        if not binding.minimum <= attribute.value <= binding.maximum:
            raise MingGeError(
                f"blocker: 属性数值越界: {attribute.property_key}={attribute.value}"
            )
        if attribute.unit != binding.unit:
            raise MingGeError(
                f"blocker: 属性单位冲突: {attribute.property_key}={attribute.unit}"
            )
        slot = slots.get(attribute.affix_id.casefold())
        if slot is None:
            raise MingGeError(f"blocker: 属性引用未知词条: {attribute.affix_id}")
        signature = (attribute.property_key, attribute.unit)
        expected = signatures.setdefault(attribute.affix_id.casefold(), signature)
        if signature != expected:
            raise MingGeError(
                f"blocker: 同一词条四品质 property_key 或 unit 不一致: {attribute.affix_id}"
            )
        rows.append((slot, attribute, binding))
    return tuple(sorted(rows, key=lambda row: (QUALITY_ORDER[row[1].quality], row[0])))


def _validated_level_slots(
    book: MingGeWorkbook,
) -> tuple[tuple[MingGeSlotRule, int], ...]:
    slots: list[tuple[MingGeSlotRule, int]] = []
    for slot in book.slots:
        if not slot.enabled:
            continue
        if slot.condition_type != "等级" or slot.condition_key != "角色等级":
            raise MingGeError(
                f"blocker: 槽位{slot.slot}条件合同不支持: "
                f"{slot.condition_type}/{slot.condition_key}"
            )
        if re.fullmatch(r"[0-9]+", slot.condition_value) is None:
            raise MingGeError(f"blocker: 槽位{slot.slot}条件值必须是数字")
        slots.append((slot, int(slot.condition_value)))
    if not slots:
        raise MingGeError("blocker: 槽位条件没有启用项")
    thresholds = tuple(threshold for _, threshold in slots)
    if any(current <= previous for previous, current in zip(thresholds, thresholds[1:])):
        raise MingGeError("blocker: 槽位等级条件必须按槽位严格递增")
    return tuple(slots)


def _validated_costs(book: MingGeWorkbook) -> dict[str, MingGeCost]:
    costs = {cost.mode: cost for cost in book.costs if cost.enabled}
    required = ("单次", "十连")
    if set(costs) != set(required) or any(
        costs[mode].cost_type != "元宝" for mode in required
    ):
        raise MingGeError("blocker: 洗练消耗必须是启用的单次/十连元宝配置")
    return costs


def _slot_navigation(
    book: MingGeWorkbook,
    slots: Sequence[tuple[MingGeSlotRule, int]],
    dialog_resource_index: int | None,
) -> str:
    costs = _validated_costs(book)
    color_cycle = next(
        rule.cycle
        for rule in book.quality_rules
        if rule.enabled and rule.quality == "彩" and rule.trigger_type == "周期彩色判定"
    )
    lines = ["[@XY_MG_PANEL_ROUTE]"]
    for opened, (_, threshold) in enumerate(slots):
        lines.extend(
            (
                "#IF",
                f"SMALL <$LEVEL> {threshold}",
                "#ACT",
                f"DELAYGOTO 50 @XY_MG_PANEL_{opened}",
                "BREAK",
            )
        )
    lines.extend(
        (
            "#IF",
            "#ACT",
            f"DELAYGOTO 50 @XY_MG_PANEL_{len(slots)}",
            "BREAK",
        )
    )
    dialog_open = (
        ""
        if dialog_resource_index is None
        else f"OPENMERCHANTBIGDLG {dialog_resource_index} 0 0 0 0 0 1 630 2 1"
    )
    for opened in range(len(slots) + 1):
        lines.extend((f"[@XY_MG_PANEL_{opened}]", "#IF", "#ACT"))
        if dialog_open:
            lines.append(dialog_open)
            lines.extend(
                (
                    "#SAY",
                    f"<&USERITEM:{book.settings.equip_slot}:79:102:1>",
                    f"<&Text:{book.settings.npc_name}·命格洗练:240:18{{FCOLOR=253}}>",
                    f"<&Text:仅支持身上准确名称为{book.settings.target_item_name}的装备，命格属性写入后请悬浮查看:34:43{{FCOLOR=161}}>",
                    f"<&Text:身上{book.settings.target_item_name}:66:178{{FCOLOR=250}}>",
                    "<&Text:命格槽位:254:47{FCOLOR=251}>",
                    "<&Text:当前选择:476:47{FCOLOR=251}>",
                    "<&Text:当前槽位：<$STR(N$XY_MG_SLOT)>:450:98{FCOLOR=250}>",
                    "<&Text:点击中间已开放槽位进行选择:420:126{FCOLOR=161}>",
                    "<&Text:洗练规则:476:202{FCOLOR=251}>",
                    f"<&Text:{book.settings.red_pity}次必出红色命格:430:228{{FCOLOR=249}}>",
                    f"<&Text:每{color_cycle}次参与彩色判定:430:250{{FCOLOR=250}}>",
                    f"<&Text:{book.settings.color_pity}次必出彩色命格:430:272{{FCOLOR=168}}>",
                    "<&Text:洗练后悬浮身上灵玉查看属性:418:294{FCOLOR=161}>",
                )
            )
            lines.extend(
                f"<&Text:{slot.display_name}（{threshold}级开放）:182:{66 + (slot.slot - 1) * 31}"
                f"{{FCOLOR=250}}/@XY_MG_SLOT{slot.slot}>"
                for slot, threshold in slots[:opened]
            )
            lines.extend(
                (
                    "<&Text:羁绊说明:105:372{FCOLOR=250}/@XY_MG_BOND_INFO>",
                    f"<&Text:单次洗练|249#需要{costs['单次'].amount}元宝:270:372"
                    "{FCOLOR=69}/@XY_MG_WASH_ONE>",
                    f"<&Text:十连洗练|249#需要{costs['十连'].amount}元宝:447:372"
                    "{FCOLOR=249}/@XY_MG_WASH_TEN>",
                )
            )
        else:
            lines.extend(("#SAY", "命格洗练\\"))
            lines.extend(
                f"<{slot.display_name}（{threshold}级开放）/@XY_MG_SLOT{slot.slot}>\\"
                for slot, threshold in slots[:opened]
            )
            lines.extend(
                (
                    "<单次洗练/@XY_MG_WASH_ONE>  <十连洗练/@XY_MG_WASH_TEN>\\",
                    "<关闭/@exit>",
                )
            )
    lines.extend(
        (
            "[@XY_MG_BOND_INFO]",
            "#IF",
            "#ACT",
            "MESSAGEBOX 当前命格按槽位独立生效，羁绊功能尚未开启。",
            "BREAK",
        )
    )
    for slot, threshold in slots:
        lines.extend(
            (
                f"[@XY_MG_SLOT{slot.slot}]",
                "#IF",
                f"SMALL <$LEVEL> {threshold}",
                "#ACT",
                f"MESSAGEBOX {slot.display_name}需要达到{threshold}级。",
                "BREAK",
                "#IF",
                "#ACT",
                f"MOV N$XY_MG_SLOT {slot.slot}",
                "DELAYGOTO 50 @XY_MG_PANEL_ROUTE",
                "BREAK",
            )
        )
    return "\n".join(lines)


def _wash_precheck(book: MingGeWorkbook) -> str:
    return "\n".join(
        (
            "[@XY_MG_PRECHECK]",
            "#IF",
            "EQUAL N$XY_MG_SLOT 0",
            "#ACT",
            "MESSAGEBOX 请先选择一个已开放的命格槽位。",
            "BREAK",
            "#IF",
            f"NOT CHECKUSEITEM {book.settings.equip_slot}",
            "#ACT",
            "MESSAGEBOX 请先佩戴命格目标装备。",
            "BREAK",
            "#IF",
            f"EQUAL <$JADE> {book.settings.target_item_name}",
            "#ACT",
            "DELAYGOTO 50 @XY_MG_COST_ROUTE",
            "BREAK",
            "#ELSEACT",
            "MESSAGEBOX 当前装备名称不符合命格配置。",
            "BREAK",
        )
    )


def _slot_progress_route(
    slots: Sequence[tuple[MingGeSlotRule, int]],
) -> str:
    lines = ["[@XY_MG_PROGRESS_ROUTE]"]
    for slot, _ in slots:
        number = slot.slot
        lines.extend(
            (
                "#IF",
                f"EQUAL N$XY_MG_SLOT {number}",
                "#ACT",
                f"INC U{200 + number} <$STR(N$XY_MG_PROGRESS_ADD)>",
                f"INC U{470 + number} <$STR(N$XY_MG_PROGRESS_ADD)>",
                f"INC U{490 + number} <$STR(N$XY_MG_PROGRESS_ADD)>",
                f"MOV N$XY_MG_RED_PROGRESS <$STR(U{200 + number})>",
                f"MOV N$XY_MG_COLOR_PROGRESS <$STR(U{470 + number})>",
                f"MOV N$XY_MG_TENTH_PROGRESS <$STR(U{490 + number})>",
                "DELAYGOTO 50 @XY_MG_QUALITY",
                "BREAK",
            )
        )
    return "\n".join(lines)


def _quality_action(quality: str, reset_fields: Sequence[str]) -> str:
    color = {"绿": 250, "橙": 69, "红": 249, "彩": 251}[quality]
    reset_names = {
        "红色进度": "N$XY_MG_RESET_RED",
        "彩色进度": "N$XY_MG_RESET_COLOR",
        "十连进度": "N$XY_MG_RESET_TENTH",
    }
    lines = [
        f"MOV N$XY_MG_QUALITY {QUALITY_ORDER[quality] + 1}",
        f"MOV N$XY_MG_COLOR {color}",
        f"MOV S$XY_MG_QUALITY {quality}",
    ]
    lines.extend(f"MOV {reset_names[field]} 1" for field in reset_fields if field in reset_names)
    lines.extend(("DELAYGOTO 50 @XY_MG_BATCH_APPLY", "BREAK"))
    return "\n".join(lines)


def _quality_logic(book: MingGeWorkbook) -> str:
    by_semantic = {
        (rule.quality, rule.trigger_type): rule
        for rule in book.quality_rules
        if rule.enabled
    }
    color_pity = by_semantic[("彩", "累计阈值")]
    color_cycle = by_semantic[("彩", "周期彩色判定")]
    red_pity = by_semantic[("红", "累计阈值")]
    red_natural = by_semantic[("红", "概率")]
    orange_natural = by_semantic[("橙", "概率")]
    green = by_semantic[("绿", "绿色兜底")]
    return "\n".join(
        (
            "[@XY_MG_QUALITY]",
            "#IF",
            "#ACT",
            "MOV N$XY_MG_QUALITY 1",
            "MOV N$XY_MG_COLOR 250",
            "MOV N$XY_MG_RESET_RED 0",
            "MOV N$XY_MG_RESET_COLOR 0",
            "MOV N$XY_MG_RESET_TENTH 0",
            "MOV S$XY_MG_QUALITY 绿",
            "#IF",
            f"LARGE N$XY_MG_COLOR_PROGRESS {color_pity.threshold - 1}",
            "#ACT",
            _quality_action("彩", color_pity.reset_fields),
            "#IF",
            f"LARGE N$XY_MG_TENTH_PROGRESS {color_cycle.cycle - 1}",
            f"RANDOM {color_cycle.denominator}",
            "#ACT",
            _quality_action("彩", color_cycle.reset_fields),
            "#IF",
            f"LARGE N$XY_MG_RED_PROGRESS {red_pity.threshold - 1}",
            "#ACT",
            _quality_action("红", red_pity.reset_fields),
            "#IF",
            f"RANDOM {red_natural.denominator}",
            "#ACT",
            _quality_action("红", red_natural.reset_fields),
            "#IF",
            f"RANDOM {orange_natural.denominator}",
            "#ACT",
            _quality_action("橙", orange_natural.reset_fields),
            "#IF",
            "#ACT",
            _quality_action("绿", green.reset_fields),
        )
    )


def _property_apply(book: MingGeWorkbook, rows: Sequence[tuple[int, MingGeQualityAttribute, PropertyBinding]], custom_text_base: int) -> str:
    by_slot: dict[int, dict[str, tuple[MingGeQualityAttribute, PropertyBinding]]] = {}
    for slot, attribute, binding in rows:
        by_slot.setdefault(slot, {})[attribute.quality] = (attribute, binding)
    reset_variables = (
        ("红色进度", "N$XY_MG_RESET_RED", 200),
        ("彩色进度", "N$XY_MG_RESET_COLOR", 470),
        ("十连进度", "N$XY_MG_RESET_TENTH", 490),
    )
    selected_resets = {
        field
        for rule in book.quality_rules
        if rule.enabled
        for field in rule.reset_fields
    }
    lines = ["[@XY_MG_BATCH_APPLY]"]
    for slot in range(1, book.settings.slot_count + 1):
        lines.extend(
            (
                "#IF",
                f"EQUAL N$XY_MG_SLOT {slot}",
                "#ACT",
                f"GOTO @XY_MG_BATCH_APPLY_SLOT_{slot}",
                "BREAK",
            )
        )
    lines.extend(("#IF", "#ACT", "MESSAGEBOX 当前命格槽位无效，未改变装备。", "BREAK"))
    for slot in range(1, book.settings.slot_count + 1):
        qualities = by_slot[slot]
        green_attribute, binding = qualities["绿"]
        display_row = book.settings.slot_count + slot
        lines.extend((f"[@XY_MG_BATCH_APPLY_SLOT_{slot}]", "#IF", "#ACT"))
        lines.append(f"MOV N$XY_MG_VALUE {green_attribute.value}")
        lines.append(
            f"MOV N$XY_MG_LABEL_LINE {label_line(custom_text_base, slot, '绿', book.settings.slot_count)}"
        )
        for quality in ("橙", "红", "彩"):
            attribute, _ = qualities[quality]
            lines.extend(
                (
                    "#IF",
                    f"EQUAL N$XY_MG_QUALITY {QUALITY_ORDER[quality] + 1}",
                    "#ACT",
                    f"MOV N$XY_MG_VALUE {attribute.value}",
                    f"MOV N$XY_MG_LABEL_LINE {label_line(custom_text_base, slot, quality, book.settings.slot_count)}",
                )
            )
        lines.extend(
            (
                "#IF",
                "#ACT",
                f"LockUpdateItem {book.settings.equip_slot}",
                f"SetCustomItemAbil {book.settings.equip_slot} {slot} 0 <$STR(N$XY_MG_COLOR)>",
                f"SetCustomItemAbil {book.settings.equip_slot} {slot} 1 {binding.binding}",
                f"SetCustomItemAbil {book.settings.equip_slot} {slot} 2 {slot}",
                f"SetCustomItemAbil {book.settings.equip_slot} {slot} 3 0",
                f"SetCustomItemAbil {book.settings.equip_slot} {slot} 4 9",
                f"SetCustomItemValue {book.settings.equip_slot} {slot} = <$STR(N$XY_MG_VALUE)>",
                f"SetCustomItemAbil {book.settings.equip_slot} {display_row} 0 255",
                f"SetCustomItemAbil {book.settings.equip_slot} {display_row} 1 60",
                f"SetCustomItemAbil {book.settings.equip_slot} {display_row} 2 {slot}",
                f"SetCustomItemAbil {book.settings.equip_slot} {display_row} 3 0",
                f"SetCustomItemAbil {book.settings.equip_slot} {display_row} 4 9",
                f"SetCustomItemValueEX {book.settings.equip_slot} {display_row} = <$STR(N$XY_MG_LABEL_LINE)> 0 0",
            )
        )
        for field, flag, index_base in reset_variables:
            if field in selected_resets:
                lines.extend(("#IF", f"EQUAL {flag} 1", "#ACT", f"MOV U{index_base + slot} 0"))
        lines.extend(
            (
                "#IF",
                "#ACT",
                f"UpdateItem {book.settings.equip_slot}",
                "DELAYGOTO 50 @XY_MG_DRAW_TAIL",
                "BREAK",
            )
        )
    return "\n".join(lines)


def _cost_routes(book: MingGeWorkbook) -> str:
    costs = _validated_costs(book)
    lines = ["[@XY_MG_COST_ROUTE]"]
    for mode, value in (("单次", 1), ("十连", 10)):
        lines.extend(("#IF", f"EQUAL N$XY_MG_COST_MODE {value}", "#ACT", f"DELAYGOTO 50 @XY_MG_COST_{value}", "BREAK"))
    for mode, value in (("单次", 1), ("十连", 10)):
        cost = costs[mode]
        lines.extend(
            (
                f"[@XY_MG_COST_{value}]",
                "#IF",
                f"CHECKGAMEGOLD > {cost.amount - 1}",
                "#ACT",
                f"DELAYGOTO 50 @XY_MG_PAY_{value}",
                "BREAK",
                "#ELSEACT",
                f"MESSAGEBOX {mode}洗练需要{cost.amount}元宝，余额或材料不足，不扣除。",
                "BREAK",
                f"[@XY_MG_PAY_{value}]",
                "#IF",
                "#ACT",
                f"GAMEGOLD - {cost.amount}",
                "DELAYGOTO 50 @XY_MG_PROGRESS_ROUTE",
                "BREAK",
            )
        )
    return "\n".join(lines)


def compile_mingge_payload(
    book: MingGeWorkbook,
    resource_index: int,
    custom_text_base: int,
    registry: dict[str, PropertyBinding],
    dialog_resource_index: int | None = None,
    server_template_root: Path | None = None,
) -> CompiledMingGePayload:
    """把已通过六规则模型的工作簿编译为未部署的翎风脚本候选。"""
    if isinstance(resource_index, bool) or not isinstance(resource_index, int) or resource_index < 0:
        raise MingGeError("资源索引必须是非负整数")
    if dialog_resource_index is not None and (
        isinstance(dialog_resource_index, bool)
        or not isinstance(dialog_resource_index, int)
        or dialog_resource_index < 0
    ):
        raise MingGeError("对话框资源索引必须是非负整数或None")
    rows = _validated_attribute_rows(book, registry)
    level_slots = _validated_level_slots(book)
    custom_lines = tuple(
        custom_text_line(
            resource_index,
            MingGeLabelFrame(
                slot,
                attribute.quality,
                QUALITY_ORDER[attribute.quality] * book.settings.slot_count + slot - 1,
                attribute.hover_text,
            ),
        )
        for slot, attribute, _ in rows
    )
    property_apply = _property_apply(book, rows, custom_text_base)
    core = _render_template(
        "命格核心.txt.tpl",
        {
            "EQUIP_SLOT": str(book.settings.equip_slot),
            "TARGET_ITEM": book.settings.target_item_name,
            "SLOT_NAVIGATION": _slot_navigation(book, level_slots, dialog_resource_index),
            "BATCH_PROGRESS": str(book.settings.batch_progress),
            "PRECHECK": _wash_precheck(book),
            "QUALITY_LOGIC": _quality_logic(book),
            "COST_ROUTES": _cost_routes(book),
            "PROGRESS_ROUTE": _slot_progress_route(level_slots),
            "PROPERTY_APPLY": property_apply,
        },
        server_template_root,
    )
    core = _wrap_questdiary_call_target(core, "@XY_MG_MAIN")
    npc = _render_template("龙魂觉醒.txt.tpl", {}, server_template_root)
    display = _render_template(
        "命格显示.txt.tpl",
        {
            "EQUIP_SLOT": str(book.settings.equip_slot),
            "TARGET_ITEM": book.settings.target_item_name,
        },
        server_template_root,
    )
    display = _wrap_questdiary_call_target(display, "@XY_MG_DISPLAY")
    attributes = _render_template(
        "命格属性.txt.tpl",
        {"PROPERTY_APPLY": property_apply},
        server_template_root,
    )
    registration_path = PurePosixPath(book.settings.script_dir.replace("\\", "/"))
    script_directory = (
        registration_path.parent
        if registration_path.name == book.settings.npc_name
        else registration_path
    )
    npc_path = (
        PurePosixPath("Mir200/Envir/Market_Def")
        / script_directory
        / f"{book.settings.npc_name}-{book.settings.map_id}.txt"
    )
    files = {
        npc_path: _server_bytes(npc),
        PurePosixPath("Mir200/Envir/QuestDiary/玄渊命格/命格核心.txt"): _server_bytes(core),
        PurePosixPath("Mir200/Envir/QuestDiary/玄渊命格/命格显示.txt"): _server_bytes(display),
        PurePosixPath("Mir200/Envir/QuestDiary/玄渊命格/命格属性.txt"): _server_bytes(attributes),
    }
    return CompiledMingGePayload(files, files[npc_path].decode("gb18030"), custom_lines)


def _mingge_hash_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _mingge_hash_file(path: Path) -> str | None:
    return _mingge_hash_bytes(path.read_bytes()) if path.is_file() else None


def _mir_lines(data: bytes, path: Path) -> list[str]:
    if re.search(rb"(?<!\r)\n|\r(?!\n)", data):
        raise MingGeError(f"Mir文本不是CRLF: {path}")
    try:
        return data.decode("gb18030").splitlines()
    except UnicodeDecodeError as exc:
        raise MingGeError(f"Mir文本不是GB18030: {path}") from exc


def _mir_bytes(lines: Sequence[str]) -> bytes:
    if not lines:
        return b""
    return ("\r\n".join(lines) + "\r\n").encode("gb18030")


def _mingge_change(path: Path, after: bytes, scope: str) -> MingGeFileChange | None:
    before_hash = _mingge_hash_file(path)
    after_hash = _mingge_hash_bytes(after)
    if before_hash == after_hash:
        return None
    return MingGeFileChange(path, before_hash, after_hash, after, scope)


def _atomic_mingge_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _effect_positions(lines: Sequence[str]) -> list[int]:
    return [index for index, line in enumerate(lines) if line.strip()]


def _valid_registration_component(value: str) -> bool:
    if not value or value in {".", ".."} or value[-1] in {" ", "."}:
        return False
    if any(ord(character) < 32 or character in '<>:"/\\|?*' for character in value):
        return False
    return True


def _registration_path_blockers(book: MingGeWorkbook) -> list[str]:
    blockers: list[str] = []
    raw_directory = book.settings.script_dir
    normalized = raw_directory.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
    ):
        blockers.append(f"NPC脚本目录不是安全相对路径: {raw_directory}")
    else:
        components = normalized.split("/")
        if not all(_valid_registration_component(component) for component in components):
            blockers.append(f"NPC脚本目录包含非法路径组件: {raw_directory}")
    for label, value in (
        ("NPC名称", book.settings.npc_name),
        ("地图号", book.settings.map_id),
    ):
        if not _valid_registration_component(value):
            blockers.append(f"{label}包含非法注册组件: {value}")
    return blockers


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return True


def _inject_mingge_hook(
    original: bytes,
    path: Path,
    label: str,
    marker: str,
) -> tuple[bytes, str | None]:
    lines = _mir_lines(original, path)
    begin = f"; XY-MINGGE-{marker}-BEGIN"
    end = f"; XY-MINGGE-{marker}-END"
    call = "#CALL [\\玄渊命格\\命格显示.txt] @XY_MG_DISPLAY"
    block = [begin, call, end]
    if begin in lines or end in lines:
        if lines.count(begin) != 1 or lines.count(end) != 1:
            return original, f"命格受管钩子标记重复或残缺: {path} ({marker})"
        start = lines.index(begin)
        if lines[start : start + len(block)] != block:
            return original, f"命格受管钩子已被修改: {path} ({marker})"
        return original, None
    anchor = f"[@{label}]"
    matches = [index for index, line in enumerate(lines) if line.casefold() == anchor.casefold()]
    if len(matches) != 1:
        return original, f"共享标签缺失或重复: {path} ({anchor})"
    at = matches[0] + 1
    return _mir_bytes((*lines[:at], *block, *lines[at:])), None


class MingGeService:
    """命格平台只读预检和可逐字节回滚的事务边界。"""

    def __init__(self, platform_root: Path) -> None:
        self.platform_root = Path(platform_root).resolve()
        self.registry_path = (
            self.platform_root
            / "packages/candidate/xy.optional.mingge-system/payload/property_registry.json"
        )
        self.provider_path = (
            self.platform_root
            / "wzl编辑/bin/XuanYuanWzlProvider/XuanYuanWzlProvider.exe"
        )
        self.template_dir = self.platform_root / "wzl编辑/workspace/mingge-template"
        self.server_template_root = (
            self.platform_root
            / "packages/candidate/xy.optional.mingge-system/payload/server/templates"
        )

    @staticmethod
    def _blocked_plan(
        server: Path,
        client: Path,
        workbook: Path,
        workbook_hash: str,
        blockers: Sequence[str],
        warnings: Sequence[str],
        resource_index: int = -1,
        custom_text_base: int = -1,
        resource_name: str = "",
    ) -> MingGePlan:
        return MingGePlan(
            uuid.uuid4().hex,
            server,
            client,
            workbook,
            workbook_hash,
            resource_index,
            custom_text_base,
            resource_name,
            tuple(blockers),
            tuple(warnings),
            (),
        )

    @staticmethod
    def _legacy_status(
        server: Path,
        client: Path,
        custom_bytes: bytes,
        effect_lines: Sequence[str],
        merchant_lines: Sequence[str],
    ) -> tuple[bool, bool]:
        script_results = {
            relative: _mingge_hash_file(server / PurePosixPath(relative))
            for relative in LEGACY_SCRIPT_HASHES
        }
        label_wzl = client / "data/XY_MingGeRainbow.wzl"
        label_wzx = client / "data/XY_MingGeRainbow.wzx"
        dialog_wzl = client / "data/XY_MingGeDialog.wzl"
        dialog_wzx = client / "data/XY_MingGeDialog.wzx"
        positions = _effect_positions(effect_lines)
        names = [effect_lines[index].strip() for index in positions]
        effect_exact = (
            len(names) > 20
            and names[19].casefold() == "xy_minggedialog.wzl"
            and names[20].casefold() == "xy_minggerainbow.wzl"
        )
        scripts_exact = all(
            script_results[relative] is not None
            and script_results[relative].casefold() == expected.casefold()
            for relative, expected in LEGACY_SCRIPT_HASHES.items()
        )
        label_exact = (
            _mingge_hash_file(label_wzl) is not None
            and _mingge_hash_file(label_wzl).casefold() == LEGACY_LABEL_WZL_HASH.casefold()
            and _mingge_hash_file(label_wzx) is not None
            and _mingge_hash_file(label_wzx).casefold() == LEGACY_LABEL_WZX_HASH.casefold()
        )
        dialog_exact = (
            _mingge_hash_file(dialog_wzl) is not None
            and _mingge_hash_file(dialog_wzl).casefold() == LEGACY_DIALOG_WZL_HASH.casefold()
            and _mingge_hash_file(dialog_wzx) is not None
            and _mingge_hash_file(dialog_wzx).casefold() == LEGACY_DIALOG_WZX_HASH.casefold()
        )
        full = (
            _mingge_hash_bytes(custom_bytes).casefold() == LEGACY_CUSTOM_TEXT_HASH.casefold()
            and effect_exact
            and scripts_exact
            and label_exact
            and dialog_exact
            and merchant_lines.count(LEGACY_MERCHANT_LINE) == 1
        )
        signal = (
            any(value is not None for value in script_results.values())
            or label_wzl.exists()
            or label_wzx.exists()
            or dialog_wzl.exists()
            or dialog_wzx.exists()
            or any("xy_minggerainbow" in line.casefold() for line in effect_lines)
            or any("<img:" in line.casefold() and ":20:" in line for line in _mir_lines(custom_bytes, Path("CustomItemPropertyTextVarList.txt")))
            or LEGACY_MERCHANT_LINE in merchant_lines
        )
        return full, signal

    @staticmethod
    def _dialog_index(effect_lines: Sequence[str], client: Path) -> int | None:
        names = [effect_lines[index].strip() for index in _effect_positions(effect_lines)]
        if len(names) <= 19 or names[19].casefold() != "xy_minggedialog.wzl":
            return None
        wzl = client / "data/XY_MingGeDialog.wzl"
        wzx = client / "data/XY_MingGeDialog.wzx"
        wzl_hash, wzx_hash = _mingge_hash_file(wzl), _mingge_hash_file(wzx)
        if (
            wzl_hash is not None
            and wzx_hash is not None
            and wzl_hash.casefold() == LEGACY_DIALOG_WZL_HASH.casefold()
            and wzx_hash.casefold() == LEGACY_DIALOG_WZX_HASH.casefold()
        ):
            return 19
        return None

    @staticmethod
    def _setup_after(original: bytes, path: Path) -> tuple[bytes, str | None]:
        lines = _mir_lines(original, path)
        values: dict[str, list[str]] = {}
        for line in lines:
            if "=" in line:
                key, value = line.split("=", 1)
                values.setdefault(key.strip().casefold(), []).append(value.strip())
        if values.get("usesqlitedb") != ["1"]:
            return original, "!Setup.txt 必须唯一启用 UseSqliteDB=1"
        check = values.get("customitempropertycheck60", [])
        binding = values.get("customitempropertybindname60", [])
        if check == ["1"] and binding == ["<TEXT:$$1>"]:
            updated = list(lines)
        elif not check and not binding:
            updated = [
                *lines,
                "CustomItemPropertyCheck60=1",
                "CustomItemPropertyBindName60=<TEXT:$$1>",
            ]
        else:
            return original, "CustomItemProperty 60 已被其他内容占用"

        hidden_checks = {
            f"customitempropertycheck{position}": (
                f"CustomItemPropertyCheck{position}=0"
            )
            for position in range(1, 8)
        }
        counts = {key: 0 for key in hidden_checks}
        for index, line in enumerate(updated):
            if "=" not in line:
                continue
            key = line.split("=", 1)[0].strip().casefold()
            if key not in hidden_checks:
                continue
            counts[key] += 1
            updated[index] = hidden_checks[key]
        duplicates = [key for key, count in counts.items() if count > 1]
        if duplicates:
            return original, "CustomItemProperty 1-7 显示开关存在重复配置"
        for key, desired in hidden_checks.items():
            if counts[key] == 0:
                updated.append(desired)
        after = _mir_bytes(updated)
        return (original if after == original else after), None

    @staticmethod
    def _merchant_after(original: bytes, path: Path, expected: str) -> tuple[bytes, str | None]:
        lines = _mir_lines(original, path)
        if lines.count(expected) == 1:
            return original, None
        if lines.count(expected) > 1:
            return original, "命格NPC登记重复"
        identity = expected.split(" ", 1)[0].casefold()
        if any(line.split(" ", 1)[0].casefold() == identity for line in lines if line.strip()):
            return original, "命格NPC登记存在冲突"
        return _mir_bytes((*lines, expected)), None

    def preflight(self, server: Path, workbook: Path, client: Path) -> MingGePlan:
        server = Path(server).resolve()
        client = Path(client).resolve()
        workbook = Path(workbook).resolve()
        if not workbook.is_file():
            raise MingGeError(f"命格配置表不存在: {workbook}")
        workbook_hash = _mingge_hash_file(workbook)
        assert workbook_hash is not None
        book = read_mingge_workbook(workbook)
        blockers: list[str] = _registration_path_blockers(book)
        if book.settings.target_item_name != MINGGE_TARGET_ITEM_NAME:
            blockers.append(
                f"命格固定目标装备必须是{MINGGE_TARGET_ITEM_NAME}: "
                f"{book.settings.target_item_name}"
            )
        if book.settings.equip_slot != MINGGE_TARGET_EQUIP_SLOT:
            blockers.append(
                f"命格固定装备位必须是{MINGGE_TARGET_EQUIP_SLOT}: "
                f"{book.settings.equip_slot}"
            )
        warnings: list[str] = []
        envir = server / "Mir200/Envir"
        paths = {
            "setup": server / "Mir200/!Setup.txt",
            "mapinfo": envir / "MapInfo.txt",
            "merchant": envir / "MerChant.txt",
            "qmanage": envir / "MapQuest_Def/QManage.txt",
            "qfunction": envir / "Market_Def/QFunction-0.txt",
            "custom": envir / "CustomItemPropertyTextVarList.txt",
            "effect": envir / "EffectImageList.txt",
            "database": server / "Mud2/DB/ApexM2.DB",
            "state": envir / "QuestDiary/玄渊命格/platform-state.json",
        }
        if not server.is_dir():
            blockers.append(f"服务端根目录不存在: {server}")
        if not (client / "data").is_dir():
            blockers.append(f"客户端data目录不存在: {client / 'data'}")
        for name in ("setup", "mapinfo", "merchant", "qmanage", "qfunction", "custom", "effect", "database"):
            if not paths[name].is_file():
                blockers.append(f"必需目标文件不存在: {paths[name]}")
        if blockers:
            return self._blocked_plan(server, client, workbook, workbook_hash, blockers, warnings)

        setup_after, setup_blocker = self._setup_after(paths["setup"].read_bytes(), paths["setup"])
        if setup_blocker:
            blockers.append(setup_blocker)
        map_lines = _mir_lines(paths["mapinfo"].read_bytes(), paths["mapinfo"])
        if not any(re.match(rf"^\[{re.escape(book.settings.map_id)}(?:\s|\])", line) for line in map_lines):
            blockers.append(f"MapInfo 未注册目标地图: {book.settings.map_id}")
        try:
            connection = sqlite3.connect(f"file:{paths['database'].as_posix()}?mode=ro", uri=True)
            try:
                rows = connection.execute(
                    "SELECT Idx, Name, StdMode FROM StdItems WHERE Name = ?",
                    (MINGGE_TARGET_ITEM_NAME,),
                ).fetchall()
            finally:
                connection.close()
            if len(rows) != 1 or int(rows[0][2]) != MINGGE_TARGET_ITEM_STD_MODE:
                blockers.append(
                    f"固定目标装备必须唯一且 StdMode={MINGGE_TARGET_ITEM_STD_MODE}: "
                    f"{MINGGE_TARGET_ITEM_NAME}"
                )
        except (sqlite3.Error, TypeError, ValueError) as exc:
            blockers.append(f"只读解析目标 StdItems 失败: {exc}")

        merchant_original = paths["merchant"].read_bytes()
        merchant_lines = _mir_lines(merchant_original, paths["merchant"])
        merchant_line = (
            f"{book.settings.script_dir} {book.settings.map_id} {book.settings.npc_x} "
            f"{book.settings.npc_y} {book.settings.npc_name} 0 {book.settings.npc_appearance} 0"
        )
        merchant_after, merchant_blocker = self._merchant_after(
            merchant_original, paths["merchant"], merchant_line
        )
        if merchant_blocker:
            blockers.append(merchant_blocker)
        qmanage_after, qmanage_blocker = _inject_mingge_hook(
            paths["qmanage"].read_bytes(), paths["qmanage"], "Login", "LOGIN"
        )
        qfunction_after = paths["qfunction"].read_bytes()
        for label, marker in (("TakeOnEx", "TAKEON"), ("TakeOffEx", "TAKEOFF")):
            qfunction_after, blocker = _inject_mingge_hook(
                qfunction_after, paths["qfunction"], label, marker
            )
            if blocker:
                blockers.append(blocker)
        if qmanage_blocker:
            blockers.append(qmanage_blocker)

        custom_original = paths["custom"].read_bytes()
        custom_lines = _mir_lines(custom_original, paths["custom"])
        effect_original = paths["effect"].read_bytes()
        effect_lines = _mir_lines(effect_original, paths["effect"])
        state: dict[str, object] | None = None
        if paths["state"].is_file():
            try:
                loaded = json.loads(paths["state"].read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or loaded.get("schema_version") != 1 or loaded.get("operation") != "mingge-system":
                    raise ValueError("schema/operation")
                state = loaded
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                blockers.append(f"命格平台状态文件无效: {exc}")

        if state is not None:
            managed_hook_markers = (
                (paths["qmanage"], "; XY-MINGGE-LOGIN-BEGIN"),
                (paths["qfunction"], "; XY-MINGGE-TAKEON-BEGIN"),
                (paths["qfunction"], "; XY-MINGGE-TAKEOFF-BEGIN"),
            )
            for hook_path, marker in managed_hook_markers:
                if marker not in _mir_lines(hook_path.read_bytes(), hook_path):
                    blockers.append(f"命格受管钩子缺失: {hook_path} ({marker})")

        legacy = False
        resource_index = -1
        custom_text_base = -1
        old_resource_name = ""
        managed_legacy_resource_index: int | None = None
        if state is not None:
            try:
                custom_state = state["custom_text"]
                effect_state = state["effect_image_list"]
                if not isinstance(custom_state, dict) or not isinstance(effect_state, dict):
                    raise ValueError("managed sections")
                custom_text_base = int(custom_state["start_line"])
                count = int(custom_state["line_count"])
                start = custom_text_base - 1
                if start < 0 or count < 1 or start + count != len(custom_lines):
                    raise ValueError("custom tail")
                current_block = _mir_bytes(custom_lines[start:])
                if _mingge_hash_bytes(current_block).casefold() != str(custom_state["line_hash"]).casefold():
                    raise ValueError("custom hash")
                resource_index = int(effect_state["line_number"])
                old_resource_name = str(effect_state["resource_name"])
                positions = _effect_positions(effect_lines)
                if resource_index < 0 or resource_index >= len(positions) or effect_lines[positions[resource_index]].strip() != old_resource_name:
                    raise ValueError("effect line")
                managed = state["managed_scripts"]
                if not isinstance(managed, dict):
                    raise ValueError("managed scripts")
                for relative, expected_hash in managed.items():
                    current_hash = _mingge_hash_file(server / PurePosixPath(str(relative)))
                    if current_hash is None or current_hash.casefold() != str(expected_hash).casefold():
                        raise ValueError(f"managed script {relative}")
                legacy_wzl = client / "data/XY_MingGeRainbow.wzl"
                legacy_wzx = client / "data/XY_MingGeRainbow.wzx"
                if (
                    resource_index == 20
                    and old_resource_name.casefold().startswith("xy_minggelabels_")
                    and _mingge_hash_file(legacy_wzl) is not None
                    and _mingge_hash_file(legacy_wzl).casefold() == LEGACY_LABEL_WZL_HASH.casefold()
                    and _mingge_hash_file(legacy_wzx) is not None
                    and _mingge_hash_file(legacy_wzx).casefold() == LEGACY_LABEL_WZX_HASH.casefold()
                ):
                    managed_legacy_resource_index = resource_index
                    resource_index = len(positions)
                    warnings.append("managed-legacy-resource-relocated")
            except (KeyError, TypeError, ValueError) as exc:
                blockers.append(f"命格受管状态与目标不一致: {exc}")
        else:
            legacy, legacy_signal = self._legacy_status(
                server, client, custom_original, effect_lines, merchant_lines
            )
            if legacy:
                resource_index = len(_effect_positions(effect_lines))
                custom_text_base = 1
                warnings.append("legacy-adopt")
            elif legacy_signal:
                blockers.append("检测到不完整或字节突变的旧命格候选，禁止模糊接管")
            else:
                resource_index = len(_effect_positions(effect_lines))
                custom_text_base = len(custom_lines) + 1

        if blockers:
            return self._blocked_plan(
                server, client, workbook, workbook_hash, blockers, warnings,
                resource_index, custom_text_base,
            )

        dialog_resource_index = self._dialog_index(effect_lines, client)
        registry = load_property_registry(self.registry_path)
        with tempfile.TemporaryDirectory(prefix="xydp-mingge-preflight-") as temporary:
            temporary_root = Path(temporary)
            from .mingge_image import render_mingge_labels

            frames = render_mingge_labels(book, temporary_root / "frames")
            library = build_mingge_library(
                frames,
                temporary_root / "library",
                self.provider_path,
                workbook_path=workbook,
                template_dir=self.template_dir,
            )
            wzl_bytes = library.wzl_path.read_bytes()
            wzx_bytes = library.wzx_path.read_bytes()
            resource_name = library.wzl_path.name
            wzx_name = library.wzx_path.name
            if library.wzl_path.stem != library.wzx_path.stem:
                raise MingGeError("命格资源WZL/WZX名称不成对")
        payload = compile_mingge_payload(
            book,
            resource_index,
            custom_text_base,
            registry,
            dialog_resource_index=dialog_resource_index,
            server_template_root=self.server_template_root,
        )

        payload_targets: dict[PurePosixPath, Path] = {}
        for relative in payload.files:
            if relative.is_absolute() or ".." in relative.parts:
                blockers.append(f"生成脚本包含不安全相对路径: {relative}")
                continue
            destination = (server / Path(*relative.parts)).resolve()
            if not _path_is_within(destination, server):
                blockers.append(f"生成脚本超出服务端目标根目录: {destination}")
                continue
            payload_targets[relative] = destination
        if blockers:
            return self._blocked_plan(
                server, client, workbook, workbook_hash, blockers, warnings,
                resource_index, custom_text_base, resource_name,
            )

        if state is None and not legacy:
            existing_scripts = [
                payload_targets[relative]
                for relative in payload.files
                if payload_targets[relative].exists()
            ]
            if existing_scripts:
                blockers.append("存在未受管的命格目标脚本: " + "、".join(str(path) for path in existing_scripts))
        desired_custom_lines = list(payload.custom_property_lines)
        if state is not None:
            start = custom_text_base - 1
            custom_after = _mir_bytes((*custom_lines[:start], *desired_custom_lines))
        elif legacy:
            custom_after = _mir_bytes(desired_custom_lines)
        else:
            custom_after = _mir_bytes((*custom_lines, *desired_custom_lines))

        effect_after_lines = list(effect_lines)
        positions = _effect_positions(effect_after_lines)
        if state is not None:
            if managed_legacy_resource_index is not None:
                if managed_legacy_resource_index >= len(positions):
                    blockers.append("EffectImageList 旧命格资源行不存在")
                elif any(
                    line.strip().casefold() == resource_name.casefold()
                    for index, line in enumerate(effect_after_lines)
                    if index != positions[managed_legacy_resource_index]
                ):
                    blockers.append("EffectImageList 命格资源迁移目标已存在")
                else:
                    effect_after_lines[positions[managed_legacy_resource_index]] = "XY_MingGeRainbow.wzl"
                    effect_after_lines.append(resource_name)
            elif resource_index >= len(positions):
                blockers.append("EffectImageList 受管资源行不存在")
            else:
                effect_after_lines[positions[resource_index]] = resource_name
        else:
            if any(line.strip().casefold() == resource_name.casefold() for line in effect_after_lines):
                blockers.append("内容寻址命格资源已存在但没有受管状态")
            else:
                effect_after_lines.append(resource_name)
        effect_after = _mir_bytes(effect_after_lines)

        client_wzl = client / "data" / resource_name
        client_wzx = client / "data" / wzx_name
        if client_wzl.is_file() != client_wzx.is_file():
            blockers.append(f"客户端命格资源不完整: {client_wzl} / {client_wzx}")
        for target, expected in ((client_wzl, wzl_bytes), (client_wzx, wzx_bytes)):
            if target.exists() and _mingge_hash_file(target) != _mingge_hash_bytes(expected):
                blockers.append(f"客户端命格资源冲突: {target}")
        if blockers:
            return self._blocked_plan(
                server, client, workbook, workbook_hash, blockers, warnings,
                resource_index, custom_text_base, resource_name,
            )

        managed_hashes = {
            relative.as_posix(): _mingge_hash_bytes(data)
            for relative, data in payload.files.items()
        }
        state_payload = {
            "schema_version": 1,
            "operation": "mingge-system",
            "configuration_hash": library.config_hash,
            "workbook_hash": workbook_hash,
            "custom_text": {
                "start_line": custom_text_base,
                "line_count": len(desired_custom_lines),
                "line_hash": _mingge_hash_bytes(_mir_bytes(desired_custom_lines)),
            },
            "effect_image_list": {
                "line_number": resource_index,
                "resource_name": resource_name,
            },
            "resource_name": resource_name,
            "dialog_resource_index": dialog_resource_index,
            "managed_scripts": managed_hashes,
        }
        state_after = (json.dumps(state_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        proposed: list[tuple[Path, bytes, str]] = [
            (paths["setup"], setup_after, "server"),
            (paths["merchant"], merchant_after, "server"),
            (paths["qmanage"], qmanage_after, "server"),
            (paths["qfunction"], qfunction_after, "server"),
            (paths["custom"], custom_after, "server"),
            (paths["effect"], effect_after, "server"),
        ]
        proposed.extend(
            (payload_targets[relative], data, "server")
            for relative, data in payload.files.items()
        )
        proposed.extend(((client_wzl, wzl_bytes, "client"), (client_wzx, wzx_bytes, "client")))
        proposed.append((paths["state"], state_after, "server"))
        for path, _, scope in proposed:
            root = server if scope == "server" else client if scope == "client" else None
            if root is None or not _path_is_within(path, root):
                blockers.append(f"计划目标超出{scope}目标根目录: {path}")
        if blockers:
            return self._blocked_plan(
                server, client, workbook, workbook_hash, blockers, warnings,
                resource_index, custom_text_base, resource_name,
            )
        changes = tuple(
            change
            for path, after, scope in proposed
            if (change := _mingge_change(path, after, scope)) is not None
        )
        return MingGePlan(
            uuid.uuid4().hex,
            server,
            client,
            workbook,
            workbook_hash,
            resource_index,
            custom_text_base,
            resource_name,
            (),
            tuple(warnings),
            changes,
        )

    def _atomic_replace(self, path: Path, data: bytes) -> None:
        _atomic_mingge_write(path, data)

    def install(self, plan: MingGePlan) -> MingGeReceipt:
        if plan.blockers:
            raise MingGeError("预检存在阻止项: " + "；".join(plan.blockers))
        for change in plan.changes:
            root = (
                plan.server
                if change.scope == "server"
                else plan.client
                if change.scope == "client"
                else None
            )
            if root is None or not _path_is_within(change.path, root):
                raise MingGeError(f"计划目标超出{change.scope}目标根目录: {change.path}")
        if _mingge_hash_file(plan.workbook) != plan.workbook_hash:
            raise MingGeError(f"预检后文件已变化: {plan.workbook}")
        for change in plan.changes:
            if _mingge_hash_file(change.path) != change.before_hash:
                raise MingGeError(f"预检后文件已变化: {change.path}")
        if not plan.changes:
            return MingGeReceipt(plan.plan_id, Path(), "already-current", ())

        transaction_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        backup_dir = self.platform_root / "backups/mingge-system" / transaction_id
        files_dir = backup_dir / "files"
        staging_dir = backup_dir / ".staging"
        files_dir.mkdir(parents=True, exist_ok=False)
        staging_dir.mkdir()
        entries: list[dict[str, object]] = []
        receipt_path = backup_dir / "receipt.json"
        try:
            for index, change in enumerate(plan.changes):
                existed = change.path.is_file()
                backup = files_dir / f"{index:02d}.bin"
                staged = staging_dir / f"{index:02d}.bin"
                if existed:
                    shutil.copyfile(change.path, backup)
                _atomic_mingge_write(staged, change.after_bytes)
                if _mingge_hash_file(staged) != change.after_hash:
                    raise MingGeError(f"临时副本验证失败: {change.path}")
                entries.append({
                    "path": str(change.path),
                    "scope": change.scope,
                    "existed_before": existed,
                    "before_hash": change.before_hash,
                    "after_hash": change.after_hash,
                    "backup": str(backup) if existed else None,
                })
            for change in plan.changes:
                self._atomic_replace(change.path, change.after_bytes)
                if _mingge_hash_file(change.path) != change.after_hash:
                    raise MingGeError(f"写入后哈希不符: {change.path}")
            receipt_payload = {
                "schema_version": 1,
                "operation": "mingge-system",
                "transaction_id": transaction_id,
                "created_at": datetime.now().astimezone().isoformat(),
                "status": "installed-pending-game-verification",
                "server": str(plan.server),
                "client": str(plan.client),
                "workbook": str(plan.workbook),
                "workbook_hash": plan.workbook_hash,
                "resource_index": plan.resource_index,
                "custom_text_base": plan.custom_text_base,
                "resource_name": plan.resource_name,
                "warnings": list(plan.warnings),
                "files": entries,
            }
            _atomic_mingge_write(
                receipt_path,
                (json.dumps(receipt_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
        except BaseException:
            for change, entry in reversed(list(zip(plan.changes, entries))):
                if bool(entry["existed_before"]):
                    _atomic_mingge_write(change.path, Path(str(entry["backup"])).read_bytes())
                elif change.path.exists():
                    change.path.unlink()
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            raise
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
        return MingGeReceipt(
            transaction_id,
            receipt_path,
            "installed-pending-game-verification",
            tuple(change.path for change in plan.changes),
        )

    def rollback(self, server: Path, transaction_id: str) -> str:
        receipt_path = self.platform_root / "backups/mingge-system" / transaction_id / "receipt.json"
        if not receipt_path.is_file():
            raise MingGeError(f"命格事务收据不存在: {transaction_id}")
        rollback_path = receipt_path.with_name("rollback.json")
        if rollback_path.exists():
            raise MingGeError(f"命格事务已有回滚证据: {transaction_id}")
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        if payload.get("operation") != "mingge-system":
            raise MingGeError("收据不属于命格系统")
        if Path(str(payload.get("server", ""))).resolve() != Path(server).resolve():
            raise MingGeError("回滚目标服务端与收据不一致")
        if payload.get("status") != "installed-pending-game-verification":
            raise MingGeError("命格事务状态不允许回滚")
        entries = payload.get("files")
        if not isinstance(entries, list):
            raise MingGeError("命格事务收据文件列表无效")
        installed: dict[Path, bytes] = {}
        for entry in entries:
            path = Path(str(entry["path"]))
            current_hash = _mingge_hash_file(path)
            if current_hash != entry["after_hash"]:
                raise MingGeError(f"安装后文件已被修改，禁止盲目回滚: {path}")
            installed[path] = path.read_bytes()
        try:
            for entry in reversed(entries):
                path = Path(str(entry["path"]))
                if entry["existed_before"]:
                    backup = Path(str(entry["backup"]))
                    _atomic_mingge_write(path, backup.read_bytes())
                    if _mingge_hash_file(path) != entry["before_hash"]:
                        raise MingGeError(f"回滚后哈希不符: {path}")
                elif path.exists():
                    path.unlink()
        except BaseException:
            for path, data in installed.items():
                _atomic_mingge_write(path, data)
            raise
        rollback_payload = {
            "schema_version": 1,
            "operation": "mingge-system-rollback",
            "transaction_id": transaction_id,
            "status": "rolled-back",
            "rolled_back_at": datetime.now().astimezone().isoformat(),
            "receipt": str(receipt_path),
            "receipt_hash": _mingge_hash_file(receipt_path),
        }
        _atomic_mingge_write(
            rollback_path,
            (json.dumps(rollback_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        return "rolled-back"
