# Benchmark del LLM en la Raspberry Pi

Generar con `python3 tools/benchmark_llm.py --modelos qwen2.5:3b qwen2.5:1.5b gemma3:1b --fidelidad`
y completar RAM (`ollama ps`) y calidad a mano.

| Modelo (Q4_K_M) | eval rate (tok/s) | RAM (ollama ps) | Tiempo total (s) | Fidelidad (de 10) | Calidad (1–5) |
|---|---|---|---|---|---|
| qwen2.5:3b | | | | | |
| qwen2.5:1.5b | | | | | |
| gemma3:1b | | | | | |

Referencia orientativa de la guía (Pi 5): gemma3:1b 8–12 tok/s, qwen2.5:1.5b 6–9, qwen2.5:3b 3–5.
Criterios: ≥ 3 tok/s, respuesta ≤ 90 s, 8 de 10 casos usan solo objetos detectados.

**Modelo final:** _______ (si no es qwen2.5:3b, cambiar `FROM` en `pi/ollama/Modelfile` y volver a ejecutar `ollama create asistente -f /Modelfile`).
