import sqlite3
import datetime
import numpy as np
import threading
from scipy.spatial.distance import cosine

class AirportDatabase:
    def __init__(self, db_path="airport.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=15.0)
        self.cursor = self.conn.cursor()
        self.lock = threading.RLock() 
        self.setup_tables()

    def setup_tables(self):
        with self.lock:
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS passengers (
                    person_id TEXT PRIMARY KEY,
                    nume TEXT,
                    poarta_destinatie TEXT,
                    timp_zbor TIMESTAMP,
                    vector_biometric BLOB
                )
            ''')
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS tracking_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id TEXT,
                    camera_id TEXT,
                    timestamp TIMESTAMP
                )
            ''')
            self.conn.commit()

    def register_passenger(self, person_id, nume, poarta, timp_zbor, feature_vector):
        vector_blob = feature_vector.tobytes()
        with self.lock:
            self.cursor.execute('''
                INSERT OR REPLACE INTO passengers (person_id, nume, poarta_destinatie, timp_zbor, vector_biometric)
                VALUES (?, ?, ?, ?, ?)
            ''', (person_id, nume, poarta, timp_zbor, vector_blob))
            self.conn.commit()

    def log_movement(self, person_id, camera_id):
        acum = datetime.datetime.now()
        with self.lock:
            self.cursor.execute('''
                SELECT camera_id FROM tracking_logs 
                WHERE person_id = ? ORDER BY timestamp DESC LIMIT 1
            ''', (person_id,))
            last_cam = self.cursor.fetchone()

            if not last_cam or last_cam[0] != camera_id:
                self.cursor.execute('''
                    INSERT INTO tracking_logs (person_id, camera_id, timestamp)
                    VALUES (?, ?, ?)
                ''', (person_id, camera_id, acum))
                self.conn.commit()
                print(f"[TRACKING] Persoana {person_id} a intrat în zona {camera_id}.")
                self.check_boarding_risk(person_id, camera_id, acum)

    def find_best_match(self, new_vector, threshold=0.75):
        with self.lock:
            self.cursor.execute("SELECT person_id, vector_biometric FROM passengers")
            rows = self.cursor.fetchall()
            
        best_id = None
        max_sim = 0.0

        for row in rows:
            db_id = row[0]
            db_vector = np.frombuffer(row[1], dtype=np.float32)
            
            if len(new_vector) != len(db_vector): continue
                
            sim = 1 - cosine(new_vector, db_vector)
            if sim > threshold and sim > max_sim:
                max_sim = sim
                best_id = db_id

        return best_id

    def check_boarding_risk(self, person_id, camera_id, current_time):
        with self.lock:
            self.cursor.execute("SELECT poarta_destinatie, timp_zbor FROM passengers WHERE person_id = ?", (person_id,))
            result = self.cursor.fetchone()
        
        if result:
            poarta, timp_zbor_str = result
            timp_zbor = datetime.datetime.strptime(timp_zbor_str, "%Y-%m-%d %H:%M:%S")
            minute_ramase = (timp_zbor - current_time).total_seconds() / 60.0

            zone_critice = ["Camera_Securitate"]
            if minute_ramase < 20 and camera_id in zone_critice:
                print(f"!!! ALERTĂ: Pasagerul {person_id} riscă să piardă zborul! !!!")

    def update_vector(self, person_id, new_vector, alpha=0.1):
        with self.lock:
            self.cursor.execute("SELECT vector_biometric FROM passengers WHERE person_id = ?", (person_id,))
            result = self.cursor.fetchone()
            
            if result:
                db_vector = np.frombuffer(result[0], dtype=np.float32)
                
                updated_vector = (alpha * new_vector) + ((1 - alpha) * db_vector)
                updated_vector = updated_vector / np.linalg.norm(updated_vector)
                
                self.cursor.execute('''
                    UPDATE passengers SET vector_biometric = ? WHERE person_id = ?
                ''', (updated_vector.tobytes(), person_id))
                self.conn.commit()