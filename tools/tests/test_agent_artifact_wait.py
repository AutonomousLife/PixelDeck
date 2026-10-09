"""A stop/logs waiter must never follow a replacement session's artifacts."""
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
CTL = runpy.run_path(str(TOOLS / "droiddeckctl"))
WAIT = CTL["wait_for_artifacts"]


def state(session_id, complete=False):
    return {"session": {"id": session_id, "artifactsAvailable": True, "artifactsComplete": complete}}


class ArtifactWaitTest(unittest.TestCase):
    def test_returns_completed_original_session(self):
        completed = state("original", True)
        with patch.dict(WAIT.__globals__, get_state=Mock(return_value=completed)), patch.object(CTL["time"], "sleep"):
            self.assertIs(WAIT("adb", "phone", state("original"), 10), completed)

    def test_replacement_session_does_not_report_false_success(self):
        with patch.dict(WAIT.__globals__, get_state=Mock(return_value=state("replacement", True))), patch.object(CTL["time"], "sleep"):
            with self.assertRaises(CTL["ControlError"]) as error:
                WAIT("adb", "phone", state("original"), 10)
            self.assertEqual(error.exception.code, "SESSION_CHANGED")

    def test_incomplete_original_session_times_out(self):
        with self.assertRaises(CTL["ControlError"]) as error:
            WAIT("adb", "phone", state("original"), 0)
        self.assertEqual(error.exception.code, "ARTIFACT_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
