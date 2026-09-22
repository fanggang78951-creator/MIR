"""命格短标签 PNG 的确定性本地渲染器。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .mingge import QUALITIES, MingGeAffix, MingGeQualityStyle, MingGeWorkbook


QUALITY_COLORS = {
    "绿": ((58, 220, 78),),
    "橙": ((255, 145, 35),),
    "红": ((245, 48, 48),),
    "彩": ((255, 73, 188), (127, 91, 255), (46, 194, 255), (72, 232, 146), (255, 216, 74)),
}
FONT_FILES = {
    "microsoft yahei": (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
    ),
}
BLACK = (0, 0, 0)
MAX_CANVAS_WIDTH = 512


class MingGeImageError(ValueError):
    """命格标签图片无法按表格样式安全渲染。"""


@dataclass(frozen=True)
class MingGeLabelFrame:
    line_no: int
    frame_id: int
    png_path: Path
    label: str
    hover_text: str
    sha256: str


def _color(value: str, label: str) -> tuple[int, int, int]:
    try:
        color = ImageColor.getrgb(value)
    except (TypeError, ValueError) as exc:
        raise MingGeImageError(f"{label}颜色非法: {value}") from exc
    if len(color) != 3:
        raise MingGeImageError(f"{label}颜色必须为RGB: {value}")
    return color


def _font(style: MingGeQualityStyle) -> ImageFont.FreeTypeFont:
    mapped = FONT_FILES.get(style.font_name.casefold())
    candidate = Path(style.font_name)
    if mapped is not None:
        candidate = mapped[1 if style.bold else 0]
    if not candidate.is_file():
        raise MingGeImageError(f"字体不存在: {style.font_name}")
    try:
        return ImageFont.truetype(str(candidate), style.font_size)
    except OSError as exc:
        raise MingGeImageError(f"字体无法加载: {candidate}") from exc


def _style_colors(style: MingGeQualityStyle) -> tuple[tuple[int, int, int], ...]:
    colors = tuple(_color(value, style.quality) for value in style.colors)
    if style.quality == "彩":
        if len(colors) < 2:
            raise MingGeImageError("彩色样式至少需要两段渐变色")
    elif len(colors) != 1:
        raise MingGeImageError(f"{style.quality}色样式必须恰好有一个主色")
    if style.outline_width != 1:
        raise MingGeImageError("描边宽度必须为1像素")
    return colors


def _gradient(colors: tuple[tuple[int, int, int], ...], width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), BLACK)
    pixels = image.load()
    span = max(width - 1, 1)
    sections = len(colors) - 1
    for x in range(width):
        position = x * sections / span
        left = min(int(position), sections - 1)
        fraction = position - left
        start, end = colors[left], colors[left + 1]
        color = tuple(round(start[index] + (end[index] - start[index]) * fraction) for index in range(3))
        for y in range(height):
            pixels[x, y] = color
    return image


def _render_label(label: str, style: MingGeQualityStyle) -> Image.Image:
    font = _font(style)
    colors = _style_colors(style)
    outline = _color(style.outline_color, "描边")
    if style.horizontal_padding < 0:
        raise MingGeImageError("左右留白必须为非负整数")
    bbox = font.getbbox(label, stroke_width=style.outline_width)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    width = text_width + style.horizontal_padding * 2
    if width <= 0 or width > MAX_CANVAS_WIDTH:
        raise MingGeImageError(f"文字宽度或左右留白超出画布: {width}")
    if style.canvas_height < text_height:
        raise MingGeImageError(
            f"画布高度不足以容纳文字: {style.canvas_height} < {text_height}"
        )
    x = style.horizontal_padding - bbox[0]
    y = (style.canvas_height - text_height) // 2 - bbox[1]
    outline_bounds = (x + bbox[0], y + bbox[1], x + bbox[2], y + bbox[3])
    if (
        outline_bounds[0] < 0
        or outline_bounds[1] < 0
        or outline_bounds[2] > width
        or outline_bounds[3] > style.canvas_height
    ):
        raise MingGeImageError("含描边文字边界超出画布")
    text_mask = Image.new("L", (width, style.canvas_height), 0)
    outline_mask = Image.new("L", (width, style.canvas_height), 0)
    ImageDraw.Draw(text_mask).text((x, y), label, font=font, fill=255)
    ImageDraw.Draw(outline_mask).text(
        (x, y), label, font=font, fill=255, stroke_width=style.outline_width
    )
    image = Image.new("RGB", (width, style.canvas_height), BLACK)
    image.paste(outline, mask=outline_mask)
    fill = _gradient(colors, width, style.canvas_height) if style.quality == "彩" else colors[0]
    image.paste(fill, mask=text_mask)
    return image


def _attribute_rows(book: MingGeWorkbook, affix: MingGeAffix, quality: str) -> tuple:
    return tuple(
        sorted(
            (
                attribute
                for attribute in book.attributes
                if attribute.affix_id.casefold() == affix.affix_id.casefold()
                and attribute.quality == quality
            ),
            key=lambda attribute: attribute.order,
        )
    )


def _frames(book: MingGeWorkbook) -> Iterable[tuple[str, MingGeQualityStyle, str]]:
    styles = {style.quality: style for style in book.styles}
    affixes = tuple(sorted((affix for affix in book.affixes if affix.enabled), key=lambda item: item.order))
    for quality in QUALITIES:
        style = styles.get(quality)
        if style is None:
            raise MingGeImageError(f"缺少{quality}色样式")
        for affix in affixes:
            attributes = _attribute_rows(book, affix, quality)
            if attributes:
                yield f"{affix.name}·{quality}", style, "\n".join(
                    attribute.hover_text for attribute in attributes
                )


def render_mingge_labels(
    book: MingGeWorkbook, output_dir: Path
) -> tuple[MingGeLabelFrame, ...]:
    """把当前工作簿中的有效词条品质组合渲染为黑底 RGB PNG。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for frame_id, (label, style, hover_text) in enumerate(_frames(book)):
        png_path = output_dir / f"{frame_id:03}.png"
        _render_label(label, style).save(
            png_path, format="PNG", optimize=False, compress_level=9
        )
        frames.append(
            MingGeLabelFrame(
                line_no=frame_id + 1,
                frame_id=frame_id,
                png_path=png_path,
                label=label,
                hover_text=hover_text,
                sha256=sha256(png_path.read_bytes()).hexdigest(),
            )
        )
    return tuple(frames)
