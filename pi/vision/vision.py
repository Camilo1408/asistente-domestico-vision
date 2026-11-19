"""Servicio vision: cámaras IP (ESP32 /capture, app del iPhone) -> YOLO (ONNX) -> MQTT.

Por cada cámara de CAMARAS publica, con el mismo contrato que el ESP32:
  casa/<cam>/detecciones  {"conteo": {...}, "latencia_ms": n, "umbral": x, "fuente": "yolo"}
  casa/<cam>/presencia    {"personas": n, "brillo": 0-255, "ts": epoch}   (retain)
  casa/<cam>/imagen       JPEG con las detecciones dibujadas (cámara MQTT en HA)
  casa/<cam>/estado       online | offline                                (retain)
Las cámaras en SOLO_PRESENCIA (p. ej. el ESP32 con firmware FOMO) no publican detecciones,
para no duplicar el conteo que ya envía el propio ESP32.
"""
import io
import json
import logging
import os
import threading
import time

import numpy as np
import onnxruntime as ort
import paho.mqtt.client as mqtt
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from urllib.parse import unquote, urlsplit, urlunsplit
from PIL import Image, ImageDraw, ImageFont, ImageStat

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
INTERVALO = float(os.getenv("INTERVALO", "5"))      # segundos entre rondas por todas las cámaras
CONF = float(os.getenv("CONF", "0.35"))              # confianza mínima
IOU = float(os.getenv("IOU", "0.45"))
MODELO = os.getenv("MODELO", "/app/yolo.onnx")
HILOS = int(os.getenv("HILOS", "2"))
ANCHO_IMAGEN = int(os.getenv("ANCHO_IMAGEN", "640"))  # ancho de la imagen anotada publicada
# Mientras el LLM genera (casa/asistente/estado = pensando) YOLO se pausa: evita sumar dos picos
# de CPU, que con una fuente débil apagan la Raspberry Pi.
PAUSAR_CON_LLM = os.getenv("PAUSAR_CON_LLM", "1") == "1"
llm_ocupado = threading.Event()

# Clases del contrato (mismas que pi/cerebro/prompts.py)
CLASES = ["manzana", "tomate", "huevo", "limon", "zanahoria", "leche", "banano", "naranja", "brocoli",
          "taza", "botella", "libro", "zapato", "mochila", "laptop", "celular"]
# Índices COCO (YOLO preentrenado) -> nombre del contrato. tomate, huevo, leche, limon y zapato
# no existen en COCO: esas clases solo las detecta el modelo FOMO propio del ESP32.
COCO_A_CONTRATO = {
    0: "persona", 24: "mochila", 39: "botella", 41: "taza", 46: "banano", 47: "manzana",
    49: "naranja", 50: "brocoli", 51: "zanahoria", 63: "laptop", 67: "celular", 73: "libro",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vision")


def parsear_camaras(texto: str) -> dict:
    """'camara1=http://a/capture,iphone=http://b:8081/video' -> {'camara1': url, 'iphone': url}"""
    camaras = {}
    for item in filter(None, (x.strip() for x in texto.split(","))):
        nombre, _, url = item.partition("=")
        nombre = nombre.strip().lower()
        if nombre and url.strip() and nombre.replace("_", "").isalnum() and nombre != "asistente":
            camaras[nombre] = url.strip()
        else:
            log.warning("Entrada de CAMARAS inválida: %r", item)
    return camaras


def _auth(url: str):
    """Credenciales en la URL (http://usuario:clave@ip:puerto/ruta) -> (url sin credenciales, (u, c))."""
    p = urlsplit(url)
    if not p.username:
        return url, None
    host = p.hostname + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, host, p.path, p.query, p.fragment)), (unquote(p.username), unquote(p.password or ""))


def abrir(url: str, timeout=(3, 10)):
    """GET en streaming con autenticación Basic o Digest (credenciales en la URL)."""
    url, cred = _auth(url)
    r = requests.get(url, stream=True, timeout=timeout, auth=HTTPBasicAuth(*cred) if cred else None)
    if r.status_code == 401 and cred and "digest" in r.headers.get("WWW-Authenticate", "").lower():
        r.close()
        r = requests.get(url, stream=True, timeout=timeout, auth=HTTPDigestAuth(*cred))
    r.raise_for_status()
    return r


SOI, EOI = bytes([0xFF, 0xD8]), bytes([0xFF, 0xD9])  # inicio / fin de un JPEG


def cuadros_mjpeg(r):
    """Itera los cuadros JPEG de un stream MJPEG (multipart)."""
    buf = bytearray()
    # read1 (urllib3 2.x) devuelve lo que ya llegó, sin esperar a llenar el bloque -> sin retraso de cuadros
    leer = getattr(r.raw, "read1", None) or (lambda n: r.raw.read(4096))
    while True:
        chunk = leer(65536)
        if not chunk:
            break
        buf += chunk
        while True:
            i = buf.find(SOI)
            if i < 0:
                del buf[:-1]
                break
            j = buf.find(EOI, i + 2)
            if j < 0:
                if i > 0:
                    del buf[:i]
                break
            yield bytes(buf[i:j + 2])
            del buf[:j + 2]
        if len(buf) > 8_000_000:
            buf.clear()


def leer_jpeg(url: str) -> bytes:
    """Devuelve un JPEG desde una URL de foto fija o el primer cuadro de un stream MJPEG."""
    with abrir(url, timeout=(3, 8)) as r:
        if "multipart" not in r.headers.get("Content-Type", "").lower():
            return r.content
        for cuadro in cuadros_mjpeg(r):
            return cuadro
    raise ValueError("no se encontró un cuadro JPEG en el stream")


class Fuente(threading.Thread):
    """Mantiene UNA conexión abierta con la cámara y guarda el último cuadro.

    Con un stream MJPEG lee continuamente (sin reconectar cada vez); con una URL de foto fija
    la consulta cada `intervalo` s. Si la conexión se cae, reintenta con espera creciente (1 a 15 s).
    """

    def __init__(self, nombre: str, url: str, intervalo: float):
        super().__init__(daemon=True, name=f"fuente-{nombre}")
        self.nombre, self.url, self.intervalo = nombre, url, intervalo
        self._cuadro, self._t = None, 0.0
        self._lock = threading.Lock()
        self.cuadros = 0
        self.error = None

    def _guardar(self, jpeg: bytes):
        with self._lock:
            self._cuadro, self._t = jpeg, time.time()
        self.cuadros += 1

    def ultimo(self, max_edad: float):
        with self._lock:
            return self._cuadro if self._cuadro and time.time() - self._t <= max_edad else None

    def run(self):
        espera = 1
        while True:
            try:
                with abrir(self.url) as r:
                    if "multipart" in r.headers.get("Content-Type", "").lower():
                        if self.error:
                            log.info("%s: stream conectado", self.nombre)
                        self.error = None
                        for cuadro in cuadros_mjpeg(r):
                            self._guardar(cuadro)
                            espera = 1
                        raise ConnectionError("el stream terminó")
                    self._guardar(r.content)
                self.error = None
                espera = 1
                time.sleep(self.intervalo)
                continue
            except Exception as e:  # cámara apagada, app cerrada, WiFi...
                if str(e) != self.error:
                    log.warning("%s: conexión perdida (%s), reintento", self.nombre, e)
                self.error = str(e)
            time.sleep(espera)
            espera = min(espera * 2, 15)


def nms(cajas: np.ndarray, puntajes: np.ndarray, iou: float) -> list:
    orden = puntajes.argsort()[::-1]
    areas = (cajas[:, 2] - cajas[:, 0]) * (cajas[:, 3] - cajas[:, 1])
    quedan = []
    while orden.size:
        i = orden[0]
        quedan.append(int(i))
        resto = orden[1:]
        x1 = np.maximum(cajas[i, 0], cajas[resto, 0])
        y1 = np.maximum(cajas[i, 1], cajas[resto, 1])
        x2 = np.minimum(cajas[i, 2], cajas[resto, 2])
        y2 = np.minimum(cajas[i, 3], cajas[resto, 3])
        inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        orden = resto[inter / (areas[i] + areas[resto] - inter + 1e-9) < iou]
    return quedan


class Detector:
    """YOLOv8 exportado a ONNX (salida 1 x 84 x N: cx, cy, w, h + 80 puntajes COCO)."""

    def __init__(self, ruta: str, hilos: int):
        so = ort.SessionOptions()
        so.intra_op_num_threads = hilos
        so.inter_op_num_threads = 1
        self.sesion = ort.InferenceSession(ruta, so, providers=["CPUExecutionProvider"])
        self.entrada = self.sesion.get_inputs()[0]
        lado = self.entrada.shape[2]
        self.lado = lado if isinstance(lado, int) else 320

    def detectar(self, img: Image.Image) -> list:
        """Devuelve [(clase_coco, confianza, (x1, y1, x2, y2))] en coordenadas de la imagen original."""
        w, h = img.size
        s = self.lado
        r = min(s / w, s / h)
        nw, nh = max(1, round(w * r)), max(1, round(h * r))
        px, py = (s - nw) // 2, (s - nh) // 2
        lienzo = Image.new("RGB", (s, s), (114, 114, 114))
        lienzo.paste(img.resize((nw, nh), Image.BILINEAR), (px, py))
        x = np.asarray(lienzo, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        salida = self.sesion.run(None, {self.entrada.name: x})[0][0].T  # (N, 84)
        puntajes = salida[:, 4:]
        clases = puntajes.argmax(1)
        conf = puntajes.max(1)
        m = conf >= CONF
        if not m.any():
            return []
        cx, cy, bw, bh = salida[m, 0], salida[m, 1], salida[m, 2], salida[m, 3]
        cajas = np.stack([(cx - bw / 2 - px) / r, (cy - bh / 2 - py) / r,
                          (cx + bw / 2 - px) / r, (cy + bh / 2 - py) / r], axis=1)
        cajas[:, [0, 2]] = cajas[:, [0, 2]].clip(0, w)
        cajas[:, [1, 3]] = cajas[:, [1, 3]].clip(0, h)
        clases, conf = clases[m], conf[m]
        desplazadas = cajas + clases[:, None] * 10000.0  # NMS por clase
        return [(int(clases[i]), float(conf[i]), tuple(cajas[i])) for i in nms(desplazadas, conf, IOU)]


def fuente(tam: int):
    try:
        return ImageFont.load_default(size=tam)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def anotar(img: Image.Image, dets: list, texto_sup: str) -> bytes:
    img = img.copy()
    escala = ANCHO_IMAGEN / img.width if img.width > ANCHO_IMAGEN else 1.0
    if escala < 1.0:
        img = img.resize((ANCHO_IMAGEN, round(img.height * escala)), Image.BILINEAR)
    d = ImageDraw.Draw(img)
    f = fuente(16)
    for clase, conf, (x1, y1, x2, y2) in dets:
        nombre = COCO_A_CONTRATO.get(clase)
        if not nombre:
            continue
        color = (255, 80, 80) if nombre == "persona" else (60, 220, 120)
        caja = [v * escala for v in (x1, y1, x2, y2)]
        d.rectangle(caja, outline=color, width=3)
        etiqueta = f"{nombre} {conf:.0%}"
        d.rectangle([caja[0], max(0, caja[1] - 20), caja[0] + 9 * len(etiqueta), caja[1]], fill=color)
        d.text((caja[0] + 3, max(0, caja[1] - 19)), etiqueta, fill=(0, 0, 0), font=f)
    d.rectangle([0, 0, img.width, 22], fill=(0, 0, 0))
    d.text((6, 3), texto_sup, fill=(255, 255, 255), font=f)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=80)
    return out.getvalue()


def procesar(cliente, det: Detector, cam: str, jpeg: bytes, solo_presencia: bool):
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    t1 = time.time()
    dets = det.detectar(img)
    ms = int((time.time() - t1) * 1000)
    conteo = {c: 0 for c in CLASES}
    personas = 0
    for clase, _, _ in dets:
        nombre = COCO_A_CONTRATO.get(clase)
        if nombre == "persona":
            personas += 1
        elif nombre:
            conteo[nombre] += 1
    brillo = int(round(ImageStat.Stat(img.convert("L")).mean[0]))
    if not solo_presencia:
        cliente.publish(f"casa/{cam}/detecciones", json.dumps(
            {"conteo": conteo, "latencia_ms": ms, "umbral": CONF, "fuente": "yolo"}))
    cliente.publish(f"casa/{cam}/presencia", json.dumps(
        {"personas": personas, "brillo": brillo, "ts": int(time.time())}), retain=True)
    resumen = ", ".join(f"{n} {c}" for c, n in conteo.items() if n) or "sin objetos"
    cliente.publish(f"casa/{cam}/imagen", anotar(
        img, dets, f"{cam} | {resumen} | personas {personas} | brillo {brillo} | {ms} ms"))
    cliente.publish(f"casa/{cam}/estado", "online", retain=True)
    log.info("%s: %s | personas=%d brillo=%d | yolo %d ms", cam, resumen, personas, brillo, ms)


def main():
    camaras = parsear_camaras(os.getenv("CAMARAS", ""))
    solo_presencia = {c.strip().lower() for c in os.getenv("SOLO_PRESENCIA", "").split(",") if c.strip()}
    if not camaras:
        log.error("CAMARAS está vacío (ej. CAMARAS=camara1=http://IP/capture,iphone=http://IP:PUERTO/video)")
        while True:
            time.sleep(3600)
    visibles = {c: _auth(u)[0] + (" (con usuario/clave)" if _auth(u)[1] else "") for c, u in camaras.items()}
    log.info("Cámaras: %s | solo presencia: %s", visibles, solo_presencia or "-")
    det = Detector(MODELO, HILOS)
    log.info("Modelo %s cargado (entrada %dx%d)", MODELO, det.lado, det.lado)

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USER:
        cliente.username_pw_set(MQTT_USER, MQTT_PASS)
    while True:
        try:
            cliente.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            break
        except OSError as e:
            log.warning("MQTT no disponible (%s), reintento en 3 s", e)
            time.sleep(3)
    def on_message(_c, _u, msg):
        if msg.payload.decode(errors="ignore").strip() == "pensando":
            llm_ocupado.set()
        else:
            llm_ocupado.clear()

    def on_connect(c, _u, _f, rc, _p=None):
        if rc == 0 and PAUSAR_CON_LLM:
            c.subscribe("casa/asistente/estado")

    cliente.on_message = on_message
    cliente.on_connect = on_connect
    on_connect(cliente, None, None, 0)
    cliente.loop_start()

    fuentes = {cam: Fuente(cam, url, INTERVALO) for cam, url in camaras.items()}
    for f in fuentes.values():
        f.start()
    max_edad = max(10.0, 3 * INTERVALO)
    sin_imagen = set()
    time.sleep(3)  # dar tiempo a la primera conexión
    while True:
        inicio = time.time()
        if llm_ocupado.is_set():
            time.sleep(1)
            continue
        for cam, f in fuentes.items():
            jpeg = f.ultimo(max_edad)
            if jpeg is None:
                if cam not in sin_imagen:
                    log.warning("%s: sin cuadros recientes", cam)
                    sin_imagen.add(cam)
                cliente.publish(f"casa/{cam}/estado", "offline", retain=True)
                continue
            sin_imagen.discard(cam)
            try:
                procesar(cliente, det, cam, jpeg, cam in solo_presencia)
            except Exception as e:
                log.warning("%s: error procesando cuadro (%s)", cam, e)
        time.sleep(max(0.5, INTERVALO - (time.time() - inicio)))


if __name__ == "__main__":
    main()
