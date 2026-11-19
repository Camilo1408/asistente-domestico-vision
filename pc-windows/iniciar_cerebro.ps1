# Arranca el servicio cerebro en Windows (Mosquitto y Ollama deben estar corriendo)
$env:MQTT_HOST = "localhost"
$env:MQTT_PORT = "1883"
$env:OLLAMA_URL = "http://localhost:11434"
$env:MODEL = "asistente"
$env:DB_PATH = Join-Path $PSScriptRoot "historial.db"
python "$PSScriptRoot\..\pi\cerebro\main.py"
