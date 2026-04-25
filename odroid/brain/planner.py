"""
brain/planner.py
ARIADNA — cerebro IA, bucle principal de planificación.

Estrategia híbrida:
  - FSM reactiva para comportamientos de seguridad (obstáculos, batería baja)
  - LLM (API de Claude) para planificación de alto nivel cada N segundos

El estado del mundo se construye leyendo el bus ZeroMQ y se resume
en texto para pasárselo al LLM. El LLM devuelve una acción en JSON.

Dependencias:
  pip install anthropic zmq

Variables de entorno:
  ANTHROPIC_API_KEY — clave de API de Anthropic
"""

import zmq
import json
import time
import logging
import threading
import os
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional
import anthropic

logger = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────
ZMQ_SENSORS_ADDR = "tcp://127.0.0.1:5555"
ZMQ_VISION_ADDR  = "tcp://127.0.0.1:5558"
ZMQ_CMD_ADDR     = "tcp://127.0.0.1:5556"   # Publicamos comandos aquí

LLM_INTERVALO_S  = 3.0    # Consultar LLM cada 3 segundos
OBSTACULO_CM     = 25     # Distancia mínima antes de frenar
BATERIA_BAJA_MV  = 6500   # ~3.25V por celda en LiPo 2S

MODELO_LLM = "claude-haiku-4-5-20251001"   # Haiku: más rápido y barato para el bucle


# ── Estado del mundo ──────────────────────────────────────────
@dataclass
class EstadoMundo:
    distancia_cm:    int   = 999
    bateria_mv:      int   = 8400
    objetos_vistos:  list  = field(default_factory=list)
    ultima_accion:   str   = "ninguna"
    timestamp:       float = field(default_factory=time.time)

    def a_texto(self) -> str:
        objetos_str = ", ".join(
            f"{o['clase']} ({o['confianza']:.0%})"
            for o in self.objetos_vistos[:5]
        ) or "ninguno"
        return (
            f"Distancia frontal: {self.distancia_cm} cm. "
            f"Batería: {self.bateria_mv} mV. "
            f"Objetos detectados: {objetos_str}. "
            f"Última acción ejecutada: {self.ultima_accion}."
        )


# ── Estados FSM ───────────────────────────────────────────────
class Estado(Enum):
    PARADO       = auto()
    EXPLORANDO   = auto()
    EVITANDO     = auto()
    SIGUIENDO    = auto()
    BATERIA_BAJA = auto()


# ── Planificador ──────────────────────────────────────────────
class Planner:
    def __init__(self):
        self.estado       = Estado.PARADO
        self.mundo        = EstadoMundo()
        self._running     = False
        self._llm_client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        ctx = zmq.Context.instance()

        # Suscriptor al bus de sensores y visión
        self._sub = ctx.socket(zmq.SUB)
        self._sub.connect(ZMQ_SENSORS_ADDR)
        self._sub.connect(ZMQ_VISION_ADDR)
        self._sub.setsockopt_string(zmq.SUBSCRIBE, "/sensors")
        self._sub.setsockopt_string(zmq.SUBSCRIBE, "/vision")

        # Publicador de comandos hacia serial_driver
        self._pub = ctx.socket(zmq.PUB)
        self._pub.bind(ZMQ_CMD_ADDR)

        self._ultimo_llm = 0.0

    # ── Enviar comando al serial_driver ───────────────────────
    def _cmd(self, accion: str, izq: int = 0, der: int = 0):
        payload = {"accion": accion, "izq": izq, "der": der}
        self._pub.send_multipart([b"/cmd", json.dumps(payload).encode()])
        self.mundo.ultima_accion = accion
        logger.info(f"CMD → {accion} izq={izq} der={der}")

    def mover(self, vel=120):   self._cmd("MOVE", vel, vel)
    def parar(self):            self._cmd("STOP")
    def girar_der(self, v=100): self._cmd("TURN", v, -v)
    def girar_izq(self, v=100): self._cmd("TURN", -v, v)

    # ── Actualizar estado del mundo desde el bus ───────────────
    def _actualizar_mundo(self):
        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)

        while self._running:
            socks = dict(poller.poll(50))
            if self._sub not in socks:
                continue

            topic_b, payload_b = self._sub.recv_multipart()
            topic   = topic_b.decode()
            payload = json.loads(payload_b)

            if topic == "/sensors/us":
                self.mundo.distancia_cm = payload.get("cm", 999)
            elif topic == "/sensors/bat":
                self.mundo.bateria_mv = payload.get("mv", 8400)
            elif topic == "/vision/detections":
                self.mundo.objetos_vistos = payload

    # ── FSM reactiva (seguridad) ───────────────────────────────
    def _paso_fsm(self):
        # Prioridad máxima: batería baja
        if self.mundo.bateria_mv < BATERIA_BAJA_MV:
            if self.estado != Estado.BATERIA_BAJA:
                logger.warning("Batería baja — parando")
                self.parar()
                self.estado = Estado.BATERIA_BAJA
            return

        # Prioridad alta: obstáculo cercano
        if self.mundo.distancia_cm < OBSTACULO_CM:
            if self.estado != Estado.EVITANDO:
                logger.info(f"Obstáculo a {self.mundo.distancia_cm}cm — evitando")
                self.parar()
                time.sleep(0.2)
                self.girar_der()
                time.sleep(0.5)
                self.estado = Estado.EVITANDO
            return

        # Si estábamos evitando y ya hay espacio, volver a explorar
        if self.estado == Estado.EVITANDO:
            self.estado = Estado.EXPLORANDO

    # ── LLM: planificación de alto nivel ──────────────────────
    def _consultar_llm(self) -> Optional[dict]:
        prompt_sistema = """Eres ARIADNA, un robot móvil autónomo (Asistente Robótico
Inteligente Autónomo de Detección, Navegación y Aprendizaje).
Recibirás el estado actual del mundo y debes decidir la siguiente acción.
Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional.

Formato de respuesta:
{
  "accion": "MOVE" | "STOP" | "TURN_LEFT" | "TURN_RIGHT" | "EXPLORE",
  "velocidad": 0-255,
  "duracion_ms": 0-2000,
  "razon": "explicación breve"
}

Reglas:
- Si hay un obstáculo a menos de 30 cm, no uses MOVE.
- Si la batería está por debajo de 6500 mV, usa STOP.
- Prefiere EXPLORE si no hay objetivos concretos.
- La velocidad recomendada para moverse es 100-150.
"""

        try:
            respuesta = self._llm_client.messages.create(
                model=MODELO_LLM,
                max_tokens=200,
                system=prompt_sistema,
                messages=[{
                    "role": "user",
                    "content": f"Estado actual: {self.mundo.a_texto()}"
                }]
            )
            texto = respuesta.content[0].text.strip()
            # Limpiar posibles bloques markdown
            if texto.startswith("```"):
                texto = texto.split("```")[1]
                if texto.startswith("json"):
                    texto = texto[4:]
            return json.loads(texto)
        except Exception as e:
            logger.warning(f"Error consultando LLM: {e}")
            return None

    def _aplicar_accion_llm(self, accion_llm: dict):
        accion    = accion_llm.get("accion", "STOP")
        velocidad = int(accion_llm.get("velocidad", 100))
        duracion  = accion_llm.get("duracion_ms", 1000) / 1000.0
        razon     = accion_llm.get("razon", "")

        logger.info(f"LLM decide: {accion} v={velocidad} dur={duracion:.1f}s — {razon}")

        if accion == "MOVE":
            self.mover(velocidad)
        elif accion == "TURN_LEFT":
            self.girar_izq(velocidad)
        elif accion == "TURN_RIGHT":
            self.girar_der(velocidad)
        elif accion in ("STOP", "EXPLORE"):
            # EXPLORE: dejar que la FSM decida en el próximo tick
            self.parar()

    # ── Bucle principal ───────────────────────────────────────
    def run(self):
        self._running = True

        # Hilo de actualización del mundo
        threading.Thread(
            target=self._actualizar_mundo,
            daemon=True, name="mundo"
        ).start()

        logger.info("ARIADNA lista — estado inicial: PARADO")
        time.sleep(1.0)  # Dejar que el bus se estabilice
        self.estado = Estado.EXPLORANDO

        while self._running:
            # 1. FSM reactiva (siempre)
            self._paso_fsm()

            # 2. LLM periódico (solo si no estamos en estado crítico)
            ahora = time.monotonic()
            if (
                self.estado not in (Estado.EVITANDO, Estado.BATERIA_BAJA)
                and ahora - self._ultimo_llm > LLM_INTERVALO_S
            ):
                accion_llm = self._consultar_llm()
                if accion_llm:
                    self._aplicar_accion_llm(accion_llm)
                self._ultimo_llm = ahora

            time.sleep(0.1)  # 10 Hz

    def stop(self):
        self._running = False
        self.parar()


# ── Punto de entrada ──────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )
    planner = Planner()
    try:
        planner.run()
    except KeyboardInterrupt:
        planner.stop()
        logger.info("ARIADNA detenida")
