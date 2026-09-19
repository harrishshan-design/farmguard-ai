# FarmGuard AI — ESP32 Farm Decision System

FarmGuard AI turns three inexpensive components into one intelligent farm decision
system instead of simply displaying sensor readings:

- **HC-SR04 ultrasonic sensor** → tank/trough/feed level or perimeter proximity
- **Photoresistor (LDR)** → light percentage, day/night context, abnormal lighting
- **Passive buzzer** → physical `OFF`, `PULSE`, or `ALARM` output

This version uses FastAPI and a purpose-built responsive web interface. It contains
**no Streamlit and no Gradio**.

## Two dashboards for two audiences

### Farm Owner Dashboard — `/`

Designed for quick decisions, not configuration:

- 0–100 Farm Health Score
- One clear status: Good, Watch, or Action
- Plain-language recommended actions
- Water/feed level, light, movement, and buzzer cards
- Live trend chart
- Important event timeline
- Mobile and sunlight-readable layout

### Integrator Console — `/integrator`

Designed for the developer installing and testing hardware:

- ESP32 connection and freshness status
- Telemetry endpoint, device ID, and token
- Copyable JSON payload
- Wiring reference
- Raw distance, ADC, sequence, latency, and packet diagnostics
- Installation profile and threshold calibration
- Six simulation scenarios
- Remote buzzer tests
- Raw telemetry and security/event logs
- CSV exports and interactive API documentation

## Run on Windows

```powershell
git clone https://github.com/harrishshan-design/farmguard-ai.git
cd farmguard-ai
.\start_farmguard.ps1
```

Open:

- Farm owner: <http://127.0.0.1:7860>
- Integrator: <http://127.0.0.1:7860/integrator>
- API reference: <http://127.0.0.1:7860/api/docs>

## Run on macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 app.py
```

## ESP32 wiring

The included `esp32_example.ino` uses:

| Hardware | ESP32 pin |
|---|---:|
| HC-SR04 trigger | GPIO 5 |
| HC-SR04 echo | GPIO 18 through a voltage divider |
| Photoresistor analog output | GPIO 34 |
| Passive piezo buzzer | GPIO 25 |
| Common ground | GND |

Important electrical notes:

- ESP32 GPIO is **3.3 V only**. A common HC-SR04 echo signal is 5 V; add a voltage
  divider or level shifter before GPIO 18.
- Use a photoresistor voltage divider or analog module. GPIO 34 is input-only and
  supports ADC readings.
- The firmware generates tone frequencies for a passive buzzer. Verify its current
  requirement; use a transistor driver if the buzzer exceeds safe GPIO current.
- Do not connect pumps, sirens, or high-current loads directly to an ESP32 pin.

## Upload the ESP32 firmware

1. Open `esp32_example.ino` in Arduino IDE.
2. Install the **ArduinoJson** library from Library Manager.
3. Set `WIFI_SSID` and `WIFI_PASSWORD`.
4. Replace the IP in `SERVER_URL` with the dashboard computer's LAN address.
5. Keep the device ID and token equal to those shown in the Integrator Console.
6. Select your ESP32 board and upload.
7. Open Serial Monitor at `115200` baud.

The ESP32 posts every two seconds and receives the buzzer command in the same API
response. If the server is unreachable for 12 seconds, the firmware fails safe by
activating the local alarm pattern.

## Installation profiles

One ultrasonic sensor should have one real installation purpose:

- **Level** — distance becomes remaining tank, trough, or feed-bin percentage.
- **Perimeter** — close distance becomes animal/person proximity risk.
- **Combined demo** — demonstrates both interpretations for a hackathon judge.

The Integrator Console changes this profile without changing the farm-owner interface.

## Telemetry contract

```http
POST /api/v1/telemetry
Content-Type: application/json
```

```json
{
  "device_id": "esp32-farm-01",
  "token": "farmguard-device-01",
  "sequence": 1,
  "distance_cm": 45.2,
  "light_raw": 2580
}
```

The response contains the verified decision and the physical buzzer command:

```json
{
  "accepted": true,
  "buzzer_mode": "OFF",
  "sample_interval_ms": 2000,
  "decision": {
    "health_score": 100,
    "status": "GOOD"
  }
}
```

Sequence numbers must increase. Invalid tokens and replayed packets are rejected and
recorded in the evidence log.

## Simulation and offline behavior

The application starts in simulation mode so the complete demonstration works without
hardware. A valid ESP32 packet automatically takes control and disables simulation.

Available scenarios:

- Healthy farm
- Low tank/feed level
- Animal or intruder nearby
- Unexpected daytime darkness
- Unexpected night lighting
- Critical combined risk

If hardware telemetry stops, the dashboards mark the ESP32 offline after 12 seconds
and recommend checking power, Wi-Fi, and the server address.

## Configuration and security

For a private LAN demonstration, the default token is `farmguard-device-01`. Change it
before real deployment:

```powershell
$env:FARMGUARD_DEVICE_TOKEN = "a-long-random-secret"
python app.py
```

Update the firmware token to match. The Integrator Console intentionally displays the
token for commissioning, so do not expose this prototype directly to the public
internet. Put production deployments behind authentication and TLS.

## Data and tests

Telemetry and events are stored locally in `farmguard.db` using SQLite. CSV exports are
available from the Integrator Console.

```powershell
python -m unittest discover -s tests -v
```

## Project structure

```text
app.py                 FastAPI gateway, SQLite history, API, and page routes
farmguard_engine.py    Tested sensor-fusion and buzzer decision policy
web/index.html         Simple farm-owner dashboard
web/integrator.html    Advanced installer/developer console
web/styles.css         Responsive field-instrument visual system
web/owner.js           Owner dashboard live-data rendering
web/integrator.js      Calibration, test, and diagnostics interactions
esp32_example.ino      Complete ESP32 sensor and passive-buzzer firmware
tests/                 Decision-engine and API checks
```
