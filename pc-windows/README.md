# Probar en Windows sin Docker y sin Raspberry

Cubre: Mosquitto + cerebro + Ollama + simulador del ESP32. No incluye Home Assistant.
Ejecutar los .ps1 con: `powershell -ExecutionPolicy Bypass -File .\pc-windows\<script>.ps1`
Cada servicio va en su propia ventana de PowerShell.

1. Python 3.10+ (python.org, marcar "Add python.exe to PATH") y `pip install paho-mqtt requests pytest`
2. Mosquitto: mosquitto.org/download (instalador Windows) -> `iniciar_mosquitto.ps1`
3. Ollama: ollama.com/download/windows -> `crear_modelo.ps1`
4. `iniciar_cerebro.ps1`
5. Simulador: `python tools\simular_esp32.py --host localhost --escena cocina_basica --ruido --cada 1`
6. Escuchar: `& "C:\Program Files\mosquitto\mosquitto_sub.exe" -h localhost -t "casa/#" -v`
7. Pedir sugerencia: `& "C:\Program Files\mosquitto\mosquitto_pub.exe" -h localhost -t casa/asistente/pedir -m boton`
