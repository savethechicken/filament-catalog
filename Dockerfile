# Filament Catalog container image.
# Built and published to GHCR by .github/workflows/docker-publish.yml on every
# push to main. The server just pulls the finished image.
FROM python:3.12-slim

WORKDIR /app

# Tesseract is needed for the "scan box label" OCR feature.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first so Docker can cache this layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY app ./app

# Store the database on a mounted volume, not inside the image.
ENV FILAMENT_DB=/data/filament.db

# Commit SHA injected by the GitHub Action; shown in the page footer.
ARG BUILD_SHA=
ENV BUILD_SHA=$BUILD_SHA

EXPOSE 8077

# Seed the starter spools on first run (no-op once data exists), then serve.
CMD ["sh", "-c", "python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8077"]
