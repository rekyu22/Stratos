import os
import math
import time

from model.logger import TelemetryLogger
from model.protocol import StratosFrame, parse_frame
from model.serial_reader import SerialReader

SERIAL_PORT    = os.getenv("STRATOS_SERIAL_PORT", "COM4")
SERIAL_BAUD    = int(os.getenv("STRATOS_SERIAL_BAUD", "9600"))
LINK_TIMEOUT_S = 2.0


def _format_field(label: str, value, unit: str) -> str:
    if value is None:
        return f"  {label:<18} N/A"
    return f"  {label:<18} {value:>8.3f}  {unit}"


def display_frame(frame: StratosFrame) -> None:
    gyro_speed = None
    if frame.gyr_x is not None or frame.gyr_y is not None or frame.gyr_z is not None:
        gyro_speed = math.sqrt(
            (frame.gyr_x or 0.0) ** 2 +
            (frame.gyr_y or 0.0) ** 2 +
            (frame.gyr_z or 0.0) ** 2
        )

    print("\033[2J\033[H", end="")
    print("=" * 45)
    print(f"  STRATOS GYRO -- Trame #{frame.frame_id}")
    print("=" * 45)
    print("  [ Gyroscope ]")
    print(_format_field("Gyr X", frame.gyr_x, "°/s"))
    print(_format_field("Gyr Y", frame.gyr_y, "°/s"))
    print(_format_field("Gyr Z", frame.gyr_z, "°/s"))
    print(_format_field("Rotation", gyro_speed, "°/s"))
    print("=" * 45)


def run() -> None:
    reader = SerialReader(port=SERIAL_PORT, baudrate=SERIAL_BAUD)
    logger = TelemetryLogger()

    reader.open()
    logger.open()

    print(f"Station sol STRATOS -- {SERIAL_PORT} @ {SERIAL_BAUD} bps")
    print("En attente de trames... (Ctrl+C pour quitter)")

    last_frame_time = time.time()
    frames_received = 0
    frames_rejected = 0

    try:
        while True:
            raw = reader.read_frame()

            if raw is None:
                elapsed = time.time() - last_frame_time
                if elapsed > LINK_TIMEOUT_S:
                    print(f"\r[LIAISON PERDUE -- {elapsed:.1f}s sans trame]", end="")
                continue

            frame = parse_frame(raw)

            if frame is None:
                frames_rejected += 1
                continue

            frames_received  += 1
            last_frame_time   = time.time()

            display_frame(frame)
            logger.log(frame)
            print(f"  Recues: {frames_received}   Rejetees: {frames_rejected}")

    except KeyboardInterrupt:
        print("\nArret demande par l'utilisateur.")

    finally:
        reader.close()
        logger.close()
        print("Connexion fermee. Logs sauvegardes.")


if __name__ == "__main__":
    run()
