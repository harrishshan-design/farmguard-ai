// FarmGuard AI telemetry example for ESP32.
// Replace Wi-Fi details and SERVER_URL before uploading.

#include <WiFi.h>
#include <HTTPClient.h>

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";
const char* SERVER_URL = "http://192.168.1.100:7860/api/telemetry";

void setup() {
  Serial.begin(115200);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi connected");
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    // Replace these demo numbers with calibrated sensor readings.
    float moisture = 31.5;
    float temperature = 32.1;
    float humidity = 59.0;
    float light = 76.0;

    String body = "{\"device_id\":\"esp32-field-01\",";
    body += "\"token\":\"farmguard-demo-01\",";
    body += "\"zone_id\":\"zone-a\",";
    body += "\"moisture\":" + String(moisture, 1) + ",";
    body += "\"temperature\":" + String(temperature, 1) + ",";
    body += "\"humidity\":" + String(humidity, 1) + ",";
    body += "\"light\":" + String(light, 1) + "}";

    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "application/json");
    int status = http.POST(body);
    Serial.printf("FarmGuard response: %d\n", status);
    http.end();
  }
  delay(5000);
}
