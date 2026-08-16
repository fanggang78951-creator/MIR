from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def alpha_bbox(image: Image.Image, threshold: int = 8) -> tuple[int, int, int, int]:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > threshold else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError("cell contains no visible pixels")
    return bbox


def fit_pixel_art(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    scale = min(max_width / image.width, max_height / image.height)
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    return image.resize((width, height), Image.Resampling.NEAREST)


def checker(size: tuple[int, int], block: int = 8) -> Image.Image:
    width, height = size
    output = Image.new("RGBA", size, (35, 35, 35, 255))
    draw = ImageDraw.Draw(output)
    for y in range(0, height, block):
        for x in range(0, width, block):
            if (x // block + y // block) % 2:
                draw.rectangle((x, y, x + block - 1, y + block - 1), fill=(65, 65, 65, 255))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Split and normalize the generated execution heavy-armor sprite sheet.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-width", type=int, default=76)
    parser.add_argument("--max-height", type=int, default=58)
    args = parser.parse_args()

    source = Image.open(args.input).convert("RGBA")
    if source.width % 4 or source.height % 2:
        raise ValueError(f"expected a 4x2 sheet, got {source.size}")

    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    cell_width = source.width // 4
    cell_height = source.height // 2
    cells: list[dict[str, object]] = []
    normalized: list[Image.Image] = []

    for index in range(8):
        column = index % 4
        row = index // 4
        cell = source.crop((
            column * cell_width,
            row * cell_height,
            (column + 1) * cell_width,
            (row + 1) * cell_height,
        ))
        bbox = alpha_bbox(cell)
        cropped = cell.crop(bbox)
        fitted = fit_pixel_art(cropped, args.max_width, args.max_height)
        path = output_root / f"cell_{index}.png"
        fitted.save(path)
        normalized.append(fitted)
        cells.append({
            "cell": index,
            "source_bbox": list(bbox),
            "source_size": list(cropped.size),
            "output_size": list(fitted.size),
            "file": path.name,
        })

    card_width, card_height = 180, 120
    contact = Image.new("RGBA", (card_width * 4, card_height * 2), (18, 18, 18, 255))
    draw = ImageDraw.Draw(contact)
    for index, sprite in enumerate(normalized):
        left = (index % 4) * card_width
        top = (index // 4) * card_height
        card = checker((card_width, card_height))
        x = (card_width - sprite.width) // 2
        y = card_height - sprite.height - 10
        card.alpha_composite(sprite, (x, y))
        contact.alpha_composite(card, (left, top))
        draw.text((left + 5, top + 5), f"cell {index}", fill=(255, 235, 80, 255))
    contact.save(output_root / "contact_sheet_cells.png")

    # The generated sheet contains clean down/left/up/right-back views, but the
    # remaining AI-produced diagonals are not perfectly consistent. Mirror the
    # verified left-side views to guarantee an exact eight-direction set.
    direction_sources = {
        0: (3, False),  # up
        1: (4, False),  # up-right
        2: (2, True),   # right (mirrored left)
        3: (1, True),   # down-right (mirrored down-left)
        4: (0, False),  # down
        5: (1, False),  # down-left
        6: (2, False),  # left
        7: (4, True),   # up-left (mirrored up-right)
    }
    direction_names = ["up", "up-right", "right", "down-right", "down", "down-left", "left", "up-left"]
    directions: list[dict[str, object]] = []
    direction_images: list[Image.Image] = []
    for direction in range(8):
        cell_index, mirrored = direction_sources[direction]
        sprite = normalized[cell_index]
        if mirrored:
            sprite = ImageOps.mirror(sprite)
        path = output_root / f"dir_{direction}_{direction_names[direction]}.png"
        sprite.save(path)
        direction_images.append(sprite)
        directions.append({
            "direction": direction,
            "name": direction_names[direction],
            "source_cell": cell_index,
            "mirrored": mirrored,
            "size": list(sprite.size),
            "offset_x": round(40 - sprite.width / 2),
            "offset_y": 23 - sprite.height,
            "file": path.name,
        })

    direction_contact = Image.new("RGBA", (card_width * 4, card_height * 2), (18, 18, 18, 255))
    direction_draw = ImageDraw.Draw(direction_contact)
    for direction, sprite in enumerate(direction_images):
        left = (direction % 4) * card_width
        top = (direction // 4) * card_height
        card = checker((card_width, card_height))
        x = (card_width - sprite.width) // 2
        y = card_height - sprite.height - 10
        card.alpha_composite(sprite, (x, y))
        direction_contact.alpha_composite(card, (left, top))
        direction_draw.text((left + 5, top + 5), f"dir {direction} {direction_names[direction]}", fill=(255, 235, 80, 255))
    direction_contact.save(output_root / "contact_sheet_directions.png")

    metadata = {
        "schema": "xy-execution-heavy-armor-sprites/1",
        "source": str(Path(args.input)),
        "sheet_size": list(source.size),
        "grid": [4, 2],
        "target_max": [args.max_width, args.max_height],
        "actor_anchor": {"center_x": 40, "ground_y": 23},
        "cells": cells,
        "directions": directions,
    }
    (output_root / "cells.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
