// FarmGuard AI — ESP32 seven-sensor firmware
// Arduino IDE 1.8.19 compatible. Install ArduinoJson and DHT sensor library.
// IMPORTANT: ESP32 GPIO is 3.3 V only. Use a divider on a 5 V ultrasonic ECHO.

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <PubSubClient.h>

// ---------------- USER CONFIGURATION ----------------
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
// Use the laptop's LAN IPv4 address from ipconfig — never localhost or 127.0.0.1.
const char* SERVER_URL    = "http://192.168.1.100:7860/api/sensors";
const char* DEVICE_ID     = "esp32-farm-01";
const char* API_KEY       = "change-this-local-key";
const char* MQTT_HOST     = "192.168.98.50";
const int   MQTT_PORT     = 1883;
const char* MQTT_USER     = ""; // Leave blank when the broker has no login.
const char* MQTT_PASSWORD = "";
const char* MQTT_SENSOR_TOPIC = "farmguard/sensors";
const char* MQTT_STATUS_TOPIC = "farmguard/status";
const char* MQTT_BROADCAST_TOPIC = "/broadcast";

// Safe defaults: analog sensors use ADC1, which continues working while Wi-Fi is on.
const int ULTRASONIC_TRIG_PIN = 23;
const int ULTRASONIC_ECHO_PIN = 22; // Must receive no more than 3.3 V.
const int LDR_PIN              = 34; // ADC1, input-only.
const int STEAM_PIN            = 35; // ADC1, input-only.
const int SOIL_PIN             = 32; // ADC1.
const int WATER_PIN            = 33; // ADC1.
const int DHT_PIN              = 27;
const int PIR_PIN              = 26;
const int BUZZER_PIN           = 25;

// Change DHT11 to DHT22 only if that is the exact module printed on your sensor.
#define DHT_TYPE DHT11
// Calibrate these using dry/wet and empty/full Serial Monitor readings.
const int SOIL_DRY_RAW   = 3200;
const int SOIL_WET_RAW   = 1200;
const int WATER_EMPTY_RAW = 400;
const int WATER_FULL_RAW  = 2800;
const unsigned long SAMPLE_INTERVAL_MS = 1000;
const unsigned long WIFI_RETRY_MS = 10000;
// ----------------------------------------------------

DHT dht(DHT_PIN, DHT_TYPE);
WiFiClient mqttNetwork;
PubSubClient mqttClient(mqttNetwork);
unsigned long sequenceNumber = 0, lastSampleAt = 0, lastWiFiAttemptAt = 0;
unsigned long lastMqttAttemptAt = 0;
unsigned long motionCount = 0;
bool previousMotion = false;
String buzzerMode = "OFF";

float percentFromRaw(int raw, int zeroRaw, int hundredRaw) {
  if (zeroRaw == hundredRaw) return NAN;
  float value = (raw - zeroRaw) * 100.0f / (hundredRaw - zeroRaw);
  return constrain(value, 0.0f, 100.0f);
}

float readDistanceCm() {
  digitalWrite(ULTRASONIC_TRIG_PIN, LOW); delayMicroseconds(2);
  digitalWrite(ULTRASONIC_TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
  unsigned long duration = pulseIn(ULTRASONIC_ECHO_PIN, HIGH, 30000UL);
  if (duration == 0) return NAN; // Timeout remains null, never a fake 0 or 500.
  float distance = duration * 0.0343f / 2.0f;
  return distance <= 500.0f ? distance : NAN;
}

void updatePassiveBuzzer() {
  unsigned long phase = millis(); bool sound = false; int frequency = 1800;
  if (buzzerMode == "ALARM") { sound = (phase % 400) < 210; frequency = 2300; }
  else if (buzzerMode == "PULSE") { sound = (phase % 2000) < 180; frequency = 1500; }
  if (sound) tone(BUZZER_PIN, frequency); else noTone(BUZZER_PIN);
}

void maintainWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  unsigned long now = millis();
  if (lastWiFiAttemptAt != 0 && now - lastWiFiAttemptAt < WIFI_RETRY_MS) return;
  lastWiFiAttemptAt = now;
  WiFi.disconnect(); WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.println("Wi-Fi reconnect requested; sensor loop remains active.");
}

void onMqttMessage(char* topic, byte* payloadBytes, unsigned int length) {
  StaticJsonDocument<768> response;
  if (deserializeJson(response, payloadBytes, length) == DeserializationError::Ok && response["origin"] == "farmguard-backend") {
    const char* command = response["buzzer_mode"];
    if (command) buzzerMode = String(command);
  }
}

void maintainMqtt() {
  if (WiFi.status() != WL_CONNECTED || mqttClient.connected()) return;
  unsigned long now = millis();
  if (lastMqttAttemptAt != 0 && now - lastMqttAttemptAt < WIFI_RETRY_MS) return;
  lastMqttAttemptAt = now;
  String clientId = String("farmguard-") + DEVICE_ID;
  bool connected = strlen(MQTT_USER) ? mqttClient.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD) : mqttClient.connect(clientId.c_str());
  if (connected) {
    mqttClient.subscribe(MQTT_BROADCAST_TOPIC, 1);
    mqttClient.publish(MQTT_STATUS_TOPIC, "{\"device\":\"farmguard-esp32\",\"status\":\"online\"}", true);
    Serial.println("MQTT connected; publishing sensor data to farmguard/sensors.");
  } else Serial.printf("MQTT unavailable (state %d); HTTP fallback remains active.\n", mqttClient.state());
}

void putNullableFloat(JsonDocument& doc, const char* key, float value) {
  if (isnan(value) || isinf(value)) doc[key] = nullptr; else doc[key] = value;
}

bool postOnce(const String& body) {
  HTTPClient http; http.setConnectTimeout(2000); http.setTimeout(3000);
  if (!http.begin(SERVER_URL)) return false;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  int status = http.POST(body); String responseBody = http.getString();
  bool ok = status >= 200 && status < 300;
  if (ok) {
    StaticJsonDocument<256> response;
    if (deserializeJson(response, responseBody) == DeserializationError::Ok && response["buzzer_mode"].is<const char*>())
      buzzerMode = response["buzzer_mode"].as<String>();
  }
  Serial.printf("HTTP %d (%s)\n", status, ok ? "accepted" : "will retry next cycle");
  http.end(); return ok;
}

void sampleAndSend() {
  float distance = readDistanceCm();
  int lightRaw = analogRead(LDR_PIN), steamRaw = analogRead(STEAM_PIN);
  int soilRaw = analogRead(SOIL_PIN), waterRaw = analogRead(WATER_PIN);
  float soil = percentFromRaw(soilRaw, SOIL_DRY_RAW, SOIL_WET_RAW);
  float water = percentFromRaw(waterRaw, WATER_EMPTY_RAW, WATER_FULL_RAW);
  float humidity = dht.readHumidity(), temperature = dht.readTemperature();
  bool motion = digitalRead(PIR_PIN) == HIGH;
  if (motion && !previousMotion) motionCount++;
  previousMotion = motion;
  sequenceNumber++;

  StaticJsonDocument<768> payload;
  payload["device"] = DEVICE_ID; payload["uptime_s"] = millis() / 1000UL;
  payload["light_raw"] = lightRaw; payload["brightness"] = lightRaw;
  payload["soil_raw"] = soilRaw; putNullableFloat(payload, "soil_pct", soil);
  payload["water_raw"] = waterRaw; payload["steam_raw"] = steamRaw;
  putNullableFloat(payload, "temp_c", temperature); putNullableFloat(payload, "humidity_pct", humidity);
  putNullableFloat(payload, "distance_cm", distance);
  payload["motion_count"] = motionCount; payload["motion_now"] = motion;
  payload["pump"] = false; payload["fan"] = false; payload["led"] = false;
  payload["reservoir_state"] = isnan(water) ? 0 : water < 20 ? 0 : water < 60 ? 1 : 2;
  payload["wifi_rssi"] = WiFi.RSSI();
  String body; serializeJson(payload, body);

  Serial.println(body);
  bool sentByMqtt = mqttClient.connected() && mqttClient.publish(MQTT_SENSOR_TOPIC, body.c_str());
  if (sentByMqtt) Serial.println("MQTT farmguard/sensors published");
  else if (WiFi.status() == WL_CONNECTED) {
    StaticJsonDocument<512> httpPayload;
    httpPayload["device_id"] = DEVICE_ID; httpPayload["sequence"] = sequenceNumber;
    putNullableFloat(httpPayload, "soil_moisture", soil); putNullableFloat(httpPayload, "temperature", temperature);
    putNullableFloat(httpPayload, "humidity", humidity); httpPayload["light"] = lightRaw;
    httpPayload["steam"] = steamRaw; httpPayload["motion"] = motion;
    putNullableFloat(httpPayload, "water_level", water); putNullableFloat(httpPayload, "ultrasonic_distance", distance);
    httpPayload["uptime"] = millis() / 1000UL;
    String httpBody; serializeJson(httpPayload, httpBody); postOnce(httpBody);
  }
  else Serial.println("No Wi-Fi; sample kept visible in Serial Monitor and next sample will retry.");
}

void setup() {
  Serial.begin(115200);
  pinMode(ULTRASONIC_TRIG_PIN, OUTPUT); pinMode(ULTRASONIC_ECHO_PIN, INPUT);
  pinMode(LDR_PIN, INPUT); pinMode(STEAM_PIN, INPUT); pinMode(SOIL_PIN, INPUT); pinMode(WATER_PIN, INPUT);
  pinMode(PIR_PIN, INPUT); pinMode(BUZZER_PIN, OUTPUT);
  analogReadResolution(12); dht.begin(); WiFi.mode(WIFI_STA); maintainWiFi();
  mqttClient.setServer(MQTT_HOST, MQTT_PORT); mqttClient.setCallback(onMqttMessage); mqttClient.setBufferSize(768);
  Serial.println("FarmGuard sensor node started.");
}

void loop() {
  maintainWiFi(); maintainMqtt(); mqttClient.loop(); updatePassiveBuzzer();
  unsigned long now = millis();
  if (now - lastSampleAt >= SAMPLE_INTERVAL_MS) { lastSampleAt = now; sampleAndSend(); }
  delay(10);
}
