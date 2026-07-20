#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from quicksnaps.artifacts import Artifact, available_artifacts


RESUME_MARKER = ".quicksnaps-resume.json"


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


def resume_snapshot(
    pages: Path, branch: str, base: str | None, target: str,
) -> bool:
    """Restore a partial artifact tree from the disposable resume ref."""
    result = subprocess.run(
        ["git", "fetch", "origin", f"refs/heads/{branch}:refs/remotes/origin/{branch}"],
        cwd=pages, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        return False
    marker = subprocess.run(
        ["git", "show", f"origin/{branch}:{RESUME_MARKER}"],
        cwd=pages, check=False, text=True, stdout=subprocess.PIPE,
    )
    if marker.returncode:
        return False
    try:
        state = json.loads(marker.stdout)
    except json.JSONDecodeError:
        return False
    if state.get("base") != base or state.get("target") != target:
        return False
    run("git", "read-tree", "-m", "-u", f"origin/{branch}", cwd=pages)
    run("git", "read-tree", "HEAD", cwd=pages)
    print(f"Restored partial capture for {target}", flush=True)
    return True


def save_resume_snapshot(pages: Path, branch: str, base: str | None, target: str) -> None:
    marker = pages / RESUME_MARKER
    marker.write_text(json.dumps({"base": base, "target": target}) + "\n", encoding="utf-8")
    run("git", "config", "user.name", "quicksnaps bot", cwd=pages)
    run("git", "config", "user.email", "quicksnaps@users.noreply.github.com", cwd=pages)
    run("git", "add", "--all", cwd=pages)
    tree = run("git", "write-tree", cwd=pages, capture=True)
    commit = subprocess.run(
        ["git", "commit-tree", tree, "-p", "HEAD"],
        cwd=pages, check=True, text=True, input=f"Resume MAME {target}\n", stdout=subprocess.PIPE,
    ).stdout.strip()
    run("git", "push", "--force", "origin", f"{commit}:refs/heads/{branch}", cwd=pages)
    run("git", "read-tree", "HEAD", cwd=pages)


def delete_resume_snapshot(pages: Path, branch: str) -> None:
    subprocess.run(
        ["git", "push", "origin", "--delete", branch],
        cwd=pages, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def capture_in_batches(
    command: list[str], selection: Path, jobs: int | None, temporary: Path,
    pages: Path, resume_branch: str, base: str | None, target: str,
) -> None:
    selected = json.loads(selection.read_text(encoding="utf-8"))
    names = list(selected.get("machines", {}))
    workers = max(1, jobs or (os.cpu_count() or 1))
    batch_size = workers * workers + 20
    for offset in range(0, len(names), batch_size):
        batch = dict(selected)
        batch["machines"] = {name: selected["machines"][name] for name in names[offset : offset + batch_size]}
        batch_selection = temporary / f"batch-{offset}.json"
        batch_selection.write_text(json.dumps(batch) + "\n", encoding="utf-8")
        run(*command, "--selection-file", str(batch_selection))
        save_resume_snapshot(pages, resume_branch, base, target)
    # Rebuild the manifest/site with the complete selection; all captures now checkpoint-skip.
    run(*command, "--selection-file", str(selection))


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


def commit_pages(pages: Path, artifact: Artifact, base: str | None) -> bool:
    run("git", "add", "--all", cwd=pages)
    changed = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=pages,
        check=False,
    ).returncode
    if changed == 0:
        print(f"No generated changes for {artifact.name}; skipping commit", flush=True)
        return False
    if changed != 1:
        raise RuntimeError("unable to inspect staged Pages changes")
    run("git", "config", "user.name", "quicksnaps bot", cwd=pages)
    run("git", "config", "user.email", "quicksnaps@users.noreply.github.com", cwd=pages)
    message = ["git", "commit", "-m", f"MAME {artifact.sha}"]
    if base:
        message.extend(("-m", f"MAME-Base: {base}"))
    message.extend(("-m", f"MAME-SHA: {artifact.sha}", "-m", f"MAME-Artifact: {artifact.name}"))
    run(*message, cwd=pages)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay available MAME Linux CI artifacts")
    parser.add_argument("--pages", type=Path, required=True)
    parser.add_argument("--mame-repo", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository", default="mamedev/mame")
    parser.add_argument("--rompath")
    parser.add_argument("--jobs", type=int, help="machines to capture in parallel")
    parser.add_argument("--limit", type=int, help="maximum artifacts to process this invocation")
    parser.add_argument("--push-branch", help="push each completed commit to this origin branch")
    parser.add_argument("--resume-branch", help="temporary remote branch for interrupted captures")
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

    resume_branch = args.resume_branch or (f"{args.push_branch}-resume" if args.push_branch else None)
    if resume_branch:
        resume_snapshot(args.pages, resume_branch, current, artifacts[0].sha)

    for artifact in artifacts:
        print(f"Processing {artifact.name}", flush=True)
        run("git", "-C", str(args.mame_repo), "cat-file", "-e", f"{artifact.sha}^{{commit}}")
        with tempfile.TemporaryDirectory(prefix="quicksnaps-artifact-") as temporary:
            temporary_path = Path(temporary)
            binary = download(artifact, temporary_path / "current", args.repository)
            common = [
                sys.executable, "-m", "quicksnaps.cli", "capture",
                "--config", str(args.config), "--mame-repo", str(args.mame_repo),
                "--head", artifact.sha, "--output", str(args.pages), "--allow-failures",
            ]
            if current:
                common.extend(("--base", current))
            if args.rompath:
                common.extend(("--rompath", args.rompath))
            if args.jobs is not None:
                common.extend(("--jobs", str(args.jobs)))

            def selection_for(capture_binary: Path, filename: str) -> Path:
                selection = temporary_path / filename
                if not current:
                    # The oldest artifact is only the left edge of future comparisons.
                    selection.write_text('{"changed_files": [], "machines": {}}\n', encoding="utf-8")
                    return selection
                affected = [
                    sys.executable, "-m", "quicksnaps.cli", "affected", "--catalog",
                    "--config", str(args.config), "--mame", str(capture_binary),
                    "--mame-repo", str(args.mame_repo), "--base", current,
                    "--head", artifact.sha,
                ]
                selection.write_text(run(*affected, capture=True) + "\n", encoding="utf-8")
                return selection

            current_selection = selection_for(binary, "current-selection.json")

            if current and previous_artifact:
                previous_binary = download(
                    previous_artifact, temporary_path / "previous", args.repository
                )
                previous_selection = selection_for(previous_binary, "previous-selection.json")
                previous_command = [
                    *common, "--mame", str(previous_binary), "--variant", "previous",
                    "--capture-revision", current, "--artifact", previous_artifact.name,
                    "--catalog",
                ]
                if resume_branch:
                    capture_in_batches(
                        previous_command, previous_selection, args.jobs, temporary_path,
                        args.pages, resume_branch, current, artifact.sha,
                    )
                else:
                    run(*previous_command, "--selection-file", str(previous_selection))
            elif current:
                print(f"Previous artifact for {current} has expired; capturing current only", flush=True)

            current_command = [
                *common, "--mame", str(binary), "--variant", "current",
                "--capture-revision", artifact.sha, "--artifact", artifact.name, "--catalog",
            ]
            if resume_branch:
                capture_in_batches(
                    current_command, current_selection, args.jobs, temporary_path,
                    args.pages, resume_branch, current, artifact.sha,
                )
            else:
                run(*current_command, "--selection-file", str(current_selection))
        (args.pages / RESUME_MARKER).unlink(missing_ok=True)
        committed = commit_pages(args.pages, artifact, current)
        if committed and args.push_branch:
            run("git", "push", "origin", f"HEAD:{args.push_branch}", cwd=args.pages)
        current = artifact.sha
        previous_artifact = artifact
        if resume_branch:
            delete_resume_snapshot(args.pages, resume_branch)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
