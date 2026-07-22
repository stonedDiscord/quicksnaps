import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from quicksnaps.config import Machine
from quicksnaps.runner import (
    _failure_from_log,
    capture_machine,
    load_capture_checkpoint,
    normalize_png,
    write_capture_checkpoint,
    write_manifest,
)


class ManifestTests(unittest.TestCase):
    @patch("quicksnaps.runner.subprocess.run")
    def test_capture_configures_layout_snapshot_view(self, run):
        run.return_value.returncode = 1
        run.return_value.stdout = "capture stopped"
        machine = Machine("disc2000", 0, 0, 0, "Start", rtc_time="20150708123456")
        with tempfile.TemporaryDirectory() as temporary:
            capture_machine(Path("mame"), machine, Path(temporary))
        command = run.call_args.args[0]
        self.assertEqual("auto", command[command.index("-snapview") + 1])
        self.assertEqual(machine.rtc_time, command[command.index("-rtc") + 1])

    def test_lua_uses_layout_snapshot_for_screenless_machines(self):
        script = Path(__file__).parents[1] / "src" / "quicksnaps" / "capture.lua"
        source = script.read_text()
        self.assertIn('view.unqualified_name == "None"', source)
        self.assertIn("machine has no emulated screen or artwork layout", source)
        self.assertIn("manager.machine.options.entries.snapname:value(filename)", source)
        self.assertIn("manager.machine.video:snapshot()", source)

    def test_capture_checkpoint_requires_matching_request_and_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            directory = output / "machines" / "pacman" / "current"
            directory.mkdir(parents=True)
            (directory / "mame.log").write_text("done")
            (directory / "before.png").write_bytes(b"png")
            (directory / "after.png").write_bytes(b"png")
            request = {"revision": "abc", "variant": "current"}
            result = {
                "name": "pacman",
                "captures": {"current": {"status": "passed"}},
            }
            write_capture_checkpoint(output, "pacman", "current", request, result)
            self.assertEqual(
                result, load_capture_checkpoint(output, "pacman", "current", request)
            )
            self.assertIsNone(
                load_capture_checkpoint(output, "pacman", "current", {"revision": "new"})
            )
            (directory / "after.png").unlink()
            self.assertIsNone(load_capture_checkpoint(output, "pacman", "current", request))

    def test_png_normalization_removes_metadata_but_preserves_pixels(self):
        def chunk(kind: bytes, payload: bytes) -> bytes:
            crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shot.png"
            header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
            pixels = zlib.compress(b"\0\0\0\0\xff")
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                + chunk(b"tEXt", b"Software\0MAME old")
                + chunk(b"pHYs", struct.pack(">IIB", 1, 1, 0))
                + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
            )
            normalize_png(path)
            normalized = path.read_bytes()
            self.assertNotIn(b"tEXt", normalized)
            self.assertNotIn(b"MAME old", normalized)
            self.assertIn(b"pHYs", normalized)
            self.assertIn(pixels, normalized)

    def test_failure_summary_prefers_quicksnaps_diagnostic(self):
        log = "noise\n[quicksnaps] input field not found: 1 Player Start\n"
        self.assertEqual("input field not found: 1 Player Start", _failure_from_log(log, "failed"))

    def test_failure_summary_uses_last_mame_error(self):
        log = "Warning: -video none\nRequired ROM images are missing\n"
        self.assertEqual("Required ROM images are missing", _failure_from_log(log, "failed"))

    def test_pair_captures_merge_without_removing_existing_machines(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_manifest(
                output,
                [{"name": "pacman", "status": "passed", "captures": {"previous": {"revision": "old"}}}],
                {"head": "old"},
            )
            write_manifest(
                output,
                [{"name": "pacman", "status": "passed", "captures": {"current": {"revision": "new"}}},
                 {"name": "galaga", "status": "passed", "captures": {"current": {"revision": "new"}}}],
                {"head": "new"},
                merge_existing=True,
            )
            manifest = json.loads((output / "manifest.json").read_text())
            machines = {item["name"]: item for item in manifest["machines"]}
            self.assertEqual({"previous", "current"}, set(machines["pacman"]["captures"]))
            self.assertIn("galaga", machines)


if __name__ == "__main__":
    unittest.main()
