#!/usr/bin/env python3
"""Benchmark del LLM (prueba 6) y fidelidad con los 10 casos (prueba 7).

Usa la API de Ollama (solo librería estándar). Ejecutar en la Pi o apuntando a ella:
  python3 benchmark_llm.py --modelos qwen2.5:3b qwen2.5:1.5b gemma3:1b --salida ../docs/benchmark_llm.md
  python3 benchmark_llm.py --modelos asistente --fidelidad      # 10 casos con el modelo final

Fidelidad (automática, heurística): un caso PASA si la respuesta no menciona ninguna clase con cantidad 0
del mismo modo. Conviene revisar a mano también la calidad (campo 'esperado' de casos_prueba.json).
"""
import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pi", "cerebro"))
from prompts import CLASES_POR_MODO, construir_prompt  # noqa: E402

CASOS = os.path.join(os.path.dirname(__file__), "..", "pi", "ollama", "casos_prueba.json")
RAIZ = {"manzana": "manzana", "tomate": "tomate", "huevo": "huevo", "limon": "limon", "zanahoria": "zanahoria",
        "leche": "leche", "taza": "taza", "botella": "botella", "libro": "libro", "zapato": "zapato"}


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def generar(url, modelo, prompt):
    body = json.dumps({"model": modelo, "prompt": prompt, "stream": False, "keep_alive": "30m"}).encode()
    req = urllib.request.Request(f"{url}/api/generate", body, {"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    total = time.time() - t0
    tps = d["eval_count"] / (d["eval_duration"] / 1e9) if d.get("eval_duration") else 0
    return d["response"], tps, total


def inventos(respuesta, modo, objetos):
    txt = sin_tildes(respuesta)
    return [c for c in CLASES_POR_MODO[modo] if objetos.get(c, 0) == 0 and RAIZ[c] in txt]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--modelos", nargs="+", default=["asistente"])
    ap.add_argument("--fidelidad", action="store_true", help="correr los 10 casos")
    ap.add_argument("--salida", help="archivo .md donde guardar la tabla")
    a = ap.parse_args()

    casos = json.load(open(CASOS, encoding="utf-8"))
    filas = []
    for m in a.modelos:
        print(f"== {m} ==")
        prompt = construir_prompt("cocina", {"tomate": 3, "huevo": 2, "leche": 1})
        generar(a.url, m, "hola")  # calentar (carga el modelo en RAM)
        _, tps, total = generar(a.url, m, prompt)
        ok_vel = tps >= 3 and total <= 90
        fila = {"modelo": m, "tps": tps, "total": total, "vel_ok": ok_vel, "fid": None}
        print(f"  {tps:.1f} tok/s, {total:.1f} s  -> prueba 6: {'OK' if ok_vel else 'NO CUMPLE'}")
        if a.fidelidad:
            fieles = 0
            for c in casos:
                p = construir_prompt(c["modo"], c["objetos"])
                r, _, _ = generar(a.url, m, p)
                mal = inventos(r, c["modo"], c["objetos"])
                fieles += not mal
                print(f"  caso {c['id']:>2}: {'OK' if not mal else 'INVENTA ' + ','.join(mal)}")
            fila["fid"] = fieles
            print(f"  fidelidad: {fieles}/10 -> prueba 7: {'OK' if fieles >= 8 else 'NO CUMPLE'}")
        filas.append(fila)

    tabla = ["| Modelo | tok/s | Tiempo total (s) | Prueba 6 (≥3 tok/s y ≤90 s) | Fidelidad (de 10) |",
             "|---|---|---|---|---|"]
    for f in filas:
        tabla.append(f"| {f['modelo']} | {f['tps']:.1f} | {f['total']:.1f} | {'OK' if f['vel_ok'] else 'NO'} | "
                     f"{f['fid'] if f['fid'] is not None else '-'} |")
    print("\n" + "\n".join(tabla))
    print("\nAnota además la RAM con `ollama ps` y la calidad subjetiva de la respuesta.")
    if a.salida:
        open(a.salida, "w", encoding="utf-8").write("\n".join(tabla) + "\n")


if __name__ == "__main__":
    main()
