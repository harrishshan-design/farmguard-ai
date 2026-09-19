import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from challenge_engine import CHALLENGES, ChallengeEngine  # noqa: E402


class ChallengeEngineTests(unittest.TestCase):
    def step(self, engine):
        engine.last_step_at = 0
        return engine.step("test-node")

    def test_all_seven_challenges_generate_shared_sensor_readings(self):
        for mode in CHALLENGES:
            engine = ChallengeEngine(); engine.start(mode)
            reading, meta = self.step(engine)
            self.assertEqual(reading.device_id, "test-node")
            self.assertEqual(meta["mode"], mode)

    def test_crazy_sensor_keeps_raw_and_corrected_values(self):
        engine = ChallengeEngine(); engine.start("sensor-crazy")
        reading, meta = self.step(engine)
        self.assertEqual(meta["anomalies"][0]["raw"], 150)
        self.assertEqual(reading.temperature, 29)
        self.assertFalse(meta["anomalies"][0]["valid"])

    def test_database_challenge_buffers_then_recovers(self):
        engine = ChallengeEngine(); engine.start("database-security")
        statuses = []
        for _ in range(8):
            _, meta = self.step(engine); statuses.append(meta["database_status"])
        self.assertIn("DATABASE OFFLINE", statuses)
        self.assertIn("SYNCING", statuses)
        self.assertIn("RECOVERED", statuses)
        self.assertEqual(engine.buffered_readings, [])

    def test_perfect_storm_finishes_with_survival_score(self):
        engine = ChallengeEngine(); engine.start("perfect-storm")
        meta = None
        for _ in range(10): _, meta = self.step(engine)
        self.assertEqual(meta["final_result"], "96/100 — FARM SAVED")
        self.assertTrue(meta["scorecard"]["database_recovery"])


if __name__ == "__main__":
    unittest.main()
