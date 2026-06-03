# Hugging Face Spaces — 5G-NTN Disaster Handover Simulator
# Çok aşamalı build: önce Node ile frontend, sonra Python backend.

# ---- Aşama 1: Frontend build ----
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---- Aşama 2: Python backend + derlenmiş frontend ----
FROM python:3.11-slim
WORKDIR /app

# Python bağımlılıkları
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Backend kodu
COPY backend/ ./backend/

# Aşama 1'de derlenen frontend'i kopyala
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Skyfield'in indirdiği dosyalar ve TLE cache için yazılabilir dizin
# (HF Spaces'te sadece belirli yerler yazılabilir; /app yazılabilir)
ENV PORT=7860
EXPOSE 7860

# Hugging Face Spaces 7860 portunu bekler
WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
