import unittest
import struct

from protocol import ETX, FRAME_FORMAT, STX, parse_frame
from serial_reader import SerialReader


VALID_FRAME_HEX = "AA002A000AFFF603E80005FFFB000000DC00018A0A08AC000000960F3C9F55"
INVALID_CHECKSUM_FRAME_HEX = "AA002A000AFFF603E80005FFFB000000DC00018A0A08AC000000960F3C6B55"


def _xor(payload: bytes) -> int:
    checksum = 0
    for value in payload:
        checksum ^= value
    return checksum


def _build_frame(
    frame_id: int,
    acc_x_raw: int,
    acc_y_raw: int,
    acc_z_raw: int,
    gyr_x_raw: int,
    gyr_y_raw: int,
    gyr_z_raw: int,
    temp_imu_raw: int,
    pression_raw: int,
    temp_bmp_raw: int,
    altitude_raw: int,
    v_bat_raw: int,
) -> bytes:
    payload = struct.pack(
        FRAME_FORMAT,
        frame_id,
        acc_x_raw,
        acc_y_raw,
        acc_z_raw,
        gyr_x_raw,
        gyr_y_raw,
        gyr_z_raw,
        temp_imu_raw,
        pression_raw,
        temp_bmp_raw,
        altitude_raw,
        v_bat_raw,
    )
    checksum = _xor(payload)
    return bytes([STX]) + payload + bytes([checksum, ETX])


class TestTelemetryParser(unittest.TestCase):

    def test_parse_valid_frame(self) -> None:
        frame = parse_frame(bytes.fromhex(VALID_FRAME_HEX))
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.frame_id, 42)
        self.assertAlmostEqual(frame.acc_x, 0.010)
        self.assertAlmostEqual(frame.acc_y, -0.010)
        self.assertAlmostEqual(frame.acc_z, 1.000)
        self.assertAlmostEqual(frame.temp_imu, 22.0)
        self.assertAlmostEqual(frame.pression, 1008.74)
        self.assertAlmostEqual(frame.altitude, 1.50)
        self.assertAlmostEqual(frame.v_bat, 3.900)

    def test_reject_invalid_checksum(self) -> None:
        frame = parse_frame(bytes.fromhex(INVALID_CHECKSUM_FRAME_HEX))
        self.assertIsNone(frame)

    def test_absent_sentinels_are_none(self) -> None:
        raw = _build_frame(
            frame_id=7,
            acc_x_raw=-1,
            acc_y_raw=-20,
            acc_z_raw=1000,
            gyr_x_raw=0,
            gyr_y_raw=0,
            gyr_z_raw=0,
            temp_imu_raw=-1,
            pression_raw=0xFFFFFFFF,
            temp_bmp_raw=-1,
            altitude_raw=0x7FFFFFFF,
            v_bat_raw=0xFFFF,
        )
        frame = parse_frame(raw)
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertIsNone(frame.acc_x)
        self.assertIsNone(frame.pression)
        self.assertIsNone(frame.altitude)
        self.assertIsNone(frame.v_bat)

    def test_serial_reader_resyncs_after_false_stx(self) -> None:
        valid_raw = bytes.fromhex(VALID_FRAME_HEX)
        reader = SerialReader(port="TEST")
        reader._buffer = bytearray(b"\xAA\x00" + valid_raw)
        extracted = reader._extract_frame()
        self.assertEqual(extracted, valid_raw)


if __name__ == "__main__":
    unittest.main()
