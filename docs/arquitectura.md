# Arquitectura

## Flujo de datos (versión actual)

```mermaid
flowchart LR
  subgraph CAM["Cámaras"]
    ESP["ESP32-S3 (Goouuu)<br/>CameraWebServer / FOMO"]
    IPH["iPhone<br/>IP Camera Lite (MJPEG)"]
  end
  ESP -- "MJPEG :81/stream" --> G2R
  IPH -- "MJPEG :8081/video" --> G2R
  G2R["go2rtc<br/>1 conexión por cámara"] -- "stream continuo" --> VIS["vision<br/>YOLOv8n ONNX"]
  G2R -- "video en vivo" --> HA[Home Assistant]
  ESP -. "FOMO: casa/camara1/detecciones" .-> MQ
  VIS -- "detecciones · presencia · imagen" --> MQ[Mosquitto]
  MQ --> CER["cerebro<br/>mediana · auto · historial"]
  CER --> DB[(SQLite)]
  CER -- "prompt de texto" --> OL["Ollama<br/>gemma3:1b"]
  OL --> CER
  CER -- "inventario · respuesta · historial" --> MQ
  MQ <--> HA
```

## Contenedores (Docker Compose, `pi/docker-compose.pi-compartida.yml`)

| Servicio | Imagen | Puerto en la Pi | Función |
|---|---|---|---|
| mosquitto | eclipse-mosquitto:2 | 1884 | Broker MQTT con usuario y clave |
| homeassistant | home-assistant:stable | 8124 | Interfaz, automatizaciones, notificaciones |
| ollama | ollama/ollama | 11435 (solo local) | LLM local (`asistente` = gemma3:1b + Modelfile) |
| cerebro | build `pi/cerebro` | — | Inventario estable, sugerencias, historial |
| vision | build `pi/vision` | — | YOLO sobre las cámaras IP, presencia y brillo |
| go2rtc | alexxit/go2rtc | 1984 | Relé de video: una conexión por cámara |

Los puertos están desplazados (8124, 1884, 11435) porque la Pi también aloja otro proyecto con
Home Assistant y Mosquitto propios.

## Secuencia de una sugerencia automática

```mermaid
sequenceDiagram
  participant V as vision / ESP32
  participant C as cerebro
  participant O as Ollama
  participant HA as Home Assistant
  V->>C: detecciones cada 2–5 s
  C->>C: mediana de 5 → inventario estable
  C->>C: ¿≥ N objetos, escena estable 20 s, pasó el intervalo y cambió la escena?
  C->>HA: estado = pensando
  C->>O: prompt del modo (solo objetos detectados)
  O-->>C: texto
  C->>HA: respuesta (origen = auto) + historial + estado = listo
  HA->>HA: cambia el modo mostrado y notifica
```

## Red
Dos opciones:
1. **Red existente** (la usada en las pruebas): Pi, ESP32 e iPhone en el mismo WiFi 2.4 GHz.
   Acceso remoto por Tailscale (`http://100.90.171.87:8124`).
2. **Red propia de la Pi** (`pi/scripts/crear_hotspot.sh`): red `AsistenteCasa`, Pi en `10.42.0.1`.
   No usar si la Pi depende de su WiFi para otro proyecto (corta la conexión actual).
