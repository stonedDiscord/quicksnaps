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
        previous_capture = {"status": "passed", "revision": "oldsha", "button": "1 Player Start"}
        current_capture = {"status": "passed", "revision": "newsha", "button": "1 Player Start"}
        manifest = {
            "generated_at": "now", "head": "newsha", "base": "oldsha",
            "commit_message": "Fix the game video\n\nPreserve details <safely>.",
            "reasons": {"game": ["driver changed: src/mame/test/game.cpp"]},
            "machines": [{"name": "game", "status": "passed", "captures": {
                "previous": previous_capture, "current": current_capture,
            }}],
        }
        (output / "manifest.json").write_text(json.dumps(manifest))
        build_site(output)
        return (output / "index.html").read_text(), (output / "machines/game/index.html").read_text()

    def test_unchanged_pair_is_collapsed_on_index(self):
        index, details = self.make_site(changed=False)
        self.assertIn("No visual changes captured yet", index)
        self.assertNotIn("previous/before.png", index)
        self.assertIn("previous/before.png", details)
        self.assertIn("current/after.png", details)

    def test_changed_pair_shows_images_on_index(self):
        index, details = self.make_site(changed=True)
        self.assertNotIn("No visual changes captured yet", index)
        self.assertIn('class="gallery"', index)
        self.assertIn("previous/after.png", index)
        self.assertIn("current/after.png", index)
        self.assertIn("https://github.com/mamedev/mame/commit/newsha", index)
        self.assertIn("Fix the game video", index)
        self.assertIn("Preserve details &lt;safely&gt;.", index)
        self.assertIn("https://github.com/mamedev/mame/commit/newsha", details)
        self.assertIn("https://github.com/mamedev/mame/blob/newsha/src/mame/test/game.cpp", details)

    def test_png_metadata_difference_is_not_visual_change(self):
        index, details = self.make_site(changed=False, metadata_changed=True)
        self.assertIn("No visual changes captured yet", index)
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
            "generated_at": "now", "head": "sha", "reasons": {"game": ["driver changed"]},
            "machines": [{
                "name": "game", "status": "passed", "captures": {"current": {
                    "status": "passed", "revision": "sha", "button": "1 Player Start",
                    "button_applied": False,
                }},
            }],
        }
        (output / "manifest.json").write_text(json.dumps(manifest))
        build_site(output)
        self.assertIn("unavailable; no input pressed", (directory.parent / "index.html").read_text())

    def test_failure_links_log_without_embedding_it(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        directory = output / "machines" / "game" / "current"
        directory.mkdir(parents=True)
        marker = "VERY-LONG-CONSOLE-OUTPUT" * 1000
        (directory / "mame.log").write_text(marker)
        manifest = {
            "generated_at": "now", "head": "sha", "reasons": {"game": ["driver changed"]},
            "machines": [{
                "name": "game", "status": "failed", "captures": {"current": {
                    "status": "failed", "revision": "sha", "failure_reason": "Missing ROM",
                }},
            }],
        }
        (output / "manifest.json").write_text(json.dumps(manifest))
        build_site(output)
        index = (output / "index.html").read_text()
        details = (directory.parent / "index.html").read_text()
        self.assertNotIn(marker, index)
        self.assertNotIn(marker, details)
        self.assertNotIn("mame.log", index)
        self.assertIn('href="current/mame.log"', details)
        self.assertIn("Failure: Missing ROM", details)

    def test_past_machine_is_only_a_name_link_on_index(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        (output / "machines" / "oldgame").mkdir(parents=True)
        manifest = {
            "generated_at": "now", "head": "sha", "reasons": {},
            "machines": [{"name": "oldgame", "status": "passed", "button": "1 Player Start"}],
        }
        (output / "manifest.json").write_text(json.dumps(manifest))
        build_site(output)
        index = (output / "index.html").read_text()
        self.assertIn('href="machines/oldgame/"', index)
        self.assertIn("<span>oldgame</span>", index)
        self.assertIn('class="game-link"', index)
        self.assertNotIn("Before input", index)
        self.assertNotIn("Captured at", index)

    def test_game_directory_is_alphabetical(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        for name in ("aaa_old", "zzz_current"):
            directory = output / "machines" / name / "current"
            directory.mkdir(parents=True)
            for filename in ("before.png", "after.png"):
                (directory / filename).write_bytes(self.png(b"\0\0\0\xff", b"metadata"))
        manifest = {
            "generated_at": "now", "head": "sha",
            "reasons": {"zzz_current": ["driver changed"]},
            "machines": [
                {"name": "aaa_old", "status": "passed"},
                {"name": "zzz_current", "status": "passed", "captures": {
                    "current": {"status": "passed", "revision": "sha"},
                }},
            ],
        }
        (output / "manifest.json").write_text(json.dumps(manifest))
        build_site(output)
        index = (output / "index.html").read_text()
        game_list = index.index('class="game-list"')
        self.assertLess(
            index.index("aaa_old", game_list), index.index("zzz_current", game_list)
        )

    def test_gallery_is_limited_to_100_most_recent_changes(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        machines = []
        for index in range(102):
            name = f"game{index:03}"
            for variant in ("previous", "current"):
                directory = output / "machines" / name / variant
                directory.mkdir(parents=True)
                pixel = bytes((index % 256, 0, 0, 255))
                if variant == "current":
                    pixel = bytes(((index + 1) % 256, 0, 0, 255))
                (directory / "after.png").write_bytes(self.png(pixel, b"metadata"))
            machines.append({
                "name": name, "status": "passed", "captures": {
                    "previous": {"status": "passed", "revision": "old"},
                    "current": {
                        "status": "passed", "revision": "new",
                        "captured_at": f"2026-01-01T00:00:{index:03}",
                    },
                },
            })
        manifest = {"generated_at": "now", "head": "new", "machines": machines}
        (output / "manifest.json").write_text(json.dumps(manifest))
        build_site(output)
        index_html = (output / "index.html").read_text()
        gallery = index_html[index_html.index('class="gallery"'):index_html.index("</section>")]
        self.assertEqual(100, gallery.count('class="gallery-card"'))
        self.assertNotIn("game000", gallery)
        self.assertNotIn("game001", gallery)
        self.assertIn("game101", gallery)


if __name__ == "__main__":
    unittest.main()
