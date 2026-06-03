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

    def test_simulated_source_emits_gyro_short_frames(self):
        source = AutoFrameSource(
            SerialSourceConfig(port="__STRATOS_INVALID_PORT__", baudrate=9600, timeout=0.1),
            sim_hz=10.0,
        )
        source.open()
        try:
            ids = []
            for _ in range(30):
                raw = source.read_frame()
                frame = parse_frame(raw)
                self.assertIsNotNone(frame)
                assert frame is not None
                ids.append(frame.frame_id)
                self.assertIsNotNone(frame.gyr_x)
                self.assertIsNotNone(frame.gyr_y)
                self.assertIsNotNone(frame.gyr_z)
                self.assertIsNone(frame.v_bat)
            for i in range(1, len(ids)):
                self.assertEqual(ids[i], (ids[i - 1] + 1) % 256)
        finally:
            source.close()


if __name__ == "__main__":
    unittest.main()
