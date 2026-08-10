#include <Arduino.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_NeoPixel.h>
#include <Adafruit_SHT31.h> // Librería del SHT31 añadida
#include <SPI.h>

// ==========================================
// DEFINICIÓN DE PINES
// ==========================================
#define I2C_SDA 25 // Pines I2C para el SHT31
#define I2C_SCL 26
#define ONE_WIRE_BUS 17
#define LED_PIN 16
#define NUMPIXELS 21 
#define PELTIER_PIN 27
#define PTC_EN 13
#define PTC_RPWM 14
#define PTC_LPWM 12

// ==========================================
// OBJETOS
// ==========================================
Adafruit_SHT31 sht31 = Adafruit_SHT31(); // Objeto SHT31
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature ds18b20(&oneWire);
Adafruit_NeoPixel pixels(NUMPIXELS, LED_PIN, NEO_GRB + NEO_KHZ800);

// ================= VARIABLES DE CONTROL =================
bool enPrueba = false;
String actuadorActual = ""; 
int pwmAplicado = 0;

unsigned long tiempoInicio = 0;
unsigned long ultimoMuestreo = 0;
unsigned long ultimoMinuto = 0;
const int intervaloMuestreo = 2000; // 2 segundos

float tempAgua = 0.0;
float tempAmbiente = 0.0;
float tempHaceUnMinuto = 0.0;
int contadorMinutosEstables = 0;

void detenerTodo() {
  enPrueba = false;
  analogWrite(PELTIER_PIN, 0); 
  analogWrite(PTC_RPWM, 0);
  digitalWrite(PTC_EN, LOW);
  actuadorActual = "";
  pwmAplicado = 0;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(I2C_SDA, I2C_SCL); // Iniciar bus I2C

  // 1. CONFIGURACIÓN DE PINES Y SEGURIDAD
  pinMode(PELTIER_PIN, OUTPUT);
  pinMode(PTC_EN, OUTPUT);
  pinMode(PTC_RPWM, OUTPUT);
  pinMode(PTC_LPWM, OUTPUT);

  // Todo apagado al iniciar
  detenerTodo();
  digitalWrite(PTC_LPWM, LOW);    

  // 2. INICIALIZAR SENSORES Y LED
  ds18b20.begin();
  
  if (!sht31.begin(0x44)) {
    Serial.println("INFO: SHT31 no detectado. Se mostrará 0.00 como referencia.");
  }

  pixels.begin();
  for(int i=0; i<NUMPIXELS; i++) pixels.setPixelColor(i, pixels.Color(128, 0, 0)); 
  pixels.show();

  Serial.println("INFO: Sistema Unificado Listo. Comandos: 'PTC', 'PELTIER', 'STOP'");
}

void loop() {
  // 1. ESCUCHAR COMANDOS POR SERIAL
  if (Serial.available() > 0) {
    String comando = Serial.readStringUntil('\n');
    comando.trim();

    if (comando == "PTC" && !enPrueba) {
      enPrueba = true;
      actuadorActual = "PTC";
      pwmAplicado = 178; // PWM del PTC
      
      tiempoInicio = millis();
      ultimoMuestreo = millis();
      ultimoMinuto = millis();
      
      digitalWrite(PTC_EN, HIGH);
      analogWrite(PTC_RPWM, pwmAplicado); 
      ds18b20.requestTemperatures();
      tempHaceUnMinuto = ds18b20.getTempCByIndex(0);
      Serial.println("INFO: Prueba PTC iniciada. Calentando...");
    } 
    else if (comando == "PELTIER" && !enPrueba) {
      enPrueba = true;
      actuadorActual = "PELTIER";
      pwmAplicado = 204; // PWM del Peltier
      
      tiempoInicio = millis();
      ultimoMuestreo = millis();
      ultimoMinuto = millis();
      
      analogWrite(PELTIER_PIN, pwmAplicado); 
      
      ds18b20.requestTemperatures();
      tempHaceUnMinuto = ds18b20.getTempCByIndex(0);
      Serial.println("INFO: Prueba PELTIER iniciada...");
    }
    else if (comando == "STOP") {
      detenerTodo();
      Serial.println("INFO: Sistema detenido manualmente. Todo apagado.");
    }
  }

  // 2. RUTINA DE TOMA DE DATOS
  if (enPrueba) {
    if (millis() - ultimoMuestreo >= intervaloMuestreo) {
      ultimoMuestreo = millis();
      
      // Lectura de ambos sensores
      ds18b20.requestTemperatures();
      tempAgua = ds18b20.getTempCByIndex(0);
      
      tempAmbiente = sht31.readTemperature();
      if (isnan(tempAmbiente)) tempAmbiente = 0.0;
      
      unsigned long tiempoSec = (millis() - tiempoInicio) / 1000;
      
      // Enviar datos para el CSV (Solo 3 datos: Tiempo, Agua, PWM)
      Serial.print("DATOS:");
      Serial.print(tiempoSec);
      Serial.print(",");
      Serial.print(tempAgua, 2);
      Serial.print(",");
      Serial.println(pwmAplicado); 

      // Enviar la temperatura ambiente como referencia visual separada
      Serial.print("AMB:");
      Serial.println(tempAmbiente, 2);
    }

    // Evaluación de estabilidad cada 60 segundos
    if (millis() - ultimoMinuto >= 60000) {
      ultimoMinuto = millis();
      float derivada = abs(tempAgua - tempHaceUnMinuto);
      
      if (derivada < 0.05) { 
        contadorMinutosEstables++;
      } else {
        contadorMinutosEstables = 0; 
      }
      
      tempHaceUnMinuto = tempAgua;

      if (contadorMinutosEstables >= 10) {
        unsigned long tiempoSec = (millis() - tiempoInicio) / 1000;
        Serial.print("ALERTA: ESTABILIDAD DE ");
        Serial.print(actuadorActual);
        Serial.print(" ALCANZADA EN ");
        Serial.print(tiempoSec);
        Serial.println(" SEGUNDOS.");
        contadorMinutosEstables = -1000; // Evitar spam
      }
    }
  }
}
