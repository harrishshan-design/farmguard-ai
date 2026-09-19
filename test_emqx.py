"""Minimal EMQX Cloud subscriber using FarmGuard environment configuration."""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

from integration_service import configure_mqtt_security, env_flag


load_dotenv()

host=os.getenv("MQTT_HOST","").strip()
port=int(os.getenv("MQTT_PORT","8883"))
topic=os.getenv("MQTT_SENSOR_TOPIC") or os.getenv("MQTT_TOPIC","farmguard/sensors")
username=os.getenv("MQTT_USERNAME") or os.getenv("MQTT_USER")
password=os.getenv("MQTT_PASSWORD")
ca_cert=os.getenv("MQTT_CA_CERT") or None
tls_enabled=env_flag("MQTT_TLS",True)

if not host:
    sys.exit("MQTT_HOST is required. Configure it in .env or the process environment.")


def on_connect(client,userdata,flags,reason_code,properties):
    if reason_code != 0:
        print(f"MQTT test: connection rejected ({reason_code})")
        return
    print("MQTT test: connected")
    client.subscribe(topic,qos=1)
    print(f"MQTT test: subscribed to {topic}")


def on_connect_fail(client,userdata):
    print("MQTT test: connection failed — retrying")


def on_disconnect(client,userdata,disconnect_flags,reason_code,properties):
    if reason_code:
        print("MQTT test: connection lost — reconnecting")


def on_message(client,userdata,message):
    payload=message.payload.decode("utf-8",errors="replace")
    print(f"{message.topic} {payload}")


client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=os.getenv("MQTT_TEST_CLIENT_ID","farmguard-emqx-test"))
configure_mqtt_security(client,tls_enabled=tls_enabled,ca_cert=ca_cert,username=username,password=password)
client.reconnect_delay_set(min_delay=1,max_delay=30)
client.on_connect=on_connect
client.on_connect_fail=on_connect_fail
client.on_disconnect=on_disconnect
client.on_message=on_message

print(f"MQTT test: connecting to {host}:{port} (TLS {'enabled' if tls_enabled else 'disabled'})")
try:
    client.connect_async(host,port,30)
    client.loop_forever(retry_first_connection=True)
except KeyboardInterrupt:
    print("\nMQTT test: stopped")
finally:
    client.disconnect()
