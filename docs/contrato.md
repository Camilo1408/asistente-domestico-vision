# Contrato de interfaz

Se fija antes de empezar y no se modifica sin coordinar firmware (frente A) y Pi (frente B).
Todas las piezas (ESP32, servicio vision, cerebro, Home Assistant) se comunican solo por estos tópicos.

## Broker
Mosquitto en la Raspberry Pi, con usuario y contraseña (`pi/.env`).
- Dentro de Docker: `mosquitto:1883`.
- Desde fuera (ESP32, PC): `IP-DE-LA-PI:1884` en la variante compartida (`docker-compose.pi-compartida.yml`), `1883` en la dedicada.

## Tópicos MQTT

| Tópico | Publica | Contenido |
|---|---|---|
| `casa/<camara>/detecciones` | ESP32 (FOMO) o servicio vision (YOLO) | JSON con el conteo de todas las clases |
| `casa/<camara>/presencia` | vision | `{"personas","brillo","ts"}` (retain) |
| `casa/<camara>/imagen` | vision | JPEG con las detecciones dibujadas |
| `casa/<camara>/estado` | vision | `online` / `offline` (retain) |
| `casa/<camara>/inventario` | cerebro | Conteo estable (mediana de 5) de esa cámara (retain) |
| `casa/camara1/cmd` | Pi | `capturar` fuerza una inferencia en el ESP32 |
| `casa/inventario` | cerebro | Inventario de la **cámara activa** (retain) |
| `casa/asistente/camara` | Home Assistant | Cámara activa: `camara1` (ESP32) o `iphone` (retain) |
| `casa/asistente/modo` | Home Assistant | `cocina` o `cuarto` (retain) |
| `casa/asistente/pedir` | Home Assistant | Cualquier texto dispara una sugerencia (`boton`, `resumen`) |
| `casa/asistente/auto` | Home Assistant | Ajustes de sugerencias automáticas (JSON, retain) |
| `casa/asistente/auto/estado` | cerebro | Estado del automático y minutos para la próxima (retain) |
| `casa/asistente/respuesta` | cerebro | `{"texto","ts","modo","origen","camara"}` (retain) |
| `casa/asistente/historial` | cerebro | Últimas 5 sugerencias `{"n","items":[...]}` (retain) |
| `casa/asistente/estado` | cerebro | `pensando` o `listo` (retain) |

`<camara>`: minúsculas, letras/números/guion bajo; `asistente` está reservado.
`origen` de una respuesta: `boton` (pedida), `resumen` (19:00) o `auto` (automática).

## Mensaje de detecciones
Incluye **todas las clases**, aunque valgan 0 (las que falten se toman como 0).
```json
{"conteo":{"manzana":2,"tomate":3,"huevo":0,"limon":1,"zanahoria":0,"leche":1,"banano":0,"naranja":0,"brocoli":0,
           "taza":0,"botella":0,"libro":0,"zapato":0,"mochila":0,"laptop":0,"celular":0},
 "latencia_ms":142,"umbral":0.6}
```
El servicio vision añade `"fuente":"yolo"`.

## Ajustes de sugerencias automáticas (`casa/asistente/auto`)
```json
{"activo":true,"min_cuarto":4,"min_cocina":2,"intervalo_min":10,"estable_s":20,"recordatorio_min":60}
```

## Clases
Minúsculas, sin tildes ni espacios, exactamente como se etiquetan en Edge Impulse.

| Modo | Modelo FOMO propio (ESP32) | Extra que detecta YOLO (COCO) en la Pi |
|---|---|---|
| cocina | `manzana, tomate, huevo, limon, zanahoria, leche` | `manzana, zanahoria, banano, naranja, brocoli` |
| cuarto | `taza, botella, libro, zapato` | `taza, botella, libro, mochila, laptop, celular` |

YOLO también detecta `persona` (no es una clase del inventario: va en `presencia`).
Un cambio de clases se refleja aquí primero y luego en: `firmware/.../config.h(.example)`,
`pi/cerebro/prompts.py`, `pi/vision/vision.py`, `pi/ha/mqtt.yaml`, `pi/ha/dashboard.yaml`, `tools/simular_esp32.py`.

## Endpoints HTTP
- ESP32 (CameraWebServer): `http://<ip-esp32>/capture` (JPEG) y `http://<ip-esp32>:81/stream` (MJPEG, un solo cliente).
- go2rtc: `http://<ip-pi>:1984/api/stream.mjpeg?src=<camara>` y `.../api/frame.jpeg?src=<camara>`.
