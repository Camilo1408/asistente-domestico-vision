#!/usr/bin/env bash
# Prueba 10: recursos de la Pi durante una consulta (RAM libre >= 1 GB, temp <= 80 C)
echo "== temperatura =="; vcgencmd measure_temp 2>/dev/null || echo "vcgencmd no disponible"
echo "== memoria =="; free -h
echo "== contenedores =="; docker stats --no-stream
echo "== modelo cargado =="; docker compose exec -T ollama ollama ps 2>/dev/null || true
