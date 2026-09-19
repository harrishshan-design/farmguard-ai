"""Deterministic sensor-fusion policy shared by the API and simulator."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal


MYT = timezone(timedelta(hours=8), name="MYT")
Profile = Literal["level", "perimeter", "combined"]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class DeviceConfig:
    device_id: str = "esp32-farm-01"
    name: str = "Main Farm Node"
    zone: str = "North Field"
    token: str = "farmguard-device-01"
    profile: Profile = "level"
    mount_height_cm: float = 100.0
    adc_max: int = 4095
    invert_light: bool = False
    level_warning_pct: float = 35.0
    level_critical_pct: float = 15.0
    proximity_warning_cm: float = 35.0
    proximity_critical_cm: float = 15.0
    daylight_low_pct: float = 25.0
    night_bright_pct: float = 75.0

    def public_dict(self, include_token: bool = False) -> dict:
        payload = asdict(self)
        if not include_token:
            payload.pop("token", None)
        return payload


@dataclass(frozen=True)
class SensorReading:
    distance_cm: float
    light_raw: int
    sequence: int
    source: str
    observed_at: datetime


def evaluate(reading: SensorReading, config: DeviceConfig, expected_daylight: bool | None = None) -> dict:
    if not math.isfinite(reading.distance_cm) or not 0 <= reading.distance_cm <= 500:
        raise ValueError("distance_cm must be between 0 and 500")
    if not 0 <= reading.light_raw <= config.adc_max:
        raise ValueError(f"light_raw must be between 0 and {config.adc_max}")
    if config.mount_height_cm <= 0:
        raise ValueError("mount_height_cm must be greater than zero")

    level_pct = clamp((config.mount_height_cm - reading.distance_cm) / config.mount_height_cm * 100, 0, 100)
    proximity_pct = clamp((120 - reading.distance_cm) / 120 * 100, 0, 100)
    light_pct = clamp(reading.light_raw / config.adc_max * 100, 0, 100)
    if config.invert_light:
        light_pct = 100 - light_pct
    if expected_daylight is None:
        expected_daylight = 6 <= datetime.now(MYT).hour < 19

    penalty = 0
    reasons: list[str] = []
    actions: list[str] = []

    if config.profile in {"level", "combined"}:
        if level_pct < config.level_critical_pct:
            penalty += 50
            reasons.append(f"Water or feed level is critically low at {level_pct:.0f}%")
            actions.append("Refill the monitored container now and check for leaks.")
        elif level_pct < config.level_warning_pct:
            penalty += 22
            reasons.append(f"Water or feed level is getting low at {level_pct:.0f}%")
            actions.append("Plan a refill during the next farm round.")

    if config.profile in {"perimeter", "combined"}:
        if reading.distance_cm < config.proximity_critical_cm:
            penalty += 50
            reasons.append(f"Movement is extremely close at {reading.distance_cm:.1f} cm")
            actions.append("Inspect the monitored area immediately.")
        elif reading.distance_cm < config.proximity_warning_cm:
            penalty += 22
            reasons.append(f"Nearby movement detected at {reading.distance_cm:.1f} cm")
            actions.append("Watch the area and verify whether it is an animal or person.")

    if expected_daylight and light_pct < config.daylight_low_pct:
        penalty += 25 if light_pct < 15 else 22
        reasons.append(f"Unexpected daytime darkness detected at {light_pct:.0f}% light")
        actions.append("Check for sensor obstruction, severe shade, or enclosure problems.")
    elif not expected_daylight and light_pct > config.night_bright_pct:
        penalty += 22
        reasons.append(f"Unexpected night lighting detected at {light_pct:.0f}% light")
        actions.append("Check for an open enclosure, vehicle lights, or unauthorized activity.")

    health = int(round(clamp(100 - penalty, 0, 100)))
    if health < 55:
        status, severity, buzzer = "ACTION", "critical", "ALARM"
    elif health < 80:
        status, severity, buzzer = "WATCH", "warning", "PULSE"
    else:
        status, severity, buzzer = "GOOD", "healthy", "OFF"

    if not reasons:
        reasons.append("All monitored conditions are inside the configured safe range")
        actions.append("No action is needed. FarmGuard will keep watching.")

    if light_pct < 15:
        light_state = "Very dark"
    elif light_pct < 35:
        light_state = "Low light"
    elif light_pct < 80:
        light_state = "Normal"
    else:
        light_state = "Very bright"

    return {
        "health_score": health,
        "status": status,
        "severity": severity,
        "buzzer_mode": buzzer,
        "distance_cm": round(reading.distance_cm, 1),
        "level_pct": round(level_pct, 1),
        "proximity_risk_pct": round(proximity_pct, 1),
        "light_raw": reading.light_raw,
        "light_pct": round(light_pct, 1),
        "light_state": light_state,
        "expected_light": "Daylight" if expected_daylight else "Night",
        "reasons": reasons,
        "actions": list(dict.fromkeys(actions)),
        "profile": config.profile,
    }


SCENARIOS = {
    "healthy": "Healthy farm",
    "low-level": "Low tank / feed level",
    "intrusion": "Animal or intruder nearby",
    "darkness": "Unexpected daytime darkness",
    "night-light": "Unexpected night lighting",
    "multi-risk": "Critical combined risk",
}


def simulated_reading(scenario: str, config: DeviceConfig, tick: int, now: datetime) -> tuple[SensorReading, bool]:
    randomizer = random.Random(f"{scenario}:{tick // 3}")
    wave = math.sin(tick / 4) * 1.5
    profiles = {
        "healthy": (config.mount_height_cm * 0.45 + wave, int(config.adc_max * 0.63), True),
        "low-level": (config.mount_height_cm * 0.9 + wave, int(config.adc_max * 0.60), True),
        "intrusion": (10 + wave, int(config.adc_max * 0.62), True),
        "darkness": (config.mount_height_cm * 0.45, int(config.adc_max * 0.07), True),
        "night-light": (config.mount_height_cm * 0.45, int(config.adc_max * 0.93), False),
        "multi-risk": (config.mount_height_cm * 0.94 + wave, int(config.adc_max * 0.06), True),
    }
    distance, light, expected_day = profiles.get(scenario, profiles["healthy"])
    distance += randomizer.uniform(-0.6, 0.6)
    light += randomizer.randint(-20, 20)
    reading = SensorReading(
        distance_cm=round(clamp(distance, 0, 500), 2),
        light_raw=int(clamp(light, 0, config.adc_max)),
        sequence=tick,
        source="simulation",
        observed_at=now,
    )
    return reading, expected_day
