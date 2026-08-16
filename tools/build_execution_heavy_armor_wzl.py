from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path


ACTION_BLOCKS = (
    (0, 192, 8),
    (192, 200, 1),
    (200, 456, 8),
    (456, 472, 2),
    (472, 600, 8),
)


def direction_for_frame(index: int) -> int:
    for start, end, stride in ACTION_BLOCKS:
        if start <= index < end:
            return ((index - start) // stride) % 8
    raise ValueError(f"frame outside one-body 600-frame range: {index}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def provider_request(provider: Path, command: str, arguments: dict[str, object], allowed_root: Path) -> dict[str, object]:
    request = {
        "schemaVersion": 1,
        "requestId": str(uuid.uuid4()),
        "command": command,
        "arguments": arguments,
        "policy": {"allowedWriteRoots": [str(allowed_root)]},
    }
    completed = subprocess.run(
        [str(provider), "run", "--request", "-"],
        input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))
    response = json.loads(completed.stdout.decode("utf-8"))
    if not response.get("ok"):
        raise RuntimeError(json.dumps(response.get("error"), ensure_ascii=False))
    return response["data"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the 600-frame independent LFM2 execution kneeling dress library.")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--sprites", required=True)
    parser.add_argument("--template-wzl", required=True)
    parser.add_argument("--template-wzx", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-name", default="XYExecKneel")
    args = parser.parse_args()

    provider = Path(args.provider)
    sprites_root = Path(args.sprites)
    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)

    metadata = json.loads((sprites_root / "cells.json").read_text(encoding="utf-8"))
    directions = {int(item["direction"]): item for item in metadata["directions"]}
    if set(directions) != set(range(8)):
        raise ValueError("eight-direction sprite metadata is incomplete")

    # Copy the template into the ASCII-only staging directory so the provider's
    # stdin protocol is not affected by the Windows console code page.
    template_root = output_root / "template"
    template_root.mkdir(exist_ok=True)
    template_wzl = template_root / "template.wzl"
    template_wzx = template_root / "template.wzx"
    shutil.copy2(args.template_wzl, template_wzl)
    shutil.copy2(args.template_wzx, template_wzx)

    output_wzl = output_root / f"{args.base_name}.wzl"
    output_wzx = output_root / f"{args.base_name}.wzx"
    images: list[dict[str, object]] = []
    for frame in range(600):
        direction = direction_for_frame(frame)
        item = directions[direction]
        images.append({
            "path": str(sprites_root / item["file"]),
            "sourceId": frame,
            "x": int(item["offset_x"]),
            "y": int(item["offset_y"]),
        })

    build = provider_request(provider, "build-image-library", {
        "templateWzl": str(template_wzl),
        "templateWzx": str(template_wzx),
        "outputWzl": str(output_wzl),
        "outputWzx": str(output_wzx),
        "images": images,
    }, output_root)
    inspect = provider_request(provider, "inspect", {
        "wzl": str(output_wzl),
        "wzx": str(output_wzx),
        "selection": {"ranges": [{"start": 0, "end": 599}]},
    }, output_root)

    entries = inspect["entries"]
    if len(entries) != 600 or any(entry["empty"] or entry["frame_type"] != 6 for entry in entries):
        raise RuntimeError("provider read-back did not return 600 non-empty type-6 frames")
    for entry in entries:
        frame = int(entry["image_id"])
        item = directions[direction_for_frame(frame)]
        expected_size = item["size"]
        expected = (int(expected_size[0]), int(expected_size[1]), int(item["offset_x"]), int(item["offset_y"]))
        actual = (int(entry["width"]), int(entry["height"]), int(entry["x"]), int(entry["y"]))
        if actual != expected:
            raise RuntimeError(f"frame {frame} geometry mismatch: expected={expected}, actual={actual}")

    receipt = {
        "schema": "xy-execution-heavy-armor-wzl/1",
        "status": "candidate-static-readback-passed",
        "frame_count": 600,
        "body_shape_id": 306,
        "library": args.base_name,
        "action_blocks": [list(item) for item in ACTION_BLOCKS],
        "build": build,
        "output": {
            "wzl": str(output_wzl),
            "wzx": str(output_wzx),
            "wzl_sha256": sha256(output_wzl),
            "wzx_sha256": sha256(output_wzx),
        },
    }
    (output_root / "build_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
