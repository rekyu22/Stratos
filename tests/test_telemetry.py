import struct
import unittest

from model.protocol import ETX, FRAME_FORMAT, GYRO_FRAME_FORMAT, STX, parse_frame
from model.serial_reader import SerialReader


VALID_FRAME_HEX = "AA002A000AFFF603E80005FFFB000000DC00018A0A08AC000000960F3C9F55"
INVALID_CHECKSUM_FRAME_HEX = "AA002A000AFFF603E80005FFFB000000DC00018A0A08AC000000960F3C6B55"
LEGACY_SHORT_FRAME_HEX = "AA7779FFFFFFFFFFFFFFFFFF"
REAL_FIRMWARE_FRAME_HEX = "AA01ECF3F902E708E7FFE00054000B01AFFFFFFFFFFFFF7FFFFFFFFFFF8355"


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


def _build_gyro_frame(frame_id: int, gyr_x_raw: int, gyr_y_raw: int, gyr_z_raw: int) -> bytes:
    payload = struct.pack(GYRO_FRAME_FORMAT, frame_id, gyr_x_raw, gyr_y_raw, gyr_z_raw)
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

    def test_parse_valid_gyro_short_frame(self) -> None:
        raw = _build_gyro_frame(frame_id=42, gyr_x_raw=15, gyr_y_raw=-7, gyr_z_raw=250)
        frame = parse_frame(raw)
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.frame_id, 42)
        self.assertAlmostEqual(frame.gyr_x, 1.5)
        self.assertAlmostEqual(frame.gyr_y, -0.7)
        self.assertAlmostEqual(frame.gyr_z, 25.0)
        self.assertIsNone(frame.v_bat)

    def test_parse_real_31_byte_firmware_frame(self) -> None:
        frame = parse_frame(bytes.fromhex(REAL_FIRMWARE_FRAME_HEX))
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.protocol, "stratos31")
        self.assertEqual(frame.id_modulus, 65536)
        self.assertEqual(frame.frame_id, 492)
        self.assertAlmostEqual(frame.gyr_x, -3.2)
        self.assertAlmostEqual(frame.gyr_y, 8.4)
        self.assertAlmostEqual(frame.gyr_z, 1.1)
        self.assertAlmostEqual(frame.temp_imu, 43.1)
        self.assertIsNone(frame.pression)
        self.assertIsNone(frame.temp_bmp)
        self.assertIsNone(frame.altitude)
        self.assertIsNone(frame.v_bat)

    def test_reject_gyro_short_frame_bad_checksum(self) -> None:
        raw = bytearray(_build_gyro_frame(frame_id=42, gyr_x_raw=15, gyr_y_raw=-7, gyr_z_raw=250))
        raw[8] ^= 0x01
        self.assertIsNone(parse_frame(bytes(raw)))

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

    def test_parse_legacy_short_frame(self) -> None:
        frame = parse_frame(bytes.fromhex(LEGACY_SHORT_FRAME_HEX))
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.frame_id, 0x7779)
        self.assertIsNone(frame.altitude)
        self.assertIsNone(frame.pression)

    def test_serial_reader_extracts_legacy_short_frames(self) -> None:
        short_1 = bytes.fromhex("AA7779FFFFFFFFFFFFFFFFFF")
        short_2 = bytes.fromhex("AA777AFFFFFFFFFFFFFFFFFF")
        reader = SerialReader(port="TEST")
        reader._buffer = bytearray(b"\x00\x11" + short_1 + short_2)
        extracted_1 = reader._extract_frame()
        extracted_2 = reader._extract_frame()
        self.assertEqual(extracted_1, short_1)
        self.assertEqual(extracted_2, short_2)

    def test_serial_reader_extracts_gyro_short_frames(self) -> None:
        raw_1 = _build_gyro_frame(frame_id=1, gyr_x_raw=10, gyr_y_raw=20, gyr_z_raw=30)
        raw_2 = _build_gyro_frame(frame_id=2, gyr_x_raw=-10, gyr_y_raw=-20, gyr_z_raw=-30)
        reader = SerialReader(port="TEST")
        reader._buffer = bytearray(b"\x00\x11" + raw_1 + raw_2)
        extracted_1 = reader._extract_frame()
        extracted_2 = reader._extract_frame()
        self.assertEqual(extracted_1, raw_1)
        self.assertEqual(extracted_2, raw_2)

    def test_serial_reader_prioritizes_valid_31_byte_frame(self) -> None:
        raw = _build_frame(
            frame_id=512,
            acc_x_raw=100,
            acc_y_raw=200,
            acc_z_raw=300,
            gyr_x_raw=0x5500,
            gyr_y_raw=10,
            gyr_z_raw=20,
            temp_imu_raw=430,
            pression_raw=0xFFFFFFFF,
            temp_bmp_raw=-1,
            altitude_raw=0x7FFFFFFF,
            v_bat_raw=0xFFFF,
        )
        reader = SerialReader(port="TEST")
        reader._buffer = bytearray(raw)
        self.assertEqual(reader._extract_frame(), raw)

    def test_serial_reader_keeps_fragmented_31_byte_frame(self) -> None:
        raw = bytes.fromhex(REAL_FIRMWARE_FRAME_HEX)
        reader = SerialReader(port="TEST")
        reader._buffer = bytearray(raw[:12])

        self.assertIsNone(reader._extract_frame())
        self.assertEqual(reader._buffer, bytearray(raw[:12]))

        reader._buffer.extend(raw[12:])
        self.assertEqual(reader._extract_frame(), raw)


if __name__ == "__main__":
    unittest.main()
