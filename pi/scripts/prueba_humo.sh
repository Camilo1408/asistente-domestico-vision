#!/usr/bin/env bash
# Prueba de humo SIN ESP32: simula la cámara con mosquitto_pub DENTRO del contenedor de Mosquitto
# (no instala nada en la Pi) y verifica inventario -> sugerencia del LLM.
# Uso: ./scripts/prueba_humo.sh [cocina|cuarto]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
MODO="${1:-cocina}"
MQ="docker exec asistente-mosquitto"
AUTH=(-h localhost -u "$MQTT_USER" -P "$MQTT_PASS")

if [ "$MODO" = "cuarto" ]; then
  CONTEO='{"taza":3,"botella":2,"libro":4,"zapato":2,"manzana":0,"tomate":0,"huevo":0,"limon":0,"zanahoria":0,"leche":0}'
else
  CONTEO='{"tomate":3,"huevo":2,"leche":1,"manzana":0,"limon":0,"zanahoria":0,"taza":0,"botella":0,"libro":0,"zapato":0}'
fi

echo "== 1. Servicios =="
docker compose ps

echo "== 2. Modo: $MODO =="
$MQ mosquitto_pub "${AUTH[@]}" -t casa/asistente/modo -m "$MODO"

echo "== 3. Simulando 5 lecturas de la cámara (mediana de 5) =="
for i in 1 2 3 4 5; do
  $MQ mosquitto_pub "${AUTH[@]}" -t casa/camara1/detecciones \
    -m "{\"conteo\":$CONTEO,\"latencia_ms\":12$i,\"umbral\":0.6}"
  sleep 1
done

echo "== 4. Inventario estable publicado por el cerebro =="
$MQ mosquitto_sub "${AUTH[@]}" -t casa/inventario -C 1 -W 5 || { echo "FALLO: no hay casa/inventario"; exit 1; }

echo "== 5. Pidiendo sugerencia al LLM (puede tardar 1-3 min en la Pi) =="
T0=$(date +%s)
$MQ mosquitto_pub "${AUTH[@]}" -t casa/asistente/pedir -m prueba
sleep 2
# espera hasta 300 s a que el estado vuelva a "listo"
for _ in $(seq 1 150); do
  EST=$($MQ mosquitto_sub "${AUTH[@]}" -t casa/asistente/estado -C 1 -W 3 2>/dev/null || true)
  [ "$EST" = "listo" ] && break
  sleep 2
done
echo "Tiempo: $(( $(date +%s) - T0 )) s"

echo "== 6. Respuesta =="
$MQ mosquitto_sub "${AUTH[@]}" -t casa/asistente/respuesta -C 1 -W 5
echo
echo "OK. Revisa también el dashboard en http://$(hostname -I | awk '{print $1}'):8124"
