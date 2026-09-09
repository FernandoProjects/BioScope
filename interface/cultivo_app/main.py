import asyncio
import csv
import glob
import os
import random
import subprocess
import threading
import time

import cv2
import serial
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import vision_halos

app = FastAPI()
templates = Jinja2Templates(directory="templates")

BASE_DIR = os.path.expanduser("~/experimentos")
SERIAL_PORT = "/dev/ttyUSB0"
SERIAL_BAUD = 115200

# ---------- Estado global compartido ----------
latest_reading = {}   # se actualiza cada ~2s desde el hilo serial (o dummy)
current_session = None
ser = None
serial_write_lock = threading.Lock()


# ---------- Cámara ----------
class CameraManager:
    def __init__(self, index=0, focus_value=25):
        self.cap = cv2.VideoCapture(index)
        self.latest_frame = None
        self.lock = threading.Lock()

        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            self.cap.set(cv2.CAP_PROP_FOCUS, focus_value)
            threading.Thread(target=self._update_loop, daemon=True).start()
        else:
            print("ADVERTENCIA: no se pudo abrir la cámara en index", index)

    def _update_loop(self):
        while True:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.latest_frame = frame

    def get_frame(self):
        with self.lock:
            return None if self.latest_frame is None else self.latest_frame.copy()

    def save_snapshot(self, path):
        frame = self.get_frame()
        if frame is not None:
            cv2.imwrite(path, frame)
            return True
        return False


camera = CameraManager(index=0, focus_value=25)

# Precarga el modelo YOLO en un hilo aparte al arrancar, para que el primer
# ciclo de medición (5 min después de iniciar) no tenga que esperar la carga.
threading.Thread(target=vision_halos._get_model, daemon=True).start()


# ---------- Lector / escritor serial ----------
def parse_telemetry(line):
    # Formato del ESP32: setpoint,temp,hum,heater_effort,cooler_effort
    parts = line.split(",")
    if len(parts) != 5:
        return None
    try:
        setpoint, temp, hum, heater, cooler = map(float, parts)
        return {
            "setpoint": setpoint,
            "temp": temp,
            "humedad": hum,
            "heater_effort": heater,
            "cooler_effort": cooler,
        }
    except ValueError:
        return None


def send_serial_command(cmd: str) -> bool:
    if ser is None:
        print(f"[DUMMY] Comando '{cmd}' no enviado (sin serial real)")
        return False
    with serial_write_lock:
        ser.write((cmd + "\n").encode())
    return True


def serial_reader_loop():
    global latest_reading, ser
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2)
        print("Serial conectado en", SERIAL_PORT)
    except Exception as e:
        ser = None
        print(f"No se pudo abrir {SERIAL_PORT} ({e}). Usando datos DUMMY para pruebas.")

    while True:
        if ser is not None:
            try:
                raw = ser.readline().decode("utf-8", errors="ignore").strip()
                if not raw:
                    continue
                data = parse_telemetry(raw)
                if data is not None:
                    latest_reading = data
                else:
                    print("[ESP32]", raw)  # mensajes de estado, no telemetría
            except Exception as e:
                print("Error leyendo serial:", e)
        else:
            time.sleep(2)
            latest_reading = {
                "setpoint": 37.0,
                "temp": round(20 + 5 * random.random(), 1),
                "humedad": round(50 + 10 * random.random(), 1),
                "heater_effort": 0.0,
                "cooler_effort": 0.0,
            }


threading.Thread(target=serial_reader_loop, daemon=True).start()


# ---------- Sesión de experimento ----------
class Session:
    def __init__(self):
        self.id = time.strftime("%Y%m%d_%H%M%S")
        self.folder = os.path.join(BASE_DIR, self.id)
        self.img_folder = os.path.join(self.folder, "imagenes")
        os.makedirs(self.img_folder, exist_ok=True)

        self.csv_temp = os.path.join(self.folder, "data_temp_hum.csv")
        self.csv_halos = os.path.join(self.folder, "data_halos.csv")

        with open(self.csv_temp, "w", newline="") as f:
            csv.writer(f).writerow(["timestamp", "setpoint", "temp", "humedad", "heater_effort", "cooler_effort"])
        with open(self.csv_halos, "w", newline="") as f:
            csv.writer(f).writerow(
                ["timestamp", "halo1_mm2", "halo2_mm2", "halo3_mm2", "halo4_mm2", "foto", "disco_detectado"]
            )

        self.active = True
        self.tasks = []
        self.start_time = time.time()

        # Último resultado de visión, para mostrar en la interfaz
        self.latest_halos_mm2 = []
        self.latest_disco_detectado = False
        self.latest_annotated_path = None
        self.latest_measurement_time = None


# ---------- Tareas periódicas ----------
async def logger_temp_humedad(session):
    try:
        while True:
            with open(session.csv_temp, "a", newline="") as f:
                csv.writer(f).writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    latest_reading.get("setpoint"),
                    latest_reading.get("temp"),
                    latest_reading.get("humedad"),
                    latest_reading.get("heater_effort"),
                    latest_reading.get("cooler_effort"),
                ])
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass


async def logger_halos(session):
    contador = 0
    try:
        while True:
            img_name = f"{contador:03d}_{time.strftime('%H%M%S')}.jpg"
            img_path = os.path.join(session.img_folder, img_name)
            ok = camera.save_snapshot(img_path)
            if not ok:
                img_name = ""
                print("Advertencia: no se pudo capturar foto en este ciclo")

            halos_mm2 = []
            disco_detectado = False
            imagen_anotada = None

            if ok:
                try:
                    resultado = await asyncio.to_thread(vision_halos.medir_halos, img_path)
                    halos_mm2 = resultado["halos_mm2"]
                    disco_detectado = resultado["disco_detectado"]
                    imagen_anotada = resultado["imagen_anotada"]
                except Exception as e:
                    print("Error corriendo el modelo de visión:", e)

            # Guarda el último resultado para mostrarlo en la interfaz
            session.latest_halos_mm2 = halos_mm2
            session.latest_disco_detectado = disco_detectado
            session.latest_annotated_path = imagen_anotada
            session.latest_measurement_time = time.strftime("%Y-%m-%d %H:%M:%S")

            halos_fila = (halos_mm2 + [None, None, None, None])[:4]

            with open(session.csv_halos, "a", newline="") as f:
                csv.writer(f).writerow(
                    [time.strftime("%Y-%m-%d %H:%M:%S"), *halos_fila, img_name, disco_detectado]
                )

            contador += 1
            await asyncio.sleep(300)
    except asyncio.CancelledError:
        pass


def generar_timelapse(session):
    imgs = glob.glob(os.path.join(session.img_folder, "*.jpg"))
    if not imgs:
        return None
    output = os.path.join(session.folder, "timelapse.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", "10",
        "-pattern_type", "glob",
        "-i", os.path.join(session.img_folder, "*.jpg"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        output,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return output
    except subprocess.CalledProcessError as e:
        print("Error generando timelapse:", e.stderr.decode(errors="ignore"))
        return None


# ---------- Endpoints ----------
@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/session/start")
async def start_session():
    global current_session
    if current_session is not None and current_session.active:
        return {"error": "ya hay un experimento activo"}

    current_session = Session()
    enviado = send_serial_command("START")

    t1 = asyncio.create_task(logger_temp_humedad(current_session))
    t2 = asyncio.create_task(logger_halos(current_session))
    current_session.tasks = [t1, t2]

    return {"status": "iniciado", "session_id": current_session.id, "start_enviado": enviado}


@app.post("/session/stop")
async def stop_session():
    global current_session
    if current_session is None or not current_session.active:
        return {"error": "no hay experimento activo"}

    send_serial_command("STOP")

    current_session.active = False
    for t in current_session.tasks:
        t.cancel()
    await asyncio.gather(*current_session.tasks, return_exceptions=True)

    timelapse_path = generar_timelapse(current_session)

    result = {
        "status": "finalizado",
        "session_id": current_session.id,
        "csv_temp": current_session.csv_temp,
        "csv_halos": current_session.csv_halos,
        "timelapse": timelapse_path if timelapse_path else "no generado (sin imágenes)",
    }
    current_session = None
    return result


@app.get("/session/status")
def session_status():
    if current_session is None:
        return {"active": False, "latest_reading": latest_reading}

    return {
        "active": current_session.active,
        "session_id": current_session.id,
        "elapsed_min": round((time.time() - current_session.start_time) / 60, 1),
        "latest_reading": latest_reading,
        "latest_halos_mm2": current_session.latest_halos_mm2,
        "latest_disco_detectado": current_session.latest_disco_detectado,
        "latest_measurement_time": current_session.latest_measurement_time,
    }


class Setpoint(BaseModel):
    value: float


@app.post("/setpoint")
def set_setpoint(sp: Setpoint):
    if current_session is not None and current_session.active:
        return {"error": "no se puede cambiar el setpoint con un experimento activo"}
    if sp.value <= 0 or sp.value > 60:
        return {"error": "setpoint fuera de rango razonable"}
    enviado = send_serial_command(f"SET:{sp.value}")
    return {"status": "ok" if enviado else "dummy (sin serial real)", "setpoint": sp.value}


# ---------- Última foto anotada con los halos medidos ----------
@app.get("/latest_halo_image")
def latest_halo_image():
    if current_session is None or current_session.latest_annotated_path is None:
        return JSONResponse(status_code=404, content={"error": "sin imagen todavía"})
    if not os.path.exists(current_session.latest_annotated_path):
        return JSONResponse(status_code=404, content={"error": "archivo no encontrado"})
    return FileResponse(current_session.latest_annotated_path, media_type="image/jpeg")


# ---------- Video en vivo ----------
def mjpeg_generator():
    while True:
        frame = camera.get_frame()
        if frame is not None:
            _, jpeg = cv2.imencode(".jpg", frame)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
            )
        time.sleep(0.1)


@app.get("/video_feed")
def video_feed():
    return StreamingResponse(
        mjpeg_generator(), media_type="multipart/x-mixed-replace; boundary=frame"
    )