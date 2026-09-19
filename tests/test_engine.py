import math
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from farmguard_engine import DeviceConfig, FarmSensorReading, SensorReading, evaluate, evaluate_farm, simulated_reading  # noqa: E402


NOW = datetime(2026, 9, 19, 4, 0, tzinfo=timezone.utc)


class SensorFusionTests(unittest.TestCase):
    def decision(self, distance=45, light=2580, profile="level", daylight=True):
        config = DeviceConfig(profile=profile)
        reading = SensorReading(distance, light, 1, "test", NOW)
        return evaluate(reading, config, daylight)

    def test_healthy_reading_is_silent(self):
        result = self.decision()
        self.assertEqual(result["health_score"], 100)
        self.assertEqual(result["buzzer_mode"], "OFF")

    def test_critical_level_alarms(self):
        result = self.decision(distance=94)
        self.assertEqual(result["status"], "ACTION")
        self.assertEqual(result["buzzer_mode"], "ALARM")

    def test_close_object_only_affects_perimeter_installation(self):
        self.assertEqual(self.decision(distance=10, profile="level")["status"], "GOOD")
        self.assertEqual(self.decision(distance=10, profile="perimeter")["status"], "ACTION")

    def test_dark_day_and_bright_night_pulse(self):
        self.assertEqual(self.decision(light=100, daylight=True)["buzzer_mode"], "PULSE")
        self.assertEqual(self.decision(light=4000, daylight=False)["buzzer_mode"], "PULSE")

    def test_invalid_sensor_values_are_rejected(self):
        with self.assertRaises(ValueError):
            self.decision(distance=math.nan)
        with self.assertRaises(ValueError):
            self.decision(light=5000)

    def test_demo_data_is_repeatable(self):
        config = DeviceConfig()
        first = simulated_reading("healthy", config, 4, NOW)
        second = simulated_reading("healthy", config, 4, NOW)
        self.assertEqual(first, second)

    def test_missing_farm_sensors_are_not_treated_as_zero(self):
        reading = FarmSensorReading("node", 1, NOW, motion=False)
        result = evaluate_farm(reading, DeviceConfig())
        self.assertEqual(result["farm_health"], "NORMAL")

    def test_combined_dry_hot_condition_recommends_irrigation(self):
        reading = FarmSensorReading("node", 1, NOW, soil_moisture=12, temperature=39, water_level=80)
        result = evaluate_farm(reading, DeviceConfig())
        self.assertTrue(any("Irrigation is recommended" in action for action in result["actions"]))


if __name__ == "__main__":
    unittest.main()
