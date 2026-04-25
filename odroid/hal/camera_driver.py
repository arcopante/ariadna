"""
hal/camera_driver.py
Captura frames de cámara USB y los publica en el bus ZeroMQ.

Formato del mensaje ZeroMQ:
  topic: b"/camera/frame"
  payload: JPEG comprimido como bytes (eficiente en IPC local)

Los módulos de visión se suscriben a este topic y decodifican el JPEG.
"""

import cv2
import zmq
import time
import threading
import logging
import numpy as np

logger = logging.getLogger(__name__)

ZMQ_PUB_ADDR  = "tcp://127.0.0.1:5557"
CAMARA_IDX    = 0          # /dev/video0
TARGET_FPS    = 10         # Suficiente para navegación; el Odroid-C2 aguanta esto
FRAME_W       = 320
FRAME_H       = 240
JPEG_QUALITY  = 80


class CameraDriver:
    def __init__(self, cam_idx=CAMARA_IDX, fps=TARGET_FPS):
        self.cam_idx  = cam_idx
        self.fps      = fps
        self._running = False
        self._cap     = None

        ctx = zmq.Context.instance()
        self._pub = ctx.socket(zmq.PUB)
        self._pub.bind(ZMQ_PUB_ADDR)
        # HWM bajo para no acumular frames viejos
        self._pub.setsockopt(zmq.SNDHWM, 2)

    def _abrir_camara(self):
        cap = cv2.VideoCapture(self.cam_idx, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Evitar buffer acumulado
        if not cap.isOpened():
            raise RuntimeError(f"No se pudo abrir /dev/video{self.cam_idx}")
        return cap

    def _bucle_captura(self):
        intervalo = 1.0 / self.fps
        ultimo    = 0.0

        while self._running:
            ahora = time.monotonic()
            if ahora - ultimo < intervalo:
                time.sleep(0.005)
                continue
            ultimo = ahora

            ret, frame = self._cap.read()
            if not ret:
                logger.warning("Frame fallido, reintentando...")
                time.sleep(0.1)
                continue

            # Comprimir a JPEG
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ok:
                self._pub.send_multipart([b"/camera/frame", buf.tobytes()])

    def start(self):
        self._cap     = self._abrir_camara()
        self._running = True
        threading.Thread(target=self._bucle_captura, daemon=True, name="camera").start()
        logger.info(f"CameraDriver arrancado ({FRAME_W}x{FRAME_H} @ {self.fps}fps)")

    def stop(self):
        self._running = False
        if self._cap:
            self._cap.release()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    drv = CameraDriver()
    drv.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        drv.stop()
