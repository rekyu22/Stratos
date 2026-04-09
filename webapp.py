import asyncio
import csv
import io
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from frame_sources import SerialFrameSource, SerialSourceConfig, SimulatedFrameSource
from logger import TelemetryLogger
from telemetry_service import TelemetryService

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web_static"
INDEX_FILE = STATIC_DIR / "index.html"


def _build_service() -> TelemetryService:
    mode = os.getenv("STRATOS_SOURCE", "sim").lower()
    with_logger = os.getenv("STRATOS_LOG", "1") == "1"
    logger = TelemetryLogger() if with_logger else None

    if mode == "serial":
        port = os.getenv("STRATOS_SERIAL_PORT", "COM3")
        baud = int(os.getenv("STRATOS_SERIAL_BAUD", "9600"))
        timeout = float(os.getenv("STRATOS_SERIAL_TIMEOUT", "1.0"))
        source = SerialFrameSource(SerialSourceConfig(port=port, baudrate=baud, timeout=timeout))
    else:
        hz = float(os.getenv("STRATOS_SIM_HZ", "10.0"))
        source = SimulatedFrameSource(hz=hz)

    return TelemetryService(source=source, logger=logger)


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
def api_history(points: int = Query(default=120, ge=1, le=2000)) -> Dict[str, Any]:
    return {"samples": service.get_history(limit=points)}


@app.get("/api/history.csv")
def api_history_csv(points: int = Query(default=600, ge=1, le=10000)) -> Response:
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
    points = int(websocket.query_params.get("points", "120"))
    points = max(1, min(points, 2000))
    period_ms = int(websocket.query_params.get("period_ms", "250"))
    period_ms = max(100, min(period_ms, 2000))
    period_s = period_ms / 1000.0

    try:
        while True:
            payload = {
                "status": service.get_status(),
                "latest": service.get_latest(),
                "history": service.get_history(limit=points),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(period_s)
    except WebSocketDisconnect:
        return


def _fmt_csv(value: Any) -> str:
    if value is None:
        return "N/A"
    return str(value)
