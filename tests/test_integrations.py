import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integration_service import IntegrationService, MQTTBridge, MySQLMirror, configure_mqtt_security, normalize_live_payload  # noqa: E402


class IntegrationTests(unittest.TestCase):
    def test_deployed_esp32_payload_maps_without_inventing_values(self):
        source = {"device":"farmguard-esp32","uptime_s":159,"light_raw":3015,"brightness":3015,
                  "soil_raw":0,"soil_pct":100,"water_raw":2194,"steam_raw":0,"temp_c":24.5,
                  "humidity_pct":57.6,"distance_cm":10.3,"motion_count":0,"motion_now":False,
                  "pump":False,"fan":False,"led":False,"reservoir_state":1,"wifi_rssi":-66}
        packet, warnings = normalize_live_payload(source, 7)
        self.assertEqual(packet["device_id"], "farmguard-esp32")
        self.assertEqual(packet["sequence"], 7)
        self.assertEqual(packet["soil_moisture"], 100)
        self.assertEqual(packet["soil_raw"], 0)
        self.assertEqual(packet["water_raw"], 2194)
        self.assertNotIn("water_level", packet)
        self.assertEqual(packet["wifi_rssi"], -66)
        self.assertTrue(any("Soil raw" in warning for warning in warnings))
        self.assertTrue(any("Steam raw" in warning for warning in warnings))

    def test_mqtt_sensor_state_and_freshness_are_clear(self):
        with patch.dict(os.environ, {"MQTT_HOST": "broker.local"}, clear=False):
            bridge = MQTTBridge(lambda payload, topic: {}, MySQLMirror())
        bridge.connected = True
        bridge.last_sensor_monotonic = time.monotonic() - 2
        self.assertEqual(bridge.status()["sensor_state"], "ONLINE")
        self.assertEqual(bridge.status()["data_freshness"], "FRESH")
        bridge.last_sensor_monotonic = time.monotonic() - 8
        self.assertEqual(bridge.status()["sensor_state"], "ONLINE")
        self.assertEqual(bridge.status()["data_freshness"], "DELAYED")
        bridge.last_sensor_monotonic = time.monotonic() - 16
        self.assertEqual(bridge.status()["sensor_state"], "OFFLINE")

    def test_local_non_tls_configuration_remains_supported(self):
        with patch.dict(os.environ, {"MQTT_HOST":"127.0.0.1","MQTT_PORT":"1883","MQTT_TOPIC":"farmguard/sensors","MQTT_TLS":"false"}, clear=True):
            bridge = MQTTBridge(lambda payload, topic: {}, MySQLMirror())
        self.assertEqual(bridge.host, "127.0.0.1")
        self.assertEqual(bridge.port, 1883)
        self.assertEqual(bridge.sensor_topic, "farmguard/sensors")
        self.assertFalse(bridge.tls_enabled)
        bridge.connected = False
        bridge.last_sensor_monotonic = time.monotonic()
        self.assertEqual(bridge.status()["sensor_state"], "OFFLINE")

    def test_emqx_tls_uses_verified_context_and_new_username_variable(self):
        env={"MQTT_HOST":"cloud.example","MQTT_PORT":"8883","MQTT_USERNAME":"farmguard",
             "MQTT_PASSWORD":"private","MQTT_CA_CERT":"broker-ca.pem","MQTT_TLS":"true"}
        with patch.dict(os.environ,env,clear=True):
            bridge=MQTTBridge(lambda payload,topic:{},MySQLMirror())
        self.assertTrue(bridge.tls_enabled)
        self.assertEqual(bridge.username,"farmguard")
        status=bridge.status()
        self.assertTrue(status["tls_enabled"])
        self.assertEqual(status["connection_status"],"DISCONNECTED")
        self.assertNotIn("username",status)
        self.assertNotIn("password",status)
        self.assertNotIn("ca_cert",status)

        client=MagicMock(); context=MagicMock()
        with patch("integration_service.ssl.create_default_context",return_value=context) as create_context:
            configure_mqtt_security(client,tls_enabled=True,ca_cert="broker-ca.pem",username="farmguard",password="private")
        create_context.assert_called_once_with(cafile="broker-ca.pem")
        client.username_pw_set.assert_called_once_with("farmguard","private")
        client.tls_set_context.assert_called_once_with(context)

    def test_connected_broker_waits_for_first_real_sensor_message(self):
        with patch.dict(os.environ, {"MQTT_HOST":"127.0.0.1"}, clear=True):
            bridge = MQTTBridge(lambda payload, topic: {}, MySQLMirror())
        bridge.connected = True
        self.assertEqual(bridge.status()["sensor_state"], "WAITING FOR SENSOR DATA")

    def test_mysql_configuration_status_masks_secret(self):
        env = {"DB_HOST": "db.local", "DB_NAME": "farm", "DB_USER": "worker", "DB_PASSWORD": "top-secret"}
        with patch.dict(os.environ, env, clear=False):
            status = MySQLMirror().status()
        self.assertTrue(status["enabled"])
        self.assertNotIn("password", status)
        self.assertNotIn("top-secret", str(status))

    def test_disabled_integrations_are_safe_noops(self):
        with patch.dict(os.environ, {"MQTT_HOST": "", "DB_HOST": "", "DB_NAME": "", "DB_USER": "", "DB_PASSWORD": ""}, clear=False):
            service = IntegrationService(lambda payload, topic: {})
            service.start(); status = service.status(); service.stop()
        self.assertFalse(status["mqtt"]["enabled"])
        self.assertFalse(status["mysql"]["enabled"])


if __name__ == "__main__":
    unittest.main()
