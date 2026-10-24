#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_INA219.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>

// ---------------- EDIT THESE ----------------
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST     = "192.168.1.10";   // laptop IPv4 from ipconfig
const uint16_t MQTT_PORT  = 1883;
const char* NODE_ID       = "solar_01";
// --------------------------------------------

const uint32_t SAMPLE_INTERVAL_MS = 5000;     // 5 s sampling interval

// Physical limits of the panel; readings outside are flagged invalid
const float V_MIN = 0.0,  V_MAX = 8.0;        // volts
const float I_MIN = -5.0, I_MAX = 1000.0;     // milliamps

Adafruit_INA219 ina219;
WiFiClient   net;
PubSubClient mqtt(net);
String topic;

// Buffer: if publishing fails, keep up to 20 messages and resend later
const int BUF_SIZE = 20;
String buffer[BUF_SIZE];
int bufHead = 0, bufCount = 0;
uint32_t lastSample = 0;

void connectWiFi() {
  static bool started = false;
  static uint32_t lastTry = 0;

  if (WiFi.status() == WL_CONNECTED) return;

  if (!started) {
    started = true;
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(true);
    delay(200);

    // Show which networks the ESP32 can actually see
    Serial.println("Scanning Wi-Fi...");
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++) {
      Serial.printf("  %d: %s  (signal %d dBm)\n", i + 1, WiFi.SSID(i).c_str(), WiFi.RSSI(i));
    }
    WiFi.scanDelete();

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("Connecting to ");
    Serial.println(WIFI_SSID);
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
      delay(1000);
      Serial.print(".");
    }
    Serial.println();
    lastTry = millis();
  } else if (millis() - lastTry > 15000) {
    lastTry = millis();
    WiFi.reconnect();   // retry without resetting the config
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Wi-Fi connected: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.printf("Wi-Fi not connected (status %d)\n", WiFi.status());
  }
}
void connectMQTT() {
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
  String clientId = String("sei-") + NODE_ID;
  if (mqtt.connect(clientId.c_str())) {
    Serial.println("MQTT connected");
  } else {
    Serial.printf("MQTT failed, state=%d (will retry)\n", mqtt.state());
  }
}

void syncClock() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");   // UTC
  struct tm t;
  if (getLocalTime(&t, 10000)) Serial.println("Clock synchronised");
  else                         Serial.println("NTP not reached yet");
}

void enqueue(const String &msg) {
  int idx = (bufHead + bufCount) % BUF_SIZE;
  if (bufCount == BUF_SIZE) bufHead = (bufHead + 1) % BUF_SIZE;  // drop oldest
  else bufCount++;
  buffer[idx] = msg;
}

void flushBuffer() {
  while (bufCount > 0 && mqtt.connected()) {
    if (!mqtt.publish(topic.c_str(), buffer[bufHead].c_str())) break;
    bufHead = (bufHead + 1) % BUF_SIZE;
    bufCount--;
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  Wire.begin(21, 22);                 // SDA, SCL
  if (!ina219.begin()) {
    Serial.println("INA219 not found - check VCC->3V3, GND, SDA->21, SCL->22");
  }
  ina219.setCalibration_16V_400mA();  // best resolution for a mini panel

  topic = String("sei/solar/") + NODE_ID;
  connectWiFi();
  syncClock();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  connectMQTT();
}

void loop() {
  connectWiFi();
  connectMQTT();
  mqtt.loop();

  if (millis() - lastSample < SAMPLE_INTERVAL_MS) return;
  lastSample = millis();

  // Read the panel
  float voltage = ina219.getBusVoltage_V() + ina219.getShuntVoltage_mV() / 1000.0;
  float current = ina219.getCurrent_mA();
  float power   = voltage * current;   // mW
  bool  valid   = (voltage >= V_MIN && voltage <= V_MAX &&
                   current >= I_MIN && current <= I_MAX);

  // Build JSON message
  JsonDocument doc;
  doc["node"]       = NODE_ID;
  doc["type"]       = "solar";
  doc["ts"]         = (uint32_t) time(nullptr);
  doc["voltage_v"]  = round(voltage * 1000) / 1000.0;
  doc["current_ma"] = round(current * 10) / 10.0;
  doc["power_mw"]   = round(power * 10) / 10.0;
  doc["valid"]      = valid;
  String msg;
  serializeJson(doc, msg);

  Serial.println(msg);
  enqueue(msg);
  flushBuffer();   // publish now, or keep for the next interval
}
