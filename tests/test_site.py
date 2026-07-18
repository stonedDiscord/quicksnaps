import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from quicksnaps.site import build_site


class SiteComparisonTests(unittest.TestCase):
    @staticmethod
    def png(pixel: bytes, comment: bytes) -> bytes:
        def chunk(kind: bytes, payload: bytes) -> bytes:
            crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

        header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"tEXt", comment) + chunk(b"IDAT", zlib.compress(b"\x00" + pixel)) + chunk(b"IEND", b"")

    def make_site(self, changed: bool, metadata_changed: bool = False) -> tuple[str, str]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        for variant in ("previous", "current"):
            directory = output / "machines" / "game" / variant
            directory.mkdir(parents=True)
            comment = variant.encode() if metadata_changed else b"same metadata"
            (directory / "before.png").write_bytes(self.png(b"\0\0\0\xff", comment))
            pixel = b"\xff\0\0\xff" if changed and variant == "current" else b"\0\0\0\xff"
            (directory / "after.png").write_bytes(self.png(pixel, comment))
            (directory / "mame.log").write_text("")
        capture = {"status": "passed", "revision": "sha", "button": "1 Player Start"}
        manifest = {
            "generated_at": "now", "head": "sha", "reasons": {"game": ["driver changed"]},
            "machines": [{"name": "game", "status": "passed", "captures": {
                "previous": capture, "current": capture,
            }}],
        }
        (output / "manifest.json").write_text(json.dumps(manifest))
        build_site(output)
        return (output / "index.html").read_text(), (output / "machines/game/index.html").read_text()

    def test_unchanged_pair_is_collapsed_on_index(self):
        index, details = self.make_site(changed=False)
        self.assertIn("No screenshot change detected", index)
        self.assertNotIn("previous/before.png", index)
        self.assertIn("previous/before.png", details)
        self.assertIn("current/after.png", details)

    def test_changed_pair_shows_images_on_index(self):
        index, _ = self.make_site(changed=True)
        self.assertNotIn("No screenshot change detected", index)
        self.assertIn("previous/before.png", index)
        self.assertIn("current/after.png", index)

    def test_png_metadata_difference_is_not_visual_change(self):
        index, details = self.make_site(changed=False, metadata_changed=True)
        self.assertIn("No screenshot change detected", index)
        self.assertNotIn("previous/before.png", index)
        self.assertIn("previous/before.png", details)

    def test_skipped_input_has_honest_caption(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        directory = output / "machines" / "game" / "current"
        directory.mkdir(parents=True)
        for filename in ("before.png", "after.png"):
            (directory / filename).write_bytes(self.png(b"\0\0\0\xff", b"metadata"))
        (directory / "mame.log").write_text("[quicksnaps] input skipped")
        manifest = {
            "generated_at": "now", "head": "sha", "machines": [{
                "name": "game", "status": "passed", "captures": {"current": {
                    "status": "passed", "revision": "sha", "button": "1 Player Start",
                    "button_applied": False,
                }},
            }],
        }
        (output / "manifest.json").write_text(json.dumps(manifest))
        build_site(output)
        self.assertIn("unavailable; no input pressed", (output / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
