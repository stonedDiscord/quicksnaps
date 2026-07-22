import json
import tempfile
import unittest
from pathlib import Path

from quicksnaps.config import load_config


class ConfigTests(unittest.TestCase):
    def load(self, data: dict) -> object:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "quicksnaps.json"
            path.write_text(json.dumps(data))
            return load_config(path)

    def test_rtc_time_defaults_to_2010_and_can_be_overridden(self):
        config = self.load({
            "defaults": {"rtc_time": "20120304050607"},
            "machines": ["defaulted", {"name": "custom", "rtc_time": "20140506070809"}],
        })
        self.assertEqual("20120304050607", config.machine("defaulted").rtc_time)
        self.assertEqual("20140506070809", config.machine("custom").rtc_time)

    def test_rtc_time_must_be_a_valid_timestamp(self):
        with self.assertRaisesRegex(ValueError, "YYYYMMDDhhmmss"):
            self.load({"defaults": {"rtc_time": "20100230000000"}, "machines": ["game"]})

    def test_default_rtc_time_is_2010(self):
        config = self.load({"machines": ["game"]})
        self.assertEqual("20100101000000", config.machine("game").rtc_time)


if __name__ == "__main__":
    unittest.main()
