"""
modules/vision_module.py
Módulo de visión: recibe frames de cámara, detecta objetos con YOLOv8n,
publica resultados en el bus ZeroMQ.

Dependencias:
  pip install ultralytics opencv-python-headless zmq

El modelo YOLOv8n (~6MB) se descarga automáticamente la primera vez.
En ARM sin GPU corre a ~8-12 FPS con resolución 320x240.

Mensajes publicados en topic /vision/detections:
  [{"clase": "person", "confianza": 0.91, "bbox": [x1,y1,x2,y2]}, ...]
"""

import cv2
import zmq
import json
import time
import logging
import numpy as np
from ultralytics import YOLO

logger = logging.getLogger(__name__)

ZMQ_CAM_ADDR = "tcp://127.0.0.1:5557"   # Frames de cámara
ZMQ_PUB_ADDR = "tcp://127.0.0.1:5558"   # Detecciones publicadas
CONFIANZA_MIN = 0.45
MODELO        = "yolov8n.pt"             # Nano: más rápido, menos preciso


class VisionModule:
    def __init__(self):
        self.modelo   = None
        self._running = False

        ctx = zmq.Context.instance()

        # Suscriptor de frames
        self._sub = ctx.socket(zmq.SUB)
        self._sub.connect(ZMQ_CAM_ADDR)
        self._sub.setsockopt_string(zmq.SUBSCRIBE, "/camera/frame")
        self._sub.setsockopt(zmq.RCVHWM, 2)  # Descartar frames viejos

        # Publicador de detecciones
        self._pub = ctx.socket(zmq.PUB)
        self._pub.bind(ZMQ_PUB_ADDR)

    def _cargar_modelo(self):
        logger.info("Cargando YOLOv8n...")
        self.modelo = YOLO(MODELO)
        # Warm-up: primera inferencia es lenta, hacerla con imagen negra
        dummy = np.zeros((240, 320, 3), dtype=np.uint8)
        self.modelo(dummy, verbose=False)
        logger.info("Modelo listo")

    def _procesar_frame(self, jpeg_bytes: bytes) -> list:
        """Ejecuta YOLO sobre el frame y devuelve lista de detecciones."""
        arr   = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return []

        resultados = self.modelo(frame, conf=CONFIANZA_MIN, verbose=False)[0]
        detecciones = []

        for box in resultados.boxes:
            cls  = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
            detecciones.append({
                "clase":      self.modelo.names[cls],
                "confianza":  round(conf, 2),
                "bbox":       [x1, y1, x2, y2],
                "centro_x":   (x1 + x2) // 2,
                "centro_y":   (y1 + y2) // 2,
                "timestamp":  time.time()
            })

        return detecciones

    def run(self):
        self._cargar_modelo()
        self._running = True
        logger.info("VisionModule corriendo")

        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)

        while self._running:
            socks = dict(poller.poll(200))
            if self._sub in socks:
                topic, payload = self._sub.recv_multipart()
                dets = self._procesar_frame(payload)

                # Publicar siempre (lista vacía = sin detecciones)
                self._pub.send_multipart([
                    b"/vision/detections",
                    json.dumps(dets).encode()
                ])

                if dets:
                    clases = [d["clase"] for d in dets]
                    logger.debug(f"Detectado: {clases}")

    def stop(self):
        self._running = False


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    vm = VisionModule()
    try:
        vm.run()
    except KeyboardInterrupt:
        vm.stop()
