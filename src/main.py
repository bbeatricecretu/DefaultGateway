import cv2
import os
import datetime
from db_handler import AirportDatabase
from vision_core import VisionCore

def enroll_known_passengers(vision, db, dataset_path):
    """Încarcă pozele din folderul de date și le populează în baza de date ca profil de bază."""
    print("[INFO] Începe înregistrarea pasagerilor cunoscuți din dataset...")
    if not os.path.exists(dataset_path):
        os.makedirs(dataset_path)
        print(f"Te rog să pui imaginile cu pasageri în: {dataset_path}")
        return

    for filename in os.listdir(dataset_path):
        if filename.endswith((".jpg", ".png", ".jpeg")):
            person_id = os.path.splitext(filename)[0]
            img_path = os.path.join(dataset_path, filename)
            frame = cv2.imread(img_path)
            
            # Simulăm un bounding box pentru toată imaginea (presupunând că poza e deja doar cu persoana/fața)
            h, w = frame.shape[:2]
            bbox = [0, 0, w, h]
            
            # Extragem amprenta biometrică inițială (cea curată, de la pașaport)
            vector = vision.extract_embedding(frame, bbox)
            
            # Setăm date simulate pentru demonstrație
            timp_zbor = (datetime.datetime.now() + datetime.timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")
            db.register_passenger(person_id, f"Pasager_{person_id}", "B12", timp_zbor, vector)
            print(f" -> Înregistrat {person_id} cu succes.")

def run_camera_stream(camera_id, video_source, vision, db):
    """Procesează un stream video continuu."""
    print(f"[INFO] Pornire stream pentru {camera_id}...")
    cap = cv2.VideoCapture(video_source)
    
    # Un dicționar local pentru a nu interoga baza de date la fiecare cadru pentru aceeași persoană urmărită de YOLO
    local_track_to_global_id = {}

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        # 1. Detecție și Tracking local
        results = vision.process_frame(frame)
        
        if results.boxes.id is not None:
            boxes = results.boxes.xyxy.cpu().numpy()
            track_ids = results.boxes.id.cpu().numpy()
            
            for box, track_id in zip(boxes, track_ids):
                global_id = local_track_to_global_id.get(track_id)
                
                # 2. Dacă YOLO urmărește pe cineva nou, facem Re-Identificarea Globală facială
                if not global_id:
                    vector = vision.extract_embedding(frame, box)
                    
                    # Verificăm dacă am putut extrage o față validă în acest frame
                    if vector is not None:
                        # Am scăzut threshold-ul la 0.60 pentru că FaceNet calculează distanțele diferit
                        matched_id = db.find_best_match(vector, threshold=0.60)
                        
                        if matched_id:
                            global_id = matched_id
                            local_track_to_global_id[track_id] = global_id
                            db.log_movement(global_id, camera_id)
                        else:
                            global_id = "Necunoscut"
                    else:
                        # Dacă persoana e cu spatele, așteptăm următoarele frame-uri
                        global_id = "Se cauta fata..."
                        
                # Desenăm pe cadru pentru vizualizare
                x1, y1, x2, y2 = map(int, box)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"ID: {global_id}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                
        # Afișare (Apasă 'q' pentru a închide fereastra camerei)
        cv2.imshow(f"Camera Feed: {camera_id}", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    db = AirportDatabase("../airport.db")
    vision = VisionCore()
    
    # 1. Populează datele (Pune poze în folderul known_faces cu numele de ex: ID12345.jpg)
    enroll_known_passengers(vision, db, "../datasets/known_faces")
    
    # 2. Pornește analiza camerei
    # Pentru test, poți înlocui 0 (webcam) cu o cale către un fișier video din "../datasets/videos/test.mp4"
    run_camera_stream("Security_Main", "/Users/vlad/Desktop/DefaultGateway/datasets/videos/fight_0085.mpeg", vision, db)