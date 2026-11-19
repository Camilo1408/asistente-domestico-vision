# Imagen liviana: onnxruntime + Pillow + numpy. El modelo yolo.onnx (YOLOv8n COCO, 320x320) va en esta carpeta.
# Regenerarlo (en un PC, no en la Pi):
#   pip install ultralytics onnx onnxslim && yolo export model=yolov8n.pt format=onnx imgsz=320 simplify=True
#   y copiar yolov8n.onnx como pi/vision/yolo.onnx
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY yolo.onnx /app/yolo.onnx
COPY vision.py .
CMD ["python", "-u", "vision.py"]
