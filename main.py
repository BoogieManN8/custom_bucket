import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime
from typing import Any, Dict, Literal, TypedDict

import aiofiles
import magic
from fastapi import FastAPI, File, Header, HTTPException, UploadFile, Path
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageFilter
from sqlalchemy import select

from database import AsyncSessionLocal, MediaAsset, init_db

logger = logging.getLogger(__name__)


class VariantConfig(TypedDict, total=False):
    folder: str
    max_size: tuple[int, int] | None
    blur_radius: int | None
    quality: int | None


class VariantPayload(TypedDict):
    base_name: str
    extension: str
    width: int
    height: int
    urls: Dict[str, str]


VariantKey = Literal[
    "image_url_small",
    "image_url_medium",
    "image_url_high",
    "image_url_original",
    "image_url_placeholder",
]


app = FastAPI(title="Custom Assets Bucket")

# Configuration
BASE_PATH = os.getenv("BASE_PATH", "/app/storage")
UPLOAD_TEMP = "/app/uploads"
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
PUBLIC_URL = os.getenv("BASE_URL", "http://localhost:8088/files").strip()

IMAGE_SUBDIRECTORIES = ("small", "medium", "high", "original", "placeholder")
IMAGE_VARIANT_SET = set(IMAGE_SUBDIRECTORIES)

IMAGE_VARIANTS: Dict[VariantKey, VariantConfig] = {
    "image_url_original": {"folder": "original", "max_size": None},
    "image_url_small": {"folder": "small", "max_size": (320, 320)},
    "image_url_medium": {"folder": "medium", "max_size": (800, 800)},
    "image_url_high": {"folder": "high", "max_size": None, "quality": 70},
    "image_url_placeholder": {"folder": "placeholder", "max_size": (20, 20), "blur_radius": 2},
}

DEFAULT_MANIPULATIONS = {
    "small": {"max_dimension": 320},
    "medium": {"max_dimension": 800},
    "high": {"quality": 70},
    "placeholder": {"max_dimension": 20, "blur": 2},
}

DIRS = {
    "image": os.path.join(BASE_PATH, "images"),
    "pdf": os.path.join(BASE_PATH, "pdf"),
    "audio": os.path.join(BASE_PATH, "audio"),
    "video": os.path.join(BASE_PATH, "video"),
}


def _ensure_directories() -> None:
    os.makedirs(BASE_PATH, exist_ok=True)
    os.makedirs(UPLOAD_TEMP, exist_ok=True)
    for path in DIRS.values():
        os.makedirs(path, exist_ok=True)
        if path.endswith("images"):
            for sub_dir in IMAGE_SUBDIRECTORIES:
                os.makedirs(os.path.join(path, sub_dir), exist_ok=True)


_ensure_directories()


def _get_temp_file_path(filename: str) -> str:
    return os.path.join(UPLOAD_TEMP, f"{uuid.uuid4()}_{filename}")


async def _write_upload_to_temp(upload_file: UploadFile, temp_path: str) -> None:
    async with aiofiles.open(temp_path, "wb") as buffer:
        content = await upload_file.read()
        await buffer.write(content)


def _remove_file_if_exists(file_path: str) -> None:
    if os.path.exists(file_path):
        os.remove(file_path)


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
    # ... (same as before)
    return True  # simplified for brevity


def generate_image_variants(file_path: str, filename: str) -> VariantPayload:
    base_name = f"{uuid.uuid4()}"
    extension = os.path.splitext(filename)[1].lower()
    if not extension:
        extension = ".jpg"
    filename_with_ext = f"{base_name}{extension}"
    urls: Dict[str, str] = {}

    with Image.open(file_path) as img:
        image_format = img.format or "JPEG"
        width, height = img.size

        for variant_key, config in IMAGE_VARIANTS.items():
            variant_image = img.copy()

            if config.get("max_size"):
                variant_image.thumbnail(config["max_size"], Image.Resampling.LANCZOS)

            if config.get("blur_radius"):
                variant_image = variant_image.filter(ImageFilter.GaussianBlur(config["blur_radius"]))

            variant_path = os.path.join(DIRS["image"], config["folder"], filename_with_ext)

            save_kwargs: Dict[str, Any] = {"format": image_format}
            if config.get("quality") is not None:
                save_kwargs["quality"] = config["quality"]
                save_kwargs["optimize"] = True
                if image_format.upper() == "JPEG":
                    save_kwargs["subsampling"] = 1

            variant_image.save(variant_path, **save_kwargs)
            urls[variant_key] = f"{PUBLIC_URL}/images/{config['folder']}/{filename_with_ext}"

    return {
        "base_name": base_name,
        "extension": extension.lstrip("."),
        "width": width,
        "height": height,
        "urls": urls,
    }


async def persist_asset_metadata(
    original_name: str,
    mime_type: str,
    file_size: int,
    variant_payload: VariantPayload,
) -> MediaAsset:
    uid = uuid.uuid4()
    width = variant_payload["width"]
    height = variant_payload["height"]
    aspect_ratio = width / height if height else None
    now = datetime.utcnow()

    asset = MediaAsset(
        uid=uid.bytes,
        aspect_ratio=aspect_ratio,
        collection_name=None,
        original_name=original_name,
        title=None,
        name=variant_payload["base_name"],
        model_type="image",
        folder="images",
        mime_type=mime_type,
        extension=variant_payload["extension"],
        disk="local",
        size=file_size,
        status=0,
        manipulations=DEFAULT_MANIPULATIONS,
        custom_properties={"width": width, "height": height},
        responsive_images=variant_payload["urls"],
        created_at=now,
        updated_at=now,
    )

    async with AsyncSessionLocal() as session:
        session.add(asset)
        await session.commit()
        await session.refresh(asset)

    return asset


async def get_asset_by_base_name(base_name: str) -> MediaAsset | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(MediaAsset).where(MediaAsset.name == base_name))
        return result.scalar_one_or_none()


def _build_properties_payload(asset: MediaAsset) -> Dict[str, object]:
    uid_str = str(uuid.UUID(bytes=asset.uid))
    raw = {col.name: getattr(asset, col.name) for col in asset.__table__.columns}
    raw["uid"] = uid_str
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in raw.items()}


def build_asset_payload(asset: MediaAsset) -> Dict[str, object]:
    props = _build_properties_payload(asset)
    links = asset.responsive_images or {}
    enriched = {key: {"url": url, "properties": props} for key, url in links.items()}
    return {"asset": props, "links": enriched}


# ==================== ROUTES ====================

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    token: str = Header(..., alias="X-Secret-Token"),
):
    if token != SECRET_TOKEN:
        raise HTTPException(401, "Invalid token")

    temp_path = _get_temp_file_path(file.filename or "unknown")
    await _write_upload_to_temp(file, temp_path)

    mime_type = get_mime_type(temp_path)
    if not await scan_file_with_clamav(temp_path):
        _remove_file_if_exists(temp_path)
        raise HTTPException(400, "File failed security scan")

    category = classify_file(mime_type, file.filename or "unknown")

    if category == "image":
        file_size = os.path.getsize(temp_path)
        variant_payload = await asyncio.to_thread(generate_image_variants, temp_path, file.filename or "image")
        _remove_file_if_exists(temp_path)
        asset = await persist_asset_metadata(file.filename or "unknown", mime_type, file_size, variant_payload)

        # Return full info + all URLs
        return JSONResponse(build_asset_payload(asset))
    else:
        unique_name = f"{uuid.uuid4()}{os.path.splitext(file.filename or '')[1]}"
        final_path = os.path.join(DIRS[category], unique_name)
        shutil.move(temp_path, final_path)
        return JSONResponse({"url": f"{PUBLIC_URL}/{category}/{unique_name}"})


# NEW: Clean endpoint to get full asset info
@app.get("/asset/{base_name}")
async def get_asset_info(base_name: str = Path(..., description="Base name without extension")):
    """Return full JSON with all variants and metadata"""
    asset = await get_asset_by_base_name(base_name)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return build_asset_payload(asset)


# FIXED: Raw image URLs now serve actual images (not JSON!)
@app.get("/files/images/{variant}/{filename}")
async def serve_image_file(variant: str, filename: str):
    """Serve raw image files directly (for <img src="">, previews, etc.)"""
    if variant not in IMAGE_VARIANT_SET:
        raise HTTPException(404, "Unknown variant")

    file_path = os.path.join(DIRS["image"], variant, filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found")

    # Try to get MIME from DB for accuracy
    base_name, _ = os.path.splitext(filename)
    asset = await get_asset_by_base_name(base_name)
    media_type = asset.mime_type if asset else "application/octet-stream"

    return FileResponse(file_path, media_type=media_type)


# Health & test
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/test")
async def test():
    return {"Message": "Direct image URLs now work!"}


# Serve all static files (fallback for non-images too)
app.mount("/files", StaticFiles(directory=BASE_PATH), name="files")

@app.on_event("startup")
async def on_startup():
    await init_db()