import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import API_KEY, app, state  # noqa: E402


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

    def test_seven_sensor_packet_requires_api_key(self):
        response = self.client.post("/api/sensors", json={"device_id": "esp32-farm-01", "sequence": state.last_sequence + 1, "motion": False})
        self.assertEqual(response.status_code, 401)

    def test_seven_sensor_packet_is_stored_and_returned(self):
        sequence = max(state.last_sequence + 1, 5000)
        packet = {
            "device_id": "esp32-farm-01", "sequence": sequence, "soil_moisture": 51,
            "temperature": 30.5, "humidity": 63, "light": 2100, "steam": 320,
            "motion": False, "water_level": 74, "ultrasonic_distance": 26.2, "uptime": 100,
        }
        response = self.client.post("/api/sensors", json=packet, headers={"X-API-Key": API_KEY})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Sensor data received")
        latest = self.client.get("/api/sensors/latest").json()
        self.assertEqual(latest["sensors"]["soil_moisture"], 51)
        self.assertEqual(latest["decision"]["farm_health"], "NORMAL")

    def test_null_sensor_values_stay_null(self):
        sequence = max(state.last_sequence + 1, 6000)
        packet = {"device_id": "esp32-farm-01", "sequence": sequence, "soil_moisture": None, "motion": False}
        self.assertEqual(self.client.post("/api/sensors", json=packet, headers={"X-API-Key": API_KEY}).status_code, 200)
        self.assertIsNone(self.client.get("/api/sensors/latest").json()["sensors"]["soil_moisture"])

    def test_out_of_range_sensor_value_is_rejected(self):
        response = self.client.post("/api/sensors", json={"device_id": "esp32-farm-01", "sequence": 9000, "humidity": 120}, headers={"X-API-Key": API_KEY})
        self.assertEqual(response.status_code, 422)

    def test_challenge_lab_and_plain_language_guide(self):
        started = self.client.post("/api/challenges/start", json={"mode": "alien-attack"})
        self.assertEqual(started.status_code, 200)
        self.assertTrue(started.json()["challenge"]["active"])
        self.assertEqual(started.json()["challenge"]["meta"]["threat"], "UNKNOWN FARM INTRUSION")
        self.assertIn("intrusion pattern", started.json()["decision"]["reasons"][0].lower())
        guide = self.client.post("/api/farm-guide/ask", json={"question": "Is there a security risk?"})
        self.assertEqual(guide.status_code, 200)
        self.assertIn("Status:", guide.json()["answer"])
        self.assertIn("Reason:", guide.json()["answer"])
        self.assertIn("Action:", guide.json()["answer"])
        self.assertEqual(self.client.post("/api/challenges/stop").status_code, 200)

    def test_farm_guide_supports_languages_and_returns_sensor_context(self):
        response = self.client.post("/api/farm-guide/ask", json={"question": "What should I do today?", "language": "ms"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Tindakan:", payload["answer"])
        self.assertIn("soil_moisture", payload["sensor_values"])

    def test_integration_status_never_exposes_passwords(self):
        response = self.client.get("/api/integrations/status")
        self.assertEqual(response.status_code, 200)
        serialized = response.text.lower()
        self.assertNotIn("password", serialized)
        self.assertIn("mqtt", response.json())
        self.assertIn("mysql", response.json())

    def test_mqtt_payload_uses_the_same_sensor_pipeline(self):
        sequence = state.mqtt_sequences.get("mqtt-test-node", 0) + 1
        result = state.ingest_mqtt({"device_id": "mqtt-test-node", "sequence": sequence,
            "soil_moisture": 58, "temperature": 30, "humidity": 65, "light": 2200,
            "steam": 400, "motion": False, "water_level": 70,
            "ultrasonic_distance": 35, "uptime": 50}, "/verify")
        self.assertTrue(result["success"])
        self.assertIn(result["decision"]["farm_health"], {"NORMAL", "WARNING", "CRITICAL"})

    def test_live_mqtt_is_stored_but_does_not_replace_active_challenge(self):
        self.client.post("/api/challenges/start", json={"mode": "water-crisis"})
        challenge_source = state.last_sensor_reading.source
        sequence = state.mqtt_sequences.get("challenge-live-node", 0) + 1
        state.ingest_mqtt({"device_id":"challenge-live-node","sequence":sequence,"temperature":24.5,
                           "soil_moisture":100,"soil_raw":0,"water_raw":2194,"steam":0,
                           "humidity":57.6,"light":3015,"ultrasonic_distance":10.3,"motion":False,
                           "motion_count":0,"pump":False,"fan":False,"led":False,
                           "reservoir_state":1,"wifi_rssi":-66}, "farmguard/sensors")
        self.assertEqual(state.last_sensor_reading.source, challenge_source)
        stopped = self.client.post("/api/challenges/stop").json()
        self.assertEqual(stopped["source"], "mqtt:farmguard/sensors")
        self.assertEqual(stopped["sensors"]["water_raw"], 2194)


if __name__ == "__main__":
    unittest.main()
