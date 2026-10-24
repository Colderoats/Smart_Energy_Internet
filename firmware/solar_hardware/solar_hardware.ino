// solar_hardware: ESP32 + INA219 -> one JSON line per second over USB serial (115200 baud).
// Wiring: INA219 SDA=GPIO21, SCL=GPIO22, VCC=3V3, GND=GND, address 0x40 (A0/A1 open).
//         Panel+ -> INA219 VIN+, INA219 VIN- -> load resistor -> panel-. No battery.
// Line:   {"node":"solar_hardware","t_ms":12345,"v_bus_v":3.412,"i_ma":18.7,"p_mw":63.8}
// A line with "err" instead of readings is printed if the sensor is not found; the host bridge ignores it.
#include <Wire.h>
#include <Adafruit_INA219.h>

static const int SDA_PIN = 21;
static const int SCL_PIN = 22;
static const uint8_t INA_ADDR = 0x40;
static const uint32_t PERIOD_MS = 1000;

Adafruit_INA219 ina(INA_ADDR);
bool ok = false;

void i2cScan() {
  Serial.print("{\"i2c_scan\":[");
  bool first = true;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      if (!first) Serial.print(",");
      Serial.print("\"0x");
      Serial.print(a, HEX);
      Serial.print("\"");
      first = false;
    }
  }
  Serial.println("]}");
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  delay(500);
  ok = ina.begin(&Wire);
  if (ok) ina.setCalibration_16V_400mA();  // mini panel: well under 16 V / 400 mA, 0.1 mA resolution
  else i2cScan();
}

void loop() {
  static uint32_t last = 0;
  if (millis() - last < PERIOD_MS) return;
  last = millis();
  if (!ok) {
    Serial.println("{\"node\":\"solar_hardware\",\"err\":\"ina219_not_found\"}");
    ok = ina.begin(&Wire);
    if (ok) ina.setCalibration_16V_400mA();
    else i2cScan();
    return;
  }
  float v = ina.getBusVoltage_V();
  float i = ina.getCurrent_mA();
  float p = ina.getPower_mW();
  char buf[128];
  snprintf(buf, sizeof(buf), "{\"node\":\"solar_hardware\",\"t_ms\":%lu,\"v_bus_v\":%.3f,\"i_ma\":%.2f,\"p_mw\":%.2f}",
           (unsigned long)millis(), v, i, p);
  Serial.println(buf);
}
