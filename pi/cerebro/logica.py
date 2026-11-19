"""Lógica pura del cerebro (sin MQTT ni red) para poder probarla fácilmente."""
import sqlite3
import statistics
import time
from collections import deque

from prompts import CLASES


class Estabilizador:
    """Mediana de las últimas N lecturas por clase (FOMO fluctúa entre frames)."""

    def __init__(self, ventana: int = 5):
        self.hist = {c: deque(maxlen=ventana) for c in CLASES}
        self.estable = None  # dict clase -> int, None hasta la primera lectura

    def actualizar(self, conteo: dict):
        """Procesa una lectura. Devuelve (estable, cambios) donde cambios es {clase: (antes, ahora)}."""
        for clase in CLASES:
            try:
                valor = max(0, int(conteo.get(clase, 0)))
            except (TypeError, ValueError):
                valor = 0
            self.hist[clase].append(valor)
        nuevo = {c: int(statistics.median_low(self.hist[c])) for c in CLASES}
        primera = self.estable is None
        anterior = {c: 0 for c in CLASES} if primera else self.estable
        cambios = {c: (anterior[c], nuevo[c]) for c in CLASES if nuevo[c] != anterior[c]}
        self.estable = nuevo
        return nuevo, cambios, primera


class Historial:
    """Historial de cambios de cantidad en SQLite (objeto, cantidad, timestamp)."""

    def __init__(self, ruta: str):
        self.db = sqlite3.connect(ruta, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cambios ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, objeto TEXT NOT NULL, "
            "cantidad INTEGER NOT NULL, ts REAL NOT NULL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_obj ON cambios(objeto, id)")
        self.db.commit()

    def registrar(self, objeto: str, cantidad: int, ts: float | None = None):
        self.db.execute("INSERT INTO cambios(objeto, cantidad, ts) VALUES (?,?,?)",
                        (objeto, int(cantidad), ts if ts is not None else time.time()))
        self.db.commit()

    def dias_en_inventario(self, objeto: str, ahora: float | None = None):
        """Días desde que el objeto reapareció (último paso de 0 a >0). None si no está presente."""
        ahora = ahora if ahora is not None else time.time()
        ultimo = self.db.execute(
            "SELECT cantidad FROM cambios WHERE objeto=? ORDER BY id DESC LIMIT 1", (objeto,)).fetchone()
        if not ultimo or ultimo[0] <= 0:
            return None
        cero = self.db.execute(
            "SELECT id FROM cambios WHERE objeto=? AND cantidad=0 ORDER BY id DESC LIMIT 1", (objeto,)).fetchone()
        desde = cero[0] if cero else 0
        fila = self.db.execute(
            "SELECT ts FROM cambios WHERE objeto=? AND cantidad>0 AND id>? ORDER BY id ASC LIMIT 1",
            (objeto, desde)).fetchone()
        return (ahora - fila[0]) / 86400 if fila else None

    def mas_antiguo(self, inventario: dict, clases: list, ahora: float | None = None):
        """Ingrediente presente que lleva más días (función 'Úsalo pronto'). None si no hay datos."""
        mejor, dias_mejor = None, -1.0
        for c in clases:
            if int(inventario.get(c, 0)) <= 0:
                continue
            d = self.dias_en_inventario(c, ahora)
            if d is not None and d > dias_mejor:
                mejor, dias_mejor = c, d
        return mejor


class Sugerencias:
    """Historial de sugerencias del asistente en SQLite (para el dashboard y el informe)."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sugerencias ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, camara TEXT, modo TEXT, "
            "origen TEXT, inventario TEXT, texto TEXT)")
        self.db.commit()

    def guardar(self, camara: str, modo: str, origen: str, inventario: dict, texto: str, ts: float | None = None):
        import json
        self.db.execute(
            "INSERT INTO sugerencias(ts, camara, modo, origen, inventario, texto) VALUES (?,?,?,?,?,?)",
            (ts if ts is not None else time.time(), camara, modo, origen,
             json.dumps(inventario, sort_keys=True), texto))
        self.db.commit()

    def ultimas(self, n: int = 5) -> list:
        filas = self.db.execute(
            "SELECT ts, camara, modo, origen, texto FROM sugerencias ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [{"ts": int(ts), "camara": cam, "modo": modo, "origen": origen, "texto": texto}
                for ts, cam, modo, origen, texto in filas]


class AutoSugerencias:
    """Decide cuándo el asistente sugiere por sí solo, sin cambiar a cada rato.

    Reglas por modo (cocina y cuarto se evalúan por separado):
      1. Hay suficientes objetos (min_objetos[modo]).
      2. La escena lleva `estable_s` segundos sin cambiar (no reacciona a un objeto que pasa).
      3. Pasó al menos `intervalo_s` desde la última sugerencia automática de ese modo.
      4. La escena cambió en al menos `cambio_min` objetos respecto a la última sugerencia,
         o ya pasó `recordatorio_s` (recordatorio aunque nada haya cambiado).
    La sugerencia anterior se mantiene en pantalla hasta que estas reglas permitan otra.
    """

    def __init__(self, clases_por_modo: dict):
        self.clases_por_modo = clases_por_modo
        self.activo = True
        self.min_objetos = {"cuarto": 4, "cocina": 2}
        self.intervalo_s = 600
        self.estable_s = 20
        self.cambio_min = 2
        self.recordatorio_s = 3600
        self._ultima = {}   # modo -> (ts, firma)
        self._actual = {}   # modo -> (firma, desde_ts)

    def configurar(self, cfg: dict):
        def num(clave, defecto, minimo):
            try:
                return max(minimo, float(cfg.get(clave, defecto)))
            except (TypeError, ValueError):
                return defecto
        self.activo = str(cfg.get("activo", self.activo)).lower() in ("true", "1", "on", "si", "sí")
        self.min_objetos = {"cuarto": int(num("min_cuarto", self.min_objetos["cuarto"], 1)),
                            "cocina": int(num("min_cocina", self.min_objetos["cocina"], 1))}
        self.intervalo_s = num("intervalo_min", self.intervalo_s / 60, 1) * 60
        self.estable_s = num("estable_s", self.estable_s, 0)
        self.recordatorio_s = max(self.intervalo_s, num("recordatorio_min", self.recordatorio_s / 60, 1) * 60)

    def reiniciar(self):
        """Al cambiar de cámara la escena es otra: se vuelve a esperar estabilidad."""
        self._actual.clear()

    def firma(self, inv: dict, modo: str) -> tuple:
        return tuple(max(0, int(inv.get(c, 0))) for c in self.clases_por_modo[modo])

    def evaluar(self, inv: dict, ahora: float) -> list:
        """Modos para los que toca generar una sugerencia automática ahora (el más lleno primero)."""
        listos = []
        for modo in self.clases_por_modo:
            f = self.firma(inv, modo)
            previo = self._actual.get(modo)
            if previo is None or previo[0] != f:
                self._actual[modo] = (f, ahora)
                continue
            if not self.activo or sum(f) < self.min_objetos.get(modo, 1):
                continue
            if ahora - previo[1] < self.estable_s:
                continue
            ult = self._ultima.get(modo)
            if ult:
                transcurrido = ahora - ult[0]
                if transcurrido < self.intervalo_s:
                    continue
                cambio = sum(abs(a - b) for a, b in zip(f, ult[1]))
                if cambio < self.cambio_min and transcurrido < self.recordatorio_s:
                    continue
            listos.append((sum(f), modo))
        return [m for _, m in sorted(listos, reverse=True)]

    def marcar(self, modo: str, inv: dict, ahora: float):
        self._ultima[modo] = (ahora, self.firma(inv, modo))

    def estado(self, ahora: float) -> dict:
        prox = {}
        for modo in self.clases_por_modo:
            ult = self._ultima.get(modo)
            prox[modo] = 0 if not ult else max(0, int(self.intervalo_s - (ahora - ult[0])))
        return {"activo": self.activo, "min_objetos": self.min_objetos,
                "intervalo_min": round(self.intervalo_s / 60, 1), "segundos_para_proxima": prox}
