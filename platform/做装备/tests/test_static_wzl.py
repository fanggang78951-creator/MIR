import struct
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))
from xyequip.equipment_graphics.static_wzl import FRAME_HEADER, build_static_pair  # noqa: E402


def make_pair(folder: Path):
    header = bytearray(48)
    struct.pack_into("<I", header, 44, 3)
    records = []
    for marker in (11, 22, 33):
        records.append(FRAME_HEADER.pack(6, 0, 1, 1, marker, -marker, 0, 0) + bytes((marker, marker, marker)))
    offsets = []
    cursor = len(header)
    for record in records:
        offsets.append(cursor)
        cursor += len(record)
    wzl = bytes(header) + b"".join(records)
    wzx = bytes(header)[:44] + struct.pack("<I", 3) + b"".join(struct.pack("<I", value) for value in offsets)
    wzl_path, wzx_path = folder / "old.wzl", folder / "old.wzx"
    wzl_path.write_bytes(wzl)
    wzx_path.write_bytes(wzx)
    return wzl_path, wzx_path, wzl, wzx


class StaticWzlPortableTests(unittest.TestCase):
    def test_bottom_up_coordinates_sparse_and_repeat_noop(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            wzl, wzx, old_wzl, old_wzx = make_pair(folder)
            image = folder / "source.png"
            image_data = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
            image_data.putpixel((0, 0), (255, 0, 0, 255))  # top red
            image_data.putpixel((1, 1), (0, 0, 255, 255))  # bottom blue
            image_data.save(image)
            out_wzl, out_wzx = folder / "new.wzl", folder / "new.wzx"
            replacement = [{"index": 1, "image": image, "placement": (-7, 9), "alpha_cutoff": 128}]
            first = build_static_pair(wzl, wzx, replacement, out_wzl, out_wzx)
            self.assertEqual(first["changed_slots"], [1])
            self.assertTrue(first["old_wzl_prefix_byte_identical"])
            new_wzl, new_wzx = out_wzl.read_bytes(), out_wzx.read_bytes()
            self.assertEqual(new_wzl[: len(old_wzl)], old_wzl)
            self.assertEqual(new_wzx[48:52], old_wzx[48:52])
            self.assertEqual(new_wzx[56:60], old_wzx[56:60])
            target = struct.unpack_from("<I", new_wzx, 52)[0]
            kind, _, width, height, x, y, _, _ = FRAME_HEADER.unpack_from(new_wzl, target)
            self.assertEqual((kind, width, height, x, y), (6, 2, 2, -7, 9))
            # Bottom-up starts with bottom-left transparent, then bottom-right blue BGR.
            self.assertEqual(new_wzl[target + FRAME_HEADER.size: target + FRAME_HEADER.size + 6], bytes((0, 0, 0, 255, 0, 0)))
            # The top-left red pixel follows after the bottom row.
            self.assertEqual(new_wzl[target + FRAME_HEADER.size + 6: target + FRAME_HEADER.size + 9], bytes((0, 0, 255)))
            second = build_static_pair(out_wzl, out_wzx, replacement, out_wzl, out_wzx)
            self.assertEqual(second["changed_slots"], [])
            self.assertEqual(second["noop_slots"], [1])
            self.assertEqual(second["before"], second["after"])


if __name__ == "__main__":
    unittest.main()
