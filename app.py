"""FarmGuard AI FastAPI server and ESP32 sensor gateway."""
from __future__ import annotations

import csv, hmac, io, os, sqlite3, threading, time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from dotenv import load_dotenv
from farmguard_engine import DeviceConfig, FarmSensorReading, SCENARIOS, SensorReading, evaluate, evaluate_farm, simulated_reading
from challenge_engine import CHALLENGES, ChallengeEngine
from farm_interpreter import LANGUAGE_NAMES, answer_question, interpret_farm
from integration_service import IntegrationService

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
load_dotenv(ROOT / ".env")
DB_PATH = Path(os.getenv("FARMGUARD_DB", ROOT / "farmguard.db"))
API_KEY = os.getenv("FARMGUARD_API_KEY", "change-this-local-key")
STARTED_AT = time.monotonic()

class TelemetryPacket(BaseModel):
    """Legacy packet kept so existing two-sensor devices continue working."""
    device_id: str = Field(min_length=3, max_length=80)
    token: str = Field(min_length=4, max_length=160)
    sequence: int = Field(ge=0)
    distance_cm: float = Field(ge=0, le=500)
    light_raw: int = Field(ge=0, le=4095)

class SensorPacket(BaseModel):
    device_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    sequence: int = Field(ge=0)
    soil_moisture: float | None = Field(default=None, ge=0, le=100)
    temperature: float | None = Field(default=None, ge=-40, le=100)
    humidity: float | None = Field(default=None, ge=0, le=100)
    light: int | None = Field(default=None, ge=0, le=4095)
    steam: int | None = Field(default=None, ge=0, le=4095)
    motion: bool | None = None
    water_level: float | None = Field(default=None, ge=0, le=100)
    ultrasonic_distance: float | None = Field(default=None, ge=0, le=500)
    uptime: int | None = Field(default=None, ge=0)
    soil_raw: int | None = Field(default=None, ge=0, le=4095)
    water_raw: int | None = Field(default=None, ge=0, le=4095)
    motion_count: int | None = Field(default=None, ge=0)
    pump: bool | None = None
    fan: bool | None = None
    led: bool | None = None
    reservoir_state: int | None = None
    wifi_rssi: int | None = Field(default=None, ge=-150, le=0)

    @model_validator(mode="after")
    def has_sensor_value(self):
        fields = ("soil_moisture", "temperature", "humidity", "light", "steam", "motion", "water_level", "ultrasonic_distance")
        if all(getattr(self, field) is None for field in fields):
            raise ValueError("At least one sensor reading is required")
        return self

class SimulationRequest(BaseModel):
    enabled: bool
    scenario: str = "healthy"

class ChallengeRequest(BaseModel):
    mode: str

class FunBoxRequest(BaseModel):
    scenario: str | None = None
    temperature: float | None = Field(default=None, ge=-40, le=100)
    humidity: float | None = Field(default=None, ge=0, le=100)
    soil_moisture: float | None = Field(default=None, ge=0, le=100)
    light: int | None = Field(default=None, ge=0, le=4095)
    ultrasonic_distance: float | None = Field(default=None, ge=0, le=500)
    motion: bool | None = None
    steam: int | None = Field(default=None, ge=0, le=4095)
    water_level: float | None = Field(default=None, ge=0, le=100)

class FarmGuideQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    language: Literal["en", "ms", "ta", "zh"] = "en"

class BuzzerTestRequest(BaseModel):
    mode: Literal["OFF", "PULSE", "ALARM"]
    duration_seconds: int = Field(default=5, ge=1, le=30)

class ConfigUpdate(BaseModel):
    profile: Literal["level", "perimeter", "combined"] | None = None
    mount_height_cm: float | None = Field(default=None, ge=20, le=500)
    invert_light: bool | None = None
    level_warning_pct: float | None = Field(default=None, ge=5, le=90)
    level_critical_pct: float | None = Field(default=None, ge=1, le=80)
    proximity_warning_cm: float | None = Field(default=None, ge=5, le=200)
    proximity_critical_cm: float | None = Field(default=None, ge=2, le=100)
    soil_moisture_low_pct: float | None = Field(default=None, ge=0, le=100)
    temperature_high_c: float | None = Field(default=None, ge=-20, le=80)
    humidity_low_pct: float | None = Field(default=None, ge=0, le=100)
    water_level_low_pct: float | None = Field(default=None, ge=0, le=100)
    steam_high_raw: int | None = Field(default=None, ge=0, le=4095)
    offline_timeout_seconds: int | None = Field(default=None, ge=20, le=300)

class EventStore:
    def __init__(self, path: Path):
        self.path, self.lock = path, threading.RLock()
        self._initialize()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10); db.row_factory = sqlite3.Row
        try:
            yield db; db.commit()
        finally: db.close()

    def _initialize(self):
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS readings (
              id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL, device_id TEXT NOT NULL,
              source TEXT NOT NULL, distance_cm REAL NOT NULL, level_pct REAL NOT NULL,
              proximity_risk_pct REAL NOT NULL, light_raw INTEGER NOT NULL, light_pct REAL NOT NULL,
              health_score INTEGER NOT NULL, status TEXT NOT NULL, buzzer_mode TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sensor_readings (
              id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL, device_id TEXT NOT NULL,
              sequence INTEGER NOT NULL, source TEXT NOT NULL, soil_moisture REAL, temperature REAL,
              humidity REAL, light INTEGER, steam INTEGER, motion INTEGER, water_level REAL,
              ultrasonic_distance REAL, uptime INTEGER, health_score INTEGER NOT NULL,
              farm_health TEXT NOT NULL, buzzer_mode TEXT NOT NULL, soil_raw INTEGER,
              water_raw INTEGER, motion_count INTEGER, pump INTEGER, fan INTEGER, led INTEGER,
              reservoir_state INTEGER, wifi_rssi INTEGER);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL, severity TEXT NOT NULL,
              title TEXT NOT NULL, detail TEXT NOT NULL, action TEXT NOT NULL, source TEXT NOT NULL);
            """)
            existing={row[1] for row in db.execute("PRAGMA table_info(sensor_readings)")}
            for name,kind in {"soil_raw":"INTEGER","water_raw":"INTEGER","motion_count":"INTEGER","pump":"INTEGER",
                              "fan":"INTEGER","led":"INTEGER","reservoir_state":"INTEGER","wifi_rssi":"INTEGER"}.items():
                if name not in existing: db.execute(f"ALTER TABLE sensor_readings ADD COLUMN {name} {kind}")

    def add_reading(self, device_id, reading, decision):
        with self.lock, self.connect() as db:
            db.execute("""INSERT INTO readings (recorded_at,device_id,source,distance_cm,level_pct,proximity_risk_pct,
              light_raw,light_pct,health_score,status,buzzer_mode) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
              (reading.observed_at.isoformat(),device_id,reading.source,reading.distance_cm,decision["level_pct"],
               decision["proximity_risk_pct"],reading.light_raw,decision["light_pct"],decision["health_score"],
               decision["status"],decision["buzzer_mode"]))

    def add_sensor_reading(self, reading, decision):
        with self.lock, self.connect() as db:
            db.execute("""INSERT INTO sensor_readings (recorded_at,device_id,sequence,source,soil_moisture,temperature,
              humidity,light,steam,motion,water_level,ultrasonic_distance,uptime,health_score,farm_health,buzzer_mode,
              soil_raw,water_raw,motion_count,pump,fan,led,reservoir_state,wifi_rssi)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (reading.observed_at.isoformat(),reading.device_id,reading.sequence,reading.source,reading.soil_moisture,
               reading.temperature,reading.humidity,reading.light,reading.steam,None if reading.motion is None else int(reading.motion),
               reading.water_level,reading.ultrasonic_distance,reading.uptime,decision["health_score"],decision["farm_health"],decision["buzzer_mode"],
               reading.soil_raw,reading.water_raw,reading.motion_count,None if reading.pump is None else int(reading.pump),
               None if reading.fan is None else int(reading.fan),None if reading.led is None else int(reading.led),reading.reservoir_state,reading.wifi_rssi))

    def add_event(self, severity, title, detail, action, source):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO events (recorded_at,severity,title,detail,action,source) VALUES (?,?,?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(),severity,title,detail,action,source))

    def rows(self, table, limit):
        if table not in {"readings","sensor_readings","events"}: raise ValueError("Invalid table")
        with self.lock, self.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,))]

class FarmState:
    def __init__(self):
        self.lock, self.store = threading.RLock(), EventStore(DB_PATH)
        self.config = DeviceConfig(token=os.getenv("FARMGUARD_DEVICE_TOKEN","farmguard-device-01"))
        self.challenge = ChallengeEngine()
        self.simulation_enabled, self.scenario, self.tick = True, "healthy", 0
        self.last_reading = self.last_sensor_reading = self.last_decision = self.last_hardware_at = None
        self.last_live_sensor_reading = self.last_live_decision = None
        self.last_sequence, self.last_signature, self.rejected_packets, self.buzzer_override = -1, None, 0, None
        self.mqtt_sequences = {}
        self._simulate(force=True)

    def _event_for(self, decision, source):
        signature = (decision["status"], tuple(decision["reasons"]))
        if signature != self.last_signature:
            self.last_signature = signature
            title = {"GOOD":"Conditions stable","WATCH":"Attention recommended","ACTION":"Action required"}[decision["status"]]
            self.store.add_event(decision["severity"],title,"; ".join(decision["reasons"])," ".join(decision["actions"]),source)

    def _record(self, reading, decision):
        self.last_reading, self.last_decision = reading, decision
        self.store.add_reading(self.config.device_id,reading,decision); self._event_for(decision,reading.source)

    def _record_sensor(self, reading, decision):
        self.last_sensor_reading, self.last_decision = reading, decision
        self.store.add_sensor_reading(reading,decision); self._event_for(decision,reading.source)

    def _record_live_sensor(self, reading, decision):
        self.last_live_sensor_reading,self.last_live_decision,self.last_hardware_at=reading,decision,reading.observed_at
        self.store.add_sensor_reading(reading,decision)
        if not self.challenge.active_mode:
            self.last_sensor_reading,self.last_decision=reading,decision; self._event_for(decision,reading.source)

    def _challenge_step(self):
        stepped = self.challenge.step(self.config.device_id)
        if not stepped: return
        reading, meta = stepped; decision = evaluate_farm(reading,self.config)
        if self.challenge.active_mode == "alien-attack":
            decision.update(farm_health="CRITICAL",status="ACTION",severity="critical",buzzer_mode="ALARM")
            decision["reasons"] = ["Unknown farm intrusion pattern detected in this training simulation"]
            decision["actions"] = meta["triggered_actions"]
        self.last_sensor_reading,self.last_decision = reading,decision
        self.challenge.add_history({"recorded_at":reading.observed_at.isoformat(),"device_id":reading.device_id,
          "sequence":reading.sequence,"source":reading.source,"soil_moisture":reading.soil_moisture,
          "temperature":reading.temperature,"humidity":reading.humidity,"light":reading.light,"steam":reading.steam,
          "motion":None if reading.motion is None else int(reading.motion),"water_level":reading.water_level,
          "ultrasonic_distance":reading.ultrasonic_distance,"uptime":reading.uptime,"health_score":decision["health_score"],
          "farm_health":decision["farm_health"],"buzzer_mode":decision["buzzer_mode"]})

    def _simulate(self, force=False):
        if not self.simulation_enabled: return
        now = datetime.now(timezone.utc)
        if not force and self.last_sensor_reading and (now-self.last_sensor_reading.observed_at).total_seconds()<1.5: return
        self.tick += 1
        legacy, _ = simulated_reading(self.scenario,self.config,self.tick,now)
        profiles = {"healthy":(62,29,66,420,False,72),"low-level":(42,31,54,520,False,12),
          "intrusion":(55,29,62,410,True,68),"darkness":(58,28,70,390,False,66),
          "night-light":(58,27,72,390,False,66),"multi-risk":(8,42,22,3300,True,7)}
        soil,temp,humidity,steam,motion,water = profiles.get(self.scenario,profiles["healthy"])
        sensor = FarmSensorReading(self.config.device_id,self.tick,now,"simulation",soil,temp,humidity,legacy.light_raw,
                                   steam,motion,water,legacy.distance_cm,round(time.monotonic()-STARTED_AT))
        self.last_reading = legacy; self._record_sensor(sensor,evaluate_farm(sensor,self.config))

    def effective_buzzer(self):
        if self.buzzer_override:
            mode,expires = self.buzzer_override
            if time.monotonic()<expires: return mode
            self.buzzer_override = None
        return self.last_decision["buzzer_mode"] if self.last_decision else "OFF"

    def ingest_legacy(self, packet):
        with self.lock:
            if packet.device_id!=self.config.device_id or not hmac.compare_digest(packet.token,self.config.token):
                self.rejected_packets += 1; raise PermissionError("Invalid device ID or token")
            if packet.sequence<=self.last_sequence: self.rejected_packets += 1; raise RuntimeError("Sequence must increase to prevent replayed telemetry")
            self.challenge.stop(); self.last_sequence, self.simulation_enabled = packet.sequence, False
            now=datetime.now(timezone.utc); reading=SensorReading(packet.distance_cm,packet.light_raw,packet.sequence,"esp32-legacy",now)
            decision=evaluate(reading,self.config); decision["farm_health"]={"GOOD":"NORMAL","WATCH":"WARNING","ACTION":"CRITICAL"}[decision["status"]]
            self.last_hardware_at=now; self._record(reading,decision)
            return {"accepted":True,"server_time":now.isoformat(),"buzzer_mode":self.effective_buzzer(),"sample_interval_ms":3000,"decision":decision}

    def ingest_sensors(self, packet):
        with self.lock:
            if packet.sequence<=self.last_sequence: self.rejected_packets += 1; raise RuntimeError("Sequence must increase to prevent replayed telemetry")
            self.last_sequence, self.simulation_enabled = packet.sequence, False
            now=datetime.now(timezone.utc)
            reading=FarmSensorReading(device_id=packet.device_id,sequence=packet.sequence,observed_at=now,**packet.model_dump(exclude={"device_id","sequence"}))
            decision=evaluate_farm(reading,self.config); self._record_live_sensor(reading,decision)
            return {"success":True,"message":"Sensor data received","buzzer_mode":decision["buzzer_mode"]}

    def ingest_mqtt(self, payload, topic):
        packet=SensorPacket.model_validate(payload)
        with self.lock:
            previous=self.mqtt_sequences.get(packet.device_id,-1)
            if packet.sequence<=previous: raise RuntimeError("MQTT sequence must increase")
            self.mqtt_sequences[packet.device_id]=packet.sequence; self.simulation_enabled=False
            now=datetime.now(timezone.utc)
            reading=FarmSensorReading(device_id=packet.device_id,sequence=packet.sequence,observed_at=now,source=f"mqtt:{topic}",**packet.model_dump(exclude={"device_id","sequence"}))
            decision=evaluate_farm(reading,self.config); self._record_live_sensor(reading,decision)
            return {"success":True,"message":"MQTT sensor data received","buzzer_mode":decision["buzzer_mode"],"decision":decision}

    def _sensor_payload(self):
        r=self.last_sensor_reading
        names=("soil_moisture","temperature","humidity","light","steam","motion","water_level","ultrasonic_distance","uptime",
               "soil_raw","water_raw","motion_count","pump","fan","led","reservoir_state","wifi_rssi")
        return {name:getattr(r,name) if r else None for name in names}

    def snapshot(self, include_integrator=False):
        with self.lock:
            if self.challenge.active_mode: self._challenge_step()
            else: self._simulate()
            now=datetime.now(timezone.utc)
            age=(now-self.last_hardware_at).total_seconds() if self.last_hardware_at else None
            live_timeout=15 if self.last_live_sensor_reading and self.last_live_sensor_reading.source.startswith("mqtt:") else self.config.offline_timeout_seconds
            connected=not self.challenge.active_mode and age is not None and age<=live_timeout
            decision=dict(self.last_decision or {})
            if not self.simulation_enabled and not connected and not self.challenge.active_mode:
                decision.update(health_score=25,farm_health="CRITICAL",status="ACTION",severity="critical",buzzer_mode="ALARM",
                  reasons=["The ESP32 has stopped sending sensor data"],actions=["Check ESP32 power, Wi-Fi, and the laptop LAN address."])
            decision["buzzer_mode"]=self.effective_buzzer()
            active_device=self.last_sensor_reading.device_id if self.last_sensor_reading else self.config.device_id
            result={"updated_at":now.isoformat(),"device":{"id":active_device,"name":self.config.name,"zone":self.config.zone,
              "connected":connected,"hardware_age_seconds":round(age,1) if age is not None else None,
              "last_received":self.last_hardware_at.isoformat() if self.last_hardware_at else None},
              "source":self.last_sensor_reading.source if self.last_sensor_reading else (self.last_reading.source if self.last_reading else "none"),
              "simulation":{"enabled":self.simulation_enabled,"scenario":self.scenario},"challenge":self.challenge.snapshot(),"sensors":self._sensor_payload(),"decision":decision}
            result["interpreter"]=interpret_farm(result["sensors"],decision)
            if include_integrator:
                result.update(raw={**self._sensor_payload(),"sequence":self.last_sensor_reading.sequence if self.last_sensor_reading else self.last_sequence},
                              config=self.config.public_dict(),rejected_packets=self.rejected_packets,uptime_seconds=round(time.monotonic()-STARTED_AT))
            return result

state=FarmState()
integrations=IntegrationService(state.ingest_mqtt)

@asynccontextmanager
async def lifespan(application):
    integrations.start()
    try: yield
    finally: integrations.stop()

app=FastAPI(title="FarmGuard AI",version="3.0.0",docs_url="/api/docs",redoc_url=None,lifespan=lifespan)

@app.get("/health")
def health(): return {"status":"ok","service":"FarmGuard AI","version":"3.0.0","integrations":integrations.status()}
@app.get("/api/integrations/status")
def integration_status(): return integrations.status()
@app.get("/api/v1/state")
def get_state():
    result=state.snapshot(); result["mqtt"]=integrations.mqtt.status(); return result
@app.get("/api/v1/integrator/state")
def get_integrator_state():
    result=state.snapshot(include_integrator=True); result["mqtt"]=integrations.mqtt.status(); return result
@app.get("/api/v1/history")
def get_history(limit:int=Query(80,ge=1,le=500)):
    rows = state.challenge.ephemeral_history[-limit:] if state.challenge.active_mode else list(reversed(state.store.rows("sensor_readings",limit)))
    return {"readings":rows}
@app.get("/api/v1/events")
def get_events(limit:int=Query(50,ge=1,le=500)):
    challenge_events = state.challenge.event_log if state.challenge.active_mode else []
    return {"events":(challenge_events + state.store.rows("events",limit))[:limit]}

@app.post("/api/sensors")
def post_sensors(packet:SensorPacket,x_api_key:str|None=Header(default=None,alias="X-API-Key")):
    if not x_api_key or not hmac.compare_digest(x_api_key,API_KEY):
        state.rejected_packets+=1
        state.store.add_event("critical","Unauthorized API request blocked","Invalid or missing X-API-Key","Verify the sending device and rotate the key if needed.","security")
        raise HTTPException(401,"Invalid or missing X-API-Key")
    try: return state.ingest_sensors(packet)
    except RuntimeError as error: raise HTTPException(409,str(error)) from error

@app.get("/api/sensors/latest")
def get_latest_sensors(): return {"success":True,**state.snapshot(),"mqtt":integrations.mqtt.status()}
@app.get("/api/sensors/history")
def get_sensor_history(limit:int=Query(80,ge=1,le=500)):
    rows = state.challenge.ephemeral_history[-limit:] if state.challenge.active_mode else list(reversed(state.store.rows("sensor_readings",limit)))
    return {"readings":rows}

@app.get("/api/challenges")
def get_challenges(): return state.challenge.snapshot()

@app.post("/api/challenges/start")
def start_challenge(request:ChallengeRequest):
    if request.mode not in CHALLENGES: raise HTTPException(422,"Unknown challenge")
    with state.lock:
        state.simulation_enabled=False; state.challenge.start(request.mode); state._challenge_step()
    return state.snapshot()

@app.post("/api/challenges/stop")
def stop_challenge():
    with state.lock:
        state.challenge.stop()
        age=(datetime.now(timezone.utc)-state.last_hardware_at).total_seconds() if state.last_hardware_at else None
        if state.last_live_sensor_reading and age is not None and age<=15:
            state.simulation_enabled=False; state.last_sensor_reading=state.last_live_sensor_reading; state.last_decision=state.last_live_decision
        else:
            state.simulation_enabled=True; state._simulate(force=True)
    return state.snapshot()

@app.post("/api/challenges/reset")
def reset_challenge():
    with state.lock:
        if not state.challenge.active_mode: raise HTTPException(409,"No active challenge")
        state.challenge.reset(); state._challenge_step()
    return state.snapshot()

@app.post("/api/challenges/fun-box")
def update_fun_box(request:FunBoxRequest):
    values=request.model_dump(exclude_none=True,exclude={"scenario"})
    with state.lock:
        state.simulation_enabled=False; state.challenge.configure_fun_box(values,request.scenario); state._challenge_step()
    return state.snapshot()

@app.post("/api/farm-guide/ask")
def ask_farm_guide(request:FarmGuideQuestion):
    snapshot=state.snapshot(); interpreted=answer_question(request.question,snapshot["sensors"],snapshot["decision"],request.language)
    return {"answer":interpreted["response"],"status":interpreted["status"],"reason":interpreted["reason"],
            "action":interpreted["actions"][0],"farm_health":interpreted["priority"],
            "health_score":snapshot["decision"]["health_score"],"language":request.language,
            "grounded_in":"current FarmGuard sensor state","sensor_values":snapshot["sensors"]}

@app.get("/api/farm-guide/capabilities")
def farm_guide_capabilities():
    return {"languages":LANGUAGE_NAMES,"voice":{"available":False,"pipeline":["speech-to-text","FarmGuard interpreter","live sensor context","response","text-to-speech"]},
            "device_control":{"available":False,"requires":["safety rule verification","user confirmation","device acknowledgement","action log"]}}

@app.post("/api/v1/telemetry")
def post_telemetry(packet:TelemetryPacket):
    try: return state.ingest_legacy(packet)
    except PermissionError as error: raise HTTPException(403,str(error)) from error
    except RuntimeError as error: raise HTTPException(409,str(error)) from error

@app.post("/api/v1/integrator/simulation")
def set_simulation(request:SimulationRequest):
    if request.scenario not in SCENARIOS: raise HTTPException(422,"Unknown scenario")
    with state.lock:
        state.challenge.stop(); state.simulation_enabled,state.scenario=request.enabled,request.scenario; state._simulate(force=True)
    return state.snapshot(include_integrator=True)

@app.post("/api/v1/integrator/buzzer-test")
def test_buzzer(request:BuzzerTestRequest):
    with state.lock:
        state.buzzer_override=(request.mode,time.monotonic()+request.duration_seconds)
        state.store.add_event("warning" if request.mode!="OFF" else "healthy","Buzzer test",f"Integrator requested {request.mode}","No farm action required; this is a hardware test.","integrator")
    return {"ok":True,"mode":request.mode,"duration_seconds":request.duration_seconds}

@app.patch("/api/v1/integrator/config")
def update_config(request:ConfigUpdate):
    with state.lock:
        candidate=DeviceConfig(**state.config.public_dict(include_token=True))
        for key,value in request.model_dump(exclude_none=True).items(): setattr(candidate,key,value)
        if candidate.level_critical_pct>=candidate.level_warning_pct: raise HTTPException(422,"Critical level must be lower than warning level")
        if candidate.proximity_critical_cm>=candidate.proximity_warning_cm: raise HTTPException(422,"Critical proximity must be lower than warning proximity")
        state.config=candidate
        if state.last_sensor_reading: state.last_decision=evaluate_farm(state.last_sensor_reading,state.config)
    return {"ok":True,"config":state.config.public_dict()}

@app.get("/api/v1/export/{kind}.csv")
def export_csv(kind:Literal["readings","events"]):
    rows=state.store.rows("sensor_readings" if kind=="readings" else "events",500); output=io.StringIO()
    if rows:
        writer=csv.DictWriter(output,fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="farmguard-{kind}.csv"'})

@app.get("/")
def owner_dashboard(): return FileResponse(WEB/"index.html")
@app.get("/integrator")
def integrator_dashboard(): return FileResponse(WEB/"integrator.html")
app.mount("/static",StaticFiles(directory=WEB),name="static")

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host=os.getenv("FARMGUARD_HOST","0.0.0.0"),port=int(os.getenv("PORT","7860")))
