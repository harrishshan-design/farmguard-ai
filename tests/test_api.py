import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, state  # noqa: E402


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_and_both_dashboards(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertIn("FarmGuard AI", self.client.get("/").text)
        self.assertIn("Integrator Console", self.client.get("/integrator").text)

    def test_state_contract(self):
        response = self.client.get("/api/v1/state")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("decision", payload)
        self.assertIn(payload["decision"]["buzzer_mode"], {"OFF", "PULSE", "ALARM"})

    def test_invalid_device_is_rejected(self):
        response = self.client.post(
            "/api/v1/telemetry",
            json={"device_id": "rogue-node", "token": "wrong-token", "sequence": 10, "distance_cm": 45, "light_raw": 2000},
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_esp32_packet_returns_buzzer_command(self):
        sequence = max(state.last_sequence + 1, 1000)
        response = self.client.post(
            "/api/v1/telemetry",
            json={"device_id": state.config.device_id, "token": state.config.token, "sequence": sequence, "distance_cm": 45, "light_raw": 2500},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["accepted"])
        self.assertIn(response.json()["buzzer_mode"], {"OFF", "PULSE", "ALARM"})

    def test_replayed_sequence_is_blocked(self):
        sequence = max(state.last_sequence + 1, 500)
        packet = {"device_id": state.config.device_id, "token": state.config.token, "sequence": sequence, "distance_cm": 45, "light_raw": 2500}
        self.assertEqual(self.client.post("/api/v1/telemetry", json=packet).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/telemetry", json=packet).status_code, 409)


if __name__ == "__main__":
    unittest.main()
