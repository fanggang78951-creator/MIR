from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .encoding import TextDocument, encode_text_document, read_text_document
from .equipment_collection import QFUNCTION, USERCMD
from .installer import InstallPlan, InstallReceipt, Installer, PlannedChange
from .repository import PackageRepository
from .target import TargetInspector, is_executable_running
from .textpatch import TextPatchError, add_unique_line, install_managed_block, scan_labels


PACKAGE_ID = "xy.optional.equipment-collection.test-reset"
PACKAGE_VERSION = "1.0.0-test.1"
COMMAND = "清空收集测试"
USERCMD_NUMBER = 93
RESET_FLAGS = (400, 401, 402, 600)


class EquipmentCollectionTestResetError(ValueError):
    pass


@dataclass
class EquipmentCollectionTestResetPlan:
    server: str
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[PlannedChange] = field(default_factory=list)
    install_plan: InstallPlan | None = None


def _change(root: Path, relative: str, after: bytes, operation: str) -> PlannedChange:
    path = root / Path(relative.replace("/", "\\"))
    before = path.read_bytes() if path.exists() else None
    return PlannedChange(relative, before, after, operation, PACKAGE_ID)


def _command_conflict(text: str) -> str | None:
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        try:
            number = int(fields[1].strip())
        except ValueError:
            continue
        if number == USERCMD_NUMBER and fields[0].strip() != COMMAND:
            return fields[0].strip()
    return None


def _reset_block() -> str:
    lines = [
        "[@UserCmd93]",
        "#IF",
        "#ACT",
        "GOTO @XY_COLLECTION_TEST_RESET",
        "BREAK",
        "",
        "[@XY_COLLECTION_TEST_RESET]",
        "#IF",
        "#ACT",
    ]
    lines.extend(f"SET [{flag}] 0" for flag in RESET_FLAGS)
    lines.extend([
        "SENDMSG 6 [装备收集测试] 新手武器收藏状态已清空，请重新准备木剑、铁剑、青铜剑。",
        "GOTO @XY_COLLECTION_REFRESH",
        "BREAK",
    ])
    return "\n".join(lines)


class EquipmentCollectionTestResetService:
    def __init__(self, platform_root: Path):
        self.root = Path(platform_root).resolve()
        repository = PackageRepository(self.root / "packages")
        repository.refresh()
        self.installer = Installer(repository, self.root / "backups")

    def preflight(self, server: Path) -> EquipmentCollectionTestResetPlan:
        plan = EquipmentCollectionTestResetPlan(str(Path(server).absolute()))
        try:
            target = TargetInspector.inspect(Path(server))
            qfunction_path = target.root / Path(QFUNCTION.replace("/", "\\"))
            usercmd_path = target.root / Path(USERCMD.replace("/", "\\"))
            for path in (qfunction_path, usercmd_path):
                if not path.is_file():
                    raise EquipmentCollectionTestResetError(f"目标脚本不存在：{path}")

            qfunction_doc = read_text_document(qfunction_path)
            usercmd_doc = read_text_document(usercmd_path)
            refresh_count = len(scan_labels(qfunction_doc.text).labels.get("xy_collection_refresh", []))
            if refresh_count != 1:
                raise EquipmentCollectionTestResetError(
                    "测试重置要求已安装且唯一存在@XY_COLLECTION_REFRESH"
                )
            conflict = _command_conflict(usercmd_doc.text)
            if conflict:
                raise EquipmentCollectionTestResetError(
                    f"UserCmd编号{USERCMD_NUMBER}已被“{conflict}”占用"
                )

            qfunction_text = install_managed_block(
                qfunction_doc.text,
                PACKAGE_ID,
                _reset_block(),
                qfunction_doc.newline,
            ).text
            usercmd_text = add_unique_line(
                usercmd_doc.text,
                f"{COMMAND}\t{USERCMD_NUMBER}",
                [0],
                usercmd_doc.newline,
            ).text
            labels = scan_labels(qfunction_text)
            if labels.duplicates:
                raise EquipmentCollectionTestResetError(
                    f"生成后的QFunction存在重复标签：{labels.duplicates}"
                )

            changes = [
                _change(
                    target.root,
                    QFUNCTION,
                    encode_text_document(TextDocument(
                        qfunction_text,
                        qfunction_doc.encoding,
                        qfunction_doc.newline,
                        qfunction_doc.bom,
                    )),
                    "equipment-collection-test-reset-qfunction",
                ),
                _change(
                    target.root,
                    USERCMD,
                    encode_text_document(TextDocument(
                        usercmd_text,
                        usercmd_doc.encoding,
                        usercmd_doc.newline,
                        usercmd_doc.bom,
                    )),
                    "equipment-collection-test-reset-usercmd",
                ),
            ]
            plan.changes = [change for change in changes if change.before != change.after]
            plan.warnings.append("此命令只清除当前角色的收集状态，不返还已经消耗的装备。")
            plan.warnings.append("游戏验收通过后必须回滚本测试事务，删除临时命令和受管块。")
            if is_executable_running(target.mir200 / "M2Server.exe"):
                plan.warnings.append("检测到M2Server.exe正在运行：允许写入，但需由用户自行重载或重启M2。")
            plan.install_plan = InstallPlan(
                target_root=str(target.root),
                client_root=None,
                package_ids=[PACKAGE_ID],
                package_versions={PACKAGE_ID: PACKAGE_VERSION},
                parameters={
                    "command": f"@{COMMAND}",
                    "usercmd_number": USERCMD_NUMBER,
                    "reset_flags": list(RESET_FLAGS),
                },
                changes=plan.changes,
                warnings=list(plan.warnings),
                operation_type="equipment-collection-test-reset",
                candidate_packages=[PACKAGE_ID],
            )
        except (OSError, ValueError, RuntimeError, TextPatchError) as exc:
            plan.blockers.append(str(exc))
        return plan

    def install(self, plan: EquipmentCollectionTestResetPlan) -> InstallReceipt:
        if plan.blockers or plan.install_plan is None:
            raise EquipmentCollectionTestResetError("测试重置被阻止：\n" + "\n".join(plan.blockers))
        if not plan.changes:
            raise EquipmentCollectionTestResetError("测试重置已经安装，无需重复写入")
        return self.installer.install(plan.install_plan)

    def rollback(self, server: Path, transaction_id: str) -> str:
        self.installer.rollback(Path(server), transaction_id)
        return transaction_id
