"""FarmGuard AI — decision-first smart agriculture dashboard.

Run locally:
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:7860. ESP32 devices can POST JSON telemetry to
http://<computer-ip>:7860/api/telemetry.
"""

from __future__ import annotations

import copy
import os
import random
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import gradio as gr
import pandas as pd
import plotly.graph_objects as go
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


APP_TITLE = "FarmGuard AI"
MYT = ZoneInfo("Asia/Kuala_Lumpur")
LIVE_READING_HOLD_SECONDS = int(os.getenv("FARMGUARD_LIVE_HOLD_SECONDS", "30"))


def now_text() -> str:
    return datetime.now(MYT).strftime("%H:%M:%S")


class Telemetry(BaseModel):
    device_id: str = Field(min_length=2, max_length=80)
    token: str = Field(min_length=4, max_length=160)
    zone_id: str = Field(min_length=2, max_length=40)
    moisture: float = Field(ge=0, le=100)
    temperature: float = Field(ge=-10, le=70)
    humidity: float = Field(ge=0, le=100)
    light: float = Field(ge=0, le=100)


class FarmEngine:
    """Thread-safe in-memory demo engine with deterministic decisions."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "lock", threading.RLock()):
            self.water_reserve = 72.0
            self.rejected_packets = 0
            self.irrigating_zone: str | None = None
            self.irrigation_ticks = 0
            self.devices = {
                "esp32-field-01": {
                    "token": "farmguard-demo-01",
                    "zone": "zone-a",
                    "status": "Trusted",
                    "last_seen": now_text(),
                },
                "esp32-field-02": {
                    "token": "farmguard-demo-02",
                    "zone": "zone-b",
                    "status": "Trusted",
                    "last_seen": now_text(),
                },
                "esp32-nursery-01": {
                    "token": "farmguard-demo-03",
                    "zone": "zone-c",
                    "status": "Trusted",
                    "last_seen": now_text(),
                },
            }
            self.zones = {
                "zone-a": {
                    "name": "Zone A",
                    "crop": "Chilli",
                    "device": "esp32-field-01",
                    "moisture": 48.0,
                    "temperature": 29.4,
                    "humidity": 68.0,
                    "light": 72.0,
                    "previous_moisture": 48.0,
                    "trusted": True,
                    "anomaly": False,
                    "source": "demo",
                    "live_until": None,
                },
                "zone-b": {
                    "name": "Zone B",
                    "crop": "Tomato",
                    "device": "esp32-field-02",
                    "moisture": 35.0,
                    "temperature": 31.2,
                    "humidity": 61.0,
                    "light": 78.0,
                    "previous_moisture": 35.0,
                    "trusted": True,
                    "anomaly": False,
                    "source": "demo",
                    "live_until": None,
                },
                "zone-c": {
                    "name": "Nursery",
                    "crop": "Seedlings",
                    "device": "esp32-nursery-01",
                    "moisture": 56.0,
                    "temperature": 28.1,
                    "humidity": 74.0,
                    "light": 51.0,
                    "previous_moisture": 56.0,
                    "trusted": True,
                    "anomaly": False,
                    "source": "demo",
                    "live_until": None,
                },
            }
            self.events: deque[dict[str, str]] = deque(maxlen=100)
            self.history: deque[dict[str, Any]] = deque(maxlen=180)
            self._event("SYSTEM", "FarmGuard started", "All monitoring rules are online.")
            self._capture_history()

    def _event(self, level: str, event: str, detail: str) -> None:
        self.events.appendleft(
            {"Time": now_text(), "Level": level, "Event": event, "Detail": detail}
        )

    def _capture_history(self) -> None:
        for zone_id, zone in self.zones.items():
            self.history.append(
                {
                    "time": datetime.now(MYT),
                    "zone_id": zone_id,
                    "zone": zone["name"],
                    "moisture": round(zone["moisture"], 1),
                }
            )

    @staticmethod
    def evaluate(zone: dict[str, Any]) -> dict[str, Any]:
        if not zone["trusted"] or zone["anomaly"]:
            return {
                "risk": 70,
                "health": 30,
                "status": "VERIFY",
                "reasons": ["Sensor data requires verification"],
                "action": "Inspect the sensor before allowing automation.",
            }

        risk = 0
        reasons: list[str] = []
        moisture = zone["moisture"]
        temperature = zone["temperature"]
        humidity = zone["humidity"]
        drop = zone["previous_moisture"] - moisture

        if moisture < 20:
            risk += 45
            reasons.append(f"Critical soil moisture ({moisture:.0f}%)")
        elif moisture < 30:
            risk += 28
            reasons.append(f"Low soil moisture ({moisture:.0f}%)")
        elif moisture < 38:
            risk += 12
            reasons.append(f"Moisture trending toward dry ({moisture:.0f}%)")

        if temperature > 34:
            risk += 22
            reasons.append(f"High temperature ({temperature:.1f} °C)")
        elif temperature > 32:
            risk += 10
            reasons.append(f"Elevated temperature ({temperature:.1f} °C)")

        if humidity < 40:
            risk += 12
            reasons.append(f"Low humidity ({humidity:.0f}%)")
        if drop >= 6:
            risk += 18
            reasons.append(f"Rapid moisture drop ({drop:.0f} points)")

        risk = min(risk, 100)
        if risk >= 60:
            status = "CRITICAL"
            action = "Approve irrigation now, then verify moisture recovery."
        elif risk >= 35:
            status = "WARNING"
            action = "Inspect the zone and prepare targeted irrigation."
        elif risk >= 15:
            status = "WATCH"
            action = "Monitor the next readings; no immediate automation needed."
        else:
            status = "HEALTHY"
            action = "No action required. Continue monitoring."

        return {
            "risk": risk,
            "health": 100 - risk,
            "status": status,
            "reasons": reasons or ["All monitored conditions are within range"],
            "action": action,
        }

    def tick(self) -> None:
        """Advance the offline demo simulation by one small step."""
        with self.lock:
            for zone_id, zone in self.zones.items():
                # A real sensor owns its zone briefly after every packet. This keeps
                # the demo animation from corrupting live telemetry between posts.
                live_until = zone.get("live_until")
                if live_until and datetime.now(MYT) < live_until:
                    continue
                if live_until:
                    zone["source"] = "demo"
                    zone["live_until"] = None
                zone["previous_moisture"] = zone["moisture"]
                if zone_id == self.irrigating_zone:
                    zone["moisture"] = min(58, zone["moisture"] + random.uniform(3.5, 5.5))
                    self.water_reserve = max(0, self.water_reserve - 1.1)
                else:
                    zone["moisture"] = max(0, zone["moisture"] - random.uniform(0.02, 0.15))
                zone["temperature"] = max(20, min(43, zone["temperature"] + random.uniform(-0.12, 0.12)))
                zone["humidity"] = max(15, min(95, zone["humidity"] + random.uniform(-0.2, 0.2)))

            if self.irrigating_zone:
                self.irrigation_ticks += 1
                zone = self.zones[self.irrigating_zone]
                if zone["moisture"] >= 42 or self.irrigation_ticks >= 7:
                    recovered_zone = zone["name"]
                    self._event(
                        "SUCCESS",
                        "Recovery verified",
                        f"{recovered_zone} reached {zone['moisture']:.1f}% moisture; irrigation stopped.",
                    )
                    self.irrigating_zone = None
                    self.irrigation_ticks = 0
            self._capture_history()

    def simulate_drought(self, zone_id: str) -> None:
        with self.lock:
            zone = self.zones[zone_id]
            zone["previous_moisture"] = 40.0
            zone["moisture"] = 16.0
            zone["temperature"] = 36.8
            zone["humidity"] = 37.0
            zone["anomaly"] = False
            result = self.evaluate(zone)
            self._event(
                "CRITICAL",
                "Water stress detected",
                f"{zone['name']} risk {result['risk']}/100; ranked as the first action priority.",
            )
            self._capture_history()

    def approve_irrigation(self, zone_id: str) -> None:
        with self.lock:
            zone = self.zones[zone_id]
            result = self.evaluate(zone)
            if result["status"] in {"VERIFY", "HEALTHY"}:
                self._event(
                    "INFO",
                    "Action held",
                    f"Irrigation for {zone['name']} was not started: {result['status'].lower()} state.",
                )
                return
            if self.water_reserve < 10:
                self._event("CRITICAL", "Irrigation blocked", "Water reserve is below the safe limit.")
                return
            self.irrigating_zone = zone_id
            self.irrigation_ticks = 0
            self._event(
                "ACTION",
                "Irrigation approved",
                f"Pump activated for {zone['name']}; FarmGuard is now checking recovery.",
            )

    def inject_untrusted(self) -> None:
        with self.lock:
            self.rejected_packets += 1
            self._event(
                "BLOCKED",
                "Unknown device rejected",
                "rogue-sensor-99 attempted to submit 2% moisture without a valid token.",
            )

    def ingest(self, packet: Telemetry) -> dict[str, Any]:
        with self.lock:
            device = self.devices.get(packet.device_id)
            if not device or device["token"] != packet.token:
                self.rejected_packets += 1
                self._event("BLOCKED", "Telemetry rejected", f"Untrusted device: {packet.device_id}.")
                raise ValueError("Device identity or token is invalid")
            if device["zone"] != packet.zone_id or packet.zone_id not in self.zones:
                self.rejected_packets += 1
                self._event("BLOCKED", "Zone mismatch", f"{packet.device_id} cannot write to {packet.zone_id}.")
                raise ValueError("Device is not registered to this zone")

            zone = self.zones[packet.zone_id]
            suspicious_jump = abs(packet.moisture - zone["moisture"]) > 45
            if suspicious_jump:
                zone["anomaly"] = True
                self._event(
                    "VERIFY",
                    "Sensor anomaly isolated",
                    f"{packet.device_id} reported an implausible moisture jump; automation is held.",
                )
                return {"accepted": False, "reason": "suspicious_jump", "requires_verification": True}

            zone["previous_moisture"] = zone["moisture"]
            zone.update(
                moisture=packet.moisture,
                temperature=packet.temperature,
                humidity=packet.humidity,
                light=packet.light,
                anomaly=False,
                trusted=True,
                source="sensor",
                live_until=datetime.now(MYT) + timedelta(seconds=LIVE_READING_HOLD_SECONDS),
            )
            device["last_seen"] = now_text()
            result = self.evaluate(zone)
            self._capture_history()
            self._event(
                "SENSOR",
                "Live telemetry received",
                f"{packet.device_id} updated {zone['name']} at {packet.moisture:.1f}% moisture.",
            )
            return {"accepted": True, "zone": packet.zone_id, "source": "sensor", **result}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            zones = copy.deepcopy(self.zones)
            evaluations = {zone_id: self.evaluate(zone) for zone_id, zone in zones.items()}
            return {
                "zones": zones,
                "evaluations": evaluations,
                "events": list(self.events),
                "history": list(self.history),
                "devices": copy.deepcopy(self.devices),
                "water_reserve": self.water_reserve,
                "rejected_packets": self.rejected_packets,
                "irrigating_zone": self.irrigating_zone,
            }


engine = FarmEngine()


STATUS_COLOURS = {
    "HEALTHY": "#42d392",
    "WATCH": "#f2c94c",
    "WARNING": "#ff9f43",
    "CRITICAL": "#ff5d6c",
    "VERIFY": "#a78bfa",
}


def priority(snapshot: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    zone_id = max(snapshot["evaluations"], key=lambda item: snapshot["evaluations"][item]["risk"])
    return zone_id, snapshot["zones"][zone_id], snapshot["evaluations"][zone_id]


def kpi_html(snapshot: dict[str, Any]) -> str:
    evaluations = snapshot["evaluations"]
    health = round(sum(item["health"] for item in evaluations.values()) / len(evaluations))
    critical = sum(item["status"] == "CRITICAL" for item in evaluations.values())
    trusted = sum(device["status"] == "Trusted" for device in snapshot["devices"].values())
    cards = [
        ("Farm health", f"{health}/100", "Overall verified condition"),
        ("Critical zones", str(critical), "Requires immediate action"),
        ("Trusted sensors", f"{trusted}/{len(snapshot['devices'])}", f"{snapshot['rejected_packets']} packets blocked"),
        ("Water reserve", f"{snapshot['water_reserve']:.0f}%", "Available for irrigation"),
    ]
    return '<div class="kpi-grid">' + "".join(
        f'<div class="kpi"><span>{label}</span><strong>{value}</strong><small>{caption}</small></div>'
        for label, value, caption in cards
    ) + "</div>"


def zone_cards_html(snapshot: dict[str, Any]) -> str:
    items = []
    for zone_id, zone in snapshot["zones"].items():
        result = snapshot["evaluations"][zone_id]
        colour = STATUS_COLOURS[result["status"]]
        live = "Irrigating" if snapshot["irrigating_zone"] == zone_id else "Live"
        items.append(
            f"""
            <div class="zone-card" style="--status:{colour}">
              <div class="zone-top"><div><b>{zone['name']}</b><small>{zone['crop']} · {zone['device']}</small></div>
              <span class="status">{result['status']}</span></div>
              <div class="moisture"><strong>{zone['moisture']:.1f}%</strong><span>soil moisture</span></div>
              <div class="meter"><i style="width:{min(zone['moisture'], 100):.0f}%"></i></div>
              <div class="zone-stats"><span>🌡 {zone['temperature']:.1f}°C</span><span>💧 {zone['humidity']:.0f}% RH</span><span>☀ {zone['light']:.0f}%</span></div>
              <div class="zone-foot"><span>Risk {result['risk']}/100</span><span>● {live} · {zone.get('source', 'demo').title()}</span></div>
            </div>"""
        )
    return '<div class="zone-grid">' + "".join(items) + "</div>"


def advisor_markdown(snapshot: dict[str, Any]) -> str:
    zone_id, zone, result = priority(snapshot)
    reason_text = "; ".join(result["reasons"])
    action_state = "Irrigation is running and recovery is being measured." if snapshot["irrigating_zone"] == zone_id else result["action"]
    return (
        f"### Priority 1 · {zone['name']} — {result['status']}\n\n"
        f"**Why:** {reason_text}.\n\n"
        f"**Recommended action:** {action_state}\n\n"
        "> Grounded advisor: this explanation is generated only from the verified deterministic farm state."
    )


def history_chart(snapshot: dict[str, Any]) -> go.Figure:
    fig = go.Figure()
    frame = pd.DataFrame(snapshot["history"])
    if not frame.empty:
        for zone_name, group in frame.groupby("zone"):
            fig.add_trace(
                go.Scatter(
                    x=group["time"],
                    y=group["moisture"],
                    mode="lines",
                    name=zone_name,
                    line={"width": 3, "shape": "spline"},
                )
            )
    fig.add_hrect(y0=0, y1=20, fillcolor="#ff5d6c", opacity=0.08, line_width=0)
    fig.add_hline(y=20, line_dash="dot", line_color="#ff7a86", annotation_text="Critical threshold")
    fig.update_layout(
        title={"text": "Soil moisture trend", "font": {"size": 18}},
        height=330,
        margin={"l": 35, "r": 20, "t": 50, "b": 30},
        paper_bgcolor="#0e1712",
        plot_bgcolor="#0e1712",
        font={"color": "#d8e9de"},
        legend={"orientation": "h", "y": 1.13, "x": 0},
        yaxis={"title": "Moisture %", "range": [0, 70], "gridcolor": "#243a2e"},
        xaxis={"title": None, "gridcolor": "#243a2e"},
        hovermode="x unified",
    )
    return fig


def events_frame(snapshot: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(snapshot["events"], columns=["Time", "Level", "Event", "Detail"])


def devices_frame(snapshot: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for device_id, device in snapshot["devices"].items():
        rows.append(
            {
                "Device": device_id,
                "Zone": snapshot["zones"][device["zone"]]["name"],
                "Trust": device["status"],
                "Last seen": device["last_seen"],
            }
        )
    return pd.DataFrame(rows)


def state_json(snapshot: dict[str, Any]) -> dict[str, Any]:
    zone_id, zone, result = priority(snapshot)
    return {
        "farm_state": "CRITICAL" if any(v["status"] == "CRITICAL" for v in snapshot["evaluations"].values()) else "MONITORING",
        "priority_zone": zone_id,
        "priority_status": result["status"],
        "verified_reasons": result["reasons"],
        "recommended_action": result["action"],
        "actuator": {
            "irrigation_active": snapshot["irrigating_zone"] is not None,
            "zone": snapshot["irrigating_zone"],
        },
    }


def refresh(advance: bool = True):
    if advance:
        engine.tick()
    snapshot = engine.snapshot()
    return (
        kpi_html(snapshot),
        zone_cards_html(snapshot),
        advisor_markdown(snapshot),
        history_chart(snapshot),
        events_frame(snapshot),
        devices_frame(snapshot),
        state_json(snapshot),
    )


def choose_zone(label: str) -> str:
    mapping = {"Zone A · Chilli": "zone-a", "Zone B · Tomato": "zone-b", "Nursery · Seedlings": "zone-c"}
    return mapping.get(label, "zone-a")


def drought_action(selected_zone: str):
    engine.simulate_drought(choose_zone(selected_zone))
    return refresh(advance=False)


def irrigation_action(selected_zone: str):
    engine.approve_irrigation(choose_zone(selected_zone))
    return refresh(advance=False)


def untrusted_action():
    engine.inject_untrusted()
    return refresh(advance=False)


def reset_action():
    engine.reset()
    return refresh(advance=False)


CSS = """
:root { --green:#42d392; --surface:#111d16; --line:#263a2e; }
.gradio-container { background: radial-gradient(circle at 15% 0%, #173324 0, #09110d 34%, #080d0a 100%) !important; color:#e9f5ed; }
.app-shell { max-width:1500px; margin:auto; }
.hero { display:flex; justify-content:space-between; align-items:flex-end; gap:20px; padding:18px 2px 12px; }
.brand { display:flex; align-items:center; gap:14px; }
.brand-mark { width:48px; height:48px; border-radius:15px; display:grid; place-items:center; background:linear-gradient(135deg,#55eea3,#159c64); box-shadow:0 10px 35px #24ca7950; font-size:25px; }
.brand h1 { margin:0; font-size:29px; letter-spacing:-1px; color:#f5fff7; }
.brand p { margin:3px 0 0; color:#8fb6a0; font-size:13px; }
.live-pill { border:1px solid #2a5c42; border-radius:999px; padding:7px 12px; color:#91eab6; background:#123322; font-size:12px; }
.kpi-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:8px 0 16px; }
.kpi { border:1px solid var(--line); border-radius:17px; padding:16px 18px; background:linear-gradient(145deg,#14231a,#0f1913); box-shadow:0 12px 30px #0004; }
.kpi span,.kpi small { display:block; color:#89aa96; } .kpi span{font-size:12px;text-transform:uppercase;letter-spacing:.7px}.kpi strong{display:block;font-size:28px;margin:7px 0;color:#f3fff7}.kpi small{font-size:11px}
.zone-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.zone-card { border:1px solid var(--line); border-top:3px solid var(--status); border-radius:17px; padding:16px; background:#111d16; }
.zone-top,.zone-foot,.zone-stats { display:flex; justify-content:space-between; align-items:center; gap:8px; }
.zone-top b{font-size:17px}.zone-top small{display:block;color:#789687;margin-top:3px}.status{color:var(--status);border:1px solid var(--status);padding:4px 8px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.6px}
.moisture{margin:18px 0 8px}.moisture strong{font-size:28px}.moisture span{display:block;color:#7f9c8b;font-size:11px}.meter{height:6px;background:#26362d;border-radius:9px;overflow:hidden}.meter i{display:block;height:100%;background:var(--status);border-radius:9px}.zone-stats{color:#a7c0ae;font-size:12px;margin:16px 0}.zone-foot{border-top:1px solid #25372c;padding-top:11px;color:#71917e;font-size:11px}
.panel { border:1px solid var(--line) !important; border-radius:17px !important; background:#101a14 !important; }
.control-note { color:#8cab98; font-size:12px; margin-top:-4px; }
.footer-note { text-align:center;color:#688273;font-size:11px;padding:20px 0 5px; }
button.primary { background:linear-gradient(135deg,#36d98b,#159b62) !important; border:none !important; color:#06110b !important; font-weight:800 !important; }
@media(max-width:900px){.kpi-grid{grid-template-columns:repeat(2,1fr)}.zone-grid{grid-template-columns:1fr}.hero{align-items:flex-start;flex-direction:column}}
"""


def build_dashboard() -> gr.Blocks:
    initial = refresh(advance=False)
    with gr.Blocks(title=APP_TITLE, fill_width=True) as dashboard:
        with gr.Column(elem_classes="app-shell"):
            gr.HTML(
                """<div class="hero"><div class="brand"><div class="brand-mark">🌱</div><div>
                <h1>FarmGuard AI</h1><p>Sense · Verify · Understand · Act · Measure</p></div></div>
                <div class="live-pill">● OFFLINE-SAFE MONITORING ONLINE</div></div>"""
            )
            kpis = gr.HTML(initial[0])

            with gr.Tabs():
                with gr.Tab("Command Centre"):
                    zones = gr.HTML(initial[1])
                    with gr.Row(equal_height=True):
                        with gr.Column(scale=5, elem_classes="panel"):
                            advisor = gr.Markdown(initial[2])
                        with gr.Column(scale=7, elem_classes="panel"):
                            chart = gr.Plot(initial[3], show_label=False)

                with gr.Tab("Events & Trust"):
                    gr.Markdown("### Evidence timeline\nEvery sensing, trust, decision, action and recovery event is recorded.")
                    events = gr.Dataframe(
                        value=initial[4],
                        headers=["Time", "Level", "Event", "Detail"],
                        interactive=False,
                        wrap=True,
                        elem_classes="panel",
                    )
                    with gr.Row():
                        devices = gr.Dataframe(value=initial[5], interactive=False, elem_classes="panel")
                        structured_state = gr.JSON(value=initial[6], label="Verified state supplied to the AI layer")

                with gr.Tab("Demo Controls"):
                    gr.Markdown(
                        "### 90-second judge demo\nSelect a zone, create water stress, approve irrigation, then watch FarmGuard verify recovery."
                    )
                    selected_zone = gr.Dropdown(
                        choices=["Zone A · Chilli", "Zone B · Tomato", "Nursery · Seedlings"],
                        value="Zone A · Chilli",
                        label="Demo zone",
                    )
                    with gr.Row():
                        drought = gr.Button("1 · Simulate dry soil", variant="stop")
                        irrigate = gr.Button("2 · Approve irrigation", variant="primary")
                        attack = gr.Button("Test untrusted device")
                        reset = gr.Button("Reset demo")
                    gr.HTML(
                        '<p class="control-note">Tip: after approval, return to Command Centre. Moisture rises automatically until recovery is verified and the pump stops.</p>'
                    )

            gr.HTML('<div class="footer-note">Deterministic monitoring establishes truth. AI explains only the verified farm state.</div>')

        outputs = [kpis, zones, advisor, chart, events, devices, structured_state]
        drought.click(drought_action, inputs=selected_zone, outputs=outputs)
        irrigate.click(irrigation_action, inputs=selected_zone, outputs=outputs)
        attack.click(untrusted_action, outputs=outputs)
        reset.click(reset_action, outputs=outputs)
        timer = gr.Timer(value=2.0, active=True)
        timer.tick(refresh, outputs=outputs, show_progress="hidden")
    return dashboard


dashboard = build_dashboard()
api = FastAPI(title="FarmGuard AI API", version="1.0.0")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "FarmGuard AI"}


@api.get("/api/state")
def api_state() -> dict[str, Any]:
    """Machine-readable current farm state for integrations."""
    snapshot = engine.snapshot()
    return {
        "zones": snapshot["zones"],
        "evaluations": snapshot["evaluations"],
        "water_reserve": snapshot["water_reserve"],
        "irrigating_zone": snapshot["irrigating_zone"],
    }


@api.get("/api/devices")
def api_devices() -> dict[str, Any]:
    """List the registered device IDs and zones without exposing tokens."""
    snapshot = engine.snapshot()
    return {
        device_id: {"zone": details["zone"], "last_seen": details["last_seen"]}
        for device_id, details in snapshot["devices"].items()
    }


@api.post("/api/telemetry")
def telemetry(packet: Telemetry) -> dict[str, Any]:
    try:
        return engine.ingest(packet)
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


app = gr.mount_gradio_app(
    api,
    dashboard,
    path="/",
    css=CSS,
    theme=gr.themes.Base(primary_hue="green", neutral_hue="slate"),
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("FARMGUARD_HOST", "0.0.0.0"), port=int(os.getenv("PORT", "7860")))
