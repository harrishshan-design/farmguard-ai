import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import FarmEngine, Telemetry  # noqa: E402


class FarmEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = FarmEngine()

    def test_drought_becomes_critical(self):
        self.engine.simulate_drought("zone-a")
        result = self.engine.snapshot()["evaluations"]["zone-a"]
        self.assertEqual(result["status"], "CRITICAL")
        self.assertGreaterEqual(result["risk"], 60)

    def test_irrigation_closes_the_recovery_loop(self):
        self.engine.simulate_drought("zone-a")
        self.engine.approve_irrigation("zone-a")
        for _ in range(8):
            self.engine.tick()
        snapshot = self.engine.snapshot()
        self.assertIsNone(snapshot["irrigating_zone"])
        self.assertGreaterEqual(snapshot["zones"]["zone-a"]["moisture"], 42)
        self.assertTrue(any(event["Event"] == "Recovery verified" for event in snapshot["events"]))

    def test_untrusted_device_is_rejected(self):
        packet = Telemetry(
            device_id="rogue-device",
            token="invalid-token",
            zone_id="zone-a",
            moisture=20,
            temperature=30,
            humidity=60,
            light=70,
        )
        with self.assertRaises(ValueError):
            self.engine.ingest(packet)
        self.assertEqual(self.engine.snapshot()["rejected_packets"], 1)

    def test_trusted_device_updates_zone(self):
        packet = Telemetry(
            device_id="esp32-field-01",
            token="farmguard-demo-01",
            zone_id="zone-a",
            moisture=42,
            temperature=30,
            humidity=65,
            light=70,
        )
        response = self.engine.ingest(packet)
        self.assertTrue(response["accepted"])
        self.assertEqual(self.engine.snapshot()["zones"]["zone-a"]["moisture"], 42)

    def test_demo_tick_does_not_overwrite_recent_live_reading(self):
        packet = Telemetry(
            device_id="esp32-field-01",
            token="farmguard-demo-01",
            zone_id="zone-a",
            moisture=42,
            temperature=30,
            humidity=65,
            light=70,
        )
        self.engine.ingest(packet)
        self.engine.tick()
        zone = self.engine.snapshot()["zones"]["zone-a"]
        self.assertEqual(zone["moisture"], 42)
        self.assertEqual(zone["source"], "sensor")

    def test_device_token_is_not_exposed_in_snapshot_copy_mutation(self):
        snapshot = self.engine.snapshot()
        snapshot["devices"]["esp32-field-01"]["token"] = "changed"
        self.assertEqual(
            self.engine.snapshot()["devices"]["esp32-field-01"]["token"],
            "farmguard-demo-01",
        )


if __name__ == "__main__":
    unittest.main()
