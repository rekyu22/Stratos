import math
import struct
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from model.protocol import ETX, FRAME_FORMAT, STX
from model.serial_reader import SerialReader

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None


class FrameSource(Protocol):
    def open(self) -> None:
        ...

    def close(self) -> None:
        ...

    def read_frame(self) -> Optional[bytes]:
        ...


@dataclass
class SerialSourceConfig:
    port: Optional[str] = None
    baudrate: int = 9600
    timeout: float = 1.0


class SerialFrameSource:
    def __init__(self, config: SerialSourceConfig):
        if not config.port:
            raise ValueError("serial port is required")
        self._config = config
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

    @property
    def mode(self) -> str:
        return "serial"

    @property
    def source_detail(self) -> str:
        return str(self._config.port)


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

    @property
    def mode(self) -> str:
        return "sim"

    @property
    def source_detail(self) -> str:
        return f"{1.0 / self._period:.1f} Hz"


class AutoFrameSource:
    def __init__(self, serial_config: SerialSourceConfig, sim_hz: float = 10.0):
        self._serial_config = serial_config
        self._sim_hz = sim_hz
        self._active = None
        self._mode = "auto"
        self._source_detail = "pending"

    def open(self) -> None:
        candidates = _candidate_ports(self._serial_config.port)
        for port in candidates:
            try:
                serial_source = SerialFrameSource(
                    SerialSourceConfig(
                        port=port,
                        baudrate=self._serial_config.baudrate,
                        timeout=self._serial_config.timeout,
                    )
                )
                serial_source.open()
                self._active = serial_source
                self._mode = "serial"
                self._source_detail = port
                return
            except Exception:
                continue

        sim_source = SimulatedFrameSource(hz=self._sim_hz)
        sim_source.open()
        self._active = sim_source
        self._mode = "sim"
        self._source_detail = f"{self._sim_hz:.1f} Hz fallback"

    def close(self) -> None:
        if self._active is not None:
            self._active.close()
            self._active = None

    def read_frame(self) -> Optional[bytes]:
        if self._active is None:
            return None
        return self._active.read_frame()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def source_detail(self) -> str:
        return self._source_detail


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


def _candidate_ports(configured_port: Optional[str]) -> list[str]:
    if configured_port:
        return [configured_port]
    if list_ports is None:
        return []

    ports = [port.device for port in list_ports.comports()]
    if not ports:
        return []

    preferred = []
    others = []
    for device in ports:
        lower = device.lower()
        if "usb" in lower or "acm" in lower or "com" in lower or "cu." in lower:
            preferred.append(device)
        else:
            others.append(device)
    return preferred + others
