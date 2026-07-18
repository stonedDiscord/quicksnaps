from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from .config import Machine


def capture_machine(
    mame: Path,
    machine: Machine,
    output: Path,
    rompath: str | None = None,
    timeout: float | None = None,
) -> dict[str, object]:
    machine_dir = output / "machines" / machine.name
    if machine_dir.exists():
        shutil.rmtree(machine_dir)
    machine_dir.mkdir(parents=True, exist_ok=True)

    script = Path(__file__).with_name("capture.lua").resolve()
    command = [
        str(mame), machine.name,
        "-autoboot_script", str(script),
        "-snapshot_directory", str(machine_dir.resolve()),
        "-cfg_directory", str((machine_dir / "cfg").resolve()),
        "-nvram_directory", str((machine_dir / "nvram").resolve()),
        "-state_directory", str((machine_dir / "state").resolve()),
        "-snapview", "native", "-skip_gameinfo", "-noconfirm_quit",
        "-sound", "none", "-video", "none", "-nothrottle", "-noreadconfig",
        *machine.mame_args,
    ]
    if rompath:
        command.extend(("-rompath", rompath))

    env = os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    env.update(
        QUICKSNAPS_WARMUP=str(machine.warmup_seconds),
        QUICKSNAPS_AFTER=str(machine.after_seconds),
        QUICKSNAPS_HOLD=str(machine.press_seconds),
        QUICKSNAPS_BUTTON=machine.button,
    )
    started = time.monotonic()
    limit = timeout or max(60.0, (machine.warmup_seconds + machine.after_seconds + machine.press_seconds) * 5)
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=limit)
        status = "passed" if result.returncode == 0 else "failed"
        log = result.stdout
    except subprocess.TimeoutExpired as error:
        status = "failed"
        captured = error.stdout or ""
        if isinstance(captured, bytes):
            captured = captured.decode(errors="replace")
        log = captured + f"\nTimed out after {limit:.1f} seconds.\n"

    for runtime_dir in ("cfg", "nvram", "state"):
        shutil.rmtree(machine_dir / runtime_dir, ignore_errors=True)
    images_present = all((machine_dir / name).is_file() for name in ("before.png", "after.png"))
    if not images_present:
        status = "failed"
    (machine_dir / "mame.log").write_text(log, encoding="utf-8")
    return {
        "name": machine.name,
        "status": status,
        "duration_seconds": round(time.monotonic() - started, 3),
        "button": machine.button,
        "warmup_seconds": machine.warmup_seconds,
        "after_seconds": machine.after_seconds,
        "press_seconds": machine.press_seconds,
    }


def write_manifest(
    output: Path,
    machines: list[dict[str, object]],
    metadata: dict[str, object],
    merge_existing: bool = False,
) -> None:
    if merge_existing and (output / "manifest.json").is_file():
        existing = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        previous = {item["name"]: item for item in existing.get("machines", [])}
        previous.update({item["name"]: item for item in machines})
        machines = list(previous.values())
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        **metadata,
        "machines": machines,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
