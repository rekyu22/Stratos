from typing import Optional
from model.protocol import ETX, FRAME_LENGTH, STX

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

            if len(self._buffer) < FRAME_LENGTH:
                return None

            candidate = bytes(self._buffer[:FRAME_LENGTH])
            if candidate[-1] == ETX:
                del self._buffer[:FRAME_LENGTH]
                return candidate

            del self._buffer[0]
