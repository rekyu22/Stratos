from typing import Optional
from model.protocol import ETX, FRAME_LENGTH, GYRO_FRAME_LENGTH, LEGACY_SHORT_FRAME_LENGTH, STX

try:
    import serial
except ModuleNotFoundError:
    serial = None


class SerialReader:

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 1.0):
        self._port     = port
        self._baudrate = baudrate
        self._timeout  = timeout
        self._serial   = None
        self._buffer   = bytearray()

    def open(self) -> None:
        if serial is None:
            raise RuntimeError("pyserial is required. Install with: pip install pyserial")
        self._serial = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            timeout=self._timeout
        )
        self._buffer.clear()

    def close(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()

    def read_frame(self) -> Optional[bytes]:
        if self._serial is None or not self._serial.is_open:
            return None

        chunk = self._serial.read(self._serial.in_waiting or 1)
        if chunk:
            self._buffer.extend(chunk)

        return self._extract_frame()

    def _extract_frame(self) -> Optional[bytes]:
        while True:
            stx_index = self._buffer.find(STX)
            if stx_index == -1:
                self._buffer.clear()
                return None

            if stx_index > 0:
                del self._buffer[:stx_index]

            if len(self._buffer) >= GYRO_FRAME_LENGTH:
                candidate = bytes(self._buffer[:GYRO_FRAME_LENGTH])
                if candidate[-1] == ETX:
                    del self._buffer[:GYRO_FRAME_LENGTH]
                    return candidate

            if len(self._buffer) >= FRAME_LENGTH:
                candidate = bytes(self._buffer[:FRAME_LENGTH])
                if candidate[-1] == ETX:
                    del self._buffer[:FRAME_LENGTH]
                    return candidate

            if len(self._buffer) >= LEGACY_SHORT_FRAME_LENGTH and self._looks_like_legacy_short():
                candidate = bytes(self._buffer[:LEGACY_SHORT_FRAME_LENGTH])
                del self._buffer[:LEGACY_SHORT_FRAME_LENGTH]
                return candidate

            if len(self._buffer) < LEGACY_SHORT_FRAME_LENGTH:
                return None

            del self._buffer[0]

    def _looks_like_legacy_short(self) -> bool:
        if len(self._buffer) < LEGACY_SHORT_FRAME_LENGTH:
            return False
        candidate = self._buffer[:LEGACY_SHORT_FRAME_LENGTH]
        if candidate[0] != STX:
            return False
        if any(byte != 0xFF for byte in candidate[3:LEGACY_SHORT_FRAME_LENGTH]):
            return False
        if len(self._buffer) > LEGACY_SHORT_FRAME_LENGTH and self._buffer[LEGACY_SHORT_FRAME_LENGTH] != STX:
            return False
        return True
