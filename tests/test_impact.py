import unittest

from quicksnaps.config import Config, ImpactRule, Machine
from quicksnaps.impact import resolve


def machine(name: str) -> Machine:
    return Machine(name, 1, 1, 0.1, "P1 Button 1")


class ResolveTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
