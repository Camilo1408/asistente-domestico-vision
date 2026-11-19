"""Prompts por modo y construcción del mensaje para el LLM.

El LLM nunca ve imágenes: solo recibe la lista de objetos en texto.
"""

# Base del contrato (modelo FOMO del ESP32) + extras que detecta YOLO (COCO) en la Pi
CLASES_COCINA = ["manzana", "tomate", "huevo", "limon", "zanahoria", "leche", "banano", "naranja", "brocoli"]
CLASES_CUARTO = ["taza", "botella", "libro", "zapato", "mochila", "laptop", "celular"]
CLASES = CLASES_COCINA + CLASES_CUARTO

CLASES_POR_MODO = {"cocina": CLASES_COCINA, "cuarto": CLASES_CUARTO}

# Nombres para mostrar (el contrato usa minúsculas sin tildes)
NOMBRE_PLURAL = {
    "manzana": "manzanas", "tomate": "tomates", "huevo": "huevos", "limon": "limones",
    "zanahoria": "zanahorias", "leche": "leche (envases)", "taza": "tazas",
    "botella": "botellas", "libro": "libros", "zapato": "zapatos",
    "banano": "bananos", "naranja": "naranjas", "brocoli": "brócolis",
    "mochila": "mochilas", "laptop": "portátiles", "celular": "celulares",
}

PROMPT_COCINA = """Estás en MODO COCINA. Ingredientes detectados por la cámara:
{lista}
{pronto}
Reglas estrictas:
- Usa SOLO los ingredientes de la lista. No inventes ni agregues ingredientes (sal, aceite y agua sí se asumen disponibles).
- Propón 1 o 2 recetas sencillas con esos ingredientes.
- Formato: nombre de la receta, ingredientes que usa y 3 a 5 pasos cortos.
- Si con la lista no se puede preparar nada razonable, dilo y sugiere qué comprar.
- Responde en español, breve."""

PROMPT_CUARTO = """Estás en MODO CUARTO. Objetos detectados por la cámara:
{lista}

Reglas estrictas:
- Usa SOLO los objetos de la lista. No inventes otros objetos.
- Da primero un "Índice de orden: N/100" (más objetos fuera de lugar = menor índice).
- Luego da de 3 a 5 acciones concretas y cortas para ordenar, mencionando los objetos de la lista.
- Responde en español, breve."""

PROMPTS = {"cocina": PROMPT_COCINA, "cuarto": PROMPT_CUARTO}


def formatear_lista(inventario: dict, modo: str) -> str:
    """Solo los objetos del modo activo con cantidad > 0, uno por línea."""
    lineas = []
    for clase in CLASES_POR_MODO[modo]:
        n = int(inventario.get(clase, 0))
        if n > 0:
            lineas.append(f"- {n} {NOMBRE_PLURAL[clase]}")
    return "\n".join(lineas)


def faltantes(inventario: dict, modo: str = "cocina") -> list:
    return [c for c in CLASES_POR_MODO[modo] if int(inventario.get(c, 0)) == 0]


def construir_prompt(modo: str, inventario: dict, mas_antiguo: str | None = None) -> str:
    """Devuelve el prompt de usuario, o None si no hay objetos detectados en ese modo."""
    if modo not in PROMPTS:
        raise ValueError(f"modo desconocido: {modo}")
    lista = formatear_lista(inventario, modo)
    if not lista:
        return None
    pronto = ""
    if modo == "cocina" and mas_antiguo:
        pronto = f"Úsalo pronto: {NOMBRE_PLURAL[mas_antiguo]} es lo que lleva más días; priorízalo en la receta.\n"
    return PROMPTS[modo].format(lista=lista, pronto=pronto)


MENSAJE_SIN_OBJETOS = {
    "cocina": "No detecto ingredientes en la bandeja. Coloca algunos y vuelve a pedir una sugerencia.",
    "cuarto": "No detecto objetos del cuarto en la escena. Coloca algunos y vuelve a pedir una sugerencia.",
}
