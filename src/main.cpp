#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <Adafruit_SHT31.h>
#include <Adafruit_NeoPixel.h> 
#include "SplitRangePID.h"

// HARDWARE PIN MAPPING
#define I2C_SDA 25
#define I2C_SCL 26
#define PELTIER_PIN 27
#define PTC_EN 13
#define PTC_RPWM 14
#define PTC_LPWM 12
#define LED_PIN 16     
#define NUMPIXELS 21   

// Globals & objects
Adafruit_SHT31 sht31 = Adafruit_SHT31();
Adafruit_NeoPixel pixels(NUMPIXELS, LED_PIN, NEO_GRB + NEO_KHZ800);
SplitRangePID incubatorPID(0.10);

const double target_setpoint = 37.0;
unsigned long last_time = 0;
const unsigned long sample_interval = 2000;

// ---- Máquina de estados (reemplaza los while(true) bloqueantes) ----
enum SystemState { WAITING, RUNNING };
SystemState state = WAITING;

bool is_maintaining = false;  // antes era "static" dentro de loop(); ahora se resetea en cada START

void setup() {
    Serial.begin(115200);
    Wire.begin(I2C_SDA, I2C_SCL);

    pinMode(PELTIER_PIN, OUTPUT);
    pinMode(PTC_EN, OUTPUT);
    pinMode(PTC_RPWM, OUTPUT);
    pinMode(PTC_LPWM, OUTPUT);

    // Default safety state (Everything OFF)
    analogWrite(PELTIER_PIN, 0);
    analogWrite(PTC_RPWM, 0);
    digitalWrite(PTC_EN, LOW);
    digitalWrite(PTC_LPWM, LOW);

    if (!sht31.begin(0x44)) {
        Serial.println("[ERROR] SHT31 not detected!");
    }

    // Configure controller gains
    incubatorPID.setHeaterGains(11.94, 0.01145, 0.0); // PI Control for Heater
    incubatorPID.setCoolerGains(1000.0, 0.0, 0.0);    // ON/OFF control for Peltier
    incubatorPID.setOutputLimits(20.0, 90.0);          // Prevent heat soak

    pixels.begin();
    pixels.clear();
    pixels.show();

    Serial.println("Waiting for START command from Python...");
    state = WAITING;
}

void loop() {
    if (Serial.available() > 0) {
        String command = Serial.readStringUntil('\n');
        command.trim();

        if (command == "START" && state == WAITING) {
            is_maintaining = false;
            incubatorPID.setOutputLimits(20.0, 90.0);

            digitalWrite(PTC_EN, HIGH);

            // Turn LEDs red upon start
            for (int i = 0; i < NUMPIXELS; i++) {
                pixels.setPixelColor(i, pixels.Color(3, 0, 0));
            }
            pixels.show();

            last_time = millis();
            state = RUNNING;

        } else if (command == "STOP" && state == RUNNING) {
            analogWrite(PTC_RPWM, 0);
            analogWrite(PELTIER_PIN, 0);
            digitalWrite(PTC_EN, LOW);

            pixels.clear();
            pixels.show();

            Serial.println("STOP command received. Hardware disabled.");
            state = WAITING;
        }
    }

    if (state != RUNNING) {
        return;  // no corre el control mientras espera, pero ya no bloquea el programa
    }

    unsigned long current_time = millis();

    // Execute strictly every 2 seconds
    if (current_time - last_time >= sample_interval) {

        double dt = (current_time - last_time) / 1000.0;
        last_time = current_time;

        // Poll sensors
        double current_temp = sht31.readTemperature();
        if (isnan(current_temp)) current_temp = 0.0;

        double current_hum = sht31.readHumidity();
        if (isnan(current_hum)) current_hum = 0.0;

        if (!is_maintaining && current_temp >= target_setpoint) {
            is_maintaining = true;
            // The initial approach is complete.
            // Unlock 30% power to reduce undershoots.
            incubatorPID.setOutputLimits(30.0, 90.0);
            Serial.println("[SYSTEM] Target reached. Heater ceiling raised to 30%.");
        }

        // Compute PID
        double heater_effort = 0.0;
        double cooler_effort = 0.0;
        incubatorPID.compute(target_setpoint, current_temp, dt, heater_effort, cooler_effort);

        // Convert 0-100% effort to 0-255 8-bit PWM
        int heater_pwm_8bit = (int)(heater_effort * 2.55);
        int cooler_pwm_8bit = (int)(cooler_effort * 2.55);

        analogWrite(PTC_RPWM, heater_pwm_8bit);
        analogWrite(PELTIER_PIN, cooler_pwm_8bit);

        // Send Telemetry formatted for the Python Plotter
        Serial.printf("%.2f,%.2f,%.2f,%.1f,%.1f\n", target_setpoint, current_temp, current_hum, heater_effort, cooler_effort);
    }
}