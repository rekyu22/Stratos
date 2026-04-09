import time
import unittest

from telemetry_service import TelemetryService


VALID_FRAME = bytes.fromhex("AA002A000AFFF603E80005FFFB000000DC00018A0A08AC000000960F3C9F55")
INVALID_FRAME = bytes.fromhex("AA002A000AFFF603E80005FFFB000000DC00018A0A08AC000000960F3C6B55")


class FakeSource:
    def __init__(self, frames):
        self._frames = list(frames)
        self.opened = False

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def read_frame(self):
        if not self._frames:
            return None
        return self._frames.pop(0)


class TestTelemetryService(unittest.TestCase):
    def test_service_counts_and_latest(self):
        source = FakeSource([INVALID_FRAME, VALID_FRAME])
        service = TelemetryService(source=source, logger=None, history_size=5)
        service.start()
        time.sleep(0.05)
        service.stop()

        status = service.get_status()
        latest = service.get_latest()
        history = service.get_history(10)

        self.assertEqual(status["frames_received"], 1)
        self.assertEqual(status["frames_rejected"], 1)
        self.assertEqual(status["history_size"], 1)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["frame_id"], 42)
        self.assertEqual(len(history), 1)

    def test_status_contains_link_metrics(self):
        source = FakeSource([VALID_FRAME, VALID_FRAME, VALID_FRAME])
        service = TelemetryService(source=source, logger=None, history_size=5)
        service.start()
        time.sleep(0.08)
        service.stop()

        status = service.get_status()
        self.assertIn("rx_fps", status)
        self.assertIn("jitter_ms", status)
        self.assertIn("drop_rate_pct", status)
        self.assertIn("reject_rate_pct", status)
        self.assertGreaterEqual(status["rx_fps"], 0.0)
        self.assertGreaterEqual(status["jitter_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
