import unittest

from model.frame_sources import AutoFrameSource, SerialSourceConfig
from model.protocol import parse_frame


class TestFrameSources(unittest.TestCase):
    def test_auto_fallback_to_sim_when_serial_unavailable(self):
        source = AutoFrameSource(
            SerialSourceConfig(port="__STRATOS_INVALID_PORT__", baudrate=9600, timeout=0.1),
            sim_hz=10.0,
        )
        source.open()
        try:
            self.assertEqual(source.mode, "sim")
            frame = source.read_frame()
            self.assertIsNotNone(frame)
        finally:
            source.close()

    def test_simulated_battery_is_monotonic_non_increasing(self):
        source = AutoFrameSource(
            SerialSourceConfig(port="__STRATOS_INVALID_PORT__", baudrate=9600, timeout=0.1),
            sim_hz=10.0,
        )
        source.open()
        try:
            values = []
            for _ in range(30):
                raw = source.read_frame()
                frame = parse_frame(raw)
                self.assertIsNotNone(frame)
                assert frame is not None
                values.append(frame.v_bat)
            for i in range(1, len(values)):
                self.assertLessEqual(values[i], values[i - 1])
        finally:
            source.close()


if __name__ == "__main__":
    unittest.main()
