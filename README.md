
## System Overview
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Backend-000000?logo=flask&logoColor=white)
![YOLOv8](https://img.shields.io/badge/YOLOv8-Computer%20Vision-FF6F00)
![OpenCV](https://img.shields.io/badge/OpenCV-4.x-5C3EE8?logo=opencv&logoColor=white)
![Qwen](https://img.shields.io/badge/LLM-Qwen-FF4B4B)
![SQLite](https://img.shields.io/badge/SQLite-Local%20DB-003B57?logo=sqlite&logoColor=white)
![WebSockets](https://img.shields.io/badge/WebSockets-RealTime-2ECC71)
![SSE](https://img.shields.io/badge/SSE-Streaming-3498DB)

**AeroVision** is an AI-powered airport operations platform developed during **HackTech Oradea 2026**, Romania’s first hackathon held inside a **real airport environment**, by a **team of 6 participants**, where the project achieved **🥉 3rd Place in Airport Infrastructure**.

The system was designed to transform real-time airport data into **actionable operational intelligence**, helping:

- detect congestion early  
- predict flight delays  
- optimize counter allocation  
- improve passenger flow  

👉 The platform combines **computer vision, real-time processing, and AI decision-making** into a unified system.

---

## System Architecture

### 1. Computer Vision Layer

The computer vision module processes live video streams using:

- YOLOv8 + OpenCV for object detection  
- NumPy for frame processing  

It detects and extracts structured data such as:

- number of people in queue  
- baggage count  
- special items  
- passenger flow rate  

This module communicates with the backend via **WebSockets** for real-time data streaming.

---

### 2. Backend Processing Layer

The backend is built entirely in **Python using Flask**, providing:

- API endpoints  
- operational dashboard  
- real-time updates  

It ingests AI-generated data and combines it with:

- flight schedules  
- counter assignments  

The system computes:

- throughput  
- queue clearance time  
- congestion levels  
- flight delay risk  

---

### 3. AI Decision Layer

Processed data is analyzed using **LLMs (Qwen)** to generate:

- operational alerts  
- optimization suggestions  

Each insight follows a structured format:

👉 **Problem – Solution – Reason**

And is assigned a risk level:

- 🟢 Green — normal  
- 🟠 Orange — moderate risk  
- 🔴 Red — critical  

---

### 4. Real-Time Communication

- **WebSockets** → receive live data from CV system  
- **Server-Sent Events (SSE)** → stream updates to dashboard  

---

### 5. Data Storage

- SQLite → structured system data  
- JSON / CSV → analytics snapshots  

---

## System Summary

AeroVision is a real-time system that:

- ingests AI-detected crowd data  
- analyzes passenger flow  
- detects bottlenecks  
- predicts flight risks  
- suggests operational improvements  

👉 Turning airport monitoring into **proactive decision-making**
