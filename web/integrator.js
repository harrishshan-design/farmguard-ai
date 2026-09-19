"use strict";

const $ = (id) => document.getElementById(id);
let current = null;
let configLoaded = false;

function text(id, value) { const node = $(id); if (node) node.textContent = String(value); }
function toast(message) { text("toast", message); $("toast").classList.add("show"); setTimeout(() => $("toast").classList.remove("show"), 1800); }
async function jsonRequest(url, options = {}) { const response = await fetch(url, { headers: {"Content-Type": "application/json"}, ...options }); if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || `${response.status} ${response.statusText}`); } return response.json(); }

function renderState(state, latency) {
  current = state; const d = state.decision; document.body.dataset.severity = d.severity;
  const connected = state.device.connected; const pill = $("dev-connection-pill"); pill.className = `connection-pill ${connected ? "online" : state.simulation.enabled ? "" : "offline"}`;
  text("dev-connection-text", connected ? "ESP32 connected" : state.simulation.enabled ? "Simulator active" : "ESP32 offline"); text("latency-value", `${Math.round(latency)} ms`); text("uptime-value", `${Math.floor(state.uptime_seconds / 60)}m`); text("packet-value", state.rejected_packets);
  text("raw-distance", `${Number(state.raw.distance_cm || 0).toFixed(1)} cm`); text("raw-light", state.raw.light_raw ?? "—"); text("raw-health", `${d.health_score}/100`); text("raw-buzzer", d.buzzer_mode); text("raw-sequence", state.raw.sequence ?? "—");
  text("trust-chip", connected ? "Trusted · receiving" : state.simulation.enabled ? "No hardware · simulated" : "Waiting for telemetry");
  $("endpoint-value").value = `${location.origin}/api/v1/telemetry`; $("device-id-value").value = state.config.device_id; $("token-value").value = state.config.token;
  text("payload-code", JSON.stringify({device_id: state.config.device_id, token: state.config.token, sequence: 1, distance_cm: 45.2, light_raw: 2580}, null, 2));
  const toggle = $("simulation-toggle"); toggle.classList.toggle("on", state.simulation.enabled); toggle.setAttribute("aria-pressed", String(state.simulation.enabled)); $("scenario-input").value = state.simulation.scenario;
  if (!configLoaded && !$("config-form").contains(document.activeElement)) {
    $("profile-input").value = state.config.profile; $("mount-input").value = state.config.mount_height_cm; $("invert-input").value = String(state.config.invert_light);
    $("level-warning-input").value = state.config.level_warning_pct; $("level-critical-input").value = state.config.level_critical_pct; $("near-warning-input").value = state.config.proximity_warning_cm; $("near-critical-input").value = state.config.proximity_critical_cm; configLoaded = true;
  }
}

function renderTelemetry(rows) {
  const body = $("telemetry-body"); const nodes = rows.slice(-12).reverse().map((row) => { const tr = document.createElement("tr"); const values = [new Date(row.recorded_at).toLocaleTimeString(), row.source, `${Number(row.distance_cm).toFixed(1)} cm`, row.light_raw, `${Math.round(row.level_pct)}%`, `${Math.round(row.light_pct)}%`, row.health_score, row.buzzer_mode]; values.forEach((value) => { const td = document.createElement("td"); td.textContent = value; tr.append(td); }); return tr; }); body.replaceChildren(...nodes);
}

function renderEvents(events) {
  const list = $("integrator-events"); const nodes = events.slice(0, 6).map((event) => { const row = document.createElement("div"); row.className = `event ${event.severity}`; const dot = document.createElement("div"); dot.className = "event-dot"; const content = document.createElement("div"); const title = document.createElement("strong"); title.textContent = event.title; const meta = document.createElement("span"); meta.textContent = `${new Date(event.recorded_at).toLocaleTimeString()} · ${event.source}`; content.append(title, meta); row.append(dot, content); return row; }); list.replaceChildren(...nodes);
}

async function refresh() {
  const started = performance.now();
  try {
    const [state, history, events] = await Promise.all([jsonRequest("/api/v1/integrator/state"), jsonRequest("/api/v1/history?limit=30"), jsonRequest("/api/v1/events?limit=10")]);
    renderState(state, performance.now() - started); renderTelemetry(history.readings); renderEvents(events.events);
  } catch (error) { toast(`Gateway error: ${error.message}`); }
}

document.addEventListener("click", async (event) => {
  const copyButton = event.target.closest("[data-copy]"); if (copyButton) { const node = $(copyButton.dataset.copy); await navigator.clipboard.writeText("value" in node ? node.value : node.textContent); toast("Copied to clipboard"); return; }
  const buzzerButton = event.target.closest("[data-buzzer]"); if (buzzerButton) { try { await jsonRequest("/api/v1/integrator/buzzer-test", {method: "POST", body: JSON.stringify({mode: buzzerButton.dataset.buzzer, duration_seconds: 6})}); toast(`${buzzerButton.dataset.buzzer} command queued`); refresh(); } catch (error) { toast(error.message); } }
});

$("simulation-toggle").addEventListener("click", async () => { try { await jsonRequest("/api/v1/integrator/simulation", {method: "POST", body: JSON.stringify({enabled: !current.simulation.enabled, scenario: $("scenario-input").value})}); toast(current.simulation.enabled ? "Simulation stopped" : "Simulation started"); refresh(); } catch (error) { toast(error.message); } });
$("scenario-input").addEventListener("change", async () => { try { await jsonRequest("/api/v1/integrator/simulation", {method: "POST", body: JSON.stringify({enabled: true, scenario: $("scenario-input").value})}); toast("Scenario loaded"); configLoaded = false; refresh(); } catch (error) { toast(error.message); } });
$("config-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const payload = {profile: $("profile-input").value, mount_height_cm: Number($("mount-input").value), invert_light: $("invert-input").value === "true", level_warning_pct: Number($("level-warning-input").value), level_critical_pct: Number($("level-critical-input").value), proximity_warning_cm: Number($("near-warning-input").value), proximity_critical_cm: Number($("near-critical-input").value)};
  try { await jsonRequest("/api/v1/integrator/config", {method: "PATCH", body: JSON.stringify(payload)}); toast("Calibration applied"); configLoaded = false; refresh(); } catch (error) { toast(error.message); }
});

refresh(); setInterval(refresh, 2000);
