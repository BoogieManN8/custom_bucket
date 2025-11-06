#!/bin/bash
# setup-assets-bucket.sh
# Full auto-setup: Docker check → install → build → run → test
# Run: curl -fsSL https://raw.githubusercontent.com/your-repo/setup-assets-bucket.sh | bash

set -e

PROJECT_DIR="$(pwd)/custom_bucket"
LOG_FILE="$PROJECT_DIR/setup.log"

echo "Starting auto-setup for Assets Bucket..." | tee "$LOG_FILE"

# === 1. Check & install Docker ===
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing..." | tee -a "$LOG_FILE"
    curl -fsSL https://get.docker.com | sh
    sudo systemctl start docker
    sudo systemctl enable docker
else
    echo "Docker already installed." | tee -a "$LOG_FILE"
fi

if ! command -v docker-compose &> /dev/null; then
    echo "docker-compose not found. Installing..." | tee -a "$LOG_FILE"
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
else
    echo "docker-compose already installed." | tee -a "$LOG_FILE"
fi

# === 2. Create project dir ===
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# === 3. Generate secure token ===
SECRET_TOKEN=$(openssl rand -hex 32)

# === 4. Write .env ===
cat > .env << EOF
SECRET_TOKEN=$SECRET_TOKEN
BASE_PATH=/app/storage
CLAMAV_ENABLED=true
BASE_URL=http://localhost:8088/files
EOF

# === 5. Write requirements.txt ===
cat > requirements.txt << 'EOF'
fastapi==0.115.0
uvicorn[standard]==0.30.6
python-multipart==0.0.9
Pillow==10.4.0
pydantic==2.9.2
python-magic==0.4.27
aiofiles==24.1.0
EOF

# === 6. Write Dockerfile ===
cat > Dockerfile << 'EOF'
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    ffmpeg imagemagick libimage-exiftool-perl ghostscript poppler-utils libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8088
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]
EOF

# === 7. Write docker-compose.yml ===
cat > docker-compose.yml << 'EOF'
services:
  assets-bucket:
    build: .
    container_name: fastapi-assets-bucket
    ports:
      - "8088:8088"
    volumes:
      - ./storage:/app/storage
      - ./uploads:/app/uploads
      - .:/app
    env_file: .env
    command: uvicorn main:app --host 0.0.0.0 --port 8088 --reload
    depends_on:
      - clamav

  clamav:
    image: mkodockx/docker-clamav:alpine
    container_name: clamav
    ports:
      - "3310:3310"
    volumes:
      - clamav-data:/var/lib/clamav

volumes:
  clamav-data:
EOF

# === 8. Write main.py (final working version) ===
cat > main.py << 'EOF'
import os
import uuid
import magic
import aiofiles
import shutil
from fastapi import FastAPI, File, UploadFile, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageFilter
from pydantic import BaseModel
import asyncio

app = FastAPI(title="Custom Assets Bucket")

BASE_PATH = os.getenv("BASE_PATH", "/app/storage")
UPLOAD_TEMP = "/app/uploads"
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
CLAMAV_HOST = "clamav"
CLAMAV_PORT = 3310
CLAMAV_ENABLED = os.getenv("CLAMAV_ENABLED", "true").lower() == "true"
PUBLIC_URL = os.getenv("BASE_URL", "http://localhost:8088/files").strip()

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

app.mount("/files", StaticFiles(directory=BASE_PATH), name="files")

class UploadResponse(BaseModel):
    url: str = None
    image_url_small: str = None
    image_url_medium: str = None
    image_url_original: str = None
    image_url_placeholder: str = None

@app.get("/health")
async def health():
    return {"status": "ok"}

def get_mime_type(file_path: str) -> str:
    return magic.from_file(file_path, mime=True)

def classify_file(mime_type: str, filename: str) -> str:
    if mime_type.startswith("image/"): return "image"
    if mime_type == "application/pdf": return "pdf"
    if mime_type.startswith("audio/"): return "audio"
    if mime_type.startswith("video/"): return "video"
    raise HTTPException(400, "Unsupported file type")

async def scan_file_with_clamav(file_path: str) -> bool:
    if not CLAMAV_ENABLED: return True
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
        resp = sock.recv(4096)
        sock.close()
        return b"OK" in resp
    except Exception as e:
        print(f"Scan failed: {e}")
        return False

def generate_image_variants(file_path: str, filename: str) -> dict:
    base = f"{uuid.uuid4()}"
    ext = os.path.splitext(filename)[1].lower()
    urls = {}
    with Image.open(file_path) as img:
        fmt = img.format or "JPEG"
        # original
        p = os.path.join(DIRS["image"], "original", f"{base}{ext}")
        img.save(p, format=fmt)
        urls["image_url_original"] = f"{PUBLIC_URL}/images/original/{base}{ext}"
        # small
        s = img.copy(); s.thumbnail((320,320))
        s.save(os.path.join(DIRS["image"], "small", f"{base}{ext}"), format=fmt)
        urls["image_url_small"] = f"{PUBLIC_URL}/images/small/{base}{ext}"
        # medium
        m = img.copy(); m.thumbnail((800,800))
        m.save(os.path.join(DIRS["image"], "medium", f"{base}{ext}"), format=fmt)
        urls["image_url_medium"] = f"{PUBLIC_URL}/images/medium/{base}{ext}"
        # placeholder
        ph = img.copy(); ph.thumbnail((20,20))
        ph = ph.filter(ImageFilter.GaussianBlur(2))
        ph.save(os.path.join(DIRS["image"], "placeholder", f"{base}{ext}"), format=fmt)
        urls["image_url_placeholder"] = f"{PUBLIC_URL}/images/placeholder/{base}{ext}"
    return urls

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), token: str = Header(..., alias="X-Secret-Token")):
    if token != SECRET_TOKEN: raise HTTPException(401, "Invalid token")
    if not file.filename: raise HTTPException(400, "No file")
    temp_path = os.path.join(UPLOAD_TEMP, f"{uuid.uuid4()}_{file.filename}")
    async with aiofiles.open(temp_path, 'wb') as f:
        await f.write(await file.read())
    if not await scan_file_with_clamav(temp_path):
        os.remove(temp_path)
        raise HTTPException(400, "Security scan failed")
    cat = classify_file(get_mime_type(temp_path), file.filename)
    if cat == "image":
        urls = await asyncio.to_thread(generate_image_variants, temp_path, file.filename)
        os.remove(temp_path)
        return JSONResponse(urls)
    else:
        name = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
        final = os.path.join(DIRS[cat], name)
        shutil.move(temp_path, final)
        return JSONResponse({"url": f"{PUBLIC_URL}/{cat}/{name}"})
EOF

# === 9. Build & run ===
echo "Building and starting containers..." | tee -a "$LOG_FILE"
docker-compose down -v &> /dev/null || true
docker-compose up -d --build

# === 10. Wait & test health ===
echo "Waiting for service..." | tee -a "$LOG_FILE"
for i in {1..30}; do
    if curl -s http://localhost:8088/health &> /dev/null; then
        echo "SUCCESS: Assets Bucket is running!" | tee -a "$LOG_FILE"
        echo "Upload test command:"
        echo "curl -X POST http://localhost:8088/upload -H 'X-Secret-Token: $SECRET_TOKEN' -F 'file=@./test.pdf'"
        echo "Files: http://localhost:8088/files/"
        exit 0
    fi
    sleep 2
done

echo "ERROR: Service failed to start." | tee -a "$LOG_FILE"
exit 1
