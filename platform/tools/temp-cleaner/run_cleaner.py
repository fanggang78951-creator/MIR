from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cleaner_core import CleanerError, quarantine, restore, scan, write_scan_report
from cleaner_gui import CleanerApp, load_scan_result


def platform_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="玄渊平台临时文件安全清理器")
    sub = parser.add_subparsers(dest="command")

    scan_cmd = sub.add_parser("scan", help="只读扫描")
    scan_cmd.add_argument("--root", default=str(platform_root()))
    scan_cmd.add_argument("--days", type=int, default=14)
    scan_cmd.add_argument("--output", required=True)

    quarantine_cmd = sub.add_parser("quarantine", help="按扫描报告隔离")
    quarantine_cmd.add_argument("--plan", required=True)
    quarantine_cmd.add_argument("--candidate-id", action="append", required=True)
    quarantine_cmd.add_argument("--yes", action="store_true", required=True)

    restore_cmd = sub.add_parser("restore", help="按收据恢复")
    restore_cmd.add_argument("--receipt", required=True)
    restore_cmd.add_argument("--yes", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.command:
        app = CleanerApp(platform_root())
        app.mainloop()
        return 0
    try:
        if args.command == "scan":
            result = scan(args.root, args.days)
            target = write_scan_report(result, args.output)
            print(json.dumps({"ok": True, "report": str(target), "candidates": len(result.candidates)}, ensure_ascii=False))
            return 0
        if args.command == "quarantine":
            result = load_scan_result(Path(args.plan))
            receipt = quarantine(result, args.candidate_id)
            print(json.dumps({"ok": True, "receipt": str(receipt)}, ensure_ascii=False))
            return 0
        if args.command == "restore":
            restored = restore(args.receipt)
            print(json.dumps({"ok": True, "restored_receipt": str(restored)}, ensure_ascii=False))
            return 0
    except (CleanerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

