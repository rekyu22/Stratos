import unittest

from model.frame_sources import AutoFrameSource, SerialSourceConfig


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


if __name__ == "__main__":
    unittest.main()
