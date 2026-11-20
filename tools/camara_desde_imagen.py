#!/usr/bin/env python3
"""Cámara MJPEG a partir de una foto: sirve la imagen como stream en http://0.0.0.0:PUERTO/video.

Sirve para probar o demostrar todo el sistema (go2rtc -> vision -> cerebro -> LLM -> Home Assistant)
con una escena fija, por ejemplo una foto tomada con el iPhone. Solo usa la librería estándar.

  python3 camara_desde_imagen.py foto.jpg 8081 [fps]
  # en pi/.env:  IPHONE_URL=http://asistente-demo-cam:8081/video   (contenedor en la red asistente_default)
"""
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FOTO = open(sys.argv[1], "rb").read()
PUERTO = int(sys.argv[2]) if len(sys.argv) > 2 else 8081
FPS = float(sys.argv[3]) if len(sys.argv) > 3 else 5


class Camara(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/foto") or self.path.startswith("/capture"):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(FOTO)))
            self.end_headers()
            self.wfile.write(FOTO)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=cuadro")
        self.end_headers()
        try:
            while True:
                self.wfile.write(b"--cuadro\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(FOTO)).encode() + b"\r\n\r\n" + FOTO + b"\r\n")
                self.wfile.flush()
                time.sleep(1 / FPS)
        except (BrokenPipeError, ConnectionResetError):
            pass


print(f"Cámara de imagen en :{PUERTO}/video ({len(FOTO) // 1024} KB, {FPS} fps)", flush=True)
ThreadingHTTPServer(("0.0.0.0", PUERTO), Camara).serve_forever()
