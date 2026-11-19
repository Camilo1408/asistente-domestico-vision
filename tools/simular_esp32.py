#!/usr/bin/env python3
"""Simula el ESP32 publicando el JSON del contrato (prueba del frente B sin hardware).

Ejemplos:
  python3 simular_esp32.py --host 10.42.0.1 -u asistente -p CLAVE --escena cocina_basica
  python3 simular_esp32.py --host localhost -u asistente -p CLAVE --escena cocina_basica --ruido --cada 1
Requiere: pip install paho-mqtt   (o usar mosquitto_pub, ver README)
"""
import argparse
import json
import random
import time

import paho.mqtt.client as mqtt

CLASES = ["manzana", "tomate", "huevo", "limon", "zanahoria", "leche", "taza", "botella", "libro", "zapato"]
ESCENAS = {
    "vacia": {},
    "cocina_basica": {"tomate": 3, "huevo": 2, "leche": 1},
    "cocina_llena": {"manzana": 2, "tomate": 3, "huevo": 6, "limon": 1, "zanahoria": 4, "leche": 1},
    "sin_huevos": {"tomate": 3, "leche": 1},
    "sin_leche": {"tomate": 3, "huevo": 4},
    "cuarto_desorden": {"taza": 3, "botella": 2, "libro": 4, "zapato": 2},
    "cuarto_ordenado": {"libro": 2},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("-u", "--user")
    ap.add_argument("-p", "--password")
    ap.add_argument("--escena", default="cocina_basica", choices=ESCENAS)
    ap.add_argument("--cada", type=float, default=5, help="segundos entre mensajes")
    ap.add_argument("--n", type=int, default=0, help="cantidad de mensajes (0 = infinito)")
    ap.add_argument("--ruido", action="store_true", help="simula fluctuación de FOMO (+-1 ocasional)")
    a = ap.parse_args()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if a.user:
        c.username_pw_set(a.user, a.password)
    c.connect(a.host, a.port)
    c.loop_start()
    i = 0
    while a.n == 0 or i < a.n:
        conteo = {k: ESCENAS[a.escena].get(k, 0) for k in CLASES}
        if a.ruido:
            for k in conteo:
                if random.random() < 0.15:
                    conteo[k] = max(0, conteo[k] + random.choice([-1, 1]))
        msg = {"conteo": conteo, "latencia_ms": random.randint(100, 160), "umbral": 0.6}
        c.publish("casa/camara1/detecciones", json.dumps(msg))
        print(json.dumps(msg))
        i += 1
        time.sleep(a.cada)
    c.loop_stop()


if __name__ == "__main__":
    main()
