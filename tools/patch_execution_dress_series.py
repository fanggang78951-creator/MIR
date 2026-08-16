from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind execution Shape 306 to its independent series library.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = args.source.read_bytes()
    text = raw.decode("gb18030")
    parsed = json.loads(text)
    entry = parsed.get("306")
    if not isinstance(entry, dict):
        raise ValueError("dress Shape 306 is missing")
    if entry.get("WhichLib") != "XYExecKneel" or int(entry.get("OffSet", -1)) != 0:
        raise ValueError(f"unexpected normal render mapping: {entry!r}")
    if entry.get("WhichSeriesLib") not in ("cbohum", "XYExecKneelS"):
        raise ValueError(f"unexpected series render mapping: {entry!r}")
    if int(entry.get("SeriesOffSet", -1)) != 0:
        raise ValueError(f"unexpected series offset: {entry!r}")

    old = '"SeriesOffSet":0,"WhichSeriesLib":"cbohum"'
    new = '"SeriesOffSet":0,"WhichSeriesLib":"XYExecKneelS"'
    if old in text:
        if text.count(old) != 1:
            raise ValueError("series mapping is not unique")
        text = text.replace(old, new, 1)
    elif new not in text:
        raise ValueError("Shape 306 series mapping cannot be located safely")

    readback = json.loads(text)["306"]
    if readback["WhichLib"] != "XYExecKneel" or readback["WhichSeriesLib"] != "XYExecKneelS":
        raise RuntimeError("dress read-back validation failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(text.encode("gb18030"))
    print(json.dumps(readback, ensure_ascii=False))


if __name__ == "__main__":
    main()
