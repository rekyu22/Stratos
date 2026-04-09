import random
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
        self._rng = random.Random()
        self._altitude_cm = 150.0
        self._altitude_target_cm = 150.0
        self._pressure_pa = 100874.0
        self._temp_imu_raw = 220.0
        self._temp_bmp_raw = 2220.0
        self._vbat_mv = 3900.0

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
        return self._build_frame(self._frame_id)

    @property
    def mode(self) -> str:
        return "sim"

    @property
    def source_detail(self) -> str:
        return f"{1.0 / self._period:.1f} Hz"

    def _build_frame(self, frame_id: int) -> bytes:
        if frame_id % 200 == 0:
            self._altitude_target_cm = self._rng.uniform(145.0, 165.0)

        self._altitude_cm += (self._altitude_target_cm - self._altitude_cm) * 0.035
        self._altitude_cm += self._rng.uniform(-0.35, 0.35)
        self._altitude_cm = _clamp(self._altitude_cm, 120.0, 250.0)

        expected_pressure = 100874.0 - (self._altitude_cm - 150.0) * 12.0
        self._pressure_pa += (expected_pressure - self._pressure_pa) * 0.07
        self._pressure_pa += self._rng.uniform(-1.2, 1.2)

        self._temp_imu_raw += self._rng.uniform(-0.25, 0.25)
        self._temp_imu_raw = _clamp(self._temp_imu_raw, 218.0, 235.0)

        self._temp_bmp_raw += self._rng.uniform(-0.18, 0.18)
        self._temp_bmp_raw = _clamp(self._temp_bmp_raw, 2190.0, 2300.0)

        self._vbat_mv -= 0.02
        self._vbat_mv += self._rng.uniform(-0.06, 0.01)
        self._vbat_mv = _clamp(self._vbat_mv, 3400.0, 3950.0)

        acc_x_raw = int(self._rng.uniform(-12.0, 12.0))
        acc_y_raw = int(self._rng.uniform(-12.0, 12.0))
        acc_z_raw = int(1000.0 + self._rng.uniform(-8.0, 8.0))

        gyr_x_raw = int(self._rng.uniform(-3.0, 3.0))
        gyr_y_raw = int(self._rng.uniform(-3.0, 3.0))
        gyr_z_raw = int(self._rng.uniform(-2.0, 2.0))

        payload = struct.pack(
            FRAME_FORMAT,
            frame_id,
            acc_x_raw,
            acc_y_raw,
            acc_z_raw,
            gyr_x_raw,
            gyr_y_raw,
            gyr_z_raw,
            int(round(self._temp_imu_raw)),
            int(round(self._pressure_pa)),
            int(round(self._temp_bmp_raw)),
            int(round(self._altitude_cm)),
            int(round(self._vbat_mv)),
        )
        checksum = _checksum(payload)
        return bytes([STX]) + payload + bytes([checksum, ETX])


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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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
