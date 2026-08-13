#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <Adafruit_SHT31.h>
#include "SplitRangePID.h"

// ==========================================
// HARDWARE PIN MAPPING
// ==========================================
#define I2C_SDA 25
#define I2C_SCL 26
#define PELTIER_PIN 27
#define PTC_EN 13
#define PTC_RPWM 14
#define PTC_LPWM 12

// ==========================================
// GLOBALS & OBJECTS
// ==========================================
Adafruit_SHT31 sht31 = Adafruit_SHT31();

// Instantiate PID with 0.15 C deadband
SplitRangePID incubatorPID(0.10);

const double target_setpoint = 37.0;
unsigned long last_time = 0;
const unsigned long sample_interval = 2000; // 2 seconds

void setup() {
    Serial.begin(115200);
    Wire.begin(I2C_SDA, I2C_SCL);

    // 1. Initialize Hardware Pins
    pinMode(PELTIER_PIN, OUTPUT);
    pinMode(PTC_EN, OUTPUT);
    pinMode(PTC_RPWM, OUTPUT);
    pinMode(PTC_LPWM, OUTPUT);

    // Default safety state (Everything OFF)
    analogWrite(PELTIER_PIN, 0);
    analogWrite(PTC_RPWM, 0);
    digitalWrite(PTC_EN, LOW);
    digitalWrite(PTC_LPWM, LOW);

    // 2. Initialize SHT31
    if (!sht31.begin(0x44)) {
        Serial.println("[ERROR] SHT31 not detected!");
    }

    // 3. Configure the Split-Range PID
    incubatorPID.setHeaterGains(11.94, 0.01145, 0.0); // PI Control for Heater
    incubatorPID.setCoolerGains(1000.0, 0.0, 0.0);    // ON/OFF Hack for Peltier
    incubatorPID.setOutputLimits(20.0, 90.0);          // Prevent heat soak

    // 4. Block Execution and Wait for Python
    Serial.println("[SYSTEM] Ready. Waiting for START command from Python...");
    while (true) {
        if (Serial.available() > 0) {
            String command = Serial.readStringUntil('\n');
            command.trim();
            if (command == "START") {
                digitalWrite(PTC_EN, HIGH); // Enable the BTS7960 heater driver
                last_time = millis();       // Start the timer
                break;                      // Break the infinite loop
            }
        }
        delay(100);
    }
}

void loop() {
    // ==========================================
    // THE KILL SWITCH (Listen for Python's STOP)
    // ==========================================
    if (Serial.available() > 0) {
        String command = Serial.readStringUntil('\n');
        command.trim();
        if (command == "STOP") {
            analogWrite(PTC_RPWM, 0);
            analogWrite(PELTIER_PIN, 0);
            digitalWrite(PTC_EN, LOW);
            Serial.println("[SYSTEM] STOP command received. Hardware disabled.");
            while(true) { delay(1000); } // Permanent halt
        }
    }

    unsigned long current_time = millis();
    
    // Execute strictly every 2000 ms (2 seconds)
    if (current_time - last_time >= sample_interval) {
        
        double dt = (current_time - last_time) / 1000.0; 
        last_time = current_time;

        // 1. Poll the Sensors (Temp AND Humidity)
        double current_temp = sht31.readTemperature();
        if (isnan(current_temp)) current_temp = 0.0; 
        
        double current_hum = sht31.readHumidity();
        if (isnan(current_hum)) current_hum = 0.0;

        // ==========================================
        // DYNAMIC LIMIT SHIFTING
        // ==========================================
        static bool is_maintaining = false;
        
        if (!is_maintaining && current_temp >= target_setpoint) {
            is_maintaining = true; 
            // The initial approach is complete. 
            // Unlock 30% power so the controller can defend against undershoots.
            incubatorPID.setOutputLimits(30.0, 90.0);
            Serial.println("[SYSTEM] Target reached. Heater ceiling raised to 30%.");
        }

        // 2. Compute PID Effort
        double heater_effort = 0.0;
        double cooler_effort = 0.0;
        incubatorPID.compute(target_setpoint, current_temp, dt, heater_effort, cooler_effort);

        // 3. Command Hardware (Convert 0-100% effort to 0-255 8-bit PWM)
        int heater_pwm_8bit = (int)(heater_effort * 2.55);
        int cooler_pwm_8bit = (int)(cooler_effort * 2.55);
        
        analogWrite(PTC_RPWM, heater_pwm_8bit);
        analogWrite(PELTIER_PIN, cooler_pwm_8bit);

        // 4. Send Telemetry strictly formatted for the Python Plotter
        Serial.printf("%.2f,%.2f,%.2f,%.1f,%.1f\n", target_setpoint, current_temp, current_hum, heater_effort, cooler_effort);
    }
}