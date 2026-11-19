# Frente A: modelo TinyML (FOMO)

## Dataset
- Montar primero la escena definitiva: misma cámara, distancia e iluminación que en el sistema final.
- 150–300 imágenes con la propia ESP32-S3, varios objetos por foto, variando posición y cantidad.
- Etiquetar con cajas en Edge Impulse usando exactamente los nombres de `contrato.md`.
- 20 % de las imágenes como conjunto de prueba.

## Impulse
Imagen 96×96 en escala de grises → bloque FOMO.

## Variantes a entrenar (completar con mediciones reales)

| Variante | F1 | RAM | Flash | Latencia ESP32-S3 |
|---|---|---|---|---|
| float32, MobileNetV2 0.35, RGB | | | | |
| int8, MobileNetV2 0.35, gris | | | | |
| int8 + EON, MobileNetV2 0.1, gris | | | | |

Latencia estimada: pestaña Deployment. Latencia real: puerto serie del firmware (`DSP x ms + clasificacion y ms`).

**Criterio de elección:** la variante más ligera cuyo F1 no baje más de 5 puntos respecto a la mejor.
**Modelo elegido:** _______

## Exportación
Deployment → Arduino library, con **Quantized (int8)** y **EON Compiler** activos. Guardar el `.zip` en `edge-impulse/`.

## Optimizaciones aplicadas
int8 (≈4× más pequeño), EON Compiler (sin intérprete), ESP-NN (kernels vectoriales del S3), backbone 0.1, entrada gris 96×96, inferencia solo con cambios de escena o cada 5 s.
