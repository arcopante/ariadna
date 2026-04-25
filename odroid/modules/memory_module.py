"""
modules/memory_module.py
Módulo de memoria del robot.

Dos capas:
  1. SQLite  — log de eventos con timestamp (qué vio, dónde, cuándo)
  2. ChromaDB — base de datos vectorial embebida para búsqueda semántica

La búsqueda semántica usa sentence-transformers (modelo paraphrase-MiniLM-L3-v2,
~17MB, funciona en ARM sin GPU en ~50ms por query).

Dependencias:
  pip install chromadb sentence-transformers zmq

API pública (llamada directamente desde el cerebro):
  memory.guardar_evento(tipo, descripcion, metadatos)
  memory.buscar(query, n=5)  → lista de eventos relevantes
  memory.ultimos(n=10)       → últimos N eventos
"""

import sqlite3
import json
import time
import logging
import threading
import zmq
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH      = Path("/home/odroid/ariadna/data/eventos.db")
CHROMA_DIR   = Path("/home/odroid/ariadna/data/chroma")
ZMQ_SUB_ADDR = "tcp://127.0.0.1:5555"   # Telemetría de sensores
ZMQ_VIS_ADDR = "tcp://127.0.0.1:5558"   # Detecciones de visión


class MemoryModule:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)

        self._init_sqlite()
        self._init_chroma()
        self._lock = threading.Lock()

    # ── SQLite: log estructurado ───────────────────────────────
    def _init_sqlite(self):
        self._db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS eventos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   REAL    NOT NULL,
                tipo        TEXT    NOT NULL,
                descripcion TEXT    NOT NULL,
                metadatos   TEXT    DEFAULT '{}'
            )
        """)
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_ts ON eventos(timestamp)")
        self._db.commit()
        logger.info("SQLite inicializado")

    # ── ChromaDB: búsqueda semántica ──────────────────────────
    def _init_chroma(self):
        try:
            import chromadb
            from chromadb.utils import embedding_functions
            self._chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="paraphrase-MiniLM-L3-v2"
            )
            self._coleccion = self._chroma_client.get_or_create_collection(
                name="eventos_robot",
                embedding_function=ef
            )
            self._chroma_ok = True
            logger.info("ChromaDB inicializado")
        except ImportError:
            logger.warning("ChromaDB no disponible — solo SQLite activo")
            self._chroma_ok = False

    # ── Guardar evento ────────────────────────────────────────
    def guardar_evento(self, tipo: str, descripcion: str, metadatos: dict = None):
        ts = time.time()
        meta_str = json.dumps(metadatos or {})

        with self._lock:
            cur = self._db.execute(
                "INSERT INTO eventos (timestamp, tipo, descripcion, metadatos) VALUES (?,?,?,?)",
                (ts, tipo, descripcion, meta_str)
            )
            evento_id = cur.lastrowid
            self._db.commit()

        # Indexar en ChromaDB de forma asíncrona
        if self._chroma_ok:
            threading.Thread(
                target=self._indexar_en_chroma,
                args=(evento_id, descripcion, ts, tipo, metadatos or {}),
                daemon=True
            ).start()

        logger.debug(f"Evento guardado: [{tipo}] {descripcion}")
        return evento_id

    def _indexar_en_chroma(self, eid, descripcion, ts, tipo, meta):
        try:
            self._coleccion.add(
                documents=[descripcion],
                ids=[str(eid)],
                metadatas=[{"timestamp": ts, "tipo": tipo, **meta}]
            )
        except Exception as e:
            logger.warning(f"Error indexando en ChromaDB: {e}")

    # ── Buscar eventos por semántica ──────────────────────────
    def buscar(self, query: str, n: int = 5) -> list:
        if not self._chroma_ok:
            return self.ultimos(n)
        try:
            res = self._coleccion.query(query_texts=[query], n_results=n)
            eventos = []
            for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
                eventos.append({"descripcion": doc, **meta})
            return eventos
        except Exception as e:
            logger.warning(f"Error en búsqueda semántica: {e}")
            return []

    # ── Últimos N eventos ──────────────────────────────────────
    def ultimos(self, n: int = 10) -> list:
        with self._lock:
            rows = self._db.execute(
                "SELECT timestamp, tipo, descripcion, metadatos FROM eventos ORDER BY timestamp DESC LIMIT ?",
                (n,)
            ).fetchall()
        return [
            {
                "timestamp": r[0],
                "fecha":     datetime.fromtimestamp(r[0]).isoformat(),
                "tipo":      r[1],
                "descripcion": r[2],
                "metadatos": json.loads(r[3])
            }
            for r in rows
        ]

    # ── Escuchar bus y auto-registrar eventos ─────────────────
    def run_listener(self):
        """Escucha el bus ZMQ y guarda eventos automáticamente."""
        ctx = zmq.Context.instance()
        sub = ctx.socket(zmq.SUB)
        sub.connect(ZMQ_SUB_ADDR)
        sub.connect(ZMQ_VIS_ADDR)
        sub.setsockopt_string(zmq.SUBSCRIBE, "/sensors")
        sub.setsockopt_string(zmq.SUBSCRIBE, "/vision")

        logger.info("MemoryModule escuchando el bus")
        while True:
            topic_b, payload_b = sub.recv_multipart()
            topic   = topic_b.decode()
            payload = json.loads(payload_b)

            if topic == "/sensors/us":
                if payload.get("ok") and payload.get("cm", 999) < 30:
                    self.guardar_evento(
                        "obstaculo",
                        f"Obstáculo detectado a {payload['cm']} cm",
                        {"cm": payload["cm"]}
                    )

            elif topic == "/vision/detections":
                for det in payload:
                    if det["confianza"] > 0.6:
                        self.guardar_evento(
                            "vision",
                            f"Objeto detectado: {det['clase']}",
                            {"clase": det["clase"], "confianza": det["confianza"]}
                        )


# ── Uso standalone ────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    mem = MemoryModule()
    mem.run_listener()
