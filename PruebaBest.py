import os
import cv2
import numpy as np
from ultralytics import YOLO

MODEL_PT_PATH = r"C:\Users\Clases\Documents\BS\best.pt"
CARPETA_CULTIVOS = r"C:\Users\Clases\Documents\BS\imagenes"
DIAMETRO_DISCO_MM = 7.0

model = YOLO(MODEL_PT_PATH, task='segment')

def preprocesar_suave_para_yolo(img_bgr):
    suave = cv2.bilateralFilter(img_bgr, d=5, sigmaColor=35, sigmaSpace=35)
    gauss = cv2.GaussianBlur(suave, (0, 0), 2.0)
    return cv2.addWeighted(suave, 1.3, gauss, -0.3, 0)

def reconstruir_curvatura_radial(poly_int, cX_disco, cY_disco):
    pts = poly_int.reshape(-1, 2)
    dx = pts[:, 0] - cX_disco
    dy = pts[:, 1] - cY_disco
    radios = np.sqrt(dx**2 + dy**2)
    angulos = np.arctan2(dy, dx)
    
    # Filtrar radios razonables eliminando el corte plano
    radio_ref = np.percentile(radios, 75)
    
    # Reconstruir 36 puntos a lo largo de 360 grados
    angulos_grid = np.linspace(-np.pi, np.pi, 36)
    nuevos_pts = []
    
    for ang in angulos_grid:
        diffs = np.abs(angulos - ang)
        cercanos = radios[diffs < (np.pi / 18)]
        if len(cercanos) > 0:
            r = np.median(cercanos)
            # Evitar que tome el radio acortado del plano
            if r < radio_ref * 0.75:
                r = radio_ref
        else:
            r = radio_ref
            
        x = int(cX_disco + r * np.cos(ang))
        y = int(cY_disco + r * np.sin(ang))
        nuevos_pts.append([x, y])
        
    poly_curvo = np.array(nuevos_pts, dtype=np.int32).reshape((-1, 1, 2))
    return cv2.convexHull(poly_curvo)

def ordenar_cuadrantes(halos_info):
    if len(halos_info) == 0:
        return []
    halos_ordenados_y = sorted(halos_info, key=lambda item: item['cY'])
    if len(halos_ordenados_y) >= 4:
        arriba = sorted(halos_ordenados_y[:2], key=lambda item: item['cX'])
        abajo = sorted(halos_ordenados_y[2:4], key=lambda item: item['cX'])
        return [arriba[0], arriba[1], abajo[0], abajo[1]]
    else:
        return sorted(halos_info, key=lambda item: (item['cY'] // 100, item['cX']))

print("--- RECONSTRUCCIÓN RADIAL DE HALOS TRUNCADOS ---")

salir = False

for raiz, carpetas, archivos in os.walk(CARPETA_CULTIVOS):
    if salir:
        break
        
    archivos_ordenados = sorted([f for f in archivos if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    
    for archivo in archivos_ordenados:
        ruta_imagen = os.path.join(raiz, archivo)
        img_original = cv2.imread(ruta_imagen)
        if img_original is None:
            continue
            
        img_procesada = preprocesar_suave_para_yolo(img_original)
        
        results = model.predict(
            source=img_procesada, 
            conf=0.25, 
            iou=0.20, 
            retina_masks=True, 
            verbose=False
        )
        
        img_draw = img_original.copy()
        
        for r in results:
            if r.masks is None:
                continue
            
            masks = r.masks.xy
            classes = r.boxes.cls.cpu().numpy()
            
            # 1. DISCOS (Clase 0)
            escalas_px_mm = []
            centros_discos = []
            
            for idx, cls in enumerate(classes):
                if int(cls) == 0:
                    polygon = masks[idx]
                    area_px = cv2.contourArea(polygon.astype(np.float32))
                    if area_px > 100:
                        radio_px = np.sqrt(area_px / np.pi)
                        escalas_px_mm.append((radio_px * 2.0) / DIAMETRO_DISCO_MM)
                        
                        M = cv2.moments(polygon.astype(np.float32))
                        if M["m00"] != 0:
                            cX = int(M["m10"] / M["m00"])
                            cY = int(M["m01"] / M["m00"])
                            centros_discos.append((cX, cY))
                        
                        pts = polygon.astype(np.int32).reshape((-1, 1, 2))
                        cv2.polylines(img_draw, [pts], isClosed=True, color=(0, 255, 0), thickness=2)

            pixeles_por_mm = np.mean(escalas_px_mm) if len(escalas_px_mm) > 0 else None
            
            # 2. HALOS CON RECONSTRUCCIÓN RADIAL (Clase 1)
            if pixeles_por_mm:
                halos_detectados = []
                
                for idx, cls in enumerate(classes):
                    if int(cls) == 1:
                        polygon = masks[idx]
                        poly_int = polygon.astype(np.int32)
                        
                        # Buscar el disco perteneciente a este halo
                        disco_asociado = None
                        for (dx, dy) in centros_discos:
                            dist = cv2.pointPolygonTest(poly_int, (float(dx), float(dy)), False)
                            if dist >= 0:
                                disco_asociado = (dx, dy)
                                break
                        
                        if disco_asociado is None:
                            continue
                        
                        # Reconstruir curvatura eliminado el truncamiento de YOLO
                        poly_reconstruido = reconstruir_curvatura_radial(poly_int, disco_asociado[0], disco_asociado[1])
                        
                        area_px = cv2.contourArea(poly_reconstruido.astype(np.float32))
                        area_total_mm2 = area_px / (pixeles_por_mm ** 2)
                        
                        if area_total_mm2 < 38.5:
                            continue
                            
                        halos_detectados.append({
                            'polygon': poly_reconstruido,
                            'area_mm2': area_total_mm2,
                            'cX': disco_asociado[0],
                            'cY': disco_asociado[1]
                        })

                # Ordenar espacialmente H1, H2, H3, H4
                halos_ordenados = ordenar_cuadrantes(halos_detectados)
                
                # 3. DIBUJAR
                for idx, halo in enumerate(halos_ordenados):
                    num_halo = idx + 1
                    
                    cv2.polylines(img_draw, [halo['polygon']], isClosed=True, color=(0, 255, 255), thickness=2)
                    
                    cX, cY = halo['cX'], halo['cY']
                    texto = f"H{num_halo}: {halo['area_mm2']:.1f} mm2"
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    (w_txt, h_txt), _ = cv2.getTextSize(texto, font, 0.45, 1)
                    
                    cv2.rectangle(img_draw, (cX - 5, cY - h_txt - 5), (cX + w_txt + 5, cY + 5), (0, 0, 0), -1)
                    cv2.putText(img_draw, texto, (cX, cY), font, 0.45, (255, 255, 255), 1)

        cv2.putText(img_draw, f"Reconstruccion Radial | {archivo}", (15, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.imshow('BioScope - Visualizacion de Halos Corregida', img_draw)
        
        key = cv2.waitKey(200) & 0xFF
        if key == ord('q') or key == 27:
            salir = True
            break

cv2.destroyAllWindows()
