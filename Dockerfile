# Étape 1 : compilation du frontend React (pour déploiement tout-en-un Hugging Face Spaces)
FROM node:20-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
ARG VITE_USE_MOCK=false
ARG VITE_API_URL=
ENV VITE_USE_MOCK=$VITE_USE_MOCK
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# Étape 2 : image Python API + worker + interface statique
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    WEMA_DB=/app/data/wema.db \
    WEMA_DATA=/app/data \
    AI_BACKEND=demo

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py db.py schema.py schema.sql seed.py cli.py ./
COPY api ./api
COPY domain ./domain
COPY adapters ./adapters
COPY worker ./worker
COPY Makefile .env.example ./
COPY --from=web-build /web/dist ./web/dist

RUN mkdir -p /app/data && chmod -R 777 /app/data

EXPOSE 7860 8000

# Par défaut (Hugging Face Spaces) : worker + API + interface sur $PORT (7860).
# En local, docker-compose.yml surcharge la commande pour séparer api (8000) et worker.
CMD ["python", "-m", "cli", "serve"]
