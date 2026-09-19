"""FarmGuard AI FastAPI server and ESP32 telemetry gateway."""

from __future__ import annotations

import csv
import io
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from farmguard_engine import DeviceConfig, SCENARIOS, SensorReading, evaluate, simulated_reading


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DB_PATH = Path(os.getenv("FARMGUARD_DB", ROOT / "farmguard.db"))
STARTED_AT = time.monotonic()


class TelemetryPacket(BaseModel):
    device_id: str = Field(min_length=3, max_length=80)
    token: str = Field(min_length=4, max_length=160)
    sequence: int = Field(ge=0)
    distance_cm: float = Field(ge=0, le=500)
    light_raw: int = Field(ge=0, le=4095)


class SimulationRequest(BaseModel):
    enabled: bool
    scenario: str = "healthy"


class BuzzerTestRequest(BaseModel):
    mode: Literal["OFF", "PULSE", "ALARM"]
    duration_seconds: int = Field(default=5, ge=1, le=30)


class ConfigUpdate(BaseModel):
    profile: Literal["level", "perimeter", "combined"] | None = None
    mount_height_cm: float | None = Field(default=None, ge=20, le=500)
    invert_light: bool | None = None
    level_warning_pct: float | None = Field(default=None, ge=5, le=90)
    level_critical_pct: float | None = Field(default=None, ge=1, le=80)
    proximity_warning_cm: float | None = Field(default=None, ge=5, le=200)
    proximity_critical_cm: float | None = Field(default=None, ge=2, le=100)


class EventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self._initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    distance_cm REAL NOT NULL,
                    level_pct REAL NOT NULL,
                    proximity_risk_pct REAL NOT NULL,
                    light_raw INTEGER NOT NULL,
                    light_pct REAL NOT NULL,
                    health_score INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    buzzer_mode TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    action TEXT NOT NULL,
                    source TEXT NOT NULL
                );
                """
            )

    def add_reading(self, device_id: str, reading: SensorReading, decision: dict) -> None:
        with self.lock, self.connect() as db:
            db.execute(
                """INSERT INTO readings (
                    recorded_at, device_id, source, distance_cm, level_pct,
                    proximity_risk_pct, light_raw, light_pct, health_score, status, buzzer_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    reading.observed_at.isoformat(), device_id, reading.source, reading.distance_cm,
                    decision["level_pct"], decision["proximity_risk_pct"], reading.light_raw,
                    decision["light_pct"], decision["health_score"], decision["status"], decision["buzzer_mode"],
                ),
            )

    def add_event(self, severity: str, title: str, detail: str, action: str, source: str) -> None:
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT INTO events (recorded_at, severity, title, detail, action, source) VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), severity, title, detail, action, source),
            )

    def rows(self, table: str, limit: int) -> list[dict[str, Any]]:
        if table not in {"readings", "events"}:
            raise ValueError("Invalid table")
        with self.lock, self.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,))]


class FarmState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.store = EventStore(DB_PATH)
        self.config = DeviceConfig(token=os.getenv("FARMGUARD_DEVICE_TOKEN", "farmguard-device-01"))
        self.simulation_enabled = True
        self.scenario = "healthy"
        self.tick = 0
        self.last_reading: SensorReading | None = None
        self.last_decision: dict[str, Any] | None = None
        self.last_hardware_at: datetime | None = None
        self.last_sequence = -1
        self.last_signature: tuple | None = None
        self.rejected_packets = 0
        self.buzzer_override: tuple[str, float] | None = None
        self._simulate(force=True)

    def _record(self, reading: SensorReading, decision: dict) -> None:
        self.last_reading = reading
        self.last_decision = decision
        self.store.add_reading(self.config.device_id, reading, decision)
        signature = (decision["status"], tuple(decision["reasons"]))
        if signature != self.last_signature:
            self.last_signature = signature
            title = {"GOOD": "Conditions stable", "WATCH": "Attention recommended", "ACTION": "Action required"}[decision["status"]]
            self.store.add_event(
                decision["severity"], title, "; ".join(decision["reasons"]), " ".join(decision["actions"]), reading.source
            )

    def _simulate(self, force: bool = False) -> None:
        if not self.simulation_enabled:
            return
        now = datetime.now(timezone.utc)
        if not force and self.last_reading and (now - self.last_reading.observed_at).total_seconds() < 1.5:
            return
        self.tick += 1
        reading, expected_day = simulated_reading(self.scenario, self.config, self.tick, now)
        self._record(reading, evaluate(reading, self.config, expected_day))

    def effective_buzzer(self) -> str:
        if self.buzzer_override:
            mode, expires = self.buzzer_override
            if time.monotonic() < expires:
                return mode
            self.buzzer_override = None
        return self.last_decision["buzzer_mode"] if self.last_decision else "OFF"

    def ingest(self, packet: TelemetryPacket) -> dict:
        with self.lock:
            if packet.device_id != self.config.device_id or packet.token != self.config.token:
                self.rejected_packets += 1
                self.store.add_event("critical", "Telemetry rejected", f"Unknown or invalid device: {packet.device_id}", "Verify the device ID and token.", "security")
                raise PermissionError("Invalid device ID or token")
            if packet.sequence <= self.last_sequence:
                self.rejected_packets += 1
                raise RuntimeError("Sequence must increase to prevent replayed telemetry")
            self.last_sequence = packet.sequence
            self.simulation_enabled = False
            now = datetime.now(timezone.utc)
            reading = SensorReading(packet.distance_cm, packet.light_raw, packet.sequence, "esp32", now)
            decision = evaluate(reading, self.config)
            self.last_hardware_at = now
            self._record(reading, decision)
            return {
                "accepted": True,
                "server_time": now.isoformat(),
                "buzzer_mode": self.effective_buzzer(),
                "sample_interval_ms": 2000,
                "decision": decision,
            }

    def snapshot(self, include_integrator: bool = False) -> dict:
        with self.lock:
            self._simulate()
            now = datetime.now(timezone.utc)
            hardware_age = (now - self.last_hardware_at).total_seconds() if self.last_hardware_at else None
            connected = hardware_age is not None and hardware_age < 8
            stale = not self.simulation_enabled and (hardware_age is None or hardware_age > 12)
            decision = dict(self.last_decision or {})
            if stale:
                decision.update(
                    health_score=25,
                    status="ACTION",
                    severity="critical",
                    buzzer_mode="ALARM",
                    reasons=["The ESP32 has stopped sending telemetry"],
                    actions=["Check ESP32 power, Wi-Fi, and the API address."],
                )
            decision["buzzer_mode"] = self.effective_buzzer()
            result = {
                "updated_at": now.isoformat(),
                "device": {
                    "id": self.config.device_id,
                    "name": self.config.name,
                    "zone": self.config.zone,
                    "connected": connected,
                    "hardware_age_seconds": round(hardware_age, 1) if hardware_age is not None else None,
                },
                "source": self.last_reading.source if self.last_reading else "none",
                "simulation": {"enabled": self.simulation_enabled, "scenario": self.scenario},
                "decision": decision,
            }
            if include_integrator:
                result.update(
                    raw={
                        "distance_cm": self.last_reading.distance_cm,
                        "light_raw": self.last_reading.light_raw,
                        "sequence": self.last_reading.sequence,
                    } if self.last_reading else {},
                    config=self.config.public_dict(include_token=True),
                    rejected_packets=self.rejected_packets,
                    uptime_seconds=round(time.monotonic() - STARTED_AT),
                )
            return result


state = FarmState()
app = FastAPI(title="FarmGuard AI", version="2.0.0", docs_url="/api/docs", redoc_url=None)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "FarmGuard AI", "version": "2.0.0"}


@app.get("/api/v1/state")
def get_state() -> dict:
    return state.snapshot()


@app.get("/api/v1/integrator/state")
def get_integrator_state() -> dict:
    return state.snapshot(include_integrator=True)


@app.get("/api/v1/history")
def get_history(limit: int = Query(80, ge=1, le=500)) -> dict:
    return {"readings": list(reversed(state.store.rows("readings", limit)))}


@app.get("/api/v1/events")
def get_events(limit: int = Query(50, ge=1, le=500)) -> dict:
    return {"events": state.store.rows("events", limit)}


@app.post("/api/v1/telemetry")
def post_telemetry(packet: TelemetryPacket) -> dict:
    try:
        return state.ingest(packet)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/integrator/simulation")
def set_simulation(request: SimulationRequest) -> dict:
    if request.scenario not in SCENARIOS:
        raise HTTPException(status_code=422, detail="Unknown scenario")
    with state.lock:
        state.simulation_enabled = request.enabled
        state.scenario = request.scenario
        if request.scenario == "intrusion":
            state.config.profile = "perimeter"
        elif request.scenario == "multi-risk":
            state.config.profile = "combined"
        elif request.scenario == "low-level":
            state.config.profile = "level"
        state._simulate(force=True)
    return state.snapshot(include_integrator=True)


@app.post("/api/v1/integrator/buzzer-test")
def test_buzzer(request: BuzzerTestRequest) -> dict:
    with state.lock:
        state.buzzer_override = (request.mode, time.monotonic() + request.duration_seconds)
        state.store.add_event("warning" if request.mode != "OFF" else "healthy", "Buzzer test", f"Integrator requested {request.mode}", "No farm action required; this is a hardware test.", "integrator")
    return {"ok": True, "mode": request.mode, "duration_seconds": request.duration_seconds}


@app.patch("/api/v1/integrator/config")
def update_config(request: ConfigUpdate) -> dict:
    changes = request.model_dump(exclude_none=True)
    with state.lock:
        candidate = DeviceConfig(**state.config.public_dict(include_token=True))
        for key, value in changes.items():
            setattr(candidate, key, value)
        if candidate.level_critical_pct >= candidate.level_warning_pct:
            raise HTTPException(status_code=422, detail="Critical level must be lower than warning level")
        if candidate.proximity_critical_cm >= candidate.proximity_warning_cm:
            raise HTTPException(status_code=422, detail="Critical proximity must be lower than warning proximity")
        state.config = candidate
        if state.last_reading:
            state._record(state.last_reading, evaluate(state.last_reading, state.config))
    return {"ok": True, "config": state.config.public_dict(include_token=True)}


@app.get("/api/v1/export/{kind}.csv")
def export_csv(kind: Literal["readings", "events"]) -> Response:
    rows = state.store.rows(kind, 500)
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="farmguard-{kind}.csv"'})


@app.get("/")
def owner_dashboard() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/integrator")
def integrator_dashboard() -> FileResponse:
    return FileResponse(WEB / "integrator.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("FARMGUARD_HOST", "0.0.0.0"), port=int(os.getenv("PORT", "7860")))
