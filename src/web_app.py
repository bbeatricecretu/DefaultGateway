import cv2
import json
import os
import sys
import threading
import uuid

# Ensure the src/ directory is on the path regardless of where the script is launched from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, Response, jsonify
from vision_core import VisionCore
from db_handler import AirportDatabase

app = Flask(__name__)

# Resolve paths relative to this file so the app works regardless of
# the working directory it is launched from.
_SRC_DIR     = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SRC_DIR)

# Încărcăm configurația
_CONFIG_PATH = os.path.join(_PROJECT_DIR, 'config_camere.json')
with open(_CONFIG_PATH, 'r') as f:
    config = json.load(f)

# Baza de date centrală
db = AirportDatabase(os.path.join(_PROJECT_DIR, "airport.db"))

# Dicționar pentru a stoca cadrele cele mai recente din fiecare cameră
# Astfel interfața web preia mereu ultimul frame procesat, fără lag
latest_frames = {}

def process_camera_stream(camera_id, sursa):
    """Rulează într-un thread separat pentru fiecare cameră, cu loguri de eroare."""
    print(f"[START] Se inițializează {camera_id}. Sursa: {sursa}")
    
    try:
        vision = VisionCore()
        cap = cv2.VideoCapture(sursa)
        
        if not cap.isOpened():
            print(f"[EROARE CRITICĂ] Nu s-a putut deschide video-ul pentru {camera_id}!")
            return

        local_track_to_global_id = {}
        cadre_procesate = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                print(f"[INFO] {camera_id} a ajuns la finalul clipului. O luăm de la capăt.")
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
                
            cadre_procesate += 1
            if cadre_procesate % 50 == 0:
                print(f"[RUNNING] {camera_id} procesează cadrul {cadre_procesate}...")
                
            # Analiza vizuală
            results = vision.process_frame(frame)
            
            if results.boxes.id is not None:
                boxes = results.boxes.xyxy.cpu().numpy()
                track_ids = results.boxes.id.cpu().numpy()
                
                for box, track_id in zip(boxes, track_ids):
                    global_id = local_track_to_global_id.get(track_id)
                    
                    # Extragem cum arată persoana ÎN ACEST CADRU
                    vector_curent = vision.extract_embedding(frame, box)
                    
                    # CORECLAT: Tratăm "Se cauta..." la fel ca pe un ID lipsă
                    if not global_id or global_id == "Se cauta...":
                        if vector_curent is not None:
                            matched_id = db.find_best_match(vector_curent, threshold=0.75)
                            
                            if matched_id:
                                global_id = matched_id
                                db.log_movement(global_id, camera_id)
                            else:
                                # Persoană complet nouă
                                id_nou = f"Pasager_{str(uuid.uuid4())[:4]}"
                                db.register_passenger(id_nou, "Necunoscut", "N/A", "2026-03-07 14:00:00", vector_curent)
                                global_id = id_nou
                                db.log_movement(global_id, camera_id)
                        else:
                            global_id = "Se cauta..."
                    else:
                        # ACTUALIZARE DINAMICĂ: Doar dacă are un ID real, îi actualizăm profilul
                        if vector_curent is not None:
                            db.update_vector(global_id, vector_curent, alpha=0.05)
                    
                    local_track_to_global_id[track_id] = global_id
                    
                    # CORECLAT: Desenăm mereu chenarul. Portocaliu pentru căutare, Verde pentru ID confirmat
                    x1, y1, x2, y2 = map(int, box)
                    culoare = (0, 255, 0) if global_id != "Se cauta..." else (0, 165, 255)
                    
                    cv2.rectangle(frame, (x1, y1), (x2, y2), culoare, 2)
                    cv2.putText(frame, f"ID: {global_id}", (x1, y1 - 10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, culoare, 2)

            # Trimitem cadrul către web
            ret_encode, buffer = cv2.imencode('.jpg', frame)
            if ret_encode:
                latest_frames[camera_id] = buffer.tobytes()

    except Exception as e:
        print(f"[CRASH THREAD] Eroare fatală în {camera_id}: {str(e)}")

def start_camera_threads():
    """Pornește procesarea pentru toate camerele din JSON."""
    for cam_id, date_cam in config["camere"].items():
        thread = threading.Thread(
            target=process_camera_stream, 
            args=(cam_id, date_cam["sursa"]),
            daemon=True
        )
        thread.start()
        print(f"[INFO] Thread pornit pentru {cam_id}")

def generate_mjpeg(camera_id):
    """Generatorul care trimite frame-urile către browser."""
    while True:
        frame_bytes = latest_frames.get(camera_id)
        if frame_bytes:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# --- RUTELE FLASK ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config')
def get_config():
    return jsonify(config)

@app.route('/map')
def map_view():
    return render_template('map.html')

@app.route('/video_feed/<camera_id>')
def video_feed(camera_id):
    return Response(generate_mjpeg(camera_id), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    start_camera_threads()
    # Rulăm serverul pe portul 5000, accesibil din rețea
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)