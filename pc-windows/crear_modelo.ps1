# Descarga qwen2.5:1.5b y crea el modelo "asistente" (requiere Ollama instalado e internet)
ollama pull qwen2.5:1.5b
ollama create asistente -f "$PSScriptRoot\Modelfile.pc"
ollama list
