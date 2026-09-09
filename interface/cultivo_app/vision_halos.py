"""
Módulo de inferencia con YOLO (Ultralytics) para medir discos y halos de inhibición.
El modelo se carga UNA sola vez al importar el módulo, no en cada llamada.
"""

import os
import csv
import sys

import cv2
import numpy as np
from ultralytics import YOLO

MODEL_PATH = os.path.expanduser("~/cultivo_app/modelo_halos_bioscope/best.pt")
DIAMETRO_DISCO_MM = 7.0
CLASE_DISCO = 0
CLASE_HALO = 1
CONF_THRESHOLD = 0.5

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = YOLO(MODEL_PATH)
    return _model


def medir_halos(ruta_imagen, guardar_anotada=True):
    """
    Corre el modelo sobre una imagen y devuelve las áreas de los halos detectados.

    Retorna:
        {
            "halos_mm2": [area1, area2, ...],
            "disco_detectado": bool,
            "imagen_anotada": ruta o None
        }
    """
    model = _get_model()
    img = cv2.imread(ruta_imagen)
    if img is None:
        return {"halos_mm2": [], "disco_detectado": False, "imagen_anotada": None}

    results = model.predict(source=ruta_imagen, conf=CONF_THRESHOLD, verbose=False)

    halos_mm2 = []
    disco_detectado = False

    for r in results:
        if r.masks is None:
            continue

        masks = r.masks.xy
        classes = r.boxes.cls.cpu().numpy()

        pixeles_por_mm = None
        for idx, cls in enumerate(classes):
            if int(cls) == CLASE_DISCO:
                polygon = masks[idx]
                area_px = cv2.contourArea(polygon.astype(np.float32))
                if area_px > 0:
                    radio_px = np.sqrt(area_px / np.pi)
                    diametro_px = radio_px * 2.0
                    pixeles_por_mm = diametro_px / DIAMETRO_DISCO_MM
                    disco_detectado = True

                    pts = polygon.astype(np.int32).reshape((-1, 1, 2))
                    cv2.polylines(img, [pts], isClosed=True, color=(0, 255, 0), thickness=3)
                break

        if pixeles_por_mm:
            halo_count = 0
            for idx, cls in enumerate(classes):
                if int(cls) == CLASE_HALO:
                    halo_count += 1
                    polygon = masks[idx]
                    area_px = cv2.contourArea(polygon.astype(np.float32))
                    area_mm2 = area_px / (pixeles_por_mm ** 2)
                    halos_mm2.append(round(area_mm2, 2))

                    pts = polygon.astype(np.int32).reshape((-1, 1, 2))
                    cv2.polylines(img, [pts], isClosed=True, color=(0, 255, 255), thickness=3)

                    M = cv2.moments(polygon.astype(np.float32))
                    if M["m00"] != 0:
                        cX = int(M["m10"] / M["m00"])
                        cY = int(M["m01"] / M["m00"])
                        texto = f"H{halo_count}: {area_mm2:.1f} mm2"
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        (w_txt, h_txt), _ = cv2.getTextSize(texto, font, 0.6, 2)
                        cv2.rectangle(img, (cX - 5, cY - h_txt - 5), (cX + w_txt + 5, cY + 5), (0, 0, 0), -1)
                        cv2.putText(img, texto, (cX, cY), font, 0.6, (255, 255, 255), 2)

    ruta_anotada = None
    if guardar_anotada:
        base, ext = os.path.splitext(ruta_imagen)
        ruta_anotada = f"{base}_anotada{ext}"
        cv2.imwrite(ruta_anotada, img)

    return {
        "halos_mm2": halos_mm2,
        "disco_detectado": disco_detectado,
        "imagen_anotada": ruta_anotada,
    }


# ---- Modo standalone: probar el modelo en una carpeta de imágenes ----
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 vision_halos.py <carpeta_con_imagenes>")
        sys.exit(1)

    carpeta = sys.argv[1]
    resultados_csv = os.path.join(carpeta, "resultados_vision.csv")

    with open(resultados_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["archivo", "disco_detectado", "halo1", "halo2", "halo3", "halo4"])

        for archivo in sorted(os.listdir(carpeta)):
            if not archivo.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            ruta = os.path.join(carpeta, archivo)
            print(f"Procesando {archivo}...")
            r = medir_halos(ruta, guardar_anotada=True)
            halos = r["halos_mm2"] + [None] * (4 - len(r["halos_mm2"]))
            writer.writerow([archivo, r["disco_detectado"], *halos[:4]])

    print(f"Listo. Resultados en {resultados_csv}")