"""The Steam scroll benchmark must reject runs it cannot trust and measure only the scrolling window."""
from pathlib import Path
import runpy
import unittest

BENCH = runpy.run_path(str(Path(__file__).resolve().parents[1] / "pixel-bench" / "steam_scroll.py"))
MS = 1_000_000


def latency_dump(presents, period=8_333_333):
    # Rows are desired, actual present, ready; the present is p + 10 ms. All values stay positive,
    # like real CLOCK_MONOTONIC timestamps (a negative one is not a valid row).
    lines = [str(period)] + [f"{p + 5 * MS} {p + 10 * MS} {p + 8 * MS}" for p in presents]
    return "\n".join(lines) + "\n"


class ParseLatencyTest(unittest.TestCase):
    def test_skips_pending_and_empty_rows(self):
        text = "8333333\n0\t0\t0\n10\t9223372036854775807\t5\n100\t200\t150\n\n"
        period, rows = BENCH["parse_latency"](text)
        self.assertEqual(period, 8_333_333)
        self.assertEqual(rows, [(100, 200, 150)])


class PresentLogTest(unittest.TestCase):
    def test_overlapping_polls_are_not_loss(self):
        log = BENCH["PresentLog"]()
        log.add(BENCH["parse_latency"](latency_dump([1 * MS, 2 * MS, 3 * MS]))[1])
        log.add(BENCH["parse_latency"](latency_dump([3 * MS, 4 * MS]))[1])
        self.assertFalse(log.possible_loss)
        self.assertEqual(sorted(log.frames), [11 * MS, 12 * MS, 13 * MS, 14 * MS])

    def test_a_poll_with_no_overlap_flags_possible_loss(self):
        log = BENCH["PresentLog"]()
        log.add(BENCH["parse_latency"](latency_dump([1 * MS, 2 * MS]))[1])
        log.add(BENCH["parse_latency"](latency_dump([50 * MS, 51 * MS]))[1])
        self.assertTrue(log.possible_loss)

    def test_an_idle_poll_is_not_loss(self):
        log = BENCH["PresentLog"]()
        log.add(BENCH["parse_latency"](latency_dump([1 * MS]))[1])
        log.add([])
        self.assertFalse(log.possible_loss)


class FrameStatsTest(unittest.TestCase):
    def test_only_presents_inside_the_window_count(self):
        presents = [0, 100 * MS] + [1000 * MS + i * 16_666_666 for i in range(61)] + [3000 * MS]
        stats = BENCH["frame_stats"](presents, 1000 * MS, 2000 * MS)
        self.assertEqual(stats["presentedFrames"], 61)
        self.assertEqual(stats["fps"], 61.0)
        self.assertAlmostEqual(stats["gapP50Ms"], 16.67, places=2)
        self.assertEqual(stats["gapsOver34Ms"], 0)

    def test_a_long_gap_is_reported(self):
        presents = [i * 16 * MS for i in range(10)] + [10 * 16 * MS + 150 * MS]
        stats = BENCH["frame_stats"](presents, 0, 400 * MS)
        self.assertEqual(stats["gapMaxMs"], 166.0)
        self.assertEqual(stats["gapsOver100Ms"], 1)

    def test_ready_to_present_latency(self):
        presents = [10 * MS, 20 * MS]
        stats = BENCH["frame_stats"](presents, 0, 30 * MS, {10 * MS: 4 * MS, 20 * MS: 14 * MS})
        self.assertEqual(stats["readyToPresentP50Ms"], 6.0)


class ValidityTest(unittest.TestCase):
    def good(self):
        return {"guestExit": 0, "guest": {"durationMs": 15000}, "focusLost": False, "possibleLoss": False,
                "stats": {"presentedFrames": 700, "windowSeconds": 14.5}}

    def test_a_clean_run_is_valid(self):
        self.assertEqual(BENCH["validity"](self.good()), [])

    def test_guest_error_rejects_even_with_exit_zero(self):
        run = self.good()
        run["guest"]["error"] = "no scrollable content on the Big Picture page"
        self.assertTrue(any("guest scroll failed" in r for r in BENCH["validity"](run)))

    def test_focus_loss_overflow_and_empty_runs_reject(self):
        for key, value in (("focusLost", True), ("possibleLoss", True), ("stats", {"presentedFrames": 3, "windowSeconds": 14})):
            run = self.good()
            run[key] = value
            self.assertTrue(BENCH["validity"](run), key)

    def test_missing_stats_rejects(self):
        run = self.good()
        del run["stats"]
        self.assertTrue(BENCH["validity"](run))


class GpuSummaryTest(unittest.TestCase):
    def test_summary(self):
        self.assertIsNone(BENCH["gpu_summary"]([]))
        self.assertEqual(BENCH["gpu_summary"]([202000, 471000, 848000])["p50"], 471000)


if __name__ == "__main__":
    unittest.main()
