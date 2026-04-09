import math
import struct
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from protocol import ETX, FRAME_FORMAT, STX
from serial_reader import SerialReader


class FrameSource(Protocol):
    def open(self) -> None:
        ...

    def close(self) -> None:
        ...

    def read_frame(self) -> Optional[bytes]:
        ...


@dataclass
class SerialSourceConfig:
    port: str
    baudrate: int = 9600
    timeout: float = 1.0


class SerialFrameSource:
    def __init__(self, config: SerialSourceConfig):
        self._reader = SerialReader(
            port=config.port,
            baudrate=config.baudrate,
            timeout=config.timeout,
        )

    def open(self) -> None:
        self._reader.open()

    def close(self) -> None:
        self._reader.close()

    def read_frame(self) -> Optional[bytes]:
        return self._reader.read_frame()


class SimulatedFrameSource:
    def __init__(self, hz: float = 10.0):
        self._period = 1.0 / hz
        self._opened = False
        self._frame_id = 0
        self._next_ts = 0.0
        self._phase = 0.0

    def open(self) -> None:
        self._opened = True
        self._next_ts = time.time()

    def close(self) -> None:
        self._opened = False

    def read_frame(self) -> Optional[bytes]:
        if not self._opened:
            return None

        now = time.time()
        if now < self._next_ts:
            time.sleep(min(self._next_ts - now, self._period))

        self._next_ts += self._period
        self._frame_id = (self._frame_id + 1) & 0xFFFF
        self._phase += 0.15
        return _build_simulated_frame(self._frame_id, self._phase)


def _checksum(payload: bytes) -> int:
    checksum = 0
    for byte in payload:
        checksum ^= byte
    return checksum


def _build_simulated_frame(frame_id: int, phase: float) -> bytes:
    acc_x_raw = int(10.0 * math.sin(phase))
    acc_y_raw = int(10.0 * math.cos(phase * 0.7))
    acc_z_raw = int(1000 + 15.0 * math.sin(phase * 1.3))
    gyr_x_raw = int(3.0 * math.sin(phase * 1.1))
    gyr_y_raw = int(3.0 * math.cos(phase * 0.9))
    gyr_z_raw = int(2.0 * math.sin(phase * 1.5))
    temp_imu_raw = int(220 + 4.0 * math.sin(phase * 0.2))
    pression_raw = int(100874 + 35.0 * math.sin(phase * 0.6))
    temp_bmp_raw = int(2220 + 12.0 * math.cos(phase * 0.25))
    altitude_raw = int(150 + 8.0 * math.sin(phase * 0.5))
    v_bat_raw = int(3900 - 40.0 * (0.5 + 0.5 * math.sin(phase * 0.1)))

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
    checksum = _checksum(payload)
    return bytes([STX]) + payload + bytes([checksum, ETX])
