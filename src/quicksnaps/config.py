from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Defaults:
    warmup_seconds: float = 10.0
    after_seconds: float = 2.0
    press_seconds: float = 0.25
    button: str = "P1 Button 1"
    mame_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class Machine:
    name: str
    warmup_seconds: float
    after_seconds: float
    press_seconds: float
    button: str
    mame_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImpactRule:
    paths: tuple[str, ...]
    machines: tuple[str, ...] | str
    reason: str = "impact rule"


@dataclass(frozen=True)
class Config:
    machines: tuple[Machine, ...]
    impact_rules: tuple[ImpactRule, ...] = ()
    run_all_on_unmatched: bool = True
    defaults: Defaults = field(default_factory=Defaults)

    @property
    def machine_names(self) -> tuple[str, ...]:
        return tuple(machine.name for machine in self.machines)


def _number(data: dict[str, Any], key: str, default: float) -> float:
    value = float(data.get(key, default))
    if value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def load_config(path: Path) -> Config:
    raw = json.loads(path.read_text(encoding="utf-8"))
    default_raw = raw.get("defaults", {})
    defaults = Defaults(
        warmup_seconds=_number(default_raw, "warmup_seconds", 10.0),
        after_seconds=_number(default_raw, "after_seconds", 2.0),
        press_seconds=_number(default_raw, "press_seconds", 0.25),
        button=str(default_raw.get("button", "P1 Button 1")),
        mame_args=tuple(map(str, default_raw.get("mame_args", []))),
    )

    machines: list[Machine] = []
    seen: set[str] = set()
    for item in raw.get("machines", []):
        if isinstance(item, str):
            item = {"name": item}
        name = str(item["name"])
        if not re.fullmatch(r"[a-zA-Z0-9_]+", name):
            raise ValueError(f"invalid MAME machine name: {name!r}")
        if name in seen:
            raise ValueError(f"duplicate machine: {name}")
        seen.add(name)
        machines.append(
            Machine(
                name=name,
                warmup_seconds=_number(item, "warmup_seconds", defaults.warmup_seconds),
                after_seconds=_number(item, "after_seconds", defaults.after_seconds),
                press_seconds=_number(item, "press_seconds", defaults.press_seconds),
                button=str(item.get("button", defaults.button)),
                mame_args=defaults.mame_args + tuple(map(str, item.get("mame_args", []))),
            )
        )
    if not machines:
        raise ValueError("config must contain at least one machine")

    rules: list[ImpactRule] = []
    for item in raw.get("impact_rules", []):
        targets = item.get("machines", "all")
        if targets != "all":
            targets = tuple(map(str, targets))
            unknown = set(targets) - seen
            if unknown:
                raise ValueError(f"impact rule references unknown machines: {sorted(unknown)}")
        rules.append(
            ImpactRule(
                paths=tuple(map(str, item["paths"])),
                machines=targets,
                reason=str(item.get("reason", "impact rule")),
            )
        )

    impact = raw.get("impact", {})
    return Config(
        machines=tuple(machines),
        impact_rules=tuple(rules),
        run_all_on_unmatched=bool(impact.get("run_all_on_unmatched", True)),
        defaults=defaults,
    )
