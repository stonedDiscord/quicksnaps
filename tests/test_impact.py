import unittest

from quicksnaps.config import Config, ImpactRule, Machine
from quicksnaps.impact import resolve, resolve_catalog, runnable_machines
from unittest.mock import patch


def machine(name: str) -> Machine:
    return Machine(name, 1, 1, 0.1, "P1 Button 1")


class ResolveTests(unittest.TestCase):
    @patch("quicksnaps.impact.subprocess.run")
    def test_runnable_catalog_comes_from_driver_list(self, run):
        run.return_value.stdout = "// comment\n@source:shared/mahjong.cpp\nrealgame\n\n"
        self.assertEqual({"realgame"}, runnable_machines(None, "sha"))
    def test_direct_driver_change_selects_only_matching_machine(self):
        config = Config((machine("pacman"), machine("galaga")))
        selected = resolve(
            config,
            ["src/mame/pacman/pacman.cpp"],
            {"pacman": "pacman/pacman.cpp", "galaga": "namco/galaga.cpp"},
        )
        self.assertEqual(["pacman"], list(selected))

    def test_shared_rule_selects_all(self):
        config = Config(
            (machine("pacman"), machine("galaga")),
            (ImpactRule(("src/devices/**",), "all", "shared device"),),
        )
        selected = resolve(config, ["src/devices/cpu/z80/z80.cpp"], {})
        self.assertEqual(["pacman", "galaga"], list(selected))

    def test_driver_header_selects_matching_machine(self):
        config = Config((machine("pacman"), machine("galaga")))
        selected = resolve(
            config,
            ["src/mame/pacman/pacman.h"],
            {"pacman": "pacman/pacman.cpp", "galaga": "namco/galaga.cpp"},
        )
        self.assertEqual(["pacman"], list(selected))

    def test_unknown_change_safely_selects_all(self):
        config = Config((machine("pacman"), machine("galaga")), run_all_on_unmatched=True)
        selected = resolve(config, ["scripts/build/foo.lua"], {})
        self.assertEqual(["pacman", "galaga"], list(selected))

    def test_catalog_uses_full_source_map_not_configured_samples(self):
        selected = resolve_catalog(
            ["src/mame/namco/galaga.cpp"],
            {
                "galaga": "namco/galaga.cpp",
                "galagamw": "namco/galaga.cpp",
                "pacman": "pacman/pacman.cpp",
            },
        )
        self.assertEqual(["galaga", "galagamw"], list(selected))

    def test_catalog_ignores_unmatched_shared_changes(self):
        selected = resolve_catalog(
            ["src/devices/cpu/z80/z80.cpp"],
            {"galaga": "namco/galaga.cpp", "pacman": "pacman/pacman.cpp"},
        )
        self.assertEqual({}, selected)


if __name__ == "__main__":
    unittest.main()
