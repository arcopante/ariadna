"""
hal/serial_driver.py
ARIADNA — driver de comunicación serie entre Odroid y Arduino.

Responsabilidades:
  - Abrir y mantener el puerto serie
  - Enviar comandos con formato de protocolo
  - Recibir y parsear tramas de telemetría
  - Publicar telemetría en el bus ZeroMQ
  - Implementar watchdog (ping periódico)
"""

import serial
import threading
import time
import zmq
import logging
import json

logger = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────
SERIAL_PORT   = "/dev/ttyUSB0"
BAUD_RATE     = 115200
TIMEOUT_S     = 1.0
PING_INTERVAL = 0.3    # segundos entre PINGs de keepalive
ZMQ_PUB_ADDR  = "tcp://127.0.0.1:5555"   # publica telemetría
ZMQ_SUB_ADDR  = "tcp://127.0.0.1:5556"   # escucha comandos del planificador


class SerialDriver:
    def __init__(self, port=SERIAL_PORT, baud=BAUD_RATE):
        self.port  = port
        self.baud  = baud
        self._ser  = None
        self._lock = threading.Lock()     # para escrituras concurrentes
        self._running = False

        # ZeroMQ: publicador de telemetría
        ctx = zmq.Context.instance()
        self._pub = ctx.socket(zmq.PUB)
        self._pub.bind(ZMQ_PUB_ADDR)

        # ZeroMQ: suscriptor de comandos desde otros módulos
        self._sub = ctx.socket(zmq.SUB)
        self._sub.connect(ZMQ_SUB_ADDR)
        self._sub.setsockopt_string(zmq.SUBSCRIBE, "/cmd")

    # ── Conexión ──────────────────────────────────────────────
    def connect(self, retries=5):
        for intento in range(retries):
            try:
                self._ser = serial.Serial(
                    self.port, self.baud,
                    timeout=TIMEOUT_S,
                    write_timeout=TIMEOUT_S
                )
                time.sleep(2)  # El Arduino resetea al abrir el puerto
                logger.info(f"Puerto serie abierto: {self.port}")
                return True
            except serial.SerialException as e:
                logger.warning(f"Intento {intento+1}/{retries} fallido: {e}")
                time.sleep(2)
        logger.error("No se pudo abrir el puerto serie")
        return False

    def disconnect(self):
        self._running = False
        if self._ser and self._ser.is_open:
            self.stop()
            self._ser.close()

    # ── Envío de comandos ─────────────────────────────────────
    def _enviar(self, trama: str):
        """Envía una trama al Arduino. Thread-safe."""
        if not self._ser or not self._ser.is_open:
            logger.error("Puerto serie no abierto")
            return False
        try:
            with self._lock:
                self._ser.write((trama + "\n").encode("ascii"))
            return True
        except serial.SerialException as e:
            logger.error(f"Error al enviar '{trama}': {e}")
            return False

    def move(self, vel_izq: int, vel_der: int):
        """Mover los motores. Valores -255..255."""
        vel_izq = max(-255, min(255, int(vel_izq)))
        vel_der = max(-255, min(255, int(vel_der)))
        return self._enviar(f"CMD:MOVE:{vel_izq}:{vel_der}")

    def turn(self, vel_izq: int, vel_der: int):
        return self._enviar(f"CMD:TURN:{vel_izq}:{vel_der}")

    def stop(self):
        return self._enviar("CMD:STOP")

    def ping(self):
        return self._enviar("CMD:PING")

    # ── Recepción y parseo de telemetría ──────────────────────
    def _parsear_trama(self, linea: str):
        """Devuelve un dict con los campos de la trama, o None si es inválida."""
        linea = linea.strip()
        if not linea:
            return None
        partes = linea.split(":")
        if len(partes) < 2:
            return None

        tipo = partes[0]

        if tipo == "TEL":
            subtipo = partes[1]
            if subtipo == "US" and len(partes) >= 4:
                return {"tipo": "US", "cm": int(partes[2]), "ok": partes[3] == "OK"}
            elif subtipo == "BAT" and len(partes) >= 3:
                return {"tipo": "BAT", "mv": int(partes[2])}
            elif subtipo == "ENC" and len(partes) >= 4:
                return {"tipo": "ENC", "izq": int(partes[2]), "der": int(partes[3])}
            elif subtipo == "WDG":
                logger.warning("Arduino watchdog disparado — motores parados")
                return {"tipo": "WDG"}

        elif tipo == "ACK":
            return {"tipo": "ACK", "cmd": partes[1], "ok": True}

        elif tipo == "NACK":
            logger.warning(f"NACK recibido: {linea}")
            return {"tipo": "NACK", "cmd": partes[1]}

        elif tipo == "BOOT":
            logger.info("ARIADNA: Arduino reiniciado y listo")
            return {"tipo": "BOOT"}

        return None

    def _publicar(self, datos: dict):
        """Publica telemetría en el bus ZeroMQ."""
        topic = f"/sensors/{datos['tipo'].lower()}"
        self._pub.send_multipart([
            topic.encode(),
            json.dumps(datos).encode()
        ])

    # ── Bucle de lectura (hilo dedicado) ─────────────────────
    def _bucle_lectura(self):
        while self._running:
            try:
                if self._ser and self._ser.in_waiting:
                    linea = self._ser.readline().decode("ascii", errors="ignore")
                    datos = self._parsear_trama(linea)
                    if datos:
                        self._publicar(datos)
                        logger.debug(f"< {datos}")
                else:
                    time.sleep(0.01)
            except Exception as e:
                logger.error(f"Error en bucle de lectura: {e}")
                time.sleep(0.1)

    # ── Bucle de comandos ZMQ (hilo dedicado) ─────────────────
    def _bucle_comandos(self):
        """Escucha comandos del planificador vía ZeroMQ."""
        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)
        while self._running:
            socks = dict(poller.poll(100))
            if self._sub in socks:
                topic, payload = self._sub.recv_multipart()
                cmd = json.loads(payload)
                self._ejecutar_comando(cmd)

    def _ejecutar_comando(self, cmd: dict):
        accion = cmd.get("accion")
        if accion == "MOVE":
            self.move(cmd.get("izq", 0), cmd.get("der", 0))
        elif accion == "TURN":
            self.turn(cmd.get("izq", 0), cmd.get("der", 0))
        elif accion == "STOP":
            self.stop()

    # ── Bucle watchdog / ping ─────────────────────────────────
    def _bucle_ping(self):
        while self._running:
            self.ping()
            time.sleep(PING_INTERVAL)

    # ── Arranque ──────────────────────────────────────────────
    def start(self):
        if not self.connect():
            return False
        self._running = True
        threading.Thread(target=self._bucle_lectura,  daemon=True, name="serial-rx").start()
        threading.Thread(target=self._bucle_comandos, daemon=True, name="serial-cmd").start()
        threading.Thread(target=self._bucle_ping,     daemon=True, name="serial-ping").start()
        logger.info("SerialDriver arrancado")
        return True


# ── Punto de entrada standalone (para pruebas) ────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    drv = SerialDriver()
    if drv.start():
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            drv.disconnect()
