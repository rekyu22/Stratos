import asyncio
import csv
import io
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from model.frame_sources import AutoFrameSource, SerialFrameSource, SerialSourceConfig, SimulatedFrameSource
from model.logger import TelemetryLogger
from model.telemetry_service import TelemetryService

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
STATIC_DIR = PROJECT_DIR / "view" / "web_static"
INDEX_FILE = STATIC_DIR / "index.html"


def _build_service() -> TelemetryService:
    mode = os.getenv("STRATOS_SOURCE", "auto").lower()
    with_logger = os.getenv("STRATOS_LOG", "1") == "1"
    logger = TelemetryLogger() if with_logger else None
    port = os.getenv("STRATOS_SERIAL_PORT")
    baud = int(os.getenv("STRATOS_SERIAL_BAUD", "9600"))
    timeout = float(os.getenv("STRATOS_SERIAL_TIMEOUT", "1.0"))
    hz = float(os.getenv("STRATOS_SIM_HZ", "10.0"))
    history_size = int(os.getenv("STRATOS_HISTORY_SIZE", "20000"))
    source = _build_source(mode=mode, port=port, baud=baud, timeout=timeout, sim_hz=hz)
    return TelemetryService(source=source, logger=logger, history_size=history_size)


def _build_source(mode: str, port: str | None, baud: int, timeout: float, sim_hz: float):
    mode = mode.lower()
    if mode == "serial":
        if port:
            return SerialFrameSource(SerialSourceConfig(port=port, baudrate=baud, timeout=timeout))
        return AutoFrameSource(
            SerialSourceConfig(port=port, baudrate=baud, timeout=timeout),
            sim_hz=sim_hz,
        )
    if mode == "sim":
        return SimulatedFrameSource(hz=sim_hz)
    if mode == "auto":
        return AutoFrameSource(
            SerialSourceConfig(port=port, baudrate=baud, timeout=timeout),
            sim_hz=sim_hz,
        )
    raise ValueError(f"Unsupported source mode: {mode}")


class SourceSwitchRequest(BaseModel):
    mode: str
    port: str | None = None
    baudrate: int | None = None
    timeout: float | None = None
    sim_hz: float | None = None


app = FastAPI(title="STRATOS Ground Station")
service = _build_service()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def _startup() -> None:
    service.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    service.stop()


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(str(INDEX_FILE))


@app.get("/api/status")
def api_status() -> Dict[str, Any]:
    return service.get_status()


@app.get("/api/latest")
def api_latest() -> Dict[str, Any]:
    latest = service.get_latest()
    return {"sample": latest}


@app.get("/api/history")
def api_history(points: int = Query(default=1200, ge=1, le=20000)) -> Dict[str, Any]:
    return {"samples": service.get_history(limit=points)}


@app.post("/api/source")
def api_switch_source(payload: SourceSwitchRequest) -> Dict[str, Any]:
    default_port = os.getenv("STRATOS_SERIAL_PORT")
    default_baud = int(os.getenv("STRATOS_SERIAL_BAUD", "9600"))
    default_timeout = float(os.getenv("STRATOS_SERIAL_TIMEOUT", "1.0"))
    default_sim_hz = float(os.getenv("STRATOS_SIM_HZ", "10.0"))

    mode = payload.mode.lower()
    port = payload.port if payload.port is not None else default_port
    baud = payload.baudrate if payload.baudrate is not None else default_baud
    timeout = payload.timeout if payload.timeout is not None else default_timeout
    sim_hz = payload.sim_hz if payload.sim_hz is not None else default_sim_hz

    try:
        new_source = _build_source(mode=mode, port=port, baud=baud, timeout=timeout, sim_hz=sim_hz)
        status = service.switch_source(new_source)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "status": status}


@app.get("/api/history.csv")
def api_history_csv(points: int = Query(default=2000, ge=1, le=50000)) -> Response:
    samples = service.get_history(limit=points)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "timestamp",
            "frame_id",
            "acc_x",
            "acc_y",
            "acc_z",
            "gyr_x",
            "gyr_y",
            "gyr_z",
            "temp_imu",
            "pression",
            "temp_bmp",
            "altitude",
            "v_bat",
        ]
    )
    for sample in samples:
        writer.writerow(
            [
                sample.get("timestamp"),
                sample.get("frame_id"),
                _fmt_csv(sample.get("acc_x")),
                _fmt_csv(sample.get("acc_y")),
                _fmt_csv(sample.get("acc_z")),
                _fmt_csv(sample.get("gyr_x")),
                _fmt_csv(sample.get("gyr_y")),
                _fmt_csv(sample.get("gyr_z")),
                _fmt_csv(sample.get("temp_imu")),
                _fmt_csv(sample.get("pression")),
                _fmt_csv(sample.get("temp_bmp")),
                _fmt_csv(sample.get("altitude")),
                _fmt_csv(sample.get("v_bat")),
            ]
        )
    content = output.getvalue()
    headers = {"Content-Disposition": "attachment; filename=stratos_history.csv"}
    return Response(content=content, media_type="text/csv", headers=headers)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    points = int(websocket.query_params.get("points", "20000"))
    points = max(1, min(points, 50000))
    period_ms = int(websocket.query_params.get("period_ms", "250"))
    period_ms = max(100, min(period_ms, 2000))
    period_s = period_ms / 1000.0
    forced_mode = websocket.query_params.get("mode")

    if forced_mode:
        default_port = os.getenv("STRATOS_SERIAL_PORT")
        default_baud = int(os.getenv("STRATOS_SERIAL_BAUD", "9600"))
        default_timeout = float(os.getenv("STRATOS_SERIAL_TIMEOUT", "1.0"))
        default_sim_hz = float(os.getenv("STRATOS_SIM_HZ", "10.0"))
        try:
            current_mode = str(service.get_status().get("source_mode", ""))
            if current_mode != forced_mode.lower():
                new_source = _build_source(
                    mode=forced_mode,
                    port=default_port,
                    baud=default_baud,
                    timeout=default_timeout,
                    sim_hz=default_sim_hz,
                )
                service.switch_source(new_source)
        except Exception as exc:
            await websocket.send_json({"error": f"switch_mode_failed: {exc}"})

    loop = asyncio.get_event_loop()
    initial_status = service.get_status()
    initial_latest = service.get_latest()
    initial_history = service.get_history(limit=points)
    await websocket.send_json(
        {
            "status": initial_status,
            "latest": initial_latest,
            "history": initial_history,
            "append": [],
        }
    )

    last_sent_received = int(initial_status.get("frames_received", 0))
    last_sent_at = loop.time()

    try:
        while True:
            status = service.get_status()
            frames_received = int(status.get("frames_received", 0))
            now = loop.time()
            should_send = False
            if frames_received != last_sent_received:
                should_send = True
            elif now - last_sent_at >= period_s:
                should_send = True

            if should_send:
                latest = service.get_latest()
                append = []
                if frames_received > last_sent_received and latest is not None:
                    append = [latest]
                payload = {
                    "status": status,
                    "latest": latest,
                    "append": append,
                }
                await websocket.send_json(payload)
                last_sent_received = frames_received
                last_sent_at = now

            await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        return


def _fmt_csv(value: Any) -> str:
    if value is None:
        return "N/A"
    return str(value)
