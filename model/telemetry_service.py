from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from threading import Event, Lock, Thread
import time
from typing import Any, Deque, Dict, Optional

from model.logger import TelemetryLogger
from model.protocol import StratosFrame, parse_frame


@dataclass
class TelemetrySample:
    timestamp: str
    frame_id: int
    acc_x: Optional[float]
    acc_y: Optional[float]
    acc_z: Optional[float]
    gyr_x: Optional[float]
    gyr_y: Optional[float]
    gyr_z: Optional[float]
    temp_imu: Optional[float]
    pression: Optional[float]
    temp_bmp: Optional[float]
    altitude: Optional[float]
    v_bat: Optional[float]


class TelemetryService:
    def __init__(
        self,
        source: Any,
        logger: Optional[TelemetryLogger] = None,
        history_size: int = 600,
        link_timeout_s: float = 2.0,
    ):
        self._source = source
        self._logger = logger
        self._history: Deque[TelemetrySample] = deque(maxlen=history_size)
        self._latest: Optional[TelemetrySample] = None
        self._frames_received = 0
        self._frames_rejected = 0
        self._last_frame_time: Optional[float] = None
        self._last_frame_id: Optional[int] = None
        self._estimated_missing_frames = 0
        self._duplicate_frames = 0
        self._arrival_timestamps: Deque[float] = deque(maxlen=512)
        self._intervals_s: Deque[float] = deque(maxlen=512)
        self._link_timeout_s = link_timeout_s
        self._lock = Lock()
        self._stop = Event()
        self._thread: Optional[Thread] = None

    def start(self) -> None:
        self._source.open()
        if self._logger is not None:
            self._logger.open()
        self._start_reader_thread()

    def stop(self) -> None:
        self._stop_reader_thread()
        self._source.close()
        if self._logger is not None:
            self._logger.close()

    def switch_source(self, new_source: Any) -> Dict[str, Any]:
        self._stop_reader_thread()
        try:
            self._source.close()
        except Exception:
            pass
        self._source = new_source
        self._source.open()
        with self._lock:
            self._last_frame_time = None
            self._last_frame_id = None
            self._arrival_timestamps.clear()
            self._intervals_s.clear()
        self._start_reader_thread()
        return self.get_status()

    def get_latest(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._latest is None:
                return None
            return asdict(self._latest)

    def get_history(self, limit: int = 120) -> list[Dict[str, Any]]:
        with self._lock:
            sliced = list(self._history)[-limit:]
        return [asdict(sample) for sample in sliced]

    def get_status(self) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            last = self._last_frame_time
            age = None if last is None else now - last
            linked = age is not None and age <= self._link_timeout_s
            rx_fps = _compute_fps(self._arrival_timestamps)
            jitter_ms = _compute_jitter_ms(self._intervals_s)
            total_incoming = self._frames_received + self._frames_rejected
            reject_rate_pct = 0.0
            if total_incoming > 0:
                reject_rate_pct = (self._frames_rejected / total_incoming) * 100.0
            expected_total = self._frames_received + self._estimated_missing_frames
            drop_rate_pct = 0.0
            if expected_total > 0:
                drop_rate_pct = (self._estimated_missing_frames / expected_total) * 100.0
            source_mode = getattr(self._source, "mode", self._source.__class__.__name__.lower())
            source_detail = getattr(self._source, "source_detail", "")
            return {
                "frames_received": self._frames_received,
                "frames_rejected": self._frames_rejected,
                "last_frame_age_s": age,
                "link_ok": linked,
                "history_size": len(self._history),
                "rx_fps": rx_fps,
                "jitter_ms": jitter_ms,
                "estimated_missing_frames": self._estimated_missing_frames,
                "duplicate_frames": self._duplicate_frames,
                "reject_rate_pct": reject_rate_pct,
                "drop_rate_pct": drop_rate_pct,
                "source_mode": source_mode,
                "source_detail": source_detail,
            }

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            raw = self._source.read_frame()
            if raw is None:
                time.sleep(0.005)
                continue
            frame = parse_frame(raw)
            if frame is None:
                with self._lock:
                    self._frames_rejected += 1
                continue
            sample = _to_sample(frame)
            now = time.time()
            with self._lock:
                self._frames_received += 1
                if self._last_frame_time is not None:
                    self._intervals_s.append(now - self._last_frame_time)
                if self._last_frame_id is not None:
                    delta = (frame.frame_id - self._last_frame_id) & 0xFFFF
                    if delta == 0:
                        self._duplicate_frames += 1
                    elif delta > 1:
                        self._estimated_missing_frames += delta - 1
                self._last_frame_id = frame.frame_id
                self._last_frame_time = now
                self._arrival_timestamps.append(now)
                self._latest = sample
                self._history.append(sample)
            if self._logger is not None:
                self._logger.log(frame)

    def _start_reader_thread(self) -> None:
        self._stop.clear()
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _stop_reader_thread(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


def _to_sample(frame: StratosFrame) -> TelemetrySample:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return TelemetrySample(
        timestamp=timestamp,
        frame_id=frame.frame_id,
        acc_x=frame.acc_x,
        acc_y=frame.acc_y,
        acc_z=frame.acc_z,
        gyr_x=frame.gyr_x,
        gyr_y=frame.gyr_y,
        gyr_z=frame.gyr_z,
        temp_imu=frame.temp_imu,
        pression=frame.pression,
        temp_bmp=frame.temp_bmp,
        altitude=frame.altitude,
        v_bat=frame.v_bat,
    )


def _compute_fps(timestamps: Deque[float]) -> float:
    if len(timestamps) < 2:
        return 0.0
    duration = timestamps[-1] - timestamps[0]
    if duration <= 0:
        return 0.0
    return (len(timestamps) - 1) / duration


def _compute_jitter_ms(intervals_s: Deque[float]) -> float:
    if len(intervals_s) < 2:
        return 0.0
    mean = sum(intervals_s) / len(intervals_s)
    variance = sum((value - mean) ** 2 for value in intervals_s) / len(intervals_s)
    return math.sqrt(variance) * 1000.0
