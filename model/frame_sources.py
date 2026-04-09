import random
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
        self._rng = random.Random()
        self._elapsed_s = 0.0
        self._altitude_cm = 150.0
        self._altitude_target_cm = 220.0
        self._target_hold_s = 2.0
        self._vertical_speed_cms = 0.0
        self._vertical_accel_mps2 = 0.0
        self._roll_deg = 0.0
        self._pitch_deg = 0.0
        self._yaw_rate_dps = 0.0
        self._roll_target_deg = 0.0
        self._pitch_target_deg = 0.0
        self._last_roll_deg = 0.0
        self._last_pitch_deg = 0.0
        self._pressure_pa = 100874.0
        self._ambient_temp_c = 22.2
        self._temp_imu_raw = 220.0
        self._temp_bmp_raw = 2220.0
        self._vbat_mv = 3980.0

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
        dt = self._period
        self._elapsed_s += dt

        self._target_hold_s -= dt
        if self._target_hold_s <= 0.0:
            self._target_hold_s = self._rng.uniform(2.0, 4.5)
            self._altitude_target_cm = self._rng.uniform(120.0, 520.0)
            self._roll_target_deg = self._rng.uniform(-10.0, 10.0)
            self._pitch_target_deg = self._rng.uniform(-10.0, 10.0)
            self._yaw_rate_dps = self._rng.uniform(-35.0, 35.0)

        altitude_error = self._altitude_target_cm - self._altitude_cm
        accel_cmd_cms2 = 1.4 * altitude_error - 0.38 * self._vertical_speed_cms
        accel_cmd_cms2 = _clamp(accel_cmd_cms2, -140.0, 140.0)
        self._vertical_speed_cms += accel_cmd_cms2 * dt
        self._vertical_speed_cms *= 0.985
        self._altitude_cm += self._vertical_speed_cms * dt + self._rng.uniform(-0.25, 0.25)
        self._altitude_cm = _clamp(self._altitude_cm, 80.0, 650.0)
        self._vertical_accel_mps2 = accel_cmd_cms2 / 100.0

        self._last_roll_deg = self._roll_deg
        self._last_pitch_deg = self._pitch_deg
        self._roll_deg += 0.22 * (self._roll_target_deg - self._roll_deg) + self._rng.uniform(-0.4, 0.4)
        self._pitch_deg += 0.22 * (self._pitch_target_deg - self._pitch_deg) + self._rng.uniform(-0.4, 0.4)
        self._roll_deg = _clamp(self._roll_deg, -16.0, 16.0)
        self._pitch_deg = _clamp(self._pitch_deg, -16.0, 16.0)

        roll_rad = math.radians(self._roll_deg)
        pitch_rad = math.radians(self._pitch_deg)
        gravity_mg = 1000.0
        vertical_term_mg = (self._vertical_accel_mps2 / 9.80665) * 1000.0

        acc_x_raw = _avoid_sentinel_int16(
            int(round(gravity_mg * math.sin(pitch_rad) + self._rng.uniform(-3.0, 3.0)))
        )
        acc_y_raw = _avoid_sentinel_int16(
            int(round(-gravity_mg * math.sin(roll_rad) + self._rng.uniform(-3.0, 3.0)))
        )
        acc_z_raw = _avoid_sentinel_int16(
            int(
                round(
                    gravity_mg * math.cos(roll_rad) * math.cos(pitch_rad)
                    + vertical_term_mg
                    + self._rng.uniform(-4.0, 4.0)
                )
            )
        )

        gyr_x_dps = (self._roll_deg - self._last_roll_deg) / dt
        gyr_y_dps = (self._pitch_deg - self._last_pitch_deg) / dt
        gyr_z_dps = self._yaw_rate_dps + self._rng.uniform(-2.0, 2.0)
        gyr_x_raw = _avoid_sentinel_int16(int(round(gyr_x_dps * 10.0)))
        gyr_y_raw = _avoid_sentinel_int16(int(round(gyr_y_dps * 10.0)))
        gyr_z_raw = _avoid_sentinel_int16(int(round(gyr_z_dps * 10.0)))

        altitude_delta_m = (self._altitude_cm - 150.0) / 100.0
        pressure_ideal = 100874.0 * math.exp(-altitude_delta_m / 8434.5)
        self._pressure_pa += (pressure_ideal - self._pressure_pa) * 0.32 + self._rng.uniform(-0.8, 0.8)

        total_rotation = abs(gyr_x_dps) + abs(gyr_y_dps) + abs(gyr_z_dps)
        imu_target_raw = (self._ambient_temp_c + 0.9 + 0.012 * total_rotation) * 10.0
        self._temp_imu_raw += (imu_target_raw - self._temp_imu_raw) * 0.02 + self._rng.uniform(-0.05, 0.05)
        self._temp_imu_raw = _clamp(self._temp_imu_raw, 210.0, 260.0)

        bmp_target_raw = self._ambient_temp_c * 100.0
        self._temp_bmp_raw += (bmp_target_raw - self._temp_bmp_raw) * 0.01 + self._rng.uniform(-0.3, 0.3)
        self._temp_bmp_raw = _clamp(self._temp_bmp_raw, 2100.0, 2600.0)

        thrust_metric = 0.015 * total_rotation + 0.05 * abs(self._vertical_speed_cms) + 0.02 * abs(accel_cmd_cms2)
        drain_mv_s = 0.8 + thrust_metric
        self._vbat_mv -= drain_mv_s * dt
        self._vbat_mv = _clamp(self._vbat_mv, 3400.0, 3950.0)

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


def _avoid_sentinel_int16(value: int) -> int:
    value = int(_clamp(value, -32768, 32767))
    if value == -1:
        return -2
    return value


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
