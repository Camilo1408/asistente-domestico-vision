import importlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class Msg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload.encode() if isinstance(payload, str) else payload


class ClienteFalso:
    def __init__(self):
        self.pub = []

    def publish(self, topic, payload, retain=False):
        self.pub.append((topic, payload))

    def ultimo(self, topic):
        return next((p for t, p in reversed(self.pub) if t == topic), None)


def cargar(tmp_path):
    os.environ["DB_PATH"] = str(tmp_path / "h.db")
    import main
    return importlib.reload(main)


def det(conteo):
    return json.dumps({"conteo": conteo, "latencia_ms": 1})


def test_inventario_por_camara_y_camara_activa(tmp_path):
    m = cargar(tmp_path)
    c = ClienteFalso()
    m.on_message(c, None, Msg("casa/camara1/detecciones", det({"tomate": 3})))
    m.on_message(c, None, Msg("casa/iphone/detecciones", det({"taza": 2, "libro": 1})))
    assert json.loads(c.ultimo("casa/camara1/inventario"))["tomate"] == 3
    assert json.loads(c.ultimo("casa/iphone/inventario"))["taza"] == 2
    # la activa por defecto es camara1: casa/inventario refleja solo camara1
    assert json.loads(c.ultimo("casa/inventario"))["tomate"] == 3
    m.on_message(c, None, Msg("casa/asistente/camara", "iphone"))
    assert m.camara_activa == "iphone"
    assert json.loads(c.ultimo("casa/inventario"))["taza"] == 2


def test_topicos_invalidos_se_ignoran(tmp_path):
    m = cargar(tmp_path)
    c = ClienteFalso()
    m.on_message(c, None, Msg("casa/asistente/detecciones", det({"taza": 1})))
    m.on_message(c, None, Msg("casa/asistente/camara", "asistente"))
    assert c.pub == [] and m.camara_activa == "camara1"


def test_sin_lecturas_de_camara_activa(tmp_path):
    m = cargar(tmp_path)
    c = ClienteFalso()
    m.on_message(c, None, Msg("casa/asistente/camara", "iphone"))
    m.atender_pedido(c, "boton")
    assert "iphone" in json.loads(c.ultimo("casa/asistente/respuesta"))["texto"]
