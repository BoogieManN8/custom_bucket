#!/bin/bash
# setup-assets-bucket.sh
# One-click setup for FastAPI Assets Bucket with Docker
# Run: chmod +x setup-assets-bucket.sh && ./setup-assets-bucket.sh

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Setting up FastAPI Assets Bucket in: $PROJECT_DIR"

# === CLEAN OLD PROJECT FILES (from previous attempts) ===
echo "Cleaning old project files..."
rm -rf "$PROJECT_DIR/storage" "$PROJECT_DIR/uploads" "$PROJECT_DIR/.env" \
       "$PROJECT_DIR/Dockerfile" "$PROJECT_DIR/docker-compose.yml" \
       "$PROJECT_DIR/main.py" "$PROJECT_DIR/requirements.txt" \
       "$PROJECT_DIR/.dockerignore" 2>/dev/null || true

# === CREATE FRESH BASE DIRECTORIES ===
echo "Creating base directories..."
mkdir -p "$PROJECT_DIR/storage/images"/{small,medium,original,placeholder}
mkdir -p "$PROJECT_DIR/storage"/{pdf,audio,video}
mkdir -p "$PROJECT_DIR/uploads"

# === CREATE .env WITH STRONG DEFAULT TOKEN ===
SECRET_TOKEN=$(openssl rand -hex 32)
cat > "$PROJECT_DIR/.env" << EOF
SECRET_TOKEN=$SECRET_TOKEN
BASE_PATH=/app/storage
CLAMAV_ENABLED=true
EOF
echo ".env created with secure token"

# === CREATE requirements.txt ===
cat > "$PROJECT_DIR/requirements.txt" << 'EOF'
fastapi==0.115.0
uvicorn[standard]==0.30.6
python-multipart==0.0.9
Pillow==10.4.0
pydantic==2.9.2
python-magic==0.4.27
aiofiles==24.1.0
EOF

# === CREATE Dockerfile (port 8088) ===
cat > "$PROJECT_DIR/Dockerfile" << 'EOF'
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    imagemagick \
    libimage-exiftool-perl \
    ghostscript \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8088

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]
EOF

# === CREATE docker-compose.yml (8088:8088) ===
cat > "$PROJECT_DIR/docker-compose.yml" << 'EOF'
version: '3.9'

services:
  assets-bucket:
    build: .
    container_name: fastapi-assets-bucket
    ports:
      - "8088:8088"
    volumes:
      - ./storage:/app/storage
      - ./uploads:/app/uploads
    env_file:
      - .env
    restart: unless-stopped
    depends_on:
      - clamav

  clamav:
    image: mkodockx/docker-clamav:alpine
    container_name: clamav
    ports:
      - "3310:3310"
    volumes:
      - clamav-data:/var/lib/clamav
    restart: unless-stopped

volumes:
  clamav-data:
EOF

# === CREATE .dockerignore ===
cat > "$PROJECT_DIR/.dockerignore" << 'EOF'
__pycache__
*.pyc
.git
.gitignore
README.md
.env
storage/
uploads/
EOF

# === CREATE main.py (with /health + dynamic PUBLIC_URL) ===
cat > "$PROJECT_DIR/main.py" << 'EOF'
import os
import uuid
import magic
import aiofiles
import shutil
from fastapi import FastAPI, File, UploadFile, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel
import asyncio

app = FastAPI(title="Custom Assets Bucket")

# Config
BASE_PATH = os.getenv("BASE_PATH", "/app/storage")
UPLOAD_TEMP = "/app/uploads"
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
CLAMAV_HOST = "clamav"
CLAMAV_PORT = 3310
CLAMAV_ENABLED = os.getenv("CLAMAV_ENABLED", "true").lower() == "true"

os.makedirs(BASE_PATH, exist_ok=True)
os.makedirs(UPLOAD_TEMP, exist_ok=True)

DIRS = {
    "image": os.path.join(BASE_PATH, "images"),
    "pdf": os.path.join(BASE_PATH, "pdf"),
    "audio": os.path.join(BASE_PATH, "audio"),
    "video": os.path.join(BASE_PATH, "video"),
}

for d in DIRS.values():
    os.makedirs(d, exist_ok=True)
    if "image" in d:
        for sub in ["small", "medium", "original", "placeholder"]:
            os.makedirs(os.path.join(d, sub), exist_ok=True)

# Serve static files
app.mount("/files", StaticFiles(directory=BASE_PATH), name="files")
PUBLIC_URL = "http://localhost:8088/files"

class UploadResponse(BaseModel):
    url: str = None
    image_url_small: str = None
    image_url_medium: str = None
    image_url_original: str = None
    image_url_placeholder: str = None

@app.get("/health")
async def health():
    return {"status": "ok", "service": "assets-bucket"}

def get_mime_type(file_path: str) -> str:
    return magic.from_file(file_path, mime=True)

def classify_file(mime_type: str, filename: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    elif mime_type == "application/pdf":
        return "pdf"
    elif mime_type.startswith("audio/"):
        return "audio"
    elif mime_type.startswith("video/"):
        return "video"
    else:
        raise HTTPException(400, f"Unsupported file type: {mime_type}")

async def scan_file_with_clamav(file_path: str) -> bool:
    if not CLAMAV_ENABLED:
        return True
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((CLAMAV_HOST, CLAMAV_PORT))
        sock.send(b"zINSTREAM\0")
        with open(file_path, "rb") as f:
            while chunk := f.read(1024):
                sock.send(len(chunk).to_bytes(4, "big") + chunk)
        sock.send(b"\x00\x00\x00\x00")
        response = sock.recv(4096)
        sock.close()
        return b"OK" in response
    except Exception as e:
        print(f"ClamAV scan failed: {e}")
        return False

def generate_image_variants(file_path: str, filename: str) -> dict:
    base_name = f"{uuid.uuid4()}"
    ext = os.path.splitext(filename)[1].lower()
    urls = {}

    with Image.open(file_path) as img:
        format = img.format or "JPEG"

        # Original
        orig_path = os.path.join(DIRS["image"], "original", f"{base_name}{ext}")
        img.save(orig_path, format=format)
        urls["image_url_original"] = f"{PUBLIC_URL}/images/original/{base_name}{ext}"

        # Small
        small = img.copy()
        small.thumbnail((320, 320))
        small_path = os.path.join(DIRS["image"], "small", f"{base_name}{ext}")
        small.save(small_path, format=format)
        urls["image_url_small"] = f"{PUBLIC_URL}/images/small/{base_name}{ext}"

        # Medium
        medium = img.copy()
        medium.thumbnail((800, 800))
        medium_path = os.path.join(DIRS["image"], "medium", f"{base_name}{ext}")
        medium.save(medium_path, format=format)
        urls["image_url_medium"] = f"{PUBLIC_URL}/images/medium/{base_name}{ext}"

        # Placeholder
        placeholder = img.copy()
        placeholder.thumbnail((20, 20))
        placeholder = placeholder.filter(Image.Filter.GaussianBlur(2))
        ph_path = os.path.join(DIRS["image"], "placeholder", f"{base_name}{ext}")
        placeholder.save(ph_path, format=format)
        urls["image_url_placeholder"] = f"{PUBLIC_URL}/images/placeholder/{base_name}{ext}"

    return urls

@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    token: str = Header(..., alias="X-Secret-Token")
):
    if token != SECRET_TOKEN:
        raise HTTPException(401, "Invalid token")

    if not file.filename:
        raise HTTPException(400, "No file selected")

    temp_path = os.path.join(UPLOAD_TEMP, f"{uuid.uuid4()}_{file.filename}")
    async with aiofiles.open(temp_path, 'wb') as f:
        content = await file.read()
        await f.write(content)

    mime_type = get_mime_type(temp_path)
    if not await scan_file_with_clamav(temp_path):
        os.remove(temp_path)
        raise HTTPException(400, "File failed security scan")

    category = classify_file(mime_type, file.filename)

    if category == "image":
        urls = await asyncio.to_thread(generate_image_variants, temp_path, file.filename)
        os.remove(temp_path)
        return JSONResponse(urls)
    else:
        unique_name = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
        final_path = os.path.join(DIRS[category], unique_name)
        shutil.move(temp_path, final_path)
        url = f"{PUBLIC_URL}/{category}s/{unique_name}"
        return JSONResponse({"url": url})
EOF

# === FINALIZE ===
chmod +x "$0"

echo ""
echo "Setup complete!"
echo ""
echo "Your secure token:"
echo "   SECRET_TOKEN=$SECRET_TOKEN"
echo ""
echo "Next steps:"
echo "1. cd $PROJECT_DIR"
echo "2. docker-compose up -d --build"
echo "3. Test upload:"
echo '   curl -X POST "http://localhost:8088/upload" \\'
echo "     -H \"X-Secret-Token: $SECRET_TOKEN\" \\"
echo '     -F "file=@./test.jpg" | jq'
echo ""
echo "Files served at: http://localhost:8088/files/"
echo "Health check:   curl http://localhost:8088/health"