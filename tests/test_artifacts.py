import json
import unittest
from unittest.mock import patch

from quicksnaps.artifacts import available_artifacts


class Result:
    def __init__(self, items):
        self.stdout = "\n".join(json.dumps(item) for item in items)


class ArtifactTests(unittest.TestCase):
    @patch("quicksnaps.artifacts.subprocess.run")
    def test_filters_expired_and_pr_builds_and_deduplicates_reruns(self, run):
        sha = "a" * 40
        other = "b" * 40
        run.return_value = Result([
            {"id": 1, "name": f"mame-linux-clang-{sha}", "expired": False, "created_at": "2026-01-01", "workflow_run": {"head_branch": "master"}},
            {"id": 2, "name": f"mame-linux-clang-{sha}", "expired": False, "created_at": "2026-01-02", "workflow_run": {"head_branch": "master"}},
            {"id": 3, "name": f"mame-linux-clang-{other}", "expired": True, "created_at": "2026-01-03", "workflow_run": {"head_branch": "master"}},
            {"id": 4, "name": f"mame-linux-clang-{other}", "expired": False, "created_at": "2026-01-04", "workflow_run": {"head_branch": "topic"}},
            {"id": 5, "name": f"mametiny-linux-gcc-{other}", "expired": False, "created_at": "2026-01-05", "workflow_run": {"head_branch": "master"}},
        ])
        artifacts = available_artifacts()
        self.assertEqual([(2, sha)], [(item.artifact_id, item.sha) for item in artifacts])


if __name__ == "__main__":
    unittest.main()
