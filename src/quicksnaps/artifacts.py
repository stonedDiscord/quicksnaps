from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    artifact_id: int
    name: str
    sha: str
    created_at: str


def available_artifacts(repository: str = "mamedev/mame") -> list[Artifact]:
    result = subprocess.run(
        [
            "gh", "api", "--paginate",
            f"repos/{repository}/actions/artifacts?per_page=100",
            "--jq", ".artifacts[] | @json",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    artifacts: list[Artifact] = []
    by_sha: dict[str, Artifact] = {}
    prefix = "mame-linux-clang-"
    for line in result.stdout.splitlines():
        item = json.loads(line)
        name = str(item["name"])
        run = item.get("workflow_run") or {}
        if item.get("expired") or not name.startswith(prefix) or run.get("head_branch") != "master":
            continue
        sha = name.removeprefix(prefix)
        if len(sha) != 40:
            continue
        artifact = Artifact(int(item["id"]), name, sha, str(item["created_at"]))
        previous = by_sha.get(sha)
        if previous is None or artifact.artifact_id > previous.artifact_id:
            by_sha[sha] = artifact
    return sorted(by_sha.values(), key=lambda item: (item.created_at, item.artifact_id))
