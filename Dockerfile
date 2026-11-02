# One container for the whole app: builds the frontend, then FastAPI serves it and the API.
#   docker build -t proofline . && docker run -p 8000:8000 -e MODEL_API_KEY=... proofline

FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
COPY data/samples/ data/samples/
COPY data/eval/ data/eval/
COPY --from=frontend /app/frontend/dist/ frontend/dist/
WORKDIR /app/backend
EXPOSE 8000
# Render sets PORT; one worker, because runs and usage counts live in this process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
