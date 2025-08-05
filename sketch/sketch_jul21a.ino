#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

const char* serverURL = "http://YOUR_SERVER_IP:5000/collision";

// HC-SR04 pins
const int trigPin = 12;
const int echoPin = 13;

// Configuration
const float collisionThreshold = 10.0; // Distance in cm to trigger collision alert
const unsigned long measureInterval = 100; // Measurement interval in ms
const unsigned long alertCooldown = 1000; // Cooldown between alerts in ms

// Variables
unsigned long lastMeasurement = 0;
unsigned long lastAlert = 0;
bool collisionDetected = false;

// MPU9255 configuration
const int MPU = 0x68;
const float ACCEL_SCALE = 4096.0;
const float GYRO_SCALE = 65.5;

// WiFi credentials
const char* ssid = "Peaches";
const char* password = "peaches72";

// Server endpoints
const char* fallServerURL = "http://10.0.0.86:5000/fall_data";  // Fall detection data
const char* tempServerURL = "http://10.0.0.86:5000/temp";         // Temperature/humidity/tilt data
const char* colServerURL = "http://10.0.0.86:5000/collision";   // Collision data

// DHT sensor configuration
DHT dht(26, DHT11);
const int TILT_PIN = 4;

// Timing variables
unsigned long lastFallDataSend = 0;
unsigned long lastTempDataSend = 0;
const int FALL_SEND_INTERVAL = 100;    // Send fall data every 100ms
const int TEMP_SEND_INTERVAL = 20000;  // Send temp/humidity/tilt data every 20 seconds

// Status counters
int fallDataCounter = 0;
int tempDataCounter = 0;

void setup() {
  Serial.begin(115200);
  // Initialize MPU9250 sensor
  Wire.begin();
  // Initialize DHT11 Sensor
  dht.begin();
  // Initialize tilt switch pin
  pinMode(TILT_PIN, INPUT);
  // Initialize HC-SR04 pins
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);

  delay(1000);
  
  Serial.println("=== Integrated Sensor System ===");
  Serial.println("Fall Detection: 100ms interval");
  Serial.println("Environmental: 20s interval");
  
  // Initialize MPU9255
  initializeMPU();
  
  // Connect to WiFi
  connectToWiFi();
  
  Serial.println("System ready - dual monitoring active");
}

void loop() {
  unsigned long currentTime = millis();
  
  // Measure distance at specified intervals
  if (currentTime - lastMeasurement >= measureInterval) {
    float distance = measureDistance();
    
    Serial.print("Distance: ");
    Serial.print(distance);
    Serial.println(" cm");
    
    // Check for collision
    if (distance <= collisionThreshold && distance > 0) {
      if (!collisionDetected && (currentTime - lastAlert >= alertCooldown)) {
        collisionDetected = true;
        sendCollisionAlert(distance);
        lastAlert = currentTime;
      }
    } else {
      collisionDetected = false;
    }
    
    lastMeasurement = currentTime;
  }
  
  // Send fall detection data every 100ms
  if (currentTime - lastFallDataSend >= FALL_SEND_INTERVAL) {
    handleFallDetection();
    lastFallDataSend = currentTime;
  }
  
  // Send temperature/humidity/tilt data every 20 seconds
  if (currentTime - lastTempDataSend >= TEMP_SEND_INTERVAL) {
    handleEnvironmentalData();
    lastTempDataSend = currentTime;
  }
  
  delay(1);
}

void initializeMPU() {
  Serial.println("Initializing MPU9255...");
  
  // Wake up the MPU9255
  writeRegister(0x6B, 0x00);
  delay(100);
  
  // Configure accelerometer (±8g for fall detection)
  writeRegister(0x1C, 0x10);
  
  // Configure gyroscope (±500°/s)
  writeRegister(0x1B, 0x08);
  
  // Set sample rate to 200Hz
  writeRegister(0x19, 0x04);  // 1kHz / (1 + 4) = 200Hz
  
  // Configure DLPF for noise reduction
  writeRegister(0x1A, 0x05);  // 10Hz bandwidth
  
  delay(100);
  
  // Verify initialization
  byte whoami = readRegister(0x75);
  if (whoami == 0x70) {
    Serial.println("✅ MPU9255 initialized successfully!");
  } else {
    Serial.println("❌ MPU9255 initialization failed!");
    Serial.print("WHO_AM_I: 0x"); Serial.println(whoami, HEX);
  }
}

void connectToWiFi() {
  Serial.print("Connecting to WiFi: ");
  Serial.println(ssid);
  
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.println("✅ WiFi connected!");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("❌ WiFi connection failed!");
  }
}

void handleFallDetection() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  
  // Read MPU sensor data
  float accel[3], gyro[3];
  float temperature;
  
  if (readSensorData(accel, gyro, temperature)) {
    sendFallDataToServer(accel, gyro, temperature);
  }
}

void handleEnvironmentalData() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  
  // Read DHT sensor and tilt state
  float temp = readDHTTemperature();
  float hum = readDHTHumidity();
  int tiltState = digitalRead(TILT_PIN);
  
  if (temp != -1 && hum != -1) {
    sendTempDataToServer(temp, hum, tiltState);
  }
}

bool readSensorData(float accel[3], float gyro[3], float &temperature) {
  Wire.beginTransmission(MPU);
  Wire.write(0x3B);  // Starting register
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  
  Wire.requestFrom(MPU, 14, true);
  
  if (Wire.available() < 14) {
    return false;
  }
  
  // Read accelerometer
  int16_t AcX = (Wire.read() << 8) | Wire.read();
  int16_t AcY = (Wire.read() << 8) | Wire.read();
  int16_t AcZ = (Wire.read() << 8) | Wire.read();
  
  // Read temperature
  int16_t Tmp = (Wire.read() << 8) | Wire.read();
  
  // Read gyroscope
  int16_t GyX = (Wire.read() << 8) | Wire.read();
  int16_t GyY = (Wire.read() << 8) | Wire.read();
  int16_t GyZ = (Wire.read() << 8) | Wire.read();
  
  // Convert to meaningful units
  accel[0] = AcX / ACCEL_SCALE;
  accel[1] = AcY / ACCEL_SCALE;
  accel[2] = AcZ / ACCEL_SCALE;
  
  gyro[0] = GyX / GYRO_SCALE;
  gyro[1] = GyY / GYRO_SCALE;
  gyro[2] = GyZ / GYRO_SCALE;
  
  temperature = (Tmp / 340.0) + 36.53;
  
  return true;
}

void sendFallDataToServer(float accel[3], float gyro[3], float temperature) {
  HTTPClient http;
  http.begin(fallServerURL);
  http.addHeader("Content-Type", "application/json");
  
  // Create JSON payload
  JsonDocument doc;
  doc["timestamp"] = millis();
  doc["device_id"] = WiFi.macAddress();
  
  // Add accelerometer data
  JsonArray accel_array = doc["accelerometer"].to<JsonArray>();
  accel_array.add(accel[0]);
  accel_array.add(accel[1]);
  accel_array.add(accel[2]);
  
  // Add gyroscope data
  JsonArray gyro_array = doc["gyroscope"].to<JsonArray>();
  gyro_array.add(gyro[0]);
  gyro_array.add(gyro[1]);
  gyro_array.add(gyro[2]);
  
  // Add temperature
  doc["temperature"] = temperature;
  
  // Calculate total acceleration magnitude
  float total_accel = sqrt(accel[0]*accel[0] + accel[1]*accel[1] + accel[2]*accel[2]);
  doc["total_acceleration"] = total_accel;
  
  // Serialize JSON
  String jsonString;
  serializeJson(doc, jsonString);
  
  // Send HTTP POST request
  int httpResponseCode = http.POST(jsonString);
  
  if (httpResponseCode > 0) {
    fallDataCounter++;
    
    // Print status every 50 readings (5 seconds at 100ms intervals)
    if (fallDataCounter % 50 == 0) {
      Serial.println("✅ Fall data sent (Count: " + String(fallDataCounter) + ")");
      Serial.println("   Accel=" + String(total_accel, 2) + "g, Temp=" + String(temperature, 1) + "°C");
    }
  } else {
    Serial.println("❌ Fall data HTTP error: " + String(httpResponseCode));
  }
  
  http.end();
}

void sendTempDataToServer(float temp, float hum, int tiltState) {
  HTTPClient http;
  
  String url = String(tempServerURL) + "?temperature=" + String(temp) + 
               "&humidity=" + String(hum) + "&tilted=" + String(tiltState);
  
  http.begin(url);
  int httpCode = http.GET();
  
  if (httpCode > 0) {
    tempDataCounter++;
    Serial.println("✅ Environmental data sent (Count: " + String(tempDataCounter) + ")");
    Serial.println("   Temp=" + String(temp, 1) + "°C, Humidity=" + String(hum, 1) + "%, Tilt=" + String(tiltState));
  } else {
    Serial.println("❌ Environmental data HTTP error: " + String(httpCode));
  }
  
  http.end();
}

float readDHTTemperature() {
  float t = dht.readTemperature();
  if (isnan(t)) {    
    Serial.println("❌ Failed to read temperature from DHT sensor!");
    return -1;
  }
  return t;
}

float readDHTHumidity() {
  float h = dht.readHumidity();
  if (isnan(h)) {
    Serial.println("❌ Failed to read humidity from DHT sensor!");
    return -1;
  }
  return h;
}

void writeRegister(byte reg, byte value) {
  Wire.beginTransmission(MPU);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission(true);
}

byte readRegister(byte reg) {
  Wire.beginTransmission(MPU);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU, 1, true);
  return Wire.read();
}

float measureDistance() {
  // Clear the trigger pin
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  
  // Send 10us pulse to trigger pin
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  
  // Read the echo pin and calculate distance
  long duration = pulseIn(echoPin, HIGH, 30000); // 30ms timeout
  
  if (duration == 0) {
    return -1; // Timeout or no echo
  }
  
  // Calculate distance in cm (speed of sound = 343 m/s)
  float distance = (duration * 0.0343) / 2;
  
  return distance;
}

void sendCollisionAlert(float distance) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(colServerURL);
    http.addHeader("Content-Type", "application/json");
    
    // Create JSON payload
    DynamicJsonDocument doc(1024);
    doc["device_id"] = WiFi.macAddress();
    doc["distance"] = distance;
    doc["threshold"] = collisionThreshold;
    doc["timestamp"] = millis();
    
    String jsonString;
    serializeJson(doc, jsonString);
    
    Serial.println("Sending collision alert...");
    Serial.println("Payload: " + jsonString);
    
    int httpResponseCode = http.POST(jsonString);
    
    if (httpResponseCode > 0) {
      String response = http.getString();
      Serial.println("HTTP Response: " + String(httpResponseCode));
      Serial.println("Response: " + response);
    } else {
      Serial.println("Error sending request: " + String(httpResponseCode));
    }
    
    http.end();
  } else {
    Serial.println("WiFi not connected - cannot send alert");
  }
}
