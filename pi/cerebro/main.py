"""Servicio cerebro: MQTT <-> estabilizador <-> SQLite <-> Ollama.

Tópicos (ver docs/contrato.md):
  entra  casa/<camara>/detecciones (ESP32 FOMO o servicio vision), casa/asistente/modo,
         casa/asistente/camara (cámara activa), casa/asistente/pedir,
         casa/asistente/auto (ajustes de sugerencias automáticas, JSON)
  sale   casa/<camara>/inventario y casa/inventario (= cámara activa) (retain),
         casa/asistente/respuesta, casa/asistente/estado, casa/asistente/historial,
         casa/asistente/auto/estado
"""
import json
import logging
import os
import threading
import time

import paho.mqtt.client as mqtt
import requests

from logica import AutoSugerencias, Estabilizador, Historial, Sugerencias
from prompts import CLASES, CLASES_POR_MODO, MENSAJE_SIN_OBJETOS, construir_prompt, faltantes

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("MODEL", "asistente")
DB_PATH = os.getenv("DB_PATH", "/data/historial.db")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))
VENTANA = int(os.getenv("VENTANA_MEDIANA", "5"))  # lecturas para estabilizar (3 = más rápido)

T_DETECCIONES = "casa/+/detecciones"
T_INVENTARIO = "casa/inventario"
T_MODO = "casa/asistente/modo"
T_CAMARA = "casa/asistente/camara"
T_PEDIR = "casa/asistente/pedir"
T_RESPUESTA = "casa/asistente/respuesta"
T_ESTADO = "casa/asistente/estado"
T_AUTO = "casa/asistente/auto"
T_AUTO_ESTADO = "casa/asistente/auto/estado"
T_HISTORIAL = "casa/asistente/historial"
REVISION_AUTO_S = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cerebro")

estabs = {}            # cámara -> Estabilizador (mediana de VENTANA lecturas por cámara)
ultimo_inv = {}        # cámara -> último inventario publicado (json)
historial = Historial(DB_PATH)
sugerencias = Sugerencias(historial.db)
auto = AutoSugerencias(CLASES_POR_MODO)
modo = "cocina"
camara_activa = os.getenv("CAMARA_INICIAL", "camara1")
ocupado = threading.Lock()  # una sola consulta al LLM a la vez


def nombre_valido(cam: str) -> bool:
    return bool(cam) and cam != "asistente" and cam.replace("_", "").isalnum()


def inventario_activo():
    e = estabs.get(camara_activa)
    return e.estable if e else None


def publicar_inventario_activo(client):
    inv = inventario_activo()
    client.publish(T_INVENTARIO, json.dumps(inv if inv is not None else {}, sort_keys=True), retain=True)


def consultar_ollama(prompt: str) -> str:
    r = requests.post(f"{OLLAMA_URL}/api/generate",
                      json={"model": MODEL, "prompt": prompt, "stream": False, "keep_alive": "30m"},
                      timeout=OLLAMA_TIMEOUT)
    r.raise_for_status()
    return r.json()["response"].strip()


def publicar_respuesta(client, texto: str, origen: str, modo_resp: str | None = None):
    client.publish(T_RESPUESTA, json.dumps(
        {"texto": texto, "ts": int(time.time()), "modo": modo_resp or modo, "origen": origen,
         "camara": camara_activa}, ensure_ascii=False), retain=True)


def publicar_historial(client):
    items = sugerencias.ultimas(5)
    for it in items:
        it["hora"] = time.strftime("%H:%M", time.localtime(it["ts"]))
        if len(it["texto"]) > 400:
            it["texto"] = it["texto"][:400].rsplit(" ", 1)[0] + "…"
    client.publish(T_HISTORIAL, json.dumps({"n": len(items), "items": items}, ensure_ascii=False), retain=True)


def atender_pedido(client, origen: str, modo_pedido: str | None = None) -> bool:
    """Genera una sugerencia con el LLM. Devuelve True si se publicó una respuesta del modelo."""
    if not ocupado.acquire(blocking=False):
        log.info("Consulta ignorada: ya hay una en curso")
        return False
    modo = modo_pedido or globals()["modo"]  # el automático elige su propio modo
    try:
        client.publish(T_ESTADO, "pensando", retain=True)
        inv = inventario_activo()
        if inv is None:
            publicar_respuesta(client, f"Aún no he recibido lecturas de la cámara '{camara_activa}'.", origen, modo)
            return False
        mas_antiguo = None
        if modo == "cocina":  # el historial guarda "<camara>/<clase>"
            pref = {f"{camara_activa}/{c}": n for c, n in inv.items()}
            m = historial.mas_antiguo(pref, [f"{camara_activa}/{c}" for c in CLASES_POR_MODO["cocina"]])
            mas_antiguo = m.split("/", 1)[1] if m else None
        prompt = construir_prompt(modo, inv, mas_antiguo)
        if prompt is None:
            publicar_respuesta(client, MENSAJE_SIN_OBJETOS[modo], origen, modo)
            return False
        if origen == "resumen" and modo == "cocina":
            f = faltantes(inv)
            if f:
                prompt += "\nAdemás, indica al final qué ingredientes faltan: " + ", ".join(f) + "."
        t0 = time.time()
        try:
            texto = consultar_ollama(prompt)
        except Exception as e:  # red, timeout, modelo no creado...
            log.error("Ollama falló: %s", e)
            if origen == "auto":
                return False  # el automático no reemplaza la sugerencia vigente por un error
            publicar_respuesta(client, "No pude generar la sugerencia (el modelo no respondió). Intenta de nuevo.",
                               origen, modo)
            return False
        log.info("Respuesta (%s, %s) en %.1f s", modo, origen, time.time() - t0)
        publicar_respuesta(client, texto, origen, modo)
        sugerencias.guardar(camara_activa, modo, origen, inv, texto)
        publicar_historial(client)
        return True
    finally:
        client.publish(T_ESTADO, "listo", retain=True)
        ocupado.release()


def bucle_auto(client):
    """Cada pocos segundos revisa si toca una sugerencia automática (reglas en AutoSugerencias)."""
    while True:
        time.sleep(REVISION_AUTO_S)
        try:
            inv = inventario_activo()
            if inv is None or ocupado.locked():
                continue
            ahora = time.time()
            for m in auto.evaluar(inv, ahora):
                log.info("Sugerencia automática (%s): escena estable con suficientes objetos", m)
                if atender_pedido(client, "auto", m):
                    auto.marcar(m, inv, ahora)
                break  # una a la vez; la otra se evalúa en la próxima vuelta
            client.publish(T_AUTO_ESTADO, json.dumps(auto.estado(time.time())), retain=True)
        except Exception as e:
            log.error("Error en sugerencias automáticas: %s", e)


def procesar_deteccion(client, cam: str, payload: bytes):
    try:
        conteo = json.loads(payload)["conteo"]
        if not isinstance(conteo, dict):
            raise ValueError("conteo no es objeto")
    except (ValueError, KeyError, TypeError) as e:
        log.warning("Mensaje de detección inválido: %s", e)
        return
    estable, cambios, _ = estabs.setdefault(cam, Estabilizador(VENTANA)).actualizar(conteo)
    for clase, (_, ahora) in cambios.items():
        historial.registrar(f"{cam}/{clase}", ahora)
        log.info("[%s] cambio %s -> %d", cam, clase, ahora)
    inv_json = json.dumps(estable, sort_keys=True)
    if inv_json != ultimo_inv.get(cam):
        ultimo_inv[cam] = inv_json
        client.publish(f"casa/{cam}/inventario", inv_json, retain=True)
        if cam == camara_activa:
            client.publish(T_INVENTARIO, inv_json, retain=True)


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code != 0:
        log.error("Conexión MQTT rechazada: %s", reason_code)
        return
    log.info("Conectado a MQTT %s:%s", MQTT_HOST, MQTT_PORT)
    client.subscribe([(T_DETECCIONES, 0), ("casa/asistente/#", 0)])
    client.publish(T_ESTADO, "listo", retain=True)
    publicar_historial(client)


def on_message(client, userdata, msg):
    global modo, camara_activa
    partes = msg.topic.split("/")
    if len(partes) == 3 and partes[2] == "detecciones" and nombre_valido(partes[1]):
        procesar_deteccion(client, partes[1], msg.payload)
    elif msg.topic == T_CAMARA:
        nueva = msg.payload.decode(errors="ignore").strip().lower()
        if nombre_valido(nueva) and nueva != camara_activa:
            camara_activa = nueva
            auto.reiniciar()
            log.info("Cámara activa: %s", camara_activa)
            publicar_inventario_activo(client)
    elif msg.topic == T_MODO:
        nuevo = msg.payload.decode(errors="ignore").strip().lower()
        if nuevo in CLASES_POR_MODO:
            modo = nuevo
            log.info("Modo: %s", modo)
    elif msg.topic == T_AUTO:
        try:
            auto.configurar(json.loads(msg.payload))
            log.info("Sugerencias automáticas: %s", auto.estado(time.time()))
        except (ValueError, TypeError) as e:
            log.warning("Ajustes automáticos inválidos: %s", e)
    elif msg.topic == T_PEDIR:
        origen = msg.payload.decode(errors="ignore").strip().lower() or "boton"
        threading.Thread(target=atender_pedido, args=(client, origen), daemon=True).start()


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(1, 30)
    while True:  # esperar a que Mosquitto esté listo
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            break
        except OSError as e:
            log.warning("MQTT no disponible (%s), reintento en 3 s", e)
            time.sleep(3)
    threading.Thread(target=bucle_auto, args=(client,), daemon=True).start()
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
