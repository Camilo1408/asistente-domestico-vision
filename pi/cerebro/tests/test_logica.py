import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logica import Estabilizador, Historial  # noqa: E402
from prompts import construir_prompt, faltantes  # noqa: E402

DIA = 86400


def test_mediana_ignora_pico():
    e = Estabilizador(5)
    for v in [3, 3, 3, 3]:
        e.actualizar({"tomate": v})
    estable, cambios, _ = e.actualizar({"tomate": 7})  # lectura ruidosa aislada
    assert estable["tomate"] == 3
    assert "tomate" not in cambios or cambios["tomate"][1] == 3


def test_cambio_real_tras_varias_lecturas():
    e = Estabilizador(5)
    for _ in range(5):
        e.actualizar({"huevo": 4})
    cambiados = []
    for _ in range(3):
        _, cambios, _ = e.actualizar({"huevo": 1})
        cambiados.append(cambios)
    assert e.estable["huevo"] == 1
    assert any("huevo" in c for c in cambiados)


def test_clases_ausentes_valen_cero_y_desconocidas_se_ignoran():
    e = Estabilizador(5)
    estable, _, primera = e.actualizar({"tomate": 2, "ovni": 9})
    assert primera and estable["tomate"] == 2 and estable["huevo"] == 0 and "ovni" not in estable


def test_valores_invalidos():
    e = Estabilizador(5)
    estable, _, _ = e.actualizar({"tomate": "x", "huevo": -3})
    assert estable["tomate"] == 0 and estable["huevo"] == 0


def test_historial_dias_y_mas_antiguo(tmp_path):
    h = Historial(str(tmp_path / "h.db"))
    ahora = 100 * DIA
    h.registrar("huevo", 6, ahora - 5 * DIA)
    h.registrar("tomate", 3, ahora - 2 * DIA)
    h.registrar("leche", 1, ahora - 9 * DIA)
    h.registrar("leche", 0, ahora - 8 * DIA)   # se acabó
    h.registrar("leche", 1, ahora - 1 * DIA)   # reapareció hace 1 día
    assert round(h.dias_en_inventario("huevo", ahora)) == 5
    assert round(h.dias_en_inventario("leche", ahora)) == 1
    assert h.dias_en_inventario("manzana", ahora) is None
    inv = {"huevo": 6, "tomate": 3, "leche": 1, "manzana": 0}
    assert h.mas_antiguo(inv, ["huevo", "tomate", "leche", "manzana"], ahora) == "huevo"


def test_prompt_cocina_solo_objetos_detectados():
    p = construir_prompt("cocina", {"tomate": 3, "huevo": 2, "leche": 0, "taza": 5}, "huevo")
    assert "3 tomates" in p and "2 huevos" in p
    assert "leche" not in p.split("Reglas")[0] and "taza" not in p
    assert "Úsalo pronto" in p


def test_prompt_vacio_devuelve_none():
    assert construir_prompt("cocina", {"taza": 2}) is None
    assert construir_prompt("cuarto", {"tomate": 2}) is None


def test_prompt_cuarto_pide_acciones_con_objetos():
    p = construir_prompt("cuarto", {"zapato": 2, "taza": 1})
    assert "2 zapatos" in p and "1 taza o vaso" in p and "acciones" in p


def test_faltantes():
    assert set(faltantes({"huevo": 2, "tomate": 0})) >= {"tomate", "manzana"}


def test_indice_orden_calculado():
    from prompts import encabezado, indice_orden, limpiar_respuesta
    inv = {"taza": 1, "botella": 2, "libro": 2, "laptop": 1}
    assert encabezado("cuarto", inv).startswith("Índice de orden: 40/100 (6 objetos")
    assert encabezado("cocina", inv) == ""
    assert indice_orden(0) == 100 and indice_orden(30) == 5
    assert limpiar_respuesta("Índice de orden: 20/100\n1. Guarda la taza.") == "1. Guarda la taza."
