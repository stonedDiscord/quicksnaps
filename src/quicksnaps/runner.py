from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from .config import Machine


PNG_NONVISUAL_CHUNKS = {b"tEXt", b"zTXt", b"iTXt", b"tIME", b"eXIf"}
CAPTURE_CHECKPOINT = "capture.json"


def capture_directory(output: Path, machine_name: str, variant: str | None = None) -> Path:
    directory = output / "machines" / machine_name
    return directory / variant if variant else directory


def load_capture_checkpoint(
    output: Path,
    machine_name: str,
    variant: str | None,
    request: dict[str, object],
) -> dict[str, object] | None:
    directory = capture_directory(output, machine_name, variant)
    path = directory / CAPTURE_CHECKPOINT
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if checkpoint.get("request") != request or not isinstance(checkpoint.get("result"), dict):
        return None
    result = checkpoint["result"]
    if not (directory / "mame.log").is_file():
        return None
    capture = result.get("captures", {}).get(variant, {}) if variant else result
    if capture.get("status") == "passed" and not all(
        (directory / name).is_file() for name in ("before.png", "after.png")
    ):
        return None
    return result


def write_capture_checkpoint(
    output: Path,
    machine_name: str,
    variant: str | None,
    request: dict[str, object],
    result: dict[str, object],
) -> None:
    directory = capture_directory(output, machine_name, variant)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CAPTURE_CHECKPOINT
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"request": request, "result": result}, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def normalize_png(path: Path) -> None:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    output = bytearray(data[:8])
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            return
        chunk_type = data[offset + 4 : offset + 8]
        if chunk_type not in PNG_NONVISUAL_CHUNKS:
            output.extend(data[offset:end])
        offset = end
        if chunk_type == b"IEND":
            break
    if offset == len(data) and bytes(output) != data:
        path.write_bytes(output)


def _failure_from_log(log: str, fallback: str) -> str:
    quicksnaps_errors = [
        line.removeprefix("[quicksnaps] ").strip()
        for line in log.splitlines()
        if line.startswith("[quicksnaps] ")
    ]
    if quicksnaps_errors:
        return quicksnaps_errors[-1]
    meaningful = [
        line.strip() for line in log.splitlines()
        if line.strip() and not line.startswith(("ALSA lib ", "Warning: -video none"))
    ]
    return meaningful[-1] if meaningful else fallback


def capture_machine(
    mame: Path,
    machine: Machine,
    output: Path,
    rompath: str | None = None,
    timeout: float | None = None,
    variant: str | None = None,
) -> dict[str, object]:
    machine_dir = capture_directory(output, machine.name, variant)
    if machine_dir.exists():
        shutil.rmtree(machine_dir)
    machine_dir.mkdir(parents=True, exist_ok=True)

    script = Path(__file__).with_name("capture.lua").resolve()
    emulated_limit = machine.warmup_seconds + machine.press_seconds + machine.after_seconds + 5.0
    command = [
        str(mame), machine.name,
        "-autoboot_script", str(script),
        "-snapshot_directory", str(machine_dir.resolve()),
        "-cfg_directory", str((machine_dir / "cfg").resolve()),
        "-nvram_directory", str((machine_dir / "nvram").resolve()),
        "-state_directory", str((machine_dir / "state").resolve()),
        "-snapview", "native", "-skip_gameinfo", "-noconfirm_quit",
        "-sound", "none", "-video", "none", "-nothrottle", "-noreadconfig",
        "-seconds_to_run", str(emulated_limit),
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
    limit = timeout if timeout is not None else emulated_limit
    failure_reason: str | None = None
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=limit)
        status = "passed" if result.returncode == 0 else "failed"
        log = result.stdout
        if result.returncode != 0:
            failure_reason = _failure_from_log(log, f"MAME exited with status {result.returncode}")
    except subprocess.TimeoutExpired as error:
        status = "failed"
        failure_reason = f"MAME timed out after {limit:.1f} wall-clock seconds"
        captured = error.stdout or ""
        if isinstance(captured, bytes):
            captured = captured.decode(errors="replace")
        log = captured + f"\nTimed out after {limit:.1f} seconds.\n"

    for runtime_dir in ("cfg", "nvram", "state"):
        shutil.rmtree(machine_dir / runtime_dir, ignore_errors=True)
    for filename in ("before.png", "after.png"):
        image = machine_dir / filename
        if image.is_file():
            normalize_png(image)
    images_present = all((machine_dir / name).is_file() for name in ("before.png", "after.png"))
    if not images_present:
        status = "failed"
        missing = [name for name in ("before.png", "after.png") if not (machine_dir / name).is_file()]
        if failure_reason is None:
            failure_reason = _failure_from_log(log, "") or None
        if failure_reason is None:
            failure_reason = "Missing screenshot output: " + ", ".join(missing)
    (machine_dir / "mame.log").write_text(log, encoding="utf-8")
    button_applied = not any(
        line.startswith("[quicksnaps] input skipped:") for line in log.splitlines()
    )
    return {
        "name": machine.name,
        "status": status,
        "duration_seconds": round(time.monotonic() - started, 3),
        "button": machine.button,
        "button_applied": button_applied,
        "warmup_seconds": machine.warmup_seconds,
        "after_seconds": machine.after_seconds,
        "press_seconds": machine.press_seconds,
        "failure_reason": failure_reason,
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
        for item in machines:
            old = previous.get(item["name"], {})
            captures = {**old.get("captures", {}), **item.get("captures", {})}
            previous[item["name"]] = {**old, **item, "captures": captures}
        machines = list(previous.values())
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        **metadata,
        "machines": machines,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
