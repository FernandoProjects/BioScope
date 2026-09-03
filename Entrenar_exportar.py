from pathlib import Path
from ultralytics import YOLO

ruta_data = Path(r"C:\Users\User\Documents\Visión Artificial\BioScope\Halos-2\data.yaml")

model = YOLO('yolov8n-seg.pt')

results = model.train(
    data=str(ruta_data),
    epochs=50,
    imgsz=640,
    batch=8,
    name='modelo_halos_bioscope_v2'
)

modelo_entrenado = YOLO(results.save_dir / 'weights' / 'best.pt')

ruta_onnx = modelo_entrenado.export(format='onnx', imgsz=640, dynamic=False)

print(f"\n ENTRENAMIENTO Y EXPORTACIÓN COMPLETADOS")
print(f" Pesos PyTorch (.pt): {results.save_dir}\\weights\\best.pt")
print(f" Modelo ONNX para Raspberry Pi 4 (.onnx): {ruta_onnx}")