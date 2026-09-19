"use strict";
const $ = (id) => document.getElementById(id);
let latestHistory = [];
let guideLoaded = false;
const text = (id, value) => { const node = $(id); if (node) node.textContent = String(value); };
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const available = (value, suffix = "") => value === null || value === undefined ? "Sensor unavailable" : `${value}${suffix}`;

function renderState(state) {
  const d = state.decision, s = state.sensors, i = state.interpreter;
  document.body.dataset.severity = i.priority === "CRITICAL" ? "critical" : i.priority === "WARNING" ? "warning" : "healthy";
  text("farm-zone", `${state.device.zone} · ${state.device.name}`);
  const pill = $("connection-pill"), hardware = state.device.connected, mqtt = state.mqtt || {}, mqttState = mqtt.sensor_state;
  const linkState = state.challenge?.active ? "challenge" : mqtt.enabled ? mqttState : hardware ? "LIVE" : state.simulation.enabled ? "SIM" : "OFFLINE";
  pill.className = `connection-pill ${linkState === "LIVE" ? "online" : linkState === "OFFLINE" ? "offline" : ""}`;
  text("connection-text", state.challenge?.active ? "Challenge active" : mqtt.enabled ? `ESP32 ${mqttState || "OFFLINE"}` : hardware ? "ESP32 live" : state.simulation.enabled ? "Demo mode" : "Sensor offline");
  $("health-ring").style.setProperty("--score", clamp(d.health_score, 0, 100)); text("health-score", d.health_score);
  const health = i.priority;
  const copy = {
    NORMAL:["Farm health · NORMAL","Everything looks healthy.","No action needed","✓","All available readings are inside the configured safe ranges."],
    WARNING:["Farm health · WARNING","One condition needs watching.","Check during your next round","!","One or more farm conditions are moving outside their safe range."],
    CRITICAL:["Farm health · CRITICAL","Please check the farm now.","Immediate check recommended","⚠","FarmGuard detected serious risk or lost contact with the ESP32."],
  }[health];
  text("status-chip",copy[0]); text("status-title",copy[1]); text("action-title",copy[2]); text("action-icon",copy[3]); text("action-copy",copy[4]);
  $("reason-list").replaceChildren(...[i.reason].map(value => { const li=document.createElement("li"); li.textContent=value; return li; }));
  $("action-steps").replaceChildren(...i.recommendation.slice(0,3).map(value => { const li=document.createElement("li"); li.textContent=value; return li; }));
  text("action-title",i.priority==="CRITICAL"?"Check this now":i.priority==="WARNING"?"Action recommended":"Everything looks good");
  text("action-copy",i.status); text("action-icon",i.priority==="CRITICAL"?"⚠":i.priority==="WARNING"?"!":"✓");

  text("level-value", available(s.soil_moisture, "%"));
  const quality = mqtt.quality_warnings || [];
  const soilWarning = quality.find(value => value.toLowerCase().includes("soil"));
  text("soil-caption", `${i.meanings.soil} · raw ${available(s.soil_raw)}${soilWarning ? ` · Check: ${soilWarning}` : ""}`);
  $("tank-fill").style.height = `${clamp(s.soil_moisture ?? 2, 2, 96)}%`;
  text("light-value", available(s.temperature, "°C"));
  text("light-caption", `${i.meanings.temperature} · Humidity ${available(s.humidity,"%")} · Light ${available(d.light_pct,"%")} · Steam ${available(s.steam)} · Fan ${s.fan == null ? "unavailable" : s.fan ? "ON" : "OFF"} · LED ${s.led == null ? "unavailable" : s.led ? "ON" : "OFF"}`);
  text("proximity-value", s.water_level == null ? available(s.water_raw, " raw") : available(s.water_level, "%"));
  const waterWarning = quality.find(value => value.toLowerCase().includes("water"));
  text("proximity-caption", `${i.meanings.water} · reservoir ${available(s.reservoir_state)} · pump ${s.pump == null ? "unavailable" : s.pump ? "ON" : "OFF"} · ultrasonic ${available(s.ultrasonic_distance," cm")}${waterWarning ? ` · Check: ${waterWarning}` : ""}`);
  $("radar-dot").style.setProperty("--risk", s.water_level == null ? 0 : 100-s.water_level);
  text("buzzer-value", s.motion == null ? "Sensor unavailable" : s.motion ? "MOTION" : "CLEAR");
  const last = state.device.last_received ? new Date(state.device.last_received).toLocaleTimeString() : "never";
  const updateAge = mqtt.sensor_age_seconds == null ? "no MQTT sample" : `${mqtt.sensor_age_seconds}s ago`;
  text("buzzer-caption", `${i.meanings.motion} · count ${available(s.motion_count)} · Wi-Fi ${available(s.wifi_rssi," dBm")} · ${mqtt.enabled ? `${mqttState} ${updateAge}` : hardware ? "Online" : state.simulation.enabled ? "Demo" : "Offline"} · buzzer ${d.buzzer_mode}`);
  $("buzzer-wave").classList.toggle("active", d.buzzer_mode !== "OFF");
  text("source-chip", state.challenge?.active ? "Challenge Lab" : mqtt.enabled ? `MQTT ${mqttState || "OFFLINE"}` : hardware ? "Live ESP32" : state.simulation.enabled ? "Safe simulation" : "Last known data");
  const summary=$("daily-summary"); summary.className=`event ${i.priority==="CRITICAL"?"critical":i.priority==="WARNING"?"warning":"healthy"}`; summary.querySelector("strong").textContent=`FarmGuard Says · ${i.priority}`; summary.querySelector("span").textContent=i.daily_summary;
  renderChallenge(state.challenge);
}

function renderChallenge(challenge) {
  if (!challenge) return;
  text("challenge-status", challenge.active ? challenge.name : "Stopped");
  $("fun-box-controls").hidden = challenge.mode !== "fun-box";
  const meta=challenge.meta||{}; const lines=[];
  if (!challenge.active) lines.push("Choose a challenge to begin.");
  else {
    lines.push(`${challenge.name} · step ${meta.tick||0}`, meta.message||"Training scenario active");
    const labels={database_status:"Database",security_status:"Security",reliability:"Reliability",threat:"Detection",threat_level:"Threat",confidence:"Confidence",water_status:"Water status",stress_score:"Stress score",failed_sensor:"Failed sensor",failure_type:"Failure",fallback:"Fallback",system_health:"System health",farm_risk:"Farm risk",healthy_sensors:"Healthy sensors",intrusion_status:"Intrusion",final_result:"Result"};
    Object.entries(labels).forEach(([key,label])=>{if(meta[key]!==undefined&&meta[key]!==null)lines.push(`${label}: ${meta[key]}${["reliability","confidence","stress_score","system_health"].includes(key)?"%":""}`);});
    if(meta.anomalies) meta.anomalies.forEach(item=>lines.push(`${item.sensor}: raw ${item.raw} · ${item.valid?"valid":"flagged"} · reliability ${item.reliability}% · using ${item.used} · ${item.reason}`));
    const plan=meta.emergency_plan||meta.priority_plan||meta.triggered_actions; if(plan) plan.forEach((step,index)=>lines.push(`${index+1}. ${step}`));
    if(meta.buffered_count) lines.push(`Buffered readings: ${meta.buffered_count}`);
  }
  $("challenge-summary").querySelector("code").textContent=lines.join("\n");
}

function renderEvents(events) {
  const nodes=events.slice(0,5).map(event=>{ const row=document.createElement("div"); row.className=`event ${event.severity}`;
    const dot=document.createElement("div"); dot.className="event-dot"; const copy=document.createElement("div"), title=document.createElement("strong"), meta=document.createElement("span");
    title.textContent=event.title; meta.textContent=`${new Date(event.recorded_at).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})} · ${event.detail}`;
    copy.append(title,meta); row.append(dot,copy); return row; }); $("event-list").replaceChildren(...nodes);
}

function drawChart(rows) {
  latestHistory=rows; const canvas=$("trend-chart"), rect=canvas.getBoundingClientRect(), ratio=window.devicePixelRatio||1;
  canvas.width=Math.max(1,rect.width*ratio); canvas.height=Math.max(1,rect.height*ratio); const ctx=canvas.getContext("2d"); ctx.scale(ratio,ratio);
  const w=rect.width,h=rect.height,pad={l:34,r:12,t:16,b:25}; ctx.clearRect(0,0,w,h); ctx.font="11px system-ui"; ctx.fillStyle="#7f9c8b"; ctx.strokeStyle="#183024";
  for(let v=0;v<=100;v+=25){const y=pad.t+(100-v)/100*(h-pad.t-pad.b);ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();ctx.fillText(String(v),5,y+4);}
  const data=rows.slice(-60); if(data.length<2)return;
  [["health_score","#64ee9d"],["soil_moisture","#6dd6ff"],["water_level","#ffc857"]].forEach(([key,color])=>{ctx.beginPath();let started=false;data.forEach((row,i)=>{if(row[key]==null)return;const x=pad.l+i/(data.length-1)*(w-pad.l-pad.r),y=pad.t+(100-clamp(Number(row[key]),0,100))/100*(h-pad.t-pad.b);started?ctx.lineTo(x,y):ctx.moveTo(x,y);started=true;});ctx.strokeStyle=color;ctx.lineWidth=2.2;ctx.stroke();});
  ctx.fillStyle="#91aa9b";ctx.fillText("Health",pad.l,h-5);ctx.fillStyle="#6dd6ff";ctx.fillText("Soil",pad.l+48,h-5);ctx.fillStyle="#ffc857";ctx.fillText("Water",pad.l+82,h-5);
}

async function refresh(){try{const [a,b,c]=await Promise.all([fetch("/api/sensors/latest"),fetch("/api/sensors/history?limit=80"),fetch("/api/v1/events?limit=8")]);if(!a.ok)throw new Error("State unavailable");const [state,history,events]=await Promise.all([a.json(),b.json(),c.json()]);renderState(state);drawChart(history.readings);renderEvents(events.events);$("offline-toast").classList.remove("show");if(!guideLoaded){guideLoaded=true;askGuide("What should I do now?");}}catch(error){$("offline-toast").classList.add("show");console.error(error);}}

async function postJson(url,payload={}){const response=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.detail||"Request failed");}return response.json();}
async function runAction(action){try{await action();await refresh();}catch(error){alert(error.message);}}
$("challenge-start").addEventListener("click",()=>runAction(()=>postJson("/api/challenges/start",{mode:$("challenge-mode").value})));
$("challenge-stop").addEventListener("click",()=>runAction(()=>postJson("/api/challenges/stop")));
$("challenge-reset").addEventListener("click",()=>runAction(()=>postJson("/api/challenges/reset")));
function funPayload(){return {temperature:Number($("fun-temperature").value),humidity:Number($("fun-humidity").value),soil_moisture:Number($("fun-soil").value),light:Number($("fun-light").value),ultrasonic_distance:Number($("fun-distance").value),steam:Number($("fun-steam").value),water_level:Number($("fun-water").value),motion:$("fun-motion").value==="true"};}
$("fun-apply").addEventListener("click",()=>runAction(()=>postJson("/api/challenges/fun-box",funPayload())));
$("quick-scenarios").addEventListener("click",event=>{const button=event.target.closest("[data-scenario]");if(button)runAction(()=>postJson("/api/challenges/fun-box",{scenario:button.dataset.scenario}));});
async function askGuide(question){if(!question.trim())return;const answer=await postJson("/api/farm-guide/ask",{question,language:$("guide-language").value});const box=$("guide-answer");box.className=`event ${answer.farm_health==="CRITICAL"?"critical":answer.farm_health==="WARNING"?"warning":"healthy"}`;box.querySelector("strong").textContent=`Farm Health ${answer.farm_health} · ${answer.health_score}/100`;box.querySelector("span").style.whiteSpace="pre-line";box.querySelector("span").textContent=answer.answer;}
$("guide-ask").addEventListener("click",()=>runAction(()=>askGuide($("guide-question").value)));
$("guide-question").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();runAction(()=>askGuide(event.target.value));}});
document.querySelectorAll(".guide-quick").forEach(button=>button.addEventListener("click",()=>runAction(()=>askGuide(button.dataset.question))));
$("guide-language").addEventListener("change",()=>runAction(()=>askGuide($("guide-question").value||"What should I do today?")));
$("guide-voice").addEventListener("click",()=>{const box=$("guide-answer");box.querySelector("strong").textContent="Voice support is ready for a future upgrade";box.querySelector("span").textContent="The safe pipeline is prepared: speech → FarmGuard interpreter → live sensor context → response → speech. No microphone recording starts yet.";});
window.addEventListener("resize",()=>drawChart(latestHistory)); refresh(); setInterval(refresh,3000);
