"""In-memory FarmGuard Challenge Lab scenarios.

Challenge readings are intentionally ephemeral.  They use the same FarmSensorReading
and risk engine as ESP32 data but are never written to the production readings table.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from farmguard_engine import FarmSensorReading

CHALLENGES = {
    "database-security": "Database & Security",
    "sensor-crazy": "Sensor Gone Crazy",
    "alien-attack": "Alien Attack",
    "water-crisis": "Water Crisis",
    "sensor-failure": "Sensor Failure",
    "fun-box": "Fun Box",
    "perfect-storm": "Final Boss: Perfect Storm",
}

QUICK_SCENARIOS = {
    "HEAT WAVE": {"temperature": 43, "humidity": 24, "soil_moisture": 28},
    "FLOOD": {"soil_moisture": 98, "water_level": 100, "steam": 3600},
    "DROUGHT": {"temperature": 41, "humidity": 19, "soil_moisture": 7, "water_level": 18},
    "ALIEN": {"motion": True, "ultrasonic_distance": 7, "light": 100},
    "ANIMAL": {"motion": True, "ultrasonic_distance": 24},
    "NIGHT": {"light": 20, "temperature": 23},
    "BREAK SENSOR": {"soil_moisture": None},
}

DEFAULT_FUN_VALUES = {
    "temperature": 29.0, "humidity": 66.0, "soil_moisture": 62.0,
    "light": 2580, "ultrasonic_distance": 42.0, "motion": False,
    "steam": 420, "water_level": 72.0,
}

@dataclass
class ChallengeEngine:
    active_mode: str | None = None
    tick: int = 0
    started_at: float = 0.0
    last_step_at: float = 0.0
    fun_values: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_FUN_VALUES))
    buffered_readings: list[dict[str, Any]] = field(default_factory=list)
    ephemeral_history: list[dict[str, Any]] = field(default_factory=list)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    latest_meta: dict[str, Any] = field(default_factory=dict)

    def start(self, mode: str) -> None:
        if mode not in CHALLENGES:
            raise ValueError("Unknown challenge")
        self.active_mode, self.tick, self.started_at, self.last_step_at = mode, 0, time.monotonic(), 0
        self.buffered_readings.clear(); self.ephemeral_history.clear(); self.event_log.clear(); self.latest_meta = {}
        self._event("warning", f"{CHALLENGES[mode]} started", "Training simulation only — real farm records are protected.")

    def stop(self) -> None:
        if self.active_mode:
            self._event("healthy", "Challenge stopped", "Returning to normal FarmGuard simulation.")
        self.active_mode, self.tick, self.latest_meta = None, 0, {}
        self.buffered_readings.clear(); self.ephemeral_history.clear()

    def reset(self) -> None:
        mode = self.active_mode
        if mode: self.start(mode)

    def configure_fun_box(self, values: dict[str, Any], scenario: str | None = None) -> None:
        self.start("fun-box") if self.active_mode != "fun-box" else None
        if scenario == "RANDOM CHAOS":
            rng = random.Random(time.time_ns())
            values = {"temperature": rng.uniform(-10, 55), "humidity": rng.uniform(5, 100),
                      "soil_moisture": rng.uniform(0, 100), "light": rng.randint(0, 4095),
                      "ultrasonic_distance": rng.uniform(2, 250), "motion": rng.choice([True, False]),
                      "steam": rng.randint(0, 4095), "water_level": rng.uniform(0, 100)}
        elif scenario:
            values = {**QUICK_SCENARIOS.get(scenario, {}), **values}
        self.fun_values.update(values)
        self._event("warning", scenario or "Manual values changed", "Fun Box values entered the shared sensor pipeline.")

    def _event(self, severity: str, title: str, detail: str) -> None:
        self.event_log.insert(0, {"recorded_at": datetime.now(timezone.utc).isoformat(), "severity": severity,
                                  "title": title, "detail": detail, "action": "Training scenario", "source": "challenge"})
        del self.event_log[30:]

    def due(self) -> bool:
        return bool(self.active_mode) and time.monotonic() - self.last_step_at >= 1.8

    def step(self, device_id: str) -> tuple[FarmSensorReading, dict[str, Any]] | None:
        if not self.due(): return None
        self.last_step_at = time.monotonic(); self.tick += 1
        values = dict(DEFAULT_FUN_VALUES); meta: dict[str, Any] = {"mode": self.active_mode, "name": CHALLENGES[self.active_mode], "tick": self.tick}
        mode = self.active_mode

        if mode == "database-security":
            phase = self.tick % 9
            db_status = "DATABASE OFFLINE" if 2 <= phase <= 5 else "SYNCING" if phase == 6 else "RECOVERED" if phase == 7 else "SECURE"
            security = "ATTACK DETECTED" if phase in {3, 4} else "SECURE"
            if db_status == "DATABASE OFFLINE": self.buffered_readings.append({"tick": self.tick, **values})
            if db_status in {"SYNCING", "RECOVERED"}: self.buffered_readings.clear()
            meta.update(database_status=db_status, security_status=security, buffered_count=len(self.buffered_readings),
                        blocked_requests=1 if security == "ATTACK DETECTED" else 0,
                        message="Invalid API key and abnormal payload blocked" if security != "SECURE" else "API and database protections operating")
        elif mode == "sensor-crazy":
            raw = [150, -80, 29][(self.tick - 1) % 3]
            soil_raw = [10, 95, 2][(self.tick - 1) % 3]
            distance_raw = [-4, 9999, 42][(self.tick - 1) % 3]
            values.update(temperature=29 if raw not in range(-40, 101) else raw, soil_moisture=62, ultrasonic_distance=42)
            anomalies = [{"sensor":"temperature","raw":raw,"valid":-40 <= raw <= 100,"reason":"Outside physical range" if not -40 <= raw <= 100 else "Valid","reliability":35,"used":values["temperature"]},
                         {"sensor":"soil moisture","raw":soil_raw,"valid":False,"reason":"Impossible rate of change","reliability":42,"used":62},
                         {"sensor":"ultrasonic","raw":distance_raw,"valid":0 <= distance_raw <= 500,"reason":"Outside sensor range" if not 0 <= distance_raw <= 500 else "Valid","reliability":38,"used":42}]
            meta.update(anomalies=anomalies, reliability=38, message="Outliers flagged; last trusted values used")
        elif mode == "alien-attack":
            values.update(motion=True, ultrasonic_distance=6.5, light=80 if self.tick % 2 else 3900)
            meta.update(threat="UNKNOWN FARM INTRUSION", confidence=94, threat_level="HIGH",
                        message="Game simulation: combined motion, distance, and light anomaly. This does not claim aliens exist.",
                        triggered_actions=["Sound local alarm", "Preserve event evidence", "Ask a person to inspect safely"])
        elif mode == "water-crisis":
            progress = min(self.tick, 12); values.update(soil_moisture=max(5, 68-progress*5), temperature=min(44, 28+progress*1.3),
                                                         humidity=max(18, 68-progress*4), water_level=max(4, 76-progress*6))
            stress = round(min(100, (100-values["soil_moisture"])*.35 + max(0, values["temperature"]-30)*2 + (100-values["water_level"])*.35))
            status = "CRITICAL WATER ALERT" if stress >= 75 else "HIGH WATER STRESS" if stress >= 50 else "DRY" if stress >= 25 else "NORMAL"
            meta.update(water_status=status, stress_score=stress, message=f"Crop/water stress is {stress}/100",
                        priority_plan=["Irrigate critical zone", "Check water reservoir", "Verify soil sensor", "Monitor moisture recovery"])
        elif mode == "sensor-failure":
            kinds = ["disconnected", "stale/frozen", "noisy", "heartbeat timeout"]; kind = kinds[(self.tick-1) % len(kinds)]
            values["soil_moisture"] = None
            meta.update(failed_sensor="soil moisture", failure_type=kind, sensor_online=False, reliability=12,
                        last_reading="Unavailable in this challenge step", fallback="Ignore failed sensor; continue with climate and water sensors",
                        healthy_sensors="7/8", message=f"Soil sensor {kind}; remaining sensors continue operating")
        elif mode == "fun-box":
            values.update(self.fun_values); meta.update(message="Manual values are flowing through the normal risk engine")
        elif mode == "perfect-storm":
            p=min(self.tick,10); values.update(temperature=30+p*1.4, soil_moisture=max(6,60-p*6), humidity=max(20,65-p*4),
                                               water_level=max(5,70-p*7), motion=p>=4, ultrasonic_distance=8 if p>=5 else 45,
                                               steam=3400 if p>=6 else 420)
            db_status="DATABASE OFFLINE" if 3<=p<=7 else "SYNCING" if p==8 else "RECOVERED" if p>=9 else "SECURE"
            security="ATTACK DETECTED" if p>=6 else "SECURE"; healthy=max(3,8-(p//2)); system_health=max(12,100-p*8)
            score=min(96,56+p*4) if p>=9 else None
            meta.update(system_health=system_health, farm_risk="CRITICAL" if p>=6 else "HIGH" if p>=3 else "WARNING",
                        database_status=db_status, security_status=security, healthy_sensors=f"{healthy}/8",
                        water_status="CRITICAL" if values["water_level"]<20 else "DECLINING", intrusion_status="DETECTED" if values["motion"] else "CLEAR",
                        emergency_plan=["Protect irrigation and water supply", "Ignore corrupted sensor readings", "Use trusted fallback estimates",
                                        "Block unauthorized API requests", "Buffer data while the database is offline", "Investigate movement safely", "Resync buffered data after recovery"],
                        survival_score=score, final_result=f"{score}/100 — FARM SAVED" if score else "Challenge in progress",
                        scorecard={"threats_detected":p,"correct_responses":p,"false_alarms":0,"sensor_recovery":p>=9,"database_recovery":p>=9,"security_defence":"ACTIVE"},
                        message="One prioritized emergency plan is active")

        now=datetime.now(timezone.utc)
        reading=FarmSensorReading(device_id=device_id,sequence=self.tick,observed_at=now,source=f"challenge:{mode}",uptime=round(time.monotonic()-self.started_at),**values)
        self.latest_meta=meta
        if self.tick in {1,3,6,9}: self._event("critical" if mode=="perfect-storm" and self.tick>=6 else "warning", CHALLENGES[mode], meta.get("message","Challenge updated"))
        return reading, meta

    def add_history(self, row: dict[str, Any]) -> None:
        self.ephemeral_history.append(row); del self.ephemeral_history[:-120]

    def snapshot(self) -> dict[str, Any]:
        return {"active": self.active_mode is not None, "mode": self.active_mode,
                "name": CHALLENGES.get(self.active_mode), "available": CHALLENGES,
                "meta": self.latest_meta, "fun_values": self.fun_values}
