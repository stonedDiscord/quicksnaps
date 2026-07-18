import json
import tempfile
import unittest
from pathlib import Path

from quicksnaps.site import build_site


class SiteComparisonTests(unittest.TestCase):
    def make_site(self, changed: bool) -> tuple[str, str]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        for variant in ("previous", "current"):
            directory = output / "machines" / "game" / variant
            directory.mkdir(parents=True)
            (directory / "before.png").write_bytes(b"same")
            (directory / "after.png").write_bytes(b"current" if changed and variant == "current" else b"same")
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


if __name__ == "__main__":
    unittest.main()

