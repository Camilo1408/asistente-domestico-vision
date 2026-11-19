#!/usr/bin/env bash
# Descarga los modelos candidatos y crea el modelo "asistente". Requiere internet.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d ollama
sleep 5
for m in qwen2.5:3b qwen2.5:1.5b gemma3:1b; do
  docker compose exec ollama ollama pull "$m"
done
docker compose exec ollama ollama create asistente -f /Modelfile
docker compose exec ollama ollama list
