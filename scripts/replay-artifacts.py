#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from quicksnaps.artifacts import Artifact, available_artifacts


def run(*command: str, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def pages_head(pages: Path) -> str | None:
    manifest = pages / "manifest.json"
    if not manifest.is_file():
        return None
    return str(json.loads(manifest.read_text(encoding="utf-8"))["head"])


def order_artifacts(artifacts: list[Artifact], mame_repo: Path, current: str | None) -> list[Artifact]:
    by_sha = {artifact.sha: artifact for artifact in artifacts}
    history = run(
        "git", "rev-list", "--reverse", "--first-parent", "origin/master",
        cwd=mame_repo,
        capture=True,
    ).splitlines()
    positions = {sha: index for index, sha in enumerate(history)}
    if current and current not in positions:
        raise RuntimeError(f"Pages head {current} is not on MAME's origin/master first-parent history")
    start = positions[current] if current else -1
    return [by_sha[sha] for sha in history[start + 1 :] if sha in by_sha]


def download(artifact: Artifact, destination: Path, repository: str) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "artifact.zip"
    with archive.open("wb") as output:
        subprocess.run(
            ["gh", "api", f"repos/{repository}/actions/artifacts/{artifact.artifact_id}/zip"],
            check=True,
            stdout=output,
        )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(destination)
    binary = destination / "mame"
    if not binary.is_file():
        matches = list(destination.rglob("mame"))
        if len(matches) != 1:
            raise RuntimeError(f"artifact {artifact.name} does not contain one mame binary")
        binary = matches[0]
    binary.chmod(binary.stat().st_mode | 0o111)
    return binary


def commit_pages(pages: Path, artifact: Artifact, base: str | None) -> None:
    run("git", "add", "--all", cwd=pages)
    run("git", "config", "user.name", "quicksnaps bot", cwd=pages)
    run("git", "config", "user.email", "quicksnaps@users.noreply.github.com", cwd=pages)
    message = ["git", "commit", "--allow-empty", "-m", f"MAME {artifact.sha}"]
    if base:
        message.extend(("-m", f"MAME-Base: {base}"))
    message.extend(("-m", f"MAME-SHA: {artifact.sha}", "-m", f"MAME-Artifact: {artifact.name}"))
    run(*message, cwd=pages)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay available MAME Linux CI artifacts")
    parser.add_argument("--pages", type=Path, required=True)
    parser.add_argument("--mame-repo", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository", default="mamedev/mame")
    parser.add_argument("--rompath")
    parser.add_argument("--limit", type=int, help="maximum artifacts to process this invocation")
    parser.add_argument("--push-branch", help="push each completed commit to this origin branch")
    args = parser.parse_args()

    artifacts = available_artifacts(args.repository)
    current = pages_head(args.pages)
    available_by_sha = {artifact.sha: artifact for artifact in artifacts}
    previous_artifact = available_by_sha.get(current) if current else None
    artifacts = order_artifacts(artifacts, args.mame_repo, current)
    if args.limit is not None:
        artifacts = artifacts[: args.limit]
    if not artifacts:
        print("No new MAME artifacts to process")
        return 0

    for artifact in artifacts:
        print(f"Processing {artifact.name}", flush=True)
        run("git", "-C", str(args.mame_repo), "cat-file", "-e", f"{artifact.sha}^{{commit}}")
        with tempfile.TemporaryDirectory(prefix="quicksnaps-artifact-") as temporary:
            temporary_path = Path(temporary)
            binary = download(artifact, temporary_path / "current", args.repository)
            common = [
                sys.executable, "-m", "quicksnaps.cli", "capture",
                "--config", str(args.config), "--mame-repo", str(args.mame_repo),
                "--head", artifact.sha, "--output", str(args.pages),
            ]
            if current:
                common.extend(("--base", current))
            else:
                common.append("--all")
            if args.rompath:
                common.extend(("--rompath", args.rompath))

            selection = temporary_path / "selection.json"
            affected = [
                sys.executable, "-m", "quicksnaps.cli", "affected",
                "--config", str(args.config), "--mame", str(binary),
                "--mame-repo", str(args.mame_repo), "--head", artifact.sha,
            ]
            if current:
                affected.extend(("--base", current))
            else:
                affected.append("--all")
            selection.write_text(run(*affected, capture=True) + "\n", encoding="utf-8")
            common.extend(("--selection-file", str(selection)))

            if current and previous_artifact:
                previous_binary = download(
                    previous_artifact, temporary_path / "previous", args.repository
                )
                run(
                    *common, "--mame", str(previous_binary), "--variant", "previous",
                    "--capture-revision", current, "--artifact", previous_artifact.name,
                )
            elif current:
                print(f"Previous artifact for {current} has expired; capturing current only", flush=True)

            run(
                *common, "--mame", str(binary), "--variant", "current",
                "--capture-revision", artifact.sha, "--artifact", artifact.name,
            )
        commit_pages(args.pages, artifact, current)
        if args.push_branch:
            run("git", "push", "origin", f"HEAD:{args.push_branch}", cwd=args.pages)
        current = artifact.sha
        previous_artifact = artifact
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
