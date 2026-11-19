import importlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logica import AutoSugerencias  # noqa: E402
from prompts import CLASES_POR_MODO  # noqa: E402

DESORDEN = {"taza": 2, "botella": 1, "libro": 2}          # 5 objetos de cuarto
COCINA = {"manzana": 2, "zanahoria": 1}                   # 3 ingredientes


def nuevo():
    a = AutoSugerencias(CLASES_POR_MODO)
    a.configurar({"activo": True, "min_cuarto": 4, "min_cocina": 2, "intervalo_min": 10, "estable_s": 20,
                  "recordatorio_min": 60})
    return a


def test_espera_escena_estable():
    a = nuevo()
    assert a.evaluar(DESORDEN, 0) == []        # primera vez: empieza a contar estabilidad
    assert a.evaluar(DESORDEN, 10) == []       # aún no lleva 20 s
    assert a.evaluar(DESORDEN, 25) == ["cuarto"]


def test_un_objeto_que_pasa_reinicia_la_espera():
    a = nuevo()
    a.evaluar(DESORDEN, 0)
    a.evaluar({**DESORDEN, "taza": 3}, 15)     # cambió la escena
    assert a.evaluar({**DESORDEN, "taza": 3}, 25) == []
    assert a.evaluar({**DESORDEN, "taza": 3}, 40) == ["cuarto"]


def test_pocos_objetos_no_sugiere():
    a = nuevo()
    poco = {"taza": 1, "libro": 1}
    a.evaluar(poco, 0)
    assert a.evaluar(poco, 100) == []


def test_se_mantiene_durante_el_intervalo():
    a = nuevo()
    a.evaluar(DESORDEN, 0)
    assert a.evaluar(DESORDEN, 30) == ["cuarto"]
    a.marcar("cuarto", DESORDEN, 30)
    otra = {"taza": 4, "botella": 3, "libro": 2}
    a.evaluar(otra, 60)
    assert a.evaluar(otra, 300) == []          # cambió mucho pero no pasaron 10 min
    assert a.evaluar(otra, 30 + 601) == ["cuarto"]


def test_sin_cambios_solo_recordatorio():
    a = nuevo()
    a.evaluar(DESORDEN, 0)
    a.evaluar(DESORDEN, 30)
    a.marcar("cuarto", DESORDEN, 30)
    assert a.evaluar(DESORDEN, 30 + 700) == []          # igual que antes: no repite
    assert a.evaluar(DESORDEN, 30 + 3601) == ["cuarto"]  # recordatorio a la hora


def test_cocina_y_cuarto_independientes_y_desactivar():
    a = nuevo()
    escena = {**DESORDEN, **COCINA}
    a.evaluar(escena, 0)
    assert a.evaluar(escena, 30) == ["cuarto", "cocina"]  # el más lleno primero
    a.configurar({"activo": False})
    assert a.evaluar(escena, 60) == []


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode()


class Cliente:
    def __init__(self):
        self.pub = []

    def publish(self, topic, payload, retain=False):
        self.pub.append((topic, payload))

    def ultimo(self, topic):
        return next((p for t, p in reversed(self.pub) if t == topic), None)


def test_flujo_automatico_guarda_historial(tmp_path, monkeypatch):
    os.environ["DB_PATH"] = str(tmp_path / "h.db")
    import main
    m = importlib.reload(main)
    monkeypatch.setattr(m, "consultar_ollama", lambda prompt: "Índice de orden: 40/100. Guarda las tazas.")
    c = Cliente()
    for _ in range(5):
        m.on_message(c, None, Msg("casa/camara1/detecciones", json.dumps({"conteo": DESORDEN})))
    inv = m.inventario_activo()
    m.auto.evaluar(inv, 0)
    modos = m.auto.evaluar(inv, 30)
    assert modos == ["cuarto"]
    assert m.atender_pedido(c, "auto", modos[0]) is True
    resp = json.loads(c.ultimo("casa/asistente/respuesta"))
    assert resp["origen"] == "auto" and resp["modo"] == "cuarto" and "tazas" in resp["texto"]
    hist = json.loads(c.ultimo("casa/asistente/historial"))
    assert hist["n"] == 1 and hist["items"][0]["modo"] == "cuarto"


def test_error_del_llm_en_automatico_no_borra_la_sugerencia(tmp_path, monkeypatch):
    os.environ["DB_PATH"] = str(tmp_path / "h.db")
    import main
    m = importlib.reload(main)

    def falla(prompt):
        raise TimeoutError("lento")
    monkeypatch.setattr(m, "consultar_ollama", falla)
    c = Cliente()
    m.on_message(c, None, Msg("casa/camara1/detecciones", json.dumps({"conteo": DESORDEN})))
    assert m.atender_pedido(c, "auto", "cuarto") is False
    assert c.ultimo("casa/asistente/respuesta") is None
