import cv2
import torch
import numpy as np
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

from ultralytics import YOLO
from facenet_pytorch import MTCNN, InceptionResnetV1
from PIL import Image

class VisionCore:
    def __init__(self):
        # 1. Device pentru YOLO (Accelerare GPU / MPS)
        if torch.backends.mps.is_available():
            self.device_yolo = torch.device("mps")
            print("[INFO] YOLO rulează pe Apple MPS (GPU).")
        elif torch.cuda.is_available():
            self.device_yolo = torch.device("cuda")
        else:
            self.device_yolo = torch.device("cpu")
            
        # 2. Device pentru FaceNet (Forțat pe CPU pentru a evita bug-ul de Adaptive Pooling din MPS)
        self.device_face = torch.device("cpu")
        print("[INFO] MTCNN/FaceNet rulează pe CPU (Bypass bug Apple Silicon).")
            
        # Încărcare modele pe dispozitivele lor specifice
        self.detector = YOLO("yolov8n.pt")
        self.detector.to(self.device_yolo) # YOLO merge pe GPU
        
        self.mtcnn = MTCNN(keep_all=False, device=self.device_face) # MTCNN pe CPU
        self.resnet = InceptionResnetV1(pretrained='vggface2').eval().to(self.device_face) # ResNet pe CPU

    def extract_embedding(self, frame, bbox):
        """Caută fața persoanei decupate și returnează vectorul facial."""
        x1, y1, x2, y2 = map(int, bbox)
        
        h, w = frame.shape[:2]
        y1, y2 = max(0, y1), min(h, y2)
        x1, x2 = max(0, x1), min(w, x2)
        
        person_crop = frame[y1:y2, x1:x2]
        
        # 1. FILTRU: Ignorăm cadrele goale sau decupajele prea mici
        # Dacă persoana decupată e mai mică de 40x40 pixeli, fața va fi imposibil de recunoscut
        crop_h, crop_w = person_crop.shape[:2]
        if crop_h < 40 or crop_w < 40:
            return None
            
        crop_rgb = cv2.cvtColor(person_crop, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(crop_rgb)
        
        # 2. PLASA DE SIGURANȚĂ: Prindem bug-ul "torch.cat()" al MTCNN
        try:
            # MTCNN caută coordonatele faciale
            face_tensor = self.mtcnn(pil_img)
        except Exception as e:
            # Dacă librăria crapă intern pe un crop ciudat, ignorăm acest frame silențios
            return None
            
        if face_tensor is not None:
            # Dacă am găsit o față validă, generăm vectorul biometric (amprenta)
            face_tensor = face_tensor.unsqueeze(0).to(self.device_face)
            with torch.no_grad():
                embedding = self.resnet(face_tensor)
            
            return embedding.numpy().flatten().astype(np.float32)
        
        return None

    def process_frame(self, frame):
        """Rulează detecția YOLO pe întregul cadru (folosind MPS)."""
        results = self.detector.track(frame, persist=True, classes=[0], verbose=False)
        return results[0]