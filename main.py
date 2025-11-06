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
PUBLIC_URL = os.getenv("BASE_URL")

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
        placeholder = placeholder.filter(ImageFilter.GaussianBlur(2))
        ph_path = os.path.join(DIRS["image"], "placeholder", f"{base_name}{ext}")
        placeholder.save(ph_path, format=format)
        urls["image_url_placeholder"] = f"{PUBLIC_URL}/images/placeholder/{base_name}{ext}"

    return urls

@app.post("/upload")
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
        # FIXED: Use singular directory name in URL
        url = f"{PUBLIC_URL}/{category}/{unique_name}"
        return JSONResponse({"url": url})

@app.get("/test")
async def test():
    return {"Message": "Hi mom"}