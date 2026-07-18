import json
import tempfile
import unittest
from pathlib import Path

from quicksnaps.runner import write_manifest


class ManifestTests(unittest.TestCase):
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

