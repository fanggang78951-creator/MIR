from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TextDocument:
    text: str
    encoding: str
    newline: str
    bom: bytes = b""


def read_text_document(path: Path) -> TextDocument:
    raw = Path(path).read_bytes()
    bom = b""
    if raw.startswith(b"\xef\xbb\xbf"):
        bom, body, encoding = b"\xef\xbb\xbf", raw[3:], "utf-8"
        text = body.decode(encoding)
    else:
        for encoding in ("utf-8", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise UnicodeError(f"无法识别文本编码: {path}")
    newline = "\r\n" if "\r\n" in text else "\n"
    return TextDocument(text=text, encoding=encoding, newline=newline, bom=bom)


def encode_text_document(document: TextDocument, text: str | None = None) -> bytes:
    value = document.text if text is None else text
    return document.bom + value.encode(document.encoding)


def write_text_document(path: Path, document: TextDocument, text: str | None = None) -> None:
    Path(path).write_bytes(encode_text_document(document, text))
