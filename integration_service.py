"""Optional MQTT input and MySQL mirror for FarmGuard.

All secrets come from environment variables.  Failures never stop FastAPI or the
SQLite pipeline: MySQL rows are buffered in memory and retried on later messages.
"""
from __future__ import annotations

import json
import os
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

try:
    import mysql.connector
except ImportError:  # pragma: no cover - optional dependency guard
    mysql = None
try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - optional dependency guard
    mqtt = None


def env_flag(name:str, default:bool=False) -> bool:
    value=os.getenv(name)
    return default if value is None else value.strip().lower() in {"1","true","yes","on"}


def configure_mqtt_security(client, *, tls_enabled:bool, ca_cert:str|None,
                            username:str|None, password:str|None) -> None:
    """Apply authentication and verified TLS without exposing secret values."""
    if username:
        client.username_pw_set(username,password)
    if tls_enabled:
        context=ssl.create_default_context(cafile=ca_cert or None)
        context.check_hostname=True
        context.verify_mode=ssl.CERT_REQUIRED
        client.tls_set_context(context)


def normalize_live_payload(payload:dict[str,Any], sequence:int) -> tuple[dict[str,Any],list[str]]:
    """Map the deployed ESP32 field names without modifying their actual values."""
    packet={
        "device_id":payload.get("device") or payload.get("device_id") or "farmguard-esp32",
        "sequence":payload.get("sequence",sequence),
        "uptime":payload.get("uptime_s",payload.get("uptime")),
        "temperature":payload.get("temp_c",payload.get("temperature")),
        "humidity":payload.get("humidity_pct",payload.get("humidity")),
        "light":payload.get("brightness",payload.get("light_raw",payload.get("light"))),
        "steam":payload.get("steam_raw",payload.get("steam")),
        "soil_moisture":payload.get("soil_pct",payload.get("soil_moisture")),
        "water_level":payload.get("water_pct",payload.get("water_level")),
        "ultrasonic_distance":payload.get("distance_cm",payload.get("ultrasonic_distance")),
        "motion":payload.get("motion_now",payload.get("motion")),
        "soil_raw":payload.get("soil_raw"), "water_raw":payload.get("water_raw"),
        "motion_count":payload.get("motion_count"), "pump":payload.get("pump"),
        "fan":payload.get("fan"), "led":payload.get("led"),
        "reservoir_state":payload.get("reservoir_state"), "wifi_rssi":payload.get("wifi_rssi"),
    }
    packet={key:value for key,value in packet.items() if value is not None}
    warnings=[]
    if payload.get("soil_raw")==0: warnings.append("Soil raw reading is 0; inspect wiring or calibration")
    if payload.get("steam_raw")==0: warnings.append("Steam raw reading is 0; confirm this matches dry conditions")
    if payload.get("water_raw")==0: warnings.append("Water raw reading dropped to 0; inspect sensor power or connection")
    return packet,warnings


class MySQLMirror:
    SENSOR_FIELDS = ("temperature", "humidity", "light", "ultrasonic_distance", "steam", "soil_moisture", "water_level", "motion",
                     "soil_raw", "water_raw", "motion_count", "pump", "fan", "led", "reservoir_state", "wifi_rssi")

    def __init__(self) -> None:
        self.host=os.getenv("DB_HOST",""); self.port=int(os.getenv("DB_PORT","3306")); self.database=os.getenv("DB_NAME","")
        self.user=os.getenv("DB_USER",""); self.password=os.getenv("DB_PASSWORD","")
        self.enabled=all((self.host,self.database,self.user,self.password)); self.connected=False; self.last_error=None
        self.buffer:list[dict[str,Any]]=[]; self.lock=threading.RLock()

    def _connect(self):
        if mysql is None: raise RuntimeError("mysql-connector-python is not installed")
        connection=mysql.connector.connect(host=self.host,port=self.port,database=self.database,user=self.user,password=self.password,connection_timeout=3)
        cursor=connection.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS sensor_values (
          id BIGINT AUTO_INCREMENT PRIMARY KEY, device_id VARCHAR(80) NOT NULL,
          sensor VARCHAR(64) NOT NULL, sensor_value VARCHAR(255) NULL,
          created_at DATETIME(6) NOT NULL, INDEX idx_sensor_created(sensor,created_at))""")
        connection.commit(); return connection

    def write(self, packet:dict[str,Any]) -> None:
        if not self.enabled: return
        with self.lock:
            self.buffer.append(dict(packet)); self.buffer=self.buffer[-500:]
            try:
                connection=self._connect(); cursor=connection.cursor(); pending=list(self.buffer)
                for item in pending:
                    created=datetime.now(timezone.utc).replace(tzinfo=None)
                    rows=[(str(item.get("device_id","unknown")),field,None if item.get(field) is None else str(item.get(field)),created) for field in self.SENSOR_FIELDS]
                    cursor.executemany("INSERT INTO sensor_values (device_id,sensor,sensor_value,created_at) VALUES (%s,%s,%s,%s)",rows)
                connection.commit(); cursor.close(); connection.close(); self.buffer.clear(); self.connected=True; self.last_error=None
            except Exception as error:
                self.connected=False; self.last_error=str(error)[:180]

    def status(self) -> dict[str,Any]:
        return {"enabled":self.enabled,"connected":self.connected,"host":self.host or None,"port":self.port,
                "database":self.database or None,"buffered_readings":len(self.buffer),"last_error":self.last_error}


class MQTTBridge:
    def __init__(self, handler:Callable[[dict[str,Any],str],dict[str,Any]], mysql_mirror:MySQLMirror) -> None:
        self.host=os.getenv("MQTT_HOST",""); self.port=int(os.getenv("MQTT_PORT","1883"))
        self.username=os.getenv("MQTT_USERNAME") or os.getenv("MQTT_USER"); self.password=os.getenv("MQTT_PASSWORD")
        self.tls_enabled=env_flag("MQTT_TLS"); self.ca_cert=os.getenv("MQTT_CA_CERT") or None
        self.enabled=bool(self.host); self.connected=False; self.connection_status="DISCONNECTED"; self.last_error=None
        self.received=0; self.rejected=0; self.handler=handler; self.mysql=mysql_mirror; self.client=None
        self.sensor_topic=os.getenv("MQTT_SENSOR_TOPIC") or os.getenv("MQTT_TOPIC","farmguard/sensors"); self.status_topic=os.getenv("MQTT_STATUS_TOPIC","farmguard/status")
        self.topics=(self.sensor_topic,self.status_topic,"/test","/verify","/broadcast")
        self.latest_payload=None; self.latest_status=None; self.last_sensor_monotonic=None; self.last_sensor_message_at=None
        self.quality_warnings=[]; self.previous_water_raw=None; self.logged_first_payload=False; self._stopping=False

    def start(self) -> None:
        if not self.enabled or mqtt is None:
            if self.enabled and mqtt is None: self.last_error="paho-mqtt is not installed"
            return
        try:
            self._stopping=False; self.connection_status="RECONNECTING"
            print("MQTT: Connecting to EMQX Cloud..." if self.tls_enabled else f"MQTT: Connecting to {self.host}:{self.port}...")
            self.client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id="farmguard-python-backend")
            configure_mqtt_security(self.client,tls_enabled=self.tls_enabled,ca_cert=self.ca_cert,
                                    username=self.username,password=self.password)
            if self.tls_enabled: print("MQTT: TLS enabled")
            self.client.reconnect_delay_set(min_delay=1,max_delay=30)
            self.client.on_connect=self._on_connect; self.client.on_connect_fail=self._on_connect_fail
            self.client.on_disconnect=self._on_disconnect; self.client.on_message=self._on_message
            self.client.connect_async(self.host,self.port,30); self.client.loop_start()
        except Exception as error:
            self.connection_status="DISCONNECTED"; self.last_error=str(error)[:180]
            print(f"MQTT: Connection setup failed — {self.last_error}")

    def stop(self) -> None:
        if self.client:
            try:
                self._stopping=True; self.client.disconnect(); self.client.loop_stop()
            except Exception: pass
        self.connected=False; self.connection_status="DISCONNECTED"

    def _on_connect(self,client,userdata,flags,reason_code,properties):
        self.connected=reason_code==0; self.last_error=None if self.connected else f"MQTT connect code {reason_code}"
        if self.connected:
            self.connection_status="CONNECTED"; print("MQTT: Connected")
            for topic in dict.fromkeys(self.topics):
                client.subscribe(topic,qos=1); print(f"MQTT: Subscribed to {topic}")
        else:
            self.connection_status="RECONNECTING"

    def _on_connect_fail(self,client,userdata):
        self.connected=False; self.connection_status="RECONNECTING"; self.last_error="MQTT connection attempt failed"
        print("MQTT: Connection attempt failed — reconnecting")

    def _on_disconnect(self,client,userdata,disconnect_flags,reason_code,properties):
        self.connected=False
        if reason_code: self.last_error=f"MQTT disconnected: {reason_code}"
        if self._stopping:
            self.connection_status="DISCONNECTED"
        else:
            self.connection_status="RECONNECTING"; print("MQTT: Connection lost — reconnecting")

    def _on_message(self,client,userdata,message):
        try:
            payload=json.loads(message.payload.decode("utf-8"))
            if not isinstance(payload,dict): raise ValueError("MQTT payload must be a JSON object")
            if message.topic=="/broadcast" and payload.get("origin")=="farmguard-backend": return
            self.received+=1
            if message.topic==self.status_topic:
                self.latest_status=payload; return
            if message.topic=="/test":
                self.publish({"type":"test-ack","received_at":datetime.now(timezone.utc).isoformat()}); return
            packet,warnings=normalize_live_payload(payload,self.received)
            if self.previous_water_raw is not None and packet.get("water_raw") is not None and self.previous_water_raw-packet["water_raw"]>1000:
                warnings.append(f"Water raw reading changed sharply from {self.previous_water_raw} to {packet['water_raw']}")
            if packet.get("water_raw") is not None: self.previous_water_raw=packet["water_raw"]
            result=self.handler(packet,message.topic); self.mysql.write(packet)
            self.latest_payload=dict(payload); self.quality_warnings=warnings; self.last_sensor_monotonic=time.monotonic()
            self.last_sensor_message_at=datetime.now(timezone.utc).isoformat()
            if not self.logged_first_payload:
                print(f"FarmGuard MQTT first valid payload on {message.topic}: {json.dumps(payload,default=str)}"); self.logged_first_payload=True
            self.publish({"type":"farmguard-decision","device_id":payload.get("device_id"),"buzzer_mode":result.get("buzzer_mode"),"decision":result.get("decision")})
        except Exception as error:
            self.rejected+=1; self.last_error=str(error)[:180]
            print(f"FarmGuard MQTT rejected message on {message.topic}: {self.last_error}")

    def publish(self,payload:dict[str,Any]) -> None:
        if self.client and self.connected:
            self.client.publish("/broadcast",json.dumps({"origin":"farmguard-backend",**payload},default=str),qos=1)

    def status(self) -> dict[str,Any]:
        age=round(time.monotonic()-self.last_sensor_monotonic,1) if self.last_sensor_monotonic is not None else None
        if not self.connected:
            sensor_state="OFFLINE"
        elif age is None:
            sensor_state="WAITING FOR SENSOR DATA"
        else:
            sensor_state="ONLINE" if age<=15 else "OFFLINE"
        freshness="WAITING" if age is None else "FRESH" if age<=5 else "DELAYED" if age<=15 else "EXPIRED"
        return {"enabled":self.enabled,"connected":self.connected,"connection_status":self.connection_status,
                "tls_enabled":self.tls_enabled,"host":self.host or None,"port":self.port,
                "topics":list(self.topics),"sensor_topic":self.sensor_topic,"status_topic":self.status_topic,
                "sensor_state":sensor_state,"data_freshness":freshness,"last_sensor_message_at":self.last_sensor_message_at,"sensor_age_seconds":age,
                "quality_warnings":list(self.quality_warnings),"messages_received":self.received,"messages_rejected":self.rejected,"last_error":self.last_error}


class IntegrationService:
    def __init__(self,handler:Callable[[dict[str,Any],str],dict[str,Any]]) -> None:
        self.mysql=MySQLMirror(); self.mqtt=MQTTBridge(handler,self.mysql)
    def start(self): self.mqtt.start()
    def stop(self): self.mqtt.stop()
    def status(self): return {"mqtt":self.mqtt.status(),"mysql":self.mysql.status(),"raspberry_pi":{"host":os.getenv("RASPBERRY_PI_HOST") or None}}
