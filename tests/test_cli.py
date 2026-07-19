import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quicksnaps.cli import _capture_request, _prune_nonrunnable, cmd_capture
from quicksnaps.config import Config, Defaults, Machine


class CaptureExitTests(unittest.TestCase):
    @patch("quicksnaps.cli.build_site")
    @patch("quicksnaps.cli._resolve_selection")
    @patch("quicksnaps.cli.load_config")
    def test_matching_checkpoint_skips_capture(self, load_config, selection, build_site):
        machine = Machine("pacman", 1, 1, 0.1, "P1 Button 1")
        load_config.return_value = Config((machine,), defaults=Defaults())
        selection.return_value = ({"pacman": ["driver changed"]}, ["driver.cpp"])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            directory = output / "machines" / "pacman" / "current"
            directory.mkdir(parents=True)
            (directory / "mame.log").write_text("done")
            (directory / "before.png").write_bytes(b"png")
            (directory / "after.png").write_bytes(b"png")
            request = _capture_request(machine, "sha", "artifact", "current", None, None)
            result = {
                "name": "pacman", "status": "passed", "button": "P1 Button 1",
                "revision": "sha", "captures": {"current": {"status": "passed"}},
            }
            (directory / "capture.json").write_text(json.dumps({"request": request, "result": result}))
            args = argparse.Namespace(
                config=Path("config.json"), output=output, base=None, head=None,
                mame=Path("mame"), mame_repo=Path("repo"), rompath=None, timeout=None,
                variant="current", capture_revision="sha", artifact="artifact", title="test",
                allow_failures=True, selection_file=Path("selection.json"), catalog=True,
                jobs=2, force=False,
            )
            with patch("quicksnaps.cli.capture_machine") as capture:
                self.assertEqual(0, cmd_capture(args))
                capture.assert_not_called()

    def test_prunes_nonrunnable_manifest_entry_and_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            stale = output / "machines" / "device_type"
            stale.mkdir(parents=True)
            (stale / "mame.log").write_text("old")
            (output / "manifest.json").write_text(
                '{"machines":[{"name":"realgame"},{"name":"device_type"}]}\n'
            )
            _prune_nonrunnable(output, {"realgame"})
            self.assertFalse(stale.exists())
            self.assertNotIn("device_type", (output / "manifest.json").read_text())

    @patch("quicksnaps.cli.build_site")
    @patch("quicksnaps.cli.write_manifest")
    @patch("quicksnaps.cli.capture_machine")
    @patch("quicksnaps.cli._resolve_selection")
    @patch("quicksnaps.cli.load_config")
    def test_allow_failures_records_failure_but_returns_success(
        self, load_config, selection, capture, write_manifest, build_site
    ):
        machine = Machine("broken", 1, 1, 0.1, "P1 Button 1")
        load_config.return_value = Config((machine,), defaults=Defaults())
        selection.return_value = ({"broken": ["driver changed"]}, ["driver.cpp"])
        capture.return_value = {"name": "broken", "status": "failed", "button": machine.button}
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(
                config=Path("config.json"), output=Path(temporary), base=None, head=None,
                mame=Path("mame"), mame_repo=Path("repo"), rompath=None, timeout=None,
                variant="current", capture_revision="sha", artifact="artifact", title="test",
                allow_failures=True, selection_file=Path("selection.json"), catalog=True,
                jobs=2,
            )
            self.assertEqual(0, cmd_capture(args))


if __name__ == "__main__":
    unittest.main()
