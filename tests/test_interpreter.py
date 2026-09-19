import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from farm_interpreter import answer_question, interpret_farm, prepare_device_recommendation  # noqa: E402


class FarmInterpreterTests(unittest.TestCase):
    def sensors(self, **changes):
        values = {"soil_moisture": 62, "water_level": 72, "temperature": 31,
                  "humidity": 66, "light": 2500, "steam": 400, "motion": False,
                  "ultrasonic_distance": 40, "uptime": 100}
        values.update(changes); return values

    def test_normal_summary_is_short_and_actionable(self):
        result = interpret_farm(self.sensors(), {"health_score": 100})
        self.assertEqual(result["priority"], "NORMAL")
        self.assertLessEqual(len(result["recommendation"]), 3)

    def test_security_has_priority_over_water_and_temperature(self):
        result = interpret_farm(self.sensors(motion=True, water_level=3, temperature=45), {"health_score": 10})
        self.assertEqual(result["priority"], "CRITICAL")
        self.assertIn("Movement", result["reason"])
        self.assertIn("security", result["actions"][0].lower())

    def test_question_response_uses_supplied_values(self):
        result = answer_question("Should I water?", self.sensors(soil_moisture=18, water_level=54), {"health_score": 70})
        self.assertIn("18%", result["reason"])
        self.assertIn("54%", result["reason"])

    def test_future_device_command_is_never_executed(self):
        result = prepare_device_recommendation("Start Pump 2 for 10 minutes")
        self.assertFalse(result["executed"])
        self.assertTrue(result["requires_user_confirmation"])
        self.assertTrue(result["device_confirmation_required"])


if __name__ == "__main__":
    unittest.main()
