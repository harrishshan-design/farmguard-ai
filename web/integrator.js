"use strict";

const $ = (id) => document.getElementById(id);
let current = null;
let configLoaded = false;

function text(id, value) { const node = $(id); if (node) node.textContent = String(value); }
function shown(value, suffix = "") { return value === null || value === undefined ? "Sensor unavailable" : `${value}${suffix}`; }
function toast(message) { text("toast", message); $("toast").classList.add("show"); setTimeout(() => $("toast").classList.remove("show"), 1800); }
async function jsonRequest(url, options = {}) { const response = await fetch(url, { headers: {"Content-Type": "application/json"}, ...options }); if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || `${response.status} ${response.statusText}`); } return response.json(); }

function renderState(state, latency) {
  current = state; const d = state.decision; document.body.dataset.severity = d.severity;
  const connected = state.device.connected, mqtt = state.mqtt || {}, mqttState = mqtt.sensor_state; const pill = $("dev-connection-pill"); pill.className = `connection-pill ${mqtt.enabled ? mqttState === "LIVE" ? "online" : mqttState === "OFFLINE" ? "offline" : "" : connected ? "online" : state.simulation.enabled ? "" : "offline"}`;
  text("dev-connection-text", mqtt.enabled ? `ESP32 / MQTT ${mqttState || "OFFLINE"}` : connected ? "ESP32 connected" : state.simulation.enabled ? "Simulator active" : "ESP32 offline"); text("latency-value", `${Math.round(latency)} ms`); text("uptime-value", `${Math.floor(state.uptime_seconds / 60)}m`); text("packet-value", state.rejected_packets);
  text("raw-distance", shown(state.raw.soil_moisture, "%")); text("raw-light", shown(state.raw.temperature, "°C")); text("raw-health", `${d.health_score}/100`); text("raw-buzzer", d.buzzer_mode); text("raw-sequence", state.raw.sequence ?? "—");
  text("trust-chip", mqtt.enabled ? `${mqttState || "OFFLINE"} · ${mqtt.sensor_age_seconds == null ? "no valid sample" : `${mqtt.sensor_age_seconds}s since sample`}` : connected ? "Trusted · receiving" : state.simulation.enabled ? "No hardware · simulated" : "Waiting for telemetry");
  $("endpoint-value").value = `${location.origin}/api/sensors`; $("device-id-value").value = state.config.device_id; $("token-value").value = "X-API-Key";
  text("payload-code", JSON.stringify({device:"farmguard-esp32",uptime_s:159,light_raw:3015,brightness:3015,soil_raw:0,soil_pct:100,water_raw:2194,steam_raw:0,temp_c:24.5,humidity_pct:57.6,distance_cm:10.3,motion_count:0,motion_now:false,pump:false,fan:false,led:false,reservoir_state:1,wifi_rssi:-66}, null, 2));
  const toggle = $("simulation-toggle"); toggle.classList.toggle("on", state.simulation.enabled); toggle.setAttribute("aria-pressed", String(state.simulation.enabled)); $("scenario-input").value = state.simulation.scenario;
  if (!configLoaded && !$("config-form").contains(document.activeElement)) {
    $("profile-input").value = state.config.profile; $("mount-input").value = state.config.mount_height_cm; $("invert-input").value = String(state.config.invert_light);
    $("level-warning-input").value = state.config.level_warning_pct; $("level-critical-input").value = state.config.level_critical_pct; $("near-warning-input").value = state.config.proximity_warning_cm; $("near-critical-input").value = state.config.proximity_critical_cm;
    $("soil-low-input").value = state.config.soil_moisture_low_pct; $("temp-high-input").value = state.config.temperature_high_c; $("humidity-low-input").value = state.config.humidity_low_pct; $("water-low-input").value = state.config.water_level_low_pct; $("steam-high-input").value = state.config.steam_high_raw; $("offline-input").value = state.config.offline_timeout_seconds; configLoaded = true;
  }
}

function renderTelemetry(rows) {
  const body = $("telemetry-body"); const nodes = rows.slice(-12).reverse().map((row) => { const tr = document.createElement("tr"); const values = [new Date(row.recorded_at).toLocaleTimeString(), row.source, shown(row.soil_moisture,"%"), shown(row.soil_raw), shown(row.temperature,"°C"), shown(row.humidity,"%"), shown(row.light), shown(row.steam), row.motion == null ? "Sensor unavailable" : row.motion ? "Detected" : "Clear", shown(row.motion_count), row.water_level == null ? shown(row.water_raw," raw") : shown(row.water_level,"%"), shown(row.ultrasonic_distance," cm"), row.pump == null ? "—" : row.pump ? "ON" : "OFF", row.fan == null ? "—" : row.fan ? "ON" : "OFF", row.led == null ? "—" : row.led ? "ON" : "OFF", shown(row.reservoir_state), shown(row.wifi_rssi," dBm"), row.health_score, row.buzzer_mode]; values.forEach((value) => { const td = document.createElement("td"); td.textContent = value; tr.append(td); }); return tr; }); body.replaceChildren(...nodes);
}

function renderEvents(events) {
  const list = $("integrator-events"); const nodes = events.slice(0, 6).map((event) => { const row = document.createElement("div"); row.className = `event ${event.severity}`; const dot = document.createElement("div"); dot.className = "event-dot"; const content = document.createElement("div"); const title = document.createElement("strong"); title.textContent = event.title; const meta = document.createElement("span"); meta.textContent = `${new Date(event.recorded_at).toLocaleTimeString()} · ${event.source}`; content.append(title, meta); row.append(dot, content); return row; }); list.replaceChildren(...nodes);
}

function renderIntegrations(data) {
  text("mqtt-integration-status", data.mqtt.enabled ? `${data.mqtt.sensor_state} · ${data.mqtt.host}:${data.mqtt.port} · ${data.mqtt.sensor_topic}` : "Not configured");
  text("mysql-integration-status", data.mysql.connected ? `Connected · ${data.mysql.database}` : data.mysql.enabled ? `Buffered ${data.mysql.buffered_readings} · retrying` : "Not configured");
}

async function refresh() {
  const started = performance.now();
  try {
    const [state, history, events, integrations] = await Promise.all([jsonRequest("/api/v1/integrator/state"), jsonRequest("/api/v1/history?limit=30"), jsonRequest("/api/v1/events?limit=10"), jsonRequest("/api/integrations/status")]);
    renderState(state, performance.now() - started); renderTelemetry(history.readings); renderEvents(events.events); renderIntegrations(integrations);
  } catch (error) { toast(`Gateway error: ${error.message}`); }
}

document.addEventListener("click", async (event) => {
  const copyButton = event.target.closest("[data-copy]"); if (copyButton) { const node = $(copyButton.dataset.copy); await navigator.clipboard.writeText("value" in node ? node.value : node.textContent); toast("Copied to clipboard"); return; }
  const buzzerButton = event.target.closest("[data-buzzer]"); if (buzzerButton) { try { await jsonRequest("/api/v1/integrator/buzzer-test", {method: "POST", body: JSON.stringify({mode: buzzerButton.dataset.buzzer, duration_seconds: 6})}); toast(`${buzzerButton.dataset.buzzer} command queued`); refresh(); } catch (error) { toast(error.message); } }
});

$("simulation-toggle").addEventListener("click", async () => { try { await jsonRequest("/api/v1/integrator/simulation", {method: "POST", body: JSON.stringify({enabled: !current.simulation.enabled, scenario: $("scenario-input").value})}); toast(current.simulation.enabled ? "Simulation stopped" : "Simulation started"); refresh(); } catch (error) { toast(error.message); } });
$("scenario-input").addEventListener("change", async () => { try { await jsonRequest("/api/v1/integrator/simulation", {method: "POST", body: JSON.stringify({enabled: true, scenario: $("scenario-input").value})}); toast("Scenario loaded"); configLoaded = false; refresh(); } catch (error) { toast(error.message); } });
$("config-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const payload = {profile: $("profile-input").value, mount_height_cm: Number($("mount-input").value), invert_light: $("invert-input").value === "true", level_warning_pct: Number($("level-warning-input").value), level_critical_pct: Number($("level-critical-input").value), proximity_warning_cm: Number($("near-warning-input").value), proximity_critical_cm: Number($("near-critical-input").value), soil_moisture_low_pct: Number($("soil-low-input").value), temperature_high_c: Number($("temp-high-input").value), humidity_low_pct: Number($("humidity-low-input").value), water_level_low_pct: Number($("water-low-input").value), steam_high_raw: Number($("steam-high-input").value), offline_timeout_seconds: Number($("offline-input").value)};
  try { await jsonRequest("/api/v1/integrator/config", {method: "PATCH", body: JSON.stringify(payload)}); toast("Calibration applied"); configLoaded = false; refresh(); } catch (error) { toast(error.message); }
});

refresh(); setInterval(refresh, 3000);
