FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py db.py schema.py schema.sql seed.py ./
COPY api ./api
COPY domain ./domain
COPY adapters ./adapters
COPY worker ./worker
COPY Makefile .env.example ./

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "-m", "api.app"]
