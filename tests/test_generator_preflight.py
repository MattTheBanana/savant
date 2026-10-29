import time
import unittest
from pathlib import Path
from unittest.mock import patch

import lyrics_editor


class GeneratorPreflightTests(unittest.TestCase):
    def test_run_snapshot_uses_cached_artifact_availability(self):
        run = {
            "id": "run-test",
            "status": "running",
            "operation": "align",
            "created": 0,
            "started": 0,
            "finished": None,
            "return_code": None,
            "step": "Checking output paths",
            "overall_progress": 1,
            "step_progress": 0,
            "logs": "",
            "directory": Path("/path-that-should-not-be-probed/run"),
            "artifacts": {
                "output-lrc": {
                    "label": "Output LRC",
                    "path": "/unavailable/share/output.lrc",
                    "kind": "output",
                    "available": False,
                }
            },
        }
        with patch.object(Path, "is_file", side_effect=AssertionError("status polling must not probe files")), patch.object(
            Path, "stat", side_effect=AssertionError("status polling must not stat files")
        ):
            snapshot = lyrics_editor._run_snapshot(run)

        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["step"], "Checking output paths")
        self.assertFalse(snapshot["artifacts"][0]["available"])

    def test_slow_path_probe_fails_with_a_recoverable_error(self):
        def slow_probe():
            time.sleep(0.08)
            return True

        with self.assertRaisesRegex(TimeoutError, "unavailable network share"):
            lyrics_editor._bounded_filesystem_check(
                "unavailable network share", slow_probe, timeout=0.01
            )


if __name__ == "__main__":
    unittest.main()
