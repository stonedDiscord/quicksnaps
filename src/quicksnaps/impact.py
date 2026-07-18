from __future__ import annotations

import fnmatch
import subprocess
from collections import defaultdict
from pathlib import Path

from .config import Config


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", base, head, "--"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [line for line in result.stdout.splitlines() if line]


def source_map(mame: Path, machines: tuple[str, ...] | None = None) -> dict[str, str]:
    requested = machines or ("*",)
    result = subprocess.run(
        [str(mame), "-listsource", *requested],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    mapping: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            mapping[parts[0]] = parts[1].replace("\\", "/")
    missing = set(machines or ()) - mapping.keys()
    if missing:
        raise RuntimeError(f"MAME did not recognize configured machines: {sorted(missing)}")
    return mapping


def resolve(
    config: Config,
    changed: list[str],
    sources: dict[str, str],
    machine_names: tuple[str, ...] | None = None,
) -> dict[str, list[str]]:
    universe = machine_names or config.machine_names
    reasons: dict[str, list[str]] = defaultdict(list)
    matched_files: set[str] = set()

    for path in changed:
        normalized = path.replace("\\", "/")
        for machine, source in sources.items():
            candidates = (source, f"src/mame/{source}")
            same_driver_stem = any(
                normalized.removesuffix(".h") == candidate.removesuffix(".cpp")
                for candidate in candidates
            )
            if normalized in candidates or normalized.endswith(f"/{source}") or same_driver_stem:
                reasons[machine].append(f"driver changed: {path}")
                matched_files.add(path)

        for rule in config.impact_rules:
            if any(fnmatch.fnmatch(normalized, pattern) for pattern in rule.paths):
                targets = universe if rule.machines == "all" else rule.machines
                for machine in targets:
                    reasons[machine].append(f"{rule.reason}: {path}")
                matched_files.add(path)

    unmatched = [path for path in changed if path not in matched_files]
    if unmatched and config.run_all_on_unmatched:
        message = "unmatched change (safe fallback): " + ", ".join(unmatched)
        for machine in universe:
            reasons[machine].append(message)

    return {name: reasons[name] for name in universe if name in reasons}


def resolve_catalog(changed: list[str], sources: dict[str, str]) -> dict[str, list[str]]:
    """Select catalog machines whose owning MAME driver source changed."""
    reasons: dict[str, list[str]] = defaultdict(list)
    normalized_changes = [(path, path.replace("\\", "/")) for path in changed]
    for machine, source in sources.items():
        driver = f"src/mame/{source}"
        driver_stem = driver.removesuffix(".cpp")
        for original, normalized in normalized_changes:
            if normalized == driver or normalized.removesuffix(".h") == driver_stem:
                reasons[machine].append(f"driver changed: {original}")
    return dict(reasons)
