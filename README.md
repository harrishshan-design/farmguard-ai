# FarmGuard AI — ESP32 seven-sensor dashboard

FarmGuard AI keeps the existing farm-owner dashboard and Integrator Console, but replaces mock-only values with live readings from one ESP32. It combines soil, climate, water, and security conditions into a Farm Health result of **NORMAL**, **WARNING**, or **CRITICAL**, plus a passive-buzzer command.

## Hardware supported

- Ultrasonic distance sensor
- Photoresistor / LDR module
- Steam or rain/wetness sensor
- DHT11 or DHT22 temperature and humidity sensor
- PIR motion sensor
- Analog soil-moisture sensor
- Analog water-level sensor
- Passive piezo buzzer

The exact Keyestudio module revisions are not assumed. Pin assignments and analog calibration values are grouped at the top of `esp32_example.ino` so they can be adjusted safely.

## 1. Start the Python dashboard

Install Python 3.11 or newer, open PowerShell in this folder, then run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FARMGUARD_API_KEY = "choose-a-long-private-key"
$env:MQTT_HOST = "127.0.0.1"
$env:MQTT_PORT = "1884"
$env:MQTT_TOPIC = "farmguard/sensors"
$env:MQTT_STATUS_TOPIC = "farmguard/status"
$env:PORT = "7862"
python app.py
```

Open:

- Farm owner dashboard: <http://127.0.0.1:7862/>
- Integrator Console: <http://127.0.0.1:7862/integrator>
- Interactive API docs: <http://127.0.0.1:7862/api/docs>

Simulation starts automatically, so both dashboards remain demonstrable before hardware is connected. The first valid ESP32 packet switches the system to live data.

## Owner AI guide and Challenge Lab

The farm-owner page now includes **Ask FarmGuard**, a plain-language guide grounded only in the current sensor state. It can explain what to do next, water and soil conditions, crop heat, unavailable sensors, and security readings. Answers follow a short Status → Reason → Action structure and support English, Bahasa Melayu, Tamil, and Chinese. It runs locally and needs no external AI account or API key.

Every numerical card keeps its live reading and adds a farmer-friendly meaning. The existing action panel is also the **Today's Recommendation** card and shows at most three prioritized actions. **FarmGuard Says** updates automatically as readings change.

The microphone button is a UI placeholder only: it never records audio. The backend reports a future-ready speech-to-text → interpreter → live context → response → text-to-speech pipeline. Device control is intentionally disabled; future pump or valve actions must pass safety checks, explicit user confirmation, device acknowledgement, and action logging before the system may claim anything happened.

The same page includes seven safe training challenges: Database & Security, Sensor Gone Crazy, Alien Attack, Water Crisis, Sensor Failure, Fun Box, and Final Boss: Perfect Storm. Start one from the selector, watch the existing cards and alerts react, then use **Reset** or **Stop**. Challenge readings use the real sensor-processing and risk functions but remain in memory; they are not inserted into the production `sensor_readings` table. Live ESP32 readings continue to be stored while a challenge is active, but the challenge remains visible until it is stopped. Stopping restores the latest live reading when it is no more than 15 seconds old.

Fun Box provides manual values plus Heat Wave, Flood, Drought, Alien, Animal, Night, Break Sensor, and Random Chaos presets. “Alien” is explicitly a game scenario for an unknown multi-sensor intrusion pattern, not a claim that aliens exist.

## 2. Find the laptop LAN address

The ESP32 cannot use `localhost` or `127.0.0.1` because those names point back to the ESP32 itself.

In PowerShell or Command Prompt run:

```powershell
ipconfig
```

Find the active Wi-Fi adapter and copy its **IPv4 Address**, for example `192.168.1.100`. The ESP32 and laptop must be connected to the same Wi-Fi network. Allow Python through Windows Firewall on private networks if prompted.

## 3. Wire safely

The supplied defaults avoid ESP32 boot-strapping pins and put all four analog sensors on ADC1 pins, because ADC2 conflicts with Wi-Fi.

| Module signal | ESP32 default | Important note |
|---|---:|---|
| Ultrasonic TRIG | GPIO 23 | Digital output |
| Ultrasonic ECHO | GPIO 22 | Use a resistor divider if ECHO is 5 V |
| LDR analog | GPIO 34 | ADC1, input-only |
| Steam analog | GPIO 35 | ADC1, input-only |
| Soil analog | GPIO 32 | ADC1 |
| Water-level analog | GPIO 33 | ADC1 |
| DHT data | GPIO 27 | Set `DHT11` or `DHT22` to match the module |
| PIR output | GPIO 26 | Confirm the module output does not exceed 3.3 V |
| Passive buzzer | GPIO 25 | Passive piezo only; use a driver for larger loads |
| All grounds | GND | ESP32 and every sensor must share ground |

ESP32 GPIO inputs must never receive more than 3.3 V. Many HC-SR04 boards output 5 V on ECHO; use a voltage divider before GPIO 22. Power analog modules at 3.3 V when their documentation permits it. If a module requires 5 V, verify its analog output and divide it to 3.3 V maximum. Never drive a pump, siren, relay coil, or other high-current load directly from a GPIO.

## 4. Configure and upload in Arduino IDE 1.8.19

1. Install ESP32 board support in Arduino IDE.
2. In Library Manager install **ArduinoJson**, **DHT sensor library**, **PubSubClient**, and the Adafruit Unified Sensor dependency if requested.
3. Open `esp32_example.ino`.
4. Set `WIFI_SSID` and `WIFI_PASSWORD`.
5. Set `SERVER_URL` to `http://YOUR_LAPTOP_IPV4:7862/api/sensors`.
6. Set `API_KEY` to the same value used in `FARMGUARD_API_KEY` on the server.
7. Confirm the device ID, pins, `DHT_TYPE`, and calibration values.
8. Select the correct ESP32 board and COM port, then upload.
9. Open Serial Monitor at **115200 baud**. Each sample appears as JSON followed by its HTTP result.

For soil calibration, record the raw ADC value in dry soil and wet soil and update `SOIL_DRY_RAW` / `SOIL_WET_RAW`. Do the same with an empty and full water sensor. Reversed sensors are supported because the mapping uses both endpoints.

## Live API

The ESP32 sends `POST /api/sensors` with an `X-API-Key` header:

```json
{
  "device_id": "esp32-farm-01",
  "sequence": 42,
  "soil_moisture": 62.0,
  "temperature": 29.1,
  "humidity": 66.0,
  "light": 2580,
  "steam": 420,
  "motion": false,
  "water_level": 72.0,
  "ultrasonic_distance": 28.4,
  "uptime": 120
}
```

Any failed sensor may be `null`. Missing values stay null in SQLite and are shown as **Sensor unavailable**; they are never converted to zero. A successful response includes:

```json
{"success": true, "message": "Sensor data received", "buzzer_mode": "OFF"}
```

The dashboard polls `GET /api/sensors/latest` every three seconds. `GET /api/sensors/history` provides stored readings. The original `/api/v1/telemetry` route remains available for older two-sensor firmware.

## Decisions and thresholds

The Integrator Console can adjust low soil moisture, high temperature, low humidity, low water, high steam, ultrasonic settings, and the device offline timeout. The timeout defaults to 25 seconds. A useful combined recommendation appears when soil is dry, temperature is high, and sufficient water is available.

The API key is read only from `FARMGUARD_API_KEY`; it is deliberately never returned to either dashboard. For a real deployment, always change the local placeholder and keep the server on a trusted private network.

## Live MQTT and MySQL integration

FarmGuard subscribes to the deployed ESP32 topics `farmguard/sensors` and `farmguard/status`. Legacy `/test`, `/verify`, and `/broadcast` subscriptions remain for backward compatibility. The listener runs in Paho MQTT's background network loop, reconnects automatically, parses JSON safely, validates it with the same `SensorPacket`, and passes accepted readings through the existing risk engine, interpreter, alerts, SQLite history, and optional MySQL mirror.

The deployed payload is accepted directly:

```json
{
  "device": "farmguard-esp32",
  "uptime_s": 159,
  "light_raw": 3015,
  "brightness": 3015,
  "soil_raw": 0,
  "soil_pct": 100,
  "water_raw": 2194,
  "steam_raw": 0,
  "temp_c": 24.5,
  "humidity_pct": 57.6,
  "distance_cm": 10.3,
  "motion_count": 0,
  "motion_now": false,
  "pump": false,
  "fan": false,
  "led": false,
  "reservoir_state": 1,
  "wifi_rssi": -66
}
```

FarmGuard maps `temp_c`, `humidity_pct`, `distance_cm`, and `motion_now` to its canonical fields, while preserving raw soil, water, steam, actuator, reservoir, counter, RSSI, device, and uptime values. It does not derive a water percentage when the ESP32 sends only `water_raw`; the owner view displays the real raw value instead.

Copy `.env.example` to `.env` and fill in the real values locally:

```dotenv
MQTT_HOST=127.0.0.1
MQTT_PORT=1884
MQTT_TOPIC=farmguard/sensors
MQTT_STATUS_TOPIC=farmguard/status
DB_HOST=192.168.98.50
DB_PORT=3306
DB_NAME="your database name"
DB_USER="your database user"
DB_PASSWORD="your private password"
RASPBERRY_PI_HOST=192.168.200.11
PORT=7862
```

The real `.env` is ignored by Git. Credentials are never returned by the API or displayed in the dashboard.

Validated MQTT readings remain in SQLite and are also mirrored into MySQL table `sensor_values` as `device_id`, `sensor`, `sensor_value`, and `created_at`. If MySQL is unavailable, up to 500 readings are buffered in memory and synchronized after a later successful connection. The dashboard continues operating throughout an MQTT or MySQL outage.

Connection state is visible in the Integrator Console and through `GET /api/integrations/status`. The supplied servers must be reachable from the FarmGuard computer; devices on different subnets may require the correct Wi-Fi, a router route, or a VPN.

The UI labels the sensor feed **LIVE** for samples no older than 5 seconds, **STALE** from over 5 through 15 seconds, and **OFFLINE** after 15 seconds or whenever the MQTT client is disconnected. A zero soil raw value, zero steam raw value, zero water raw value, or a sharp water-raw drop is shown as a quality warning; the original reading is retained and never silently replaced.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Project map

```text
app.py                 FastAPI API, SQLite storage, polling data contracts
farmguard_engine.py    Sensor-fusion rules and simulation scenarios
esp32_example.ino      Arduino IDE 1.8.19 seven-sensor firmware
web/                   Existing owner and integrator dashboard interface
tests/                 Engine and API tests
```
