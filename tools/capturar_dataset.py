#!/usr/bin/env python3
"""Captura fotos del ESP32 (/capture) para el dataset de Edge Impulse.

Mueve los objetos entre fotos (posición, cantidad, mezcla de clases).
Ejemplo (PC con Windows, misma red que la cámara):
  python tools/capturar_dataset.py --ip 192.168.1.35 --cada 3 --n 200 --carpeta dataset/cocina
Solo usa la librería estándar de Python.
"""
import argparse
import os
import time
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", required=True, help="IP de la cámara ESP32")
    ap.add_argument("--cada", type=float, default=3, help="segundos entre fotos")
    ap.add_argument("--n", type=int, default=200, help="cantidad de fotos")
    ap.add_argument("--carpeta", default="dataset")
    a = ap.parse_args()

    os.makedirs(a.carpeta, exist_ok=True)
    url = f"http://{a.ip}/capture"
    ok = 0
    print(f"Capturando {a.n} fotos de {url} en {a.carpeta}/ (Ctrl+C para parar)")
    while ok < a.n:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                datos = r.read()
            nombre = os.path.join(a.carpeta, f"img_{int(time.time() * 1000)}.jpg")
            with open(nombre, "wb") as f:
                f.write(datos)
            ok += 1
            print(f"[{ok}/{a.n}] {nombre}  ({len(datos) // 1024} KB) -> mueve los objetos")
        except Exception as e:  # cámara ocupada o red
            print("fallo:", e)
        time.sleep(a.cada)


if __name__ == "__main__":
    main()
