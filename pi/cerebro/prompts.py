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

PROMPT_CUARTO = """Estás en MODO CUARTO. Eres un asistente que ayuda a ordenar un escritorio o habitación.
Objetos detectados por la cámara:
{lista}

Ejemplo de respuesta para OTROS objetos (2 platos, 1 cargador, 1 chaqueta):
1. Lleva los 2 platos a la cocina y lávalos.
2. Enrolla el cargador y guárdalo en el cajón.
3. Cuelga la chaqueta en el perchero o el armario.

Ahora escribe de 3 a 5 acciones numeradas para los objetos detectados. Cada acción empieza con un verbo
(guarda, lleva, recicla, apila, cierra...), menciona un objeto DISTINTO de la lista con su cantidad y dice
a qué lugar adecuado va. Usa SOLO los objetos de la lista; no copies el ejemplo.
Responde solo con la lista numerada, en español."""

PROMPTS = {"cocina": PROMPT_COCINA, "cuarto": PROMPT_CUARTO}


NOMBRE_SINGULAR = {
    "manzana": "manzana", "tomate": "tomate", "huevo": "huevo", "limon": "limón", "zanahoria": "zanahoria",
    "leche": "envase de leche", "taza": "taza o vaso", "botella": "botella", "libro": "libro",
    "zapato": "zapato", "banano": "banano", "naranja": "naranja", "brocoli": "brócoli",
    "mochila": "mochila", "laptop": "portátil", "celular": "celular",
}


def formatear_lista(inventario: dict, modo: str) -> str:
    """Solo los objetos del modo activo con cantidad > 0, uno por línea."""
    lineas = []
    for clase in CLASES_POR_MODO[modo]:
        n = int(inventario.get(clase, 0))
        if n > 0:
            nombre = NOMBRE_SINGULAR[clase] if n == 1 else NOMBRE_PLURAL[clase]
            lineas.append(f"- {n} {nombre}")
    return "\n".join(lineas)


def faltantes(inventario: dict, modo: str = "cocina") -> list:
    return [c for c in CLASES_POR_MODO[modo] if int(inventario.get(c, 0)) == 0]


def indice_orden(total_objetos: int) -> int:
    """Índice de orden 0-100 calculado (no lo inventa el LLM): cada objeto a la vista resta 10 puntos."""
    return max(5, 100 - 10 * int(total_objetos))


def encabezado(modo: str, inventario: dict) -> str:
    """Línea que el cerebro antepone a la respuesta (dato calculado, no generado por el LLM)."""
    if modo != "cuarto":
        return ""
    total = sum(max(0, int(inventario.get(c, 0))) for c in CLASES_CUARTO)
    return f"Índice de orden: {indice_orden(total)}/100 ({total} objetos a la vista)\n\n"


def limpiar_respuesta(texto: str) -> str:
    """Quita líneas de índice que el modelo pudiera inventar."""
    return "\n".join(l for l in texto.splitlines() if "índice de orden" not in l.lower()).strip()


def construir_prompt(modo: str, inventario: dict, mas_antiguo: str | None = None) -> str:
    """Devuelve el prompt de usuario, o None si no hay objetos detectados en ese modo."""
    if modo not in PROMPTS:
        raise ValueError(f"modo desconocido: {modo}")
    lista = formatear_lista(inventario, modo)
    if not lista:
        return None
    if modo == "cuarto":
        total = sum(max(0, int(inventario.get(c, 0))) for c in CLASES_CUARTO)
        return PROMPTS[modo].format(lista=lista)
    pronto = ""
    if modo == "cocina" and mas_antiguo:
        pronto = f"Úsalo pronto: {NOMBRE_PLURAL[mas_antiguo]} es lo que lleva más días; priorízalo en la receta.\n"
    return PROMPTS[modo].format(lista=lista, pronto=pronto)


MENSAJE_SIN_OBJETOS = {
    "cocina": "No detecto ingredientes en la bandeja. Coloca algunos y vuelve a pedir una sugerencia.",
    "cuarto": "No detecto objetos del cuarto en la escena. Coloca algunos y vuelve a pedir una sugerencia.",
}
