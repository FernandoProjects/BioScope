"""
Módulo de visión de BioScope: mide halos de inhibición con YOLO (segmentación).

Pipeline (basado en Prueba7):
  1. Preprocesado suave (bilateral + unsharp) solo para la inferencia.
  2. Discos (clase 0) -> escala px/mm (promedio, disco = 7 mm).
  3. Halos (clase 1) asociados al disco que contienen.
  4. Reconstrucción radial del halo (corrige recortes de la máscara).
  5. Orden espacial H1..H4 (arriba-izq, arriba-der, abajo-izq, abajo-der).

Interfaz con main.py (sin cambios):
    medir_halos(ruta_imagen, guardar_anotada=True) ->
        {"halos_mm2": [...], "disco_detectado": bool, "imagen_anotada": ruta | None}
    _get_model()  (se precarga en un hilo al arrancar)

Modelo: acepta best.pt o best.onnx dentro de vision_model/ (prefiere .pt si existen ambos,
salvo que se defina BIOSCOPE_MODEL con la ruta). Sin cv2.imshow: funciona headless.
"""

import csv
import os
import sys

import cv2
import numpy as np
from ultralytics import YOLO

# ---------------------------------------------------------------- configuración
_DIR = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(_DIR, "vision_model")


def _resolver_modelo():
    env = os.environ.get("BIOSCOPE_MODEL")
    if env:
        return env
    for nombre in ("best.pt", "best.onnx"):
        ruta = os.path.join(_MODEL_DIR, nombre)
        if os.path.exists(ruta):
            return ruta
    return os.path.join(_MODEL_DIR, "best.pt")  # para que el error sea claro


MODEL_PATH = _resolver_modelo()

DIAMETRO_DISCO_MM = 7.0
CLASE_DISCO = 0
CLASE_HALO = 1

CONF = 0.25
IOU = 0.20
AREA_MIN_DISCO_PX = 100
AREA_MIN_HALO_MM2 = 38.5   # por debajo se descarta (ruido / halo inexistente)

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = YOLO(MODEL_PATH, task="segment")
    return _model


# ---------------------------------------------------------------- utilidades
def preprocesar_suave_para_yolo(img_bgr):
    suave = cv2.bilateralFilter(img_bgr, d=5, sigmaColor=35, sigmaSpace=35)
    gauss = cv2.GaussianBlur(suave, (0, 0), 2.0)
    return cv2.addWeighted(suave, 1.3, gauss, -0.3, 0)


def reconstruir_curvatura_radial(poly_int, cx, cy):
    """Regenera un contorno redondeado alrededor del disco (36 ángulos, radio mediano)."""
    pts = poly_int.reshape(-1, 2)
    dx = pts[:, 0] - cx
    dy = pts[:, 1] - cy
    radios = np.sqrt(dx ** 2 + dy ** 2)
    angulos = np.arctan2(dy, dx)

    radio_ref = np.percentile(radios, 75)
    nuevos = []
    for ang in np.linspace(-np.pi, np.pi, 36):
        # diferencia angular circular (evita el salto en ±pi)
        diff = np.abs(np.arctan2(np.sin(angulos - ang), np.cos(angulos - ang)))
        cercanos = radios[diff < (np.pi / 18)]
        r = np.median(cercanos) if len(cercanos) > 0 else radio_ref
        if r < radio_ref * 0.75:
            r = radio_ref
        nuevos.append([int(cx + r * np.cos(ang)), int(cy + r * np.sin(ang))])

    return cv2.convexHull(np.array(nuevos, dtype=np.int32).reshape((-1, 1, 2)))


def ordenar_cuadrantes(halos):
    if not halos:
        return []
    por_y = sorted(halos, key=lambda h: h["cY"])
    if len(por_y) >= 4:
        arriba = sorted(por_y[:2], key=lambda h: h["cX"])
        abajo = sorted(por_y[2:4], key=lambda h: h["cX"])
        return [arriba[0], arriba[1], abajo[0], abajo[1]]
    return sorted(halos, key=lambda h: (h["cY"] // 100, h["cX"]))


# ---------------------------------------------------------------- API principal
def medir_halos(ruta_imagen, guardar_anotada=True):
    """
    Devuelve {"halos_mm2": [H1..Hn], "disco_detectado": bool, "imagen_anotada": ruta|None}.
    halos_mm2 viene ordenado espacialmente (H1 arriba-izq ... H4 abajo-der).
    """
    img = cv2.imread(ruta_imagen)
    if img is None:
        return {"halos_mm2": [], "disco_detectado": False, "imagen_anotada": None}

    model = _get_model()
    results = model.predict(
        source=preprocesar_suave_para_yolo(img),
        conf=CONF, iou=IOU, retina_masks=True, verbose=False,
    )

    img_draw = img.copy()
    halos_mm2 = []
    disco_detectado = False

    for r in results:
        if r.masks is None:
            continue
        masks = r.masks.xy
        classes = r.boxes.cls.cpu().numpy()

        # 1. Discos -> escala
        escalas, centros = [], []
        for idx, cls in enumerate(classes):
            if int(cls) != CLASE_DISCO:
                continue
            poly = masks[idx]
            if len(poly) < 3:
                continue
            area_px = cv2.contourArea(poly.astype(np.float32))
            if area_px <= AREA_MIN_DISCO_PX:
                continue
            escalas.append(2.0 * np.sqrt(area_px / np.pi) / DIAMETRO_DISCO_MM)
            M = cv2.moments(poly.astype(np.float32))
            if M["m00"] != 0:
                centros.append((int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])))
            cv2.polylines(img_draw, [poly.astype(np.int32).reshape((-1, 1, 2))],
                          True, (0, 255, 0), 2)

        if not escalas:
            continue
        disco_detectado = True
        px_por_mm = float(np.mean(escalas))

        # 2. Halos con reconstrucción radial
        detectados = []
        usados = set()  # un disco solo puede pertenecer a un halo
        for idx, cls in enumerate(classes):
            if int(cls) != CLASE_HALO:
                continue
            poly = masks[idx]
            if len(poly) < 3:
                continue
            poly_int = poly.astype(np.int32)

            asociado = None
            for k, (dx, dy) in enumerate(centros):
                if k in usados:
                    continue
                if cv2.pointPolygonTest(poly_int, (float(dx), float(dy)), False) >= 0:
                    asociado = k
                    break
            if asociado is None:
                continue
            usados.add(asociado)
            cx, cy = centros[asociado]

            recon = reconstruir_curvatura_radial(poly_int, cx, cy)
            area_mm2 = cv2.contourArea(recon.astype(np.float32)) / (px_por_mm ** 2)
            if area_mm2 < AREA_MIN_HALO_MM2:
                continue
            detectados.append({"polygon": recon, "area_mm2": area_mm2, "cX": cx, "cY": cy})

        # 3. Orden + dibujo
        for n, h in enumerate(ordenar_cuadrantes(detectados), start=1):
            halos_mm2.append(round(float(h["area_mm2"]), 2))
            cv2.polylines(img_draw, [h["polygon"]], True, (0, 255, 255), 2)
            texto = f"H{n}: {h['area_mm2']:.1f} mm2"
            font = cv2.FONT_HERSHEY_SIMPLEX
            (w, hh), _ = cv2.getTextSize(texto, font, 0.45, 1)
            cv2.rectangle(img_draw, (h["cX"] - 5, h["cY"] - hh - 5),
                          (h["cX"] + w + 5, h["cY"] + 5), (0, 0, 0), -1)
            cv2.putText(img_draw, texto, (h["cX"], h["cY"]), font, 0.45, (255, 255, 255), 1)

    ruta_anotada = None
    if guardar_anotada:
        base, ext = os.path.splitext(ruta_imagen)
        ruta_anotada = f"{base}_anotada{ext}"
        cv2.imwrite(ruta_anotada, img_draw)

    return {
        "halos_mm2": halos_mm2,
        "disco_detectado": disco_detectado,
        "imagen_anotada": ruta_anotada,
    }


# ---------------------------------------------------------------- modo standalone
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 vision_program.py <carpeta_con_imagenes>")
        sys.exit(1)

    carpeta = sys.argv[1]
    salida = os.path.join(carpeta, "resultados_vision.csv")
    with open(salida, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["archivo", "disco_detectado", "halo1", "halo2", "halo3", "halo4"])
        for archivo in sorted(os.listdir(carpeta)):
            if not archivo.lower().endswith((".png", ".jpg", ".jpeg")) or "_anotada" in archivo:
                continue
            print(f"Procesando {archivo}...")
            res = medir_halos(os.path.join(carpeta, archivo))
            halos = res["halos_mm2"] + [None] * (4 - len(res["halos_mm2"]))
            w.writerow([archivo, res["disco_detectado"], *halos[:4]])
    print(f"Listo. Resultados en {salida}")