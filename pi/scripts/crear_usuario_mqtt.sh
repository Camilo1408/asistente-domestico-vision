#!/usr/bin/env bash
# Crea pi/mosquitto/passwd con el usuario/clave de pi/.env (mosquitto_passwd)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Falta pi/.env (copia .env.example)"; exit 1; }
set -a; . ./.env; set +a
rm -f mosquitto/passwd; touch mosquitto/passwd
docker run --rm -v "$PWD/mosquitto:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b /mosquitto/config/passwd "$MQTT_USER" "$MQTT_PASS"
# Mosquitto 2.1+ abre passwd como uid 1883: la carpeta debe ser atravesable (scp desde Windows la deja en 700)
# y el archivo de root, legible por el grupo mosquitto. Si no: "Unable to open pwfile" y código 13.
chmod 755 mosquitto
docker run --rm -v "$PWD/mosquitto:/mosquitto/config" eclipse-mosquitto:2 \
  sh -c "chown 0:1883 /mosquitto/config/passwd && chmod 0640 /mosquitto/config/passwd"
echo "Usuario MQTT '$MQTT_USER' creado en pi/mosquitto/passwd"
