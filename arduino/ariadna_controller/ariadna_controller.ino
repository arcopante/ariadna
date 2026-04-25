// =============================================================
//  ariadna_controller.ino
//  ARIADNA — Asistente Robótico Inteligente Autónomo de
//            Detección, Navegación y Aprendizaje
//
//  Controladora Arduino para robot Makeblock (Ranger / anterior)
//  Protocolo serie ASCII con Odroid-C2
//
//  Tramas recibidas (Odroid → Arduino):
//    CMD:MOVE:<izq>:<der>\n    (-255..255 cada motor)
//    CMD:TURN:<izq>:<der>\n
//    CMD:STOP\n
//    CMD:PING\n
//
//  Tramas enviadas (Arduino → Odroid):
//    ACK:<cmd>:OK\n
//    NACK:<cmd>:ERR\n
//    TEL:US:<cm>:<ok|err>\n          ultrasonidos
//    TEL:ENC:<tics_izq>:<tics_der>\n encoders
//    TEL:BAT:<mv>\n                  batería en mV
// =============================================================

#include <MeOrion.h>   // Librería Makeblock — ajusta si usas otra placa

// ── Pines y objetos hardware ──────────────────────────────────
MeDCMotor motorIzq(M1);
MeDCMotor motorDer(M2);
MeUltrasonicSensor sonar(PORT_3);

// Si tu placa tiene encoders, actívalos:
// MeEncoderOnBoard encoderIzq(SLOT1);
// MeEncoderOnBoard encoderDer(SLOT2);

// ── Configuración watchdog ────────────────────────────────────
const unsigned long WATCHDOG_MS = 500;   // Para si no llega CMD en 500 ms
unsigned long ultimoComando = 0;

// ── Telemetría ────────────────────────────────────────────────
const unsigned long TEL_INTERVALO_MS = 100;  // Enviar telemetría cada 100 ms
unsigned long ultimaTelemetria = 0;

// ── Buffer serie ──────────────────────────────────────────────
const uint8_t BUF_SIZE = 64;
char buf[BUF_SIZE];
uint8_t bufIdx = 0;

// ── Estado motores ────────────────────────────────────────────
int velIzq = 0;
int velDer = 0;

// =============================================================
void setup() {
  Serial.begin(115200);
  motorIzq.stop();
  motorDer.stop();
  Serial.println("ARIADNA:BOOT:OK");
}

// =============================================================
void loop() {
  leerSerial();
  watchdog();
  enviarTelemetria();
}

// ── Leer bytes del serial y procesar al llegar \n ─────────────
void leerSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (bufIdx > 0) {
        buf[bufIdx] = '\0';
        procesarTrama(buf);
        bufIdx = 0;
      }
    } else if (bufIdx < BUF_SIZE - 1) {
      buf[bufIdx++] = c;
    }
  }
}

// ── Parsear y ejecutar trama ──────────────────────────────────
void procesarTrama(char* trama) {
  // Tokenizar por ':'
  char* tokens[6];
  uint8_t n = 0;
  char copia[BUF_SIZE];
  strncpy(copia, trama, BUF_SIZE);

  char* tok = strtok(copia, ":");
  while (tok && n < 6) {
    tokens[n++] = tok;
    tok = strtok(NULL, ":");
  }

  if (n < 2) { Serial.println("NACK:PARSE:ERR"); return; }

  // Solo procesamos tramas CMD
  if (strcmp(tokens[0], "CMD") != 0) return;

  ultimoComando = millis();  // Resetear watchdog en cualquier CMD válido

  if (strcmp(tokens[1], "MOVE") == 0 && n >= 4) {
    velIzq = constrain(atoi(tokens[2]), -255, 255);
    velDer = constrain(atoi(tokens[3]), -255, 255);
    aplicarMotores();
    Serial.println("ACK:MOVE:OK");

  } else if (strcmp(tokens[1], "TURN") == 0 && n >= 4) {
    velIzq = constrain(atoi(tokens[2]), -255, 255);
    velDer = constrain(atoi(tokens[3]), -255, 255);
    aplicarMotores();
    Serial.println("ACK:TURN:OK");

  } else if (strcmp(tokens[1], "STOP") == 0) {
    pararMotores();
    Serial.println("ACK:STOP:OK");

  } else if (strcmp(tokens[1], "PING") == 0) {
    Serial.println("ACK:PING:OK");

  } else {
    Serial.print("NACK:");
    Serial.print(tokens[1]);
    Serial.println(":ERR");
  }
}

// ── Aplicar velocidades a los motores ─────────────────────────
void aplicarMotores() {
  // Makeblock: run(velocidad) acepta -255..255
  // M1/M2 pueden estar invertidos según el cableado; cambia el signo si gira al revés
  motorIzq.run(velIzq);
  motorDer.run(-velDer);  // Motor derecho suele estar invertido físicamente
}

void pararMotores() {
  velIzq = 0;
  velDer = 0;
  motorIzq.stop();
  motorDer.stop();
}

// ── Watchdog: parar si no llega CMD ──────────────────────────
void watchdog() {
  if (millis() - ultimoComando > WATCHDOG_MS && ultimoComando > 0) {
    pararMotores();
    // Reportar solo una vez (reset al recibir siguiente CMD)
    if (velIzq != 0 || velDer != 0) {
      Serial.println("TEL:WDG:TIMEOUT");
    }
  }
}

// ── Enviar telemetría periódica ───────────────────────────────
void enviarTelemetria() {
  if (millis() - ultimaTelemetria < TEL_INTERVALO_MS) return;
  ultimaTelemetria = millis();

  // Ultrasonidos
  float distancia = sonar.distanceCm();
  if (distancia > 0 && distancia < 400) {
    Serial.print("TEL:US:");
    Serial.print((int)distancia);
    Serial.println(":OK");
  } else {
    Serial.println("TEL:US:0:ERR");
  }

  // Batería (pin analógico A6 en Makeblock Orion — ajusta si es distinto)
  // La Makeblock Orion tiene un divisor de tensión: Vbat = (A6/1023)*5*3.3
  int raw = analogRead(A6);
  int mv = (int)((raw / 1023.0) * 5000.0 * 3.3);
  Serial.print("TEL:BAT:");
  Serial.println(mv);

  // Encoders (descomenta si tienes encoders conectados)
  // Serial.print("TEL:ENC:");
  // Serial.print(encoderIzq.getCounts());
  // Serial.print(":");
  // Serial.println(encoderDer.getCounts());
}
