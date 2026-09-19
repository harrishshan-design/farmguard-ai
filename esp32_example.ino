// FarmGuard AI ESP32 firmware
// Hardware: HC-SR04 ultrasonic, analog photoresistor module, passive piezo buzzer.
// Install ArduinoJson from Arduino Library Manager before compiling.

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "http://192.168.1.100:7860/api/v1/telemetry";
const char* DEVICE_ID = "esp32-farm-01";
const char* DEVICE_TOKEN = "farmguard-device-01";

const int TRIGGER_PIN = 5;
const int ECHO_PIN = 18;      // Use a voltage divider if HC-SR04 echo is 5 V.
const int LDR_PIN = 34;       // ADC-capable input-only ESP32 pin.
const int BUZZER_PIN = 25;    // Passive piezo buzzer.

unsigned long sequenceNumber = 0;
unsigned long lastSampleAt = 0;
unsigned long lastServerSuccessAt = 0;
String buzzerMode = "OFF";

float readDistanceCm() {
  digitalWrite(TRIGGER_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIGGER_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIGGER_PIN, LOW);
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return 500.0;
  return min(duration * 0.0343f / 2.0f, 500.0f);
}

void updatePassiveBuzzer() {
  unsigned long now = millis();
  bool soundOn = false;
  int frequency = 1800;
  if (buzzerMode == "ALARM") {
    soundOn = (now % 400) < 210;
    frequency = 2300;
  } else if (buzzerMode == "PULSE") {
    soundOn = (now % 2000) < 180;
    frequency = 1500;
  }
  if (soundOn) tone(BUZZER_PIN, frequency);
  else noTone(BUZZER_PIN);
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) {
    updatePassiveBuzzer();
    delay(250);
    Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " connected" : " timed out");
}

void sendTelemetry() {
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) return;

  float distanceCm = readDistanceCm();
  int lightRaw = analogRead(LDR_PIN);
  sequenceNumber++;

  JsonDocument payload;
  payload["device_id"] = DEVICE_ID;
  payload["token"] = DEVICE_TOKEN;
  payload["sequence"] = sequenceNumber;
  payload["distance_cm"] = distanceCm;
  payload["light_raw"] = lightRaw;
  String body;
  serializeJson(payload, body);

  HTTPClient http;
  http.setTimeout(3000);
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  int status = http.POST(body);
  if (status == 200) {
    JsonDocument response;
    if (deserializeJson(response, http.getString()) == DeserializationError::Ok) {
      buzzerMode = response["buzzer_mode"].as<String>();
      lastServerSuccessAt = millis();
    }
  }
  Serial.printf("distance=%.1fcm light=%d HTTP=%d buzzer=%s\n", distanceCm, lightRaw, status, buzzerMode.c_str());
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIGGER_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LDR_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  analogReadResolution(12);
  connectWiFi();
  lastServerSuccessAt = millis();
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleAt >= 2000) {
    lastSampleAt = now;
    sendTelemetry();
  }
  // Fail safe: warn locally if the dashboard has been unreachable for 12 seconds.
  if (now - lastServerSuccessAt > 12000) buzzerMode = "ALARM";
  updatePassiveBuzzer();
  delay(10);
}
