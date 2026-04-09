import csv
import os
from datetime import datetime
from model.protocol import StratosFrame

LOG_DIRECTORY = "logs"
CSV_HEADERS = [
    "timestamp",
    "frame_id",
    "acc_x_g", "acc_y_g", "acc_z_g",
    "gyr_x_dps", "gyr_y_dps", "gyr_z_dps",
    "temp_imu_c",
    "pression_hpa",
    "temp_bmp_c",
    "altitude_m",
    "v_bat_v",
]


def _format_value(value) -> str:
    if value is None:
        return "N/A"
    return str(value)


class TelemetryLogger:

    def __init__(self):
        self._file   = None
        self._writer = None

    def open(self) -> None:
        os.makedirs(LOG_DIRECTORY, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(LOG_DIRECTORY, f"stratos_{timestamp_str}.csv")
        self._file   = open(filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(CSV_HEADERS)
        self._file.flush()

    def log(self, frame: StratosFrame) -> None:
        if self._writer is None:
            return
        row = [
            datetime.now().isoformat(timespec="milliseconds"),
            frame.frame_id,
            _format_value(frame.acc_x),
            _format_value(frame.acc_y),
            _format_value(frame.acc_z),
            _format_value(frame.gyr_x),
            _format_value(frame.gyr_y),
            _format_value(frame.gyr_z),
            _format_value(frame.temp_imu),
            _format_value(frame.pression),
            _format_value(frame.temp_bmp),
            _format_value(frame.altitude),
            _format_value(frame.v_bat),
        ]
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file   = None
            self._writer = None
