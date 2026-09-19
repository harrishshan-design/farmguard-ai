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
    soil_moisture_low_pct: float = 30.0
    temperature_high_c: float = 35.0
    humidity_low_pct: float = 35.0
    water_level_low_pct: float = 25.0
    steam_high_raw: int = 2600
    offline_timeout_seconds: int = 25

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


@dataclass(frozen=True)
class FarmSensorReading:
    """One nullable sample from the seven-sensor ESP32 node."""

    device_id: str
    sequence: int
    observed_at: datetime
    source: str = "esp32"
    soil_moisture: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    light: int | None = None
    steam: int | None = None
    motion: bool | None = None
    water_level: float | None = None
    ultrasonic_distance: float | None = None
    uptime: int | None = None
    soil_raw: int | None = None
    water_raw: int | None = None
    motion_count: int | None = None
    pump: bool | None = None
    fan: bool | None = None
    led: bool | None = None
    reservoir_state: int | None = None
    wifi_rssi: int | None = None


def evaluate_farm(reading: FarmSensorReading, config: DeviceConfig) -> dict:
    """Evaluate only available sensors; a failed sensor never becomes a zero."""

    penalty = 0
    reasons: list[str] = []
    actions: list[str] = []

    def add(points: int, reason: str, action: str) -> None:
        nonlocal penalty
        penalty += points
        reasons.append(reason)
        actions.append(action)

    if reading.soil_moisture is not None and reading.soil_moisture < config.soil_moisture_low_pct:
        critical = reading.soil_moisture < max(10, config.soil_moisture_low_pct / 2)
        add(35 if critical else 20, f"Soil moisture is low at {reading.soil_moisture:.0f}%", "Inspect the crop bed and irrigate if the soil is dry.")
    if reading.temperature is not None and reading.temperature > config.temperature_high_c:
        add(25 if reading.temperature > config.temperature_high_c + 5 else 15, f"Temperature is high at {reading.temperature:.1f}°C", "Check shade, ventilation, and animal heat stress.")
    if reading.humidity is not None and reading.humidity < config.humidity_low_pct:
        add(12, f"Humidity is low at {reading.humidity:.0f}%", "Check crop and livestock water demand.")
    if reading.water_level is not None and reading.water_level < config.water_level_low_pct:
        critical = reading.water_level < max(8, config.water_level_low_pct / 2)
        add(40 if critical else 22, f"Water level is low at {reading.water_level:.0f}%", "Refill the water supply and inspect for leaks.")
    if reading.steam is not None and reading.steam > config.steam_high_raw:
        add(30, f"Steam or wetness signal is unusually high ({reading.steam})", "Inspect for a leak, rainfall ingress, or unexpected moisture.")
    if reading.motion is True:
        add(18, "Motion was detected in the monitored area", "Check whether the movement is an animal, worker, or intruder.")

    light_pct = None if reading.light is None else round(clamp(reading.light / config.adc_max * 100, 0, 100), 1)
    if light_pct is not None and config.invert_light:
        light_pct = round(100 - light_pct, 1)
    expected_daylight = 6 <= datetime.now(MYT).hour < 19
    if light_pct is not None:
        if expected_daylight and light_pct < config.daylight_low_pct:
            add(15, f"Unexpected daytime darkness detected at {light_pct:.0f}% light", "Check the light sensor, enclosure, and crop shading.")
        elif not expected_daylight and light_pct > config.night_bright_pct:
            add(15, f"Unexpected night lighting detected at {light_pct:.0f}% light", "Check for an open enclosure, vehicle lights, or activity.")

    if (
        reading.soil_moisture is not None
        and reading.temperature is not None
        and reading.water_level is not None
        and reading.soil_moisture < config.soil_moisture_low_pct
        and reading.temperature > config.temperature_high_c
        and reading.water_level >= config.water_level_low_pct
    ):
        actions.insert(0, "Irrigation is recommended now: soil is dry, heat is high, and water is available.")

    health = int(round(clamp(100 - penalty, 0, 100)))
    if health < 55:
        farm_health, legacy_status, severity, buzzer = "CRITICAL", "ACTION", "critical", "ALARM"
    elif health < 80:
        farm_health, legacy_status, severity, buzzer = "WARNING", "WATCH", "warning", "PULSE"
    else:
        farm_health, legacy_status, severity, buzzer = "NORMAL", "GOOD", "healthy", "OFF"
    if not reasons:
        reasons.append("All available sensor readings are inside the configured safe ranges")
        actions.append("No action is needed. FarmGuard will keep watching.")

    return {
        "health_score": health,
        "farm_health": farm_health,
        "status": legacy_status,
        "severity": severity,
        "buzzer_mode": buzzer,
        "light_pct": light_pct,
        "expected_light": "Daylight" if expected_daylight else "Night",
        "reasons": reasons,
        "actions": list(dict.fromkeys(actions)),
    }


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
