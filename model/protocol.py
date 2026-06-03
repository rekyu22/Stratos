import struct
from dataclasses import dataclass
from typing import Optional

FRAME_LENGTH   = 31
GYRO_FRAME_LENGTH = 10
LEGACY_SHORT_FRAME_LENGTH = 12
STX            = 0xAA
ETX            = 0x55
SENSOR_ABSENT  = 0xFFFF

FRAME_FORMAT = ">H hhhhhh h I h i H"
GYRO_FRAME_FORMAT = ">Bhhh"
DATA_START   = 1
DATA_END     = 29
GYRO_DATA_START = 1
GYRO_DATA_END = 8


@dataclass
class StratosFrame:
    frame_id:  int
    acc_x:     Optional[float]
    acc_y:     Optional[float]
    acc_z:     Optional[float]
    gyr_x:     Optional[float]
    gyr_y:     Optional[float]
    gyr_z:     Optional[float]
    temp_imu:  Optional[float]
    pression:  Optional[float]
    temp_bmp:  Optional[float]
    altitude:  Optional[float]
    v_bat:     Optional[float]


def _is_absent(raw_value: int) -> bool:
    return (raw_value & 0xFFFF) == SENSOR_ABSENT


def _verify_checksum(raw: bytes) -> bool:
    expected = raw[DATA_END]
    computed = 0
    for byte in raw[DATA_START:DATA_END]:
        computed ^= byte
    return computed == expected


def _verify_gyro_checksum(raw: bytes) -> bool:
    expected = raw[GYRO_DATA_END]
    computed = 0
    for byte in raw[GYRO_DATA_START:GYRO_DATA_END]:
        computed ^= byte
    return computed == expected


def parse_frame(raw: bytes) -> Optional[StratosFrame]:
    if len(raw) == GYRO_FRAME_LENGTH:
        if raw[0] != STX or raw[-1] != ETX:
            return None
        if not _verify_gyro_checksum(raw):
            return None

        frame_id, gyr_x_raw, gyr_y_raw, gyr_z_raw = struct.unpack_from(
            GYRO_FRAME_FORMAT,
            raw,
            GYRO_DATA_START,
        )
        return StratosFrame(
            frame_id=frame_id,
            acc_x=None,
            acc_y=None,
            acc_z=None,
            gyr_x=gyr_x_raw / 10.0,
            gyr_y=gyr_y_raw / 10.0,
            gyr_z=gyr_z_raw / 10.0,
            temp_imu=None,
            pression=None,
            temp_bmp=None,
            altitude=None,
            v_bat=None,
        )

    if len(raw) == LEGACY_SHORT_FRAME_LENGTH:
        if raw[0] != STX:
            return None
        frame_id = int.from_bytes(raw[1:3], byteorder="big", signed=False)
        return StratosFrame(
            frame_id=frame_id,
            acc_x=None,
            acc_y=None,
            acc_z=None,
            gyr_x=None,
            gyr_y=None,
            gyr_z=None,
            temp_imu=None,
            pression=None,
            temp_bmp=None,
            altitude=None,
            v_bat=None,
        )

    if len(raw) != FRAME_LENGTH:
        return None
    if raw[0] != STX or raw[-1] != ETX:
        return None
    if not _verify_checksum(raw):
        return None

    fields = struct.unpack_from(FRAME_FORMAT, raw, DATA_START)
    (frame_id,
     acc_x_raw, acc_y_raw, acc_z_raw,
     gyr_x_raw, gyr_y_raw, gyr_z_raw,
     temp_imu_raw,
     pression_raw,
     temp_bmp_raw,
     altitude_raw,
     v_bat_raw) = fields

    acc_x    = None if _is_absent(acc_x_raw)    else acc_x_raw    / 1000.0
    acc_y    = None if _is_absent(acc_y_raw)    else acc_y_raw    / 1000.0
    acc_z    = None if _is_absent(acc_z_raw)    else acc_z_raw    / 1000.0
    gyr_x    = None if _is_absent(gyr_x_raw)    else gyr_x_raw    / 10.0
    gyr_y    = None if _is_absent(gyr_y_raw)    else gyr_y_raw    / 10.0
    gyr_z    = None if _is_absent(gyr_z_raw)    else gyr_z_raw    / 10.0
    temp_imu = None if _is_absent(temp_imu_raw) else temp_imu_raw / 10.0
    pression = None if pression_raw == 0xFFFFFFFF else pression_raw / 100.0
    temp_bmp = None if _is_absent(temp_bmp_raw) else temp_bmp_raw / 100.0
    altitude = None if altitude_raw == 0x7FFFFFFF else altitude_raw / 100.0
    v_bat    = None if _is_absent(v_bat_raw)    else v_bat_raw    / 1000.0

    return StratosFrame(
        frame_id=frame_id,
        acc_x=acc_x, acc_y=acc_y, acc_z=acc_z,
        gyr_x=gyr_x, gyr_y=gyr_y, gyr_z=gyr_z,
        temp_imu=temp_imu,
        pression=pression,
        temp_bmp=temp_bmp,
        altitude=altitude,
        v_bat=v_bat,
    )
