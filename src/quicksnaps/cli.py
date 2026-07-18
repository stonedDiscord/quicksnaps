from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .artifacts import available_artifacts
from .config import load_config
from .impact import changed_files, resolve, resolve_catalog, runnable_machines, source_map
from .runner import capture_machine, write_manifest
from .site import build_site


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _revision(repo: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", revision], cwd=repo, check=True, text=True, stdout=subprocess.PIPE
    )
    return result.stdout.strip()


def _commit_message(repo: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "show", "-s", "--format=%B", revision],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.strip()


def _resolve_selection(args: argparse.Namespace) -> tuple[dict[str, list[str]], list[str]]:
    config = load_config(args.config)
    if args.selection_file:
        selection = json.loads(args.selection_file.read_text(encoding="utf-8"))
        selected = {str(name): list(map(str, reasons)) for name, reasons in selection["machines"].items()}
        unknown = set(selected) - set(config.machine_names)
        if unknown and not args.catalog:
            raise ValueError(f"selection references unknown configured machines: {sorted(unknown)}")
        return selected, list(map(str, selection.get("changed_files", [])))
    if args.all:
        names = tuple(source_map(args.mame)) if args.catalog else config.machine_names
        return {name: ["all machines requested"] for name in names}, []
    if args.machine:
        unknown = set(args.machine) - set(config.machine_names)
        if unknown:
            raise ValueError(f"unknown configured machines: {sorted(unknown)}")
        return {name: ["machine explicitly requested"] for name in args.machine}, []
    if not args.base or not args.head:
        raise ValueError("provide --base and --head, --all, or --machine")
    changed = changed_files(args.mame_repo, args.base, args.head)
    sources = source_map(args.mame, None if args.catalog else config.machine_names)
    if args.catalog:
        runnable = runnable_machines(args.mame_repo, args.head)
        sources = {name: source for name, source in sources.items() if name in runnable}
        return resolve_catalog(changed, sources), changed
    return resolve(config, changed, sources, tuple(sources)), changed


def cmd_affected(args: argparse.Namespace) -> int:
    selected, changed = _resolve_selection(args)
    print(json.dumps({"changed_files": changed, "machines": selected}, indent=2))
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    if args.jobs < 1:
        raise ValueError("--jobs must be at least 1")
    config = load_config(args.config)
    selected, changed = _resolve_selection(args)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.catalog and args.head:
        _prune_nonrunnable(args.output, runnable_machines(args.mame_repo, args.head))
    if (
        args.base and args.head
        and not args.selection_file
        and not (args.output / "manifest.json").is_file()
    ):
        selected = {name: ["initial Pages snapshot"] for name in config.machine_names}
    head = _revision(args.mame_repo, args.head) if args.head else os.environ.get("MAME_SHA", "manual")
    def run_machine(name: str) -> dict[str, object]:
        print(f"Capturing {name}...", flush=True)
        result = capture_machine(
            args.mame, config.machine(name), args.output, args.rompath, args.timeout, args.variant
        )
        revision = args.capture_revision or head
        result["revision"] = revision
        result["artifact"] = args.artifact
        if args.variant:
            capture = {key: value for key, value in result.items() if key != "name"}
            result = {
                "name": name,
                "status": capture["status"],
                "button": capture["button"],
                "revision": revision,
                "captures": {args.variant: capture},
            }
        print(f"{name}: {result['status']}", flush=True)
        return result

    results_by_name: dict[str, dict[str, object]] = {}
    workers = min(args.jobs, len(selected)) if selected else 1
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_machine, name): name for name in selected}
        for future in as_completed(futures):
            name = futures[future]
            results_by_name[name] = future.result()
    results = [results_by_name[name] for name in selected]

    metadata = {
        "title": args.title,
        "head": head,
        "base": _revision(args.mame_repo, args.base) if args.base else None,
        "artifact": args.artifact,
        "commit_message": _commit_message(args.mame_repo, args.head) if args.head else None,
        "changed_files": changed,
        "reasons": selected,
    }
    write_manifest(args.output, results, metadata, merge_existing=True)
    build_site(args.output)
    failures = sum(result["status"] != "passed" for result in results)
    if failures:
        print(f"{failures} machine capture(s) failed", file=sys.stderr)
    return 0 if args.allow_failures else (1 if failures else 0)


def _prune_nonrunnable(output: Path, runnable: set[str]) -> None:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed = [item for item in manifest.get("machines", []) if item.get("name") not in runnable]
    if not removed:
        return
    manifest["machines"] = [item for item in manifest.get("machines", []) if item.get("name") in runnable]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for item in removed:
        name = str(item.get("name", ""))
        if re.fullmatch(r"[a-zA-Z0-9_]+", name):
            shutil.rmtree(output / "machines" / name, ignore_errors=True)
        print(f"Pruned non-runnable catalog entry: {name}", flush=True)


def cmd_site(args: argparse.Namespace) -> int:
    build_site(args.output)
    return 0


def cmd_artifacts(args: argparse.Namespace) -> int:
    artifacts = available_artifacts(args.repository)
    print(json.dumps([artifact.__dict__ for artifact in artifacts], indent=2))
    return 0


def common_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=_path, default=_path("quicksnaps.json"))
    parser.add_argument("--mame", type=_path, default=_path("../mame/mamed"))
    parser.add_argument("--mame-repo", type=_path, default=_path("../mame"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true")
    group.add_argument("--machine", action="append")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--selection-file", type=_path, help="reuse an affected command JSON result")
    parser.add_argument("--catalog", action="store_true", help="use every machine reported by MAME")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quicksnaps")
    subparsers = parser.add_subparsers(dest="command", required=True)

    affected = subparsers.add_parser("affected", help="show machines affected by a revision range")
    common_selection(affected)
    affected.set_defaults(func=cmd_affected)

    capture = subparsers.add_parser("capture", help="capture affected machines and rebuild the site")
    common_selection(capture)
    capture.add_argument("--output", type=_path, default=_path("site"))
    capture.add_argument("--rompath")
    capture.add_argument("--timeout", type=float)
    capture.add_argument(
        "--jobs", type=int, default=max(1, os.cpu_count() or 1),
        help="number of machines to capture in parallel (default: CPU count)",
    )
    capture.add_argument("--title", default="MAME quick snaps")
    capture.add_argument("--artifact", help="CI artifact name used for this capture")
    capture.add_argument("--variant", choices=("previous", "current"))
    capture.add_argument("--capture-revision", help="revision of the capture binary")
    capture.add_argument(
        "--allow-failures",
        action="store_true",
        help="record failed machines without failing the overall capture command",
    )
    capture.set_defaults(func=cmd_capture)

    site = subparsers.add_parser("site", help="rebuild HTML from an existing manifest")
    site.add_argument("--output", type=_path, default=_path("site"))
    site.set_defaults(func=cmd_site)

    artifacts = subparsers.add_parser("artifacts", help="list usable upstream MAME CI artifacts")
    artifacts.add_argument("--repository", default="mamedev/mame")
    artifacts.set_defaults(func=cmd_artifacts)
    return parser


def main() -> None:
    try:
        args = make_parser().parse_args()
        raise SystemExit(args.func(args))
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
