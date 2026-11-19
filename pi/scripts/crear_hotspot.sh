#!/usr/bin/env bash
# Crea el punto de acceso WiFi "AsistenteCasa" (2.4 GHz, arranque automático) con NetworkManager.
# Ejecutar DESPUÉS de instalar todo con internet (docker pull, ollama pull).
# Uso: sudo ./crear_hotspot.sh [SSID] [CLAVE]
set -euo pipefail
SSID="${1:-AsistenteCasa}"
CLAVE="${2:-clave-segura-123}"

nmcli device wifi hotspot ifname wlan0 ssid "$SSID" password "$CLAVE"
nmcli connection modify Hotspot connection.autoconnect yes
nmcli connection modify Hotspot 802-11-wireless.band bg   # 2.4 GHz: el ESP32-S3 no soporta 5 GHz
nmcli connection up Hotspot || true

echo "--- Verificación ---"
nmcli connection show --active
ip addr show wlan0 | grep "inet "   # debe mostrar 10.42.0.1
