import json
import tempfile
import unittest
from pathlib import Path

from quicksnaps.runner import _failure_from_log, write_manifest


class ManifestTests(unittest.TestCase):
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
