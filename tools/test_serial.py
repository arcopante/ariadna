#!/usr/bin/env python3
"""
tools/test_serial.py
Herramienta interactiva para probar la comunicación con el Arduino
SIN necesitar el resto del sistema arrancado.

Uso:
  python3 tools/test_serial.py
  python3 tools/test_serial.py --puerto /dev/ttyUSB1

Comandos disponibles en el prompt:
  move <izq> <der>   — mover motores (ej: move 100 100)
  turn <izq> <der>   — girar
  stop               — parar
  ping               — comprobar conexión
  mon                — monitorizar telemetría durante 10 segundos
  q / quit           — salir
"""

import serial
import time
import threading
import argparse
import sys

BAUD = 115200

def escuchar(ser, parar_evento):
    """Hilo que imprime todo lo que llega del Arduino."""
    while not parar_evento.is_set():
        try:
            if ser.in_waiting:
                linea = ser.readline().decode("ascii", errors="ignore").strip()
                if linea:
                    print(f"  ← {linea}")
            else:
                time.sleep(0.01)
        except Exception:
            break

def enviar(ser, trama):
    ser.write((trama + "\n").encode("ascii"))
    print(f"  → {trama}")
    time.sleep(0.15)  # Dar tiempo al Arduino a responder

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--puerto", default="/dev/ttyUSB0")
    args = parser.parse_args()

    print(f"Conectando a {args.puerto} @ {BAUD} baud...")
    try:
        ser = serial.Serial(args.puerto, BAUD, timeout=1)
    except serial.SerialException as e:
        print(f"Error: {e}")
        sys.exit(1)

    print("Esperando boot del Arduino (2s)...")
    time.sleep(2)

    parar = threading.Event()
    hilo  = threading.Thread(target=escuchar, args=(ser, parar), daemon=True)
    hilo.start()

    print("Listo. Escribe 'help' para ver comandos.\n")

    while True:
        try:
            entrada = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if not entrada:
            continue

        partes = entrada.split()
        cmd    = partes[0]

        if cmd in ("q", "quit", "exit"):
            enviar(ser, "CMD:STOP")
            break
        elif cmd == "help":
            print(__doc__)
        elif cmd == "ping":
            enviar(ser, "CMD:PING")
        elif cmd == "stop":
            enviar(ser, "CMD:STOP")
        elif cmd == "move" and len(partes) == 3:
            enviar(ser, f"CMD:MOVE:{partes[1]}:{partes[2]}")
        elif cmd == "turn" and len(partes) == 3:
            enviar(ser, f"CMD:TURN:{partes[1]}:{partes[2]}")
        elif cmd == "mon":
            print("Monitorizando 10 segundos (Ctrl+C para salir antes)...")
            time.sleep(10)
        else:
            print(f"Comando desconocido: {entrada}")

    parar.set()
    ser.close()
    print("Desconectado")

if __name__ == "__main__":
    main()
