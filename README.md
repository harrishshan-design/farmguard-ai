# FarmGuard AI — Python Sensor Dashboard

FarmGuard AI is a decision-first smart agriculture dashboard for the **Save The Farm!** hackathon track. It does more than show sensor charts: it verifies telemetry, calculates risk, ranks the most urgent zone, recommends an action, activates irrigation and confirms recovery.

## What is included

- Command centre with farm health, critical zones, trusted devices and water reserve
- Three monitored zones with soil moisture, temperature, humidity and light
- Deterministic health/risk engine: `HEALTHY`, `WATCH`, `WARNING`, `CRITICAL` and `VERIFY`
- Grounded advisor that explains only the verified farm state
- Manual irrigation approval and closed-loop recovery verification
- Device registry, token checks and anomaly isolation
- Evidence timeline for detections, actions, blocked packets and recovery
- Offline-safe simulator for a reliable 90-second demo
- FastAPI telemetry endpoint for ESP32 or Raspberry Pi integration
- Dependency-free Python sensor client for Raspberry Pi, serial gateways, or test data
- Live-reading protection so the demo simulator never overwrites recently received sensor data
- Read-only state and device-discovery APIs for integrations

## Quick start on Windows

Open PowerShell inside this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py app.py
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860).

Check the server from another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:7860/health
```

## Connect a Python-capable sensor or Raspberry Pi

First start `app.py`. Then verify the full connection with the included client:

```powershell
python sensor_client.py --once
```

For a sensor computer on the same network, point it at the dashboard computer:

```powershell
python sensor_client.py `
  --server http://192.168.1.100:7860 `
  --device-id esp32-field-01 `
  --token farmguard-demo-01 `
  --zone-id zone-a
```

To connect physical hardware, open `sensor_client.py` and replace only the body of
`read_sensors()` with your GPIO, I2C, ADC, or serial library calls. It must return:

```python
return {
    "moisture": soil_moisture_percent,
    "temperature": temperature_celsius,
    "humidity": relative_humidity_percent,
    "light": light_percent,
}
```

You can also import `send_reading()` into an existing Python sensor program. Values
are validated by the server, and accepted live readings take priority over the demo
simulation for 30 seconds. Change this window with the
`FARMGUARD_LIVE_HOLD_SECONDS` environment variable.

## Connect an ESP32

Open `esp32_example.ino` in Arduino IDE, set `WIFI_SSID`, `WIFI_PASSWORD`, and
`SERVER_URL`, then replace the four demo numbers in `loop()` with your sensor reads.
The computer and ESP32 must be reachable on the same network.

If PowerShell blocks activation, use:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Quick start on macOS/Linux/Raspberry Pi

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 app.py
```

## 90-second demo flow

1. Open **Command Centre** and explain the health score, zones and trusted devices.
2. Open **Demo Controls**, select a zone and click **Simulate dry soil**.
3. Return to **Command Centre**. Show the critical state, reasons and priority action.
4. Click **Approve irrigation** in Demo Controls.
5. Watch soil moisture rise automatically.
6. Show the event timeline when FarmGuard records **Recovery verified** and stops irrigation.
7. Click **Test untrusted device** to demonstrate that invalid telemetry is blocked.

## Send real ESP32/Raspberry Pi data

The dashboard exposes:

```text
POST http://YOUR_COMPUTER_IP:7860/api/telemetry
Content-Type: application/json
```

Example payload:

```json
{
  "device_id": "esp32-field-01",
  "token": "farmguard-demo-01",
  "zone_id": "zone-a",
  "moisture": 31.5,
  "temperature": 32.1,
  "humidity": 59.0,
  "light": 76.0
}
```

Registered demo credentials:

| Zone | Device ID | Token |
|---|---|---|
| Zone A | `esp32-field-01` | `farmguard-demo-01` |
| Zone B | `esp32-field-02` | `farmguard-demo-02` |
| Nursery | `esp32-nursery-01` | `farmguard-demo-03` |

Use your computer's LAN/static IP when the sensor is on the same Wi-Fi network. Allow TCP port `7860` through the firewall. Replace the demo tokens before any real deployment.

Useful read-only endpoints:

- `GET /health` — service health
- `GET /api/devices` — registered device IDs, zones, and last-seen values (tokens omitted)
- `GET /api/state` — current sensor values, decisions, water reserve, and actuator state

## Decision logic

The core decision path does not depend on an internet AI service:

```text
sensor -> identity/range validation -> risk engine -> priority -> action -> recovery check
```

Examples:

- Soil moisture below 20%: +45 risk
- Temperature above 34°C: +22 risk
- Humidity below 40%: +12 risk
- Rapid moisture drop: +18 risk
- Suspicious jump: isolate reading and hold automation

The advisor translates that structured state into plain language. The sensor result and status remain deterministic.

## Production upgrades after the hackathon

- Store readings and events in PostgreSQL/Supabase
- Use MQTT with TLS instead of direct HTTP for many field devices
- Hash/rotate device secrets and add replay protection with timestamps/nonces
- Drive a relay/pump through a separate safe actuator service
- Add crop-specific policies calibrated with an agriculture expert
- Add Telegram alerts and weather forecasts without putting them in the critical control path

## Safety note

The included actuator is a software simulation. For a real pump, use a properly rated relay, independent electrical protection, a maximum run-time cutoff and manual override. Do not power a pump directly from an ESP32 GPIO pin.

## Run the automated checks

```bash
python -m unittest discover -s tests -v
```
