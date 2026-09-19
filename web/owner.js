"use strict";

const $ = (id) => document.getElementById(id);
let latestHistory = [];

function text(id, value) { const node = $(id); if (node) node.textContent = String(value); }
function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }

function renderState(state) {
  const d = state.decision;
  document.body.dataset.severity = d.severity;
  text("farm-zone", `${state.device.zone} · ${state.device.name}`);
  const pill = $("connection-pill");
  const hardware = state.device.connected;
  pill.className = `connection-pill ${hardware ? "online" : state.simulation.enabled ? "" : "offline"}`;
  text("connection-text", hardware ? "ESP32 live" : state.simulation.enabled ? "Demo mode" : "Sensor offline");

  const ring = $("health-ring");
  ring.style.setProperty("--score", clamp(d.health_score, 0, 100));
  text("health-score", d.health_score);
  const copy = {
    GOOD: ["Farm is good", "Everything looks healthy.", "No action needed", "✓", "You can continue normal farm work. FarmGuard will alert you when something changes."],
    WATCH: ["Needs attention", "One condition needs watching.", "Check during your next round", "!", "The farm is still operating, but one condition is moving outside its normal range."],
    ACTION: ["Action required", "Please check the farm now.", "Immediate check recommended", "⚠", "FarmGuard detected a serious condition or lost contact with the ESP32 sensor node."],
  }[d.status] || [d.status, "Farm status updated.", "Review the details", "!", "Review the current sensor readings."];
  text("status-chip", copy[0]); text("status-title", copy[1]); text("action-title", copy[2]); text("action-icon", copy[3]); text("action-copy", copy[4]);

  const reasons = $("reason-list"); reasons.replaceChildren(...d.reasons.map((reason) => { const li = document.createElement("li"); li.textContent = reason; return li; }));
  const actions = $("action-steps"); actions.replaceChildren(...d.actions.map((action) => { const li = document.createElement("li"); li.textContent = action; return li; }));

  text("level-value", `${Math.round(d.level_pct)}%`); $("tank-fill").style.height = `${clamp(d.level_pct, 2, 96)}%`;
  text("light-value", `${Math.round(d.light_pct)}%`); text("light-caption", `${d.light_state} · Expected ${d.expected_light.toLowerCase()}`);
  text("proximity-value", `${Math.round(d.proximity_risk_pct)}%`); text("proximity-caption", d.profile === "perimeter" ? "Active perimeter risk" : d.profile === "combined" ? "Combined demo interpretation" : "Information only in level mode"); $("radar-dot").style.setProperty("--risk", d.proximity_risk_pct);
  text("buzzer-value", d.buzzer_mode); text("buzzer-caption", d.buzzer_mode === "OFF" ? "Silent — no warning needed" : d.buzzer_mode === "PULSE" ? "Pulsing — attention requested" : "Alarm — urgent farm check"); $("buzzer-wave").classList.toggle("active", d.buzzer_mode !== "OFF");
  text("source-chip", state.device.connected ? "Live ESP32" : state.simulation.enabled ? "Safe simulation" : "Last known data");
}

function renderEvents(events) {
  const list = $("event-list");
  const nodes = events.slice(0, 5).map((event) => {
    const row = document.createElement("div"); row.className = `event ${event.severity}`;
    const dot = document.createElement("div"); dot.className = "event-dot";
    const copy = document.createElement("div"); const title = document.createElement("strong"); const meta = document.createElement("span");
    title.textContent = event.title; const when = new Date(event.recorded_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}); meta.textContent = `${when} · ${event.detail}`;
    copy.append(title, meta); row.append(dot, copy); return row;
  });
  list.replaceChildren(...nodes);
}

function drawChart(rows) {
  latestHistory = rows;
  const canvas = $("trend-chart"); const rect = canvas.getBoundingClientRect(); const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, rect.width * ratio); canvas.height = Math.max(1, rect.height * ratio);
  const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio); const w = rect.width, h = rect.height; const pad = {l: 34, r: 12, t: 16, b: 25};
  ctx.clearRect(0, 0, w, h); ctx.font = "11px system-ui"; ctx.fillStyle = "#7f9c8b"; ctx.strokeStyle = "#183024"; ctx.lineWidth = 1;
  for (let v = 0; v <= 100; v += 25) { const y = pad.t + (100 - v) / 100 * (h - pad.t - pad.b); ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke(); ctx.fillText(String(v), 5, y + 4); }
  const data = rows.slice(-60); if (data.length < 2) return;
  const series = [["health_score", "#64ee9d"], ["level_pct", "#6dd6ff"], ["light_pct", "#ffc857"]];
  series.forEach(([key, color]) => { ctx.beginPath(); data.forEach((row, i) => { const x = pad.l + i / (data.length - 1) * (w - pad.l - pad.r); const y = pad.t + (100 - clamp(Number(row[key]), 0, 100)) / 100 * (h - pad.t - pad.b); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.strokeStyle = color; ctx.lineWidth = 2.2; ctx.lineJoin = "round"; ctx.stroke(); });
  ctx.fillStyle = "#91aa9b"; ctx.fillText("Health", pad.l, h - 5); ctx.fillStyle = "#6dd6ff"; ctx.fillText("Level", pad.l + 48, h - 5); ctx.fillStyle = "#ffc857"; ctx.fillText("Light", pad.l + 88, h - 5);
}

async function refresh() {
  const started = performance.now();
  try {
    const [stateResponse, historyResponse, eventResponse] = await Promise.all([fetch("/api/v1/state"), fetch("/api/v1/history?limit=80"), fetch("/api/v1/events?limit=8")]);
    if (!stateResponse.ok) throw new Error("State unavailable");
    const [state, history, events] = await Promise.all([stateResponse.json(), historyResponse.json(), eventResponse.json()]);
    renderState(state); drawChart(history.readings); renderEvents(events.events); $("offline-toast").classList.remove("show");
  } catch (error) { $("offline-toast").classList.add("show"); console.error(error); }
}

window.addEventListener("resize", () => drawChart(latestHistory));
refresh(); setInterval(refresh, 2000);
