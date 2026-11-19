# Pruebas de verificación (sistema montado en el hardware final)

Fecha: ______  Responsable: ______  Marcar Resultado con ✅ / ❌ y anotar el valor medido.

| # | Prueba | Procedimiento | Criterio | Resultado / valor |
|---|---|---|---|---|
| 1 | Conectividad MQTT | `mosquitto_sub -h 10.42.0.1 -u U -P P -t 'casa/#' -v` con el ESP32 encendido | Un mensaje válido cada ≤ 5 s | |
| 2 | Precisión del modelo | Reporte de Edge Impulse (conjunto de prueba) | F1 ≥ 0.80 | |
| 3 | Conteo real | 30 escenas armadas a mano vs `casa/inventario` | ≥ 80 % exactas (≥ 24/30) | |
| 4 | Latencia en el ESP32 | Puerto serie (`DSP + clasificación`) | ≤ 300 ms | |
| 5 | Estabilidad del conteo | Escena fija 2 min, `mosquitto_sub -t casa/inventario -v` | No cambia | |
| 6 | Velocidad del LLM | `docker compose exec ollama ollama run asistente --verbose` o `tools/benchmark_llm.py` | ≥ 3 tok/s y ≤ 90 s | |
| 7 | Fidelidad del LLM | `tools/benchmark_llm.py --fidelidad` + revisión manual de `pi/ollama/casos_prueba.json` | ≥ 8/10 usan solo objetos detectados | |
| 8 | Home Assistant | Mover objetos y observar el dashboard | Sensores actualizados ≤ 15 s | |
| 9 | Lista de compras | Retirar los huevos de la bandeja | "Huevos" en la lista + notificación | |
| 10 | Recursos de la Pi | `pi/scripts/monitor.sh` durante una consulta | RAM libre ≥ 1 GB, temp ≤ 80 °C | |
| 11 | Reinicio | Desconectar y reconectar Pi y ESP32 | Todo se recupera sin intervención | |
| 12 | Punta a punta | Colocar ingredientes y pulsar "Pedir sugerencia" | Receta en el dashboard ≤ 2 min | |
| 13 | Red autónoma | Sin internet ni WiFi externo: arrancar Pi, conectar ESP32 y celular a `AsistenteCasa` | `http://10.42.0.1:8123` accesible y conteos llegando | |
| 14 | Cámaras estables | Panel go2rtc `http://IP-PI:1984` + `docker compose logs -f vision` durante 10 min | Sin "conexión perdida" sostenida; reconexión sola ≤ 15 s | |
| 15 | Latencia YOLO | Log de vision (`yolo N ms`) | ≤ 300 ms por imagen en la Pi 5 | |
| 16 | Sugerencia automática | Poner ≥ 4 objetos de cuarto y no tocar | Sugerencia sola tras ~20 s estable; no cambia antes del intervalo | |
| 17 | Aviso de luz | Luz encendida, salir del cuadro | Notificación tras los minutos configurados | |
| 18 | Alimentación | `vcgencmd get_throttled` tras 30 min de uso | `0x0` (sin bajo voltaje) con la fuente de 27 W | |

## Notas por prueba
- **Prueba 5**: simular con `tools/simular_esp32.py --ruido` valida el estabilizador sin hardware.
- **Prueba 9**: la automatización exige que el valor se mantenga < 2 durante 20 s, para evitar falsos positivos.
- **Prueba 11**: todos los contenedores usan `restart: unless-stopped` y el hotspot `autoconnect yes`; confirmar que Docker arranca con el sistema (`sudo systemctl enable docker`).
