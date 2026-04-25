# ARIADNA
### Asistente Robótico Inteligente Autónomo de Detección, Navegación y Aprendizaje

[![CI](https://github.com/TU_USUARIO/ariadna-robot/actions/workflows/ci.yml/badge.svg)](https://github.com/TU_USUARIO/ariadna-robot/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

Proyecto de investigación abierto sobre **IA en entornos de mundo real** con hardware accesible.
ARIADNA es un robot Makeblock (Ranger / generación anterior) con cerebro Odroid-C2 y controladora
Arduino, capaz de percibir su entorno, razonar con un LLM y actuar de forma autónoma.

El nombre viene de la mitología griega: Ariadna guiaba con su hilo en el laberinto.
Aquí el hilo es la IA que conecta percepción, memoria y acción en el mundo real.

> 🚧 **Proyecto en desarrollo activo** — documentando el proceso conforme avanzamos.
> Si tienes el mismo hardware o hardware similar, ¡únete!

## ¿Qué hace este robot?

- Detecta objetos en tiempo real con **YOLOv8n** (~10 fps en ARM sin GPU)
- Razona con **Claude** (API de Anthropic) para decidir qué hacer cada pocos segundos
- Evita obstáculos de forma reactiva con ultrasonidos
- Guarda memoria de lo que ha visto usando **SQLite + ChromaDB** (búsqueda semántica)
- Arquitectura modular con **ZeroMQ** — cada módulo es un proceso independiente

## Hardware necesario

| Componente | Modelo usado | Alternativas compatibles |
|---|---|---|
| Robot base | Makeblock Ranger (gen. anterior) | mBot, mBot2 |
| Cerebro (SBC) | Odroid-C2 | Raspberry Pi 4/5, Jetson Nano |
| Controladora | Arduino Uno (integrado en Makeblock) | Arduino Mega |
| Cámara | Cámara USB genérica | Módulo CSI compatible |

---

## Estructura del proyecto

```
ariadna/
├── arduino/
│   └── robot_controller/
│       └── robot_controller.ino   ← Firmware Arduino
├── odroid/
│   ├── hal/
│   │   ├── serial_driver.py       ← Comunicación Arduino ↔ Odroid
│   │   └── camera_driver.py       ← Captura de cámara
│   ├── modules/
│   │   ├── vision_module.py       ← Detección de objetos (YOLOv8n)
│   │   └── memory_module.py       ← Memoria SQLite + ChromaDB
│   └── brain/
│       └── planner.py             ← Cerebro IA (FSM + LLM)
├── tools/
│   └── test_serial.py             ← Prueba interactiva del protocolo serie
├── launch.py                      ← Arranque de todos los módulos
└── requirements.txt
```

---

## Protocolo serie (Arduino ↔ Odroid)

**Configuración:** 115200 baud, 8N1, texto ASCII, una trama por línea `\n`

| Dirección         | Trama                          | Descripción              |
|-------------------|--------------------------------|--------------------------|
| Odroid → Arduino  | `CMD:MOVE:<izq>:<der>\n`       | Mover motores (-255..255)|
| Odroid → Arduino  | `CMD:TURN:<izq>:<der>\n`       | Girar                    |
| Odroid → Arduino  | `CMD:STOP\n`                   | Parar                    |
| Odroid → Arduino  | `CMD:PING\n`                   | Keepalive                |
| Arduino → Odroid  | `ACK:<cmd>:OK\n`               | Confirmación             |
| Arduino → Odroid  | `TEL:US:<cm>:<ok\|err>\n`      | Ultrasonidos             |
| Arduino → Odroid  | `TEL:BAT:<mv>\n`               | Batería en mV            |
| Arduino → Odroid  | `TEL:WDG:TIMEOUT\n`            | Watchdog disparado       |

**Watchdog Arduino:** si no llega ningún CMD en 500ms, los motores se paran automáticamente.

---

## Bus ZeroMQ (entre módulos del Odroid)

| Puerto | Dirección      | Topic                  | Contenido                   |
|--------|----------------|------------------------|-----------------------------|
| 5555   | serial → todos | `/sensors/us`          | `{"cm": 24, "ok": true}`    |
| 5555   | serial → todos | `/sensors/bat`         | `{"mv": 7800}`              |
| 5556   | planner → serial| `/cmd`                | `{"accion": "MOVE", ...}`   |
| 5557   | camara → todos  | `/camera/frame`       | JPEG bytes                  |
| 5558   | vision → todos  | `/vision/detections`  | Lista de objetos detectados |

---

## Instalación en el Odroid-C2

```bash
# 1. Sistema operativo
# Flashear Ubuntu 22.04 ARM64 desde https://wiki.odroid.com/odroid-c2

# 2. Dependencias del sistema
sudo apt update
sudo apt install python3-pip python3-dev libopencv-dev v4l-utils

# 3. Dependencias Python
pip install -r requirements.txt

# 4. Variable de entorno para el LLM
export ANTHROPIC_API_KEY="sk-ant-..."
# (añadir al ~/.bashrc para que persista)

# 5. Permisos del puerto serie
sudo usermod -a -G dialout $USER
# (cerrar sesión y volver a entrar)
```

## Instalación del firmware Arduino

1. Abrir `arduino/robot_controller/robot_controller.ino` en Arduino IDE
2. Instalar librería **Makeblock** desde el gestor de librerías
3. Seleccionar placa: **Arduino Uno** (o la que corresponda a tu Makeblock)
4. Subir el sketch

---

## Arranque

```bash
# Probar conexión serie primero (sin el resto del sistema)
python3 tools/test_serial.py

# Arrancar todo el sistema
python3 odroid/launch.py

# Sin LLM (modo sensores/visión solamente)
python3 odroid/launch.py --sin-llm

# Solo driver serie (para debugging)
python3 odroid/launch.py --test-serial
```

---

## Orden de pruebas recomendado

1. **Arduino solo:** abrir Monitor Serie del IDE, verificar que llegan tramas `TEL:US:...`
2. **Prueba serie:** `python3 tools/test_serial.py` → probar `ping`, `move 100 100`, `stop`
3. **HAL completo:** `python3 odroid/launch.py --sin-llm` → verificar logs de visión
4. **Sistema completo:** `python3 odroid/launch.py` → el robot empieza a explorar

---

## Notas de hardware

- Motor derecho invertido por defecto en la librería Makeblock: si gira al revés, cambiar el signo en `aplicarMotores()` del firmware.
- Pin de batería: `A6` en Makeblock Orion con divisor de tensión x3.3. Ajustar si la placa es diferente.
- Cámara: `/dev/video0` por defecto. Comprobar con `v4l2-ctl --list-devices`.
- Puerto serie: `/dev/ttyUSB0` por defecto. Puede ser `/dev/ttyACM0` según el cable.

---

## Roadmap

- [x] Arquitectura base (HAL + bus ZeroMQ + cerebro FSM/LLM)
- [x] Protocolo serie Arduino ↔ Odroid
- [x] Detección de objetos con YOLOv8n
- [x] Memoria SQLite + ChromaDB
- [ ] Módulo de voz (Whisper tiny + TTS)
- [ ] Navegación con mapa (SLAM ligero)
- [ ] Soporte Raspberry Pi 4/5
- [ ] Dashboard web de monitorización en tiempo real
- [ ] Modo aprendizaje por demostración

## Contribuir

Mira [CONTRIBUTING.md](CONTRIBUTING.md) para el flujo de trabajo con Git,
convenciones de commits y cómo reportar bugs.

## Licencia

[MIT](LICENSE) — libre para usar, modificar y compartir.
