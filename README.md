# Asistente doméstico con visión

Proyecto final de Inteligencia Artificial.

| Integrante | Código |
|---|---|
| Cesar Camilo Hoyos Diaz | 20222207570 |
| Álvaro Julián Delgado Mena | 20222208840 |
| Dawin Alexis Guarin Ipuz | 20202192954 |

> **Resumen del proyecto:** [docs/RESUMEN.md](docs/RESUMEN.md)

ESP32-S3 (FOMO, Edge Impulse) cuenta objetos → MQTT → Raspberry Pi (servicio **cerebro**, SQLite, Ollama, Home Assistant).
El LLM nunca ve imágenes: recibe solo la lista de objetos en texto.

```
ESP32-S3 (FOMO int8) --MQTT JSON--> Mosquitto --> cerebro (Python)
                                                    |-- SQLite (historial)
                                                    |-- Ollama (LLM local)
                                                    `-- Home Assistant (dashboard)
```

> **Documentación completa:** [docs/DOCUMENTACION.md](docs/DOCUMENTACION.md) (qué se hizo, por qué y para qué).
> Arquitectura actual con dos cámaras, go2rtc, YOLO y sugerencias automáticas: [docs/arquitectura.md](docs/arquitectura.md).

## Estructura

```
firmware/esp32_fomo_mqtt/   sketch Arduino + config.h.example
edge-impulse/               librería exportada (.zip) y dataset (lo genera el frente A)
pi/                         docker-compose, mosquitto, ollama, cerebro, ha, scripts
tools/                      simulador del ESP32 y benchmark del LLM
docs/                       contrato, arquitectura, tablas, pruebas de verificación
```

## Componentes
| Componente | Descripción |
|---|---|
| Servicios Docker | Mosquitto, Home Assistant, Ollama, cerebro, vision y go2rtc |
| cerebro | Mediana de lecturas, sugerencias automáticas, historial SQLite, prompts y tests |
| vision | YOLOv8n (ONNX) sobre las cámaras IP: objetos, personas y brillo |
| Home Assistant | Sensores, botón, automatizaciones (compras, luz, resumen, sugerencias) y dashboard por secciones |
| Firmware ESP32-S3 | WiFi, MQTT, FOMO, umbral 0.6, `/capture` |
| Herramientas | Simulador del ESP32, captura de dataset, benchmark del LLM, scripts de operación |

## Puesta en marcha en la Raspberry Pi (desde cero)

Paso 1 se hace **con internet**. Después el sistema funciona sin internet.

```bash
# 0. Raspberry Pi OS 64 bits (Lite), SSH activo, disipador activo. Instalar Docker:
curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER   # reiniciar sesión

# 1. Clonar y configurar
git clone <URL-del-repo> asistente && cd asistente/pi
cp .env.example .env && nano .env          # usuario/clave MQTT
./scripts/crear_usuario_mqtt.sh

# 2. Levantar servicios y descargar modelos (internet)
docker compose up -d --build
./scripts/setup_ollama.sh                  # qwen2.5:3b, qwen2.5:1.5b, gemma3:1b + crea "asistente"

# 3. Probar SIN hardware (simulando el ESP32)
sudo apt install -y mosquitto-clients
mosquitto_sub -h localhost -u USUARIO -P CLAVE -t 'casa/#' -v &
mosquitto_pub -h localhost -u USUARIO -P CLAVE -t casa/camara1/detecciones \
  -m '{"conteo":{"tomate":3,"huevo":2,"leche":1},"latencia_ms":120}'
#    (o: python3 ../tools/simular_esp32.py --host localhost -u USUARIO -p CLAVE --escena cocina_basica)
mosquitto_pub -h localhost -u USUARIO -P CLAVE -t casa/asistente/pedir -m boton

# 4. Punto de acceso WiFi (al final)
sudo ./scripts/crear_hotspot.sh            # red AsistenteCasa, 2.4 GHz, IP 10.42.0.1
```

### Home Assistant (primer arranque)
1. Abrir `http://10.42.0.1:8123` desde un celular/PC conectado a `AsistenteCasa` y crear el usuario administrador.
2. **Ajustes → Dispositivos y servicios → Añadir integración → MQTT**: broker `localhost` (HA usa red host), puerto `1883`, usuario/clave del `.env`.
3. Reiniciar HA. Aparecen `sensor.inventario_*`, `button.pedir_sugerencia`, `sensor.asistente_respuesta`, `input_select.modo_asistente`.
4. Dashboard: pegar `pi/ha/dashboard.yaml` en el editor de configuración en bruto.
5. Notificaciones al celular: instalar la app de HA (misma dirección) y cambiar `notify.mobile_app_celular` en `pi/ha/automations.yaml` por el servicio real (Herramientas de desarrollo → Acciones, buscar `notify.mobile_app_`). Si no hay app, igual salen como notificación dentro de HA.

### ESP32-S3
1. Entrenar en Edge Impulse (ver `docs/variantes_tinyml.md`), exportar **Arduino library** (int8 + EON) y guardarla en `edge-impulse/`; instalarla en Arduino IDE (Sketch → Incluir biblioteca → Añadir .ZIP).
2. Instalar `PubSubClient` y `ArduinoJson` (v7) desde el gestor de librerías.
3. `cp firmware/esp32_fomo_mqtt/config.h.example firmware/esp32_fomo_mqtt/config.h` y editar: WiFi, broker `10.42.0.1`, credenciales MQTT, el `#include <..._inferencing.h>` con el nombre real de la librería y el modelo de cámara.
4. Placa `ESP32S3 Dev Module`, **PSRAM: OPI PSRAM**, **Partition Scheme: Huge APP**. Compilar y subir; ver latencia real en el monitor serie (115200).

## Cómo se comporta el sistema

- **Estabilidad**: el cerebro usa la mediana de las últimas 5 lecturas por clase y solo publica `casa/inventario` (retain) cuando cambia.
- **Historial**: cada cambio de cantidad queda en SQLite (`pi/data/historial.db`, tabla `cambios`).
- **Sugerencia**: botón en HA → `casa/asistente/pedir` → cerebro arma el prompt del modo activo solo con objetos detectados → Ollama (`keep_alive 30m`) → `casa/asistente/respuesta`.
- **"Úsalo pronto"** (modo cocina): el prompt prioriza el ingrediente que lleva más días en el inventario.
- **Lista de compras**: menos de 2 huevos o 0 leche → se añade a la lista de HA y se notifica.
- **Resumen 19:00**: HA cambia a modo cocina, pide la sugerencia y reenvía la respuesta como notificación (incluye faltantes).

## Tests y herramientas

```bash
cd pi/cerebro && python3 -m pytest -q tests          # lógica del cerebro
python3 tools/benchmark_llm.py --modelos qwen2.5:3b qwen2.5:1.5b gemma3:1b --fidelidad
pi/scripts/monitor.sh                                # temperatura, RAM, docker stats
```

Detalles del contrato en `docs/contrato.md`; las 13 pruebas en `docs/pruebas_verificacion.md`.
Cualquier cambio de clases o tópicos se hace **primero** en el contrato y luego en `firmware/config.h`, `pi/cerebro/prompts.py` y `pi/ha/mqtt.yaml`.

## Créditos y licencias de terceros
- Detector: YOLOv8n de [Ultralytics](https://github.com/ultralytics/ultralytics) (AGPL-3.0), exportado a ONNX en `pi/vision/yolo.onnx`.
- LLM: gemma3:1b vía [Ollama](https://ollama.com). Relé de video: [go2rtc](https://github.com/AlexxIT/go2rtc).

