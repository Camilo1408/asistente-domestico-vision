# Imagen liviana: onnxruntime + Pillow + numpy. Modelos (COCO): yolo.onnx = YOLOv8n 320x320 (rápido, bajo consumo)
# y yolov8s_640.onnx = YOLOv8s 640x640 (más preciso). Se elige con VISION_MODELO en pi/.env.
# Regenerarlo (en un PC, no en la Pi):
#   pip install ultralytics onnx onnxslim && yolo export model=yolov8n.pt format=onnx imgsz=320 simplify=True
#   y copiar yolov8n.onnx como pi/vision/yolo.onnx
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY yolo.onnx /app/yolo.onnx
COPY yolov8s_640.onnx /app/yolov8s_640.onnx
COPY vision.py .
CMD ["python", "-u", "vision.py"]
