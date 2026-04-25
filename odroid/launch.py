#!/usr/bin/env python3
"""
launch.py
ARIADNA — arranca todos los módulos en procesos independientes.

Uso:
  python3 launch.py               # Arranca todo
  python3 launch.py --sin-llm     # Sin cerebro LLM (modo sensor/visión solo)
  python3 launch.py --test-serial # Solo el driver serie, para probar conexión Arduino

Cada módulo corre en su propio proceso. Si uno muere, los demás siguen vivos.
El script captura SIGINT (Ctrl+C) y para todos los procesos limpiamente.
"""

import subprocess
import sys
import os
import time
import signal
import argparse
import logging

logger = logging.getLogger("launch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [launch] %(message)s")

BASE  = os.path.dirname(os.path.abspath(__file__))
ODROID = os.path.join(BASE, "odroid")

MODULOS = {
    "serial":  [sys.executable, os.path.join(ODROID, "hal/serial_driver.py")],
    "camara":  [sys.executable, os.path.join(ODROID, "hal/camera_driver.py")],
    "vision":  [sys.executable, os.path.join(ODROID, "modules/vision_module.py")],
    "memoria": [sys.executable, os.path.join(ODROID, "modules/memory_module.py")],
    "planner": [sys.executable, os.path.join(ODROID, "brain/planner.py")],
}

procesos = {}


def arrancar(nombre, cmd):
    env = os.environ.copy()
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    procesos[nombre] = proc
    logger.info(f"[{nombre}] arrancado (PID {proc.pid})")
    return proc


def parar_todo():
    logger.info("Parando todos los módulos...")
    for nombre, proc in procesos.items():
        if proc.poll() is None:
            proc.terminate()
            logger.info(f"[{nombre}] terminado")
    time.sleep(1)
    for proc in procesos.values():
        if proc.poll() is None:
            proc.kill()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin-llm",     action="store_true")
    parser.add_argument("--test-serial", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGINT,  lambda s, f: (parar_todo(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (parar_todo(), sys.exit(0)))

    # Verificar clave API si vamos a usar el LLM
    if not args.sin_llm and not args.test_serial:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            logger.error("Falta ANTHROPIC_API_KEY en el entorno. Exporta la variable o usa --sin-llm")
            sys.exit(1)

    # Decidir qué módulos arrancar
    a_arrancar = ["serial"]
    if not args.test_serial:
        a_arrancar += ["camara", "vision", "memoria"]
        if not args.sin_llm:
            a_arrancar.append("planner")

    # Arrancar con pequeño retardo entre módulos para dejar que ZMQ se enlace
    for nombre in a_arrancar:
        arrancar(nombre, MODULOS[nombre])
        time.sleep(0.8)

    logger.info(f"ARIADNA en línea: {', '.join(a_arrancar)}")
    logger.info("Ctrl+C para apagar ARIADNA")

    # Monitorizar procesos y reiniciar si mueren inesperadamente
    while True:
        time.sleep(5)
        for nombre in a_arrancar:
            proc = procesos.get(nombre)
            if proc and proc.poll() is not None:
                logger.warning(f"[{nombre}] murió (código {proc.returncode}) — reiniciando")
                time.sleep(1)
                arrancar(nombre, MODULOS[nombre])


if __name__ == "__main__":
    main()
