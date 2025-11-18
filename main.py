import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime
from typing import Any, Dict, Literal, TypedDict

import aiofiles
import magic
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
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


class VariantPayload(TypedDict):
    base_name: str
    extension: str
    width: int
    height: int
    urls: Dict[str, str]


VariantKey = Literal[
    "image_url_small",
    "image_url_medium",
    "image_url_original",
    "image_url_placeholder",
]


app = FastAPI(title="Custom Assets Bucket")

# Configuration ----------------------------------------------------------------
BASE_PATH = os.getenv("BASE_PATH", "/app/storage")
UPLOAD_TEMP = "/app/uploads"
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
CLAMAV_HOST = os.getenv("CLAMAV_HOST", "clamav")
CLAMAV_PORT = int(os.getenv("CLAMAV_PORT", "3310"))
CLAMAV_ENABLED = os.getenv("CLAMAV_ENABLED", "false").lower() == "true"
PUBLIC_URL = os.getenv("BASE_URL", "http://localhost:8088/files").strip()

IMAGE_SUBDIRECTORIES: tuple[str, ...] = (
    "small",
    "medium",
    "original",
    "placeholder",
)
IMAGE_VARIANT_SET = set(IMAGE_SUBDIRECTORIES)

IMAGE_VARIANTS: Dict[VariantKey, VariantConfig] = {
    "image_url_original": {"folder": "original", "max_size": None, "blur_radius": None},
    "image_url_small": {"folder": "small", "max_size": (320, 320), "blur_radius": None},
    "image_url_medium": {
        "folder": "medium",
        "max_size": (800, 800),
        "blur_radius": None,
    },
    "image_url_placeholder": {
        "folder": "placeholder",
        "max_size": (20, 20),
        "blur_radius": 2,
    },
}

DEFAULT_MANIPULATIONS: Dict[str, Dict[str, int]] = {
    "small": {"max_dimension": 320},
    "medium": {"max_dimension": 800},
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
    """Return a unique temporary path for an incoming upload."""

    return os.path.join(UPLOAD_TEMP, f"{uuid.uuid4()}_{filename}")


async def _write_upload_to_temp(upload_file: UploadFile, temp_path: str) -> None:
    """Persist the incoming upload to disk before processing."""

    async with aiofiles.open(temp_path, "wb") as buffer:
        content = await upload_file.read()
        await buffer.write(content)


def _remove_file_if_exists(file_path: str) -> None:
    """Best-effort removal for temporary files."""

    if os.path.exists(file_path):
        os.remove(file_path)


def _build_public_file_url(category: str, filename: str) -> str:
    """Return the externally reachable URL for a stored asset."""

    return f"{PUBLIC_URL}/{category}/{filename}"


def _validate_variant_name(variant: str) -> None:
    """Ensure the requested image variant exists."""

    if variant not in IMAGE_VARIANT_SET:
        raise HTTPException(404, "Unknown image variant")

@app.on_event("startup")
async def on_startup():
    """Initialize database tables once the service boots."""

    await init_db()


@app.get("/envtest")
async def tester():
    """Simple endpoint to confirm environment configuration."""

    return {"message": PUBLIC_URL}

@app.get("/health")
async def health():
    """Basic health probe consumed by orchestration tooling."""

    return {"status": "ok", "service": "assets-bucket"}

def get_mime_type(file_path: str) -> str:
    """Inspect a file on disk and return its MIME type."""

    return magic.from_file(file_path, mime=True)

def classify_file(mime_type: str, filename: str) -> str:
    """Map a mime type to a storage bucket."""

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
    """Run a synchronous ClamAV scan inside a thread, honoring feature flags."""

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
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning(
            "ClamAV scan failed (upload allowed due to fallback): %s", exc
        )
        return True

def generate_image_variants(file_path: str, filename: str) -> VariantPayload:
    """
    Generate and persist image variants (original, small, medium, placeholder)
    while returning their public URLs and dimensions.
    """

    base_name = f"{uuid.uuid4()}"
    extension = os.path.splitext(filename)[1].lower()
    urls: Dict[str, str] = {}
    filename_with_ext = f"{base_name}{extension}"

    with Image.open(file_path) as img:
        image_format = img.format or "JPEG"
        width, height = img.size

        for variant_key, config in IMAGE_VARIANTS.items():
            variant_image = img.copy()

            if config["max_size"]:
                variant_image.thumbnail(config["max_size"])

            blur_radius = config.get("blur_radius")
            if blur_radius:
                variant_image = variant_image.filter(ImageFilter.GaussianBlur(blur_radius))

            variant_path = os.path.join(
                DIRS["image"], config["folder"], filename_with_ext
            )
            variant_image.save(variant_path, format=image_format)
            urls[variant_key] = (
                f"{PUBLIC_URL}/images/{config['folder']}/{filename_with_ext}"
            )

    return {
        "base_name": base_name,
        "extension": extension.lstrip("."),
        "width": width,
        "height": height,
        "urls": urls,
    }


def _serialize_value(value: Any) -> Any:
    """Normalize values for JSON serialization."""

    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _build_properties_payload(asset: MediaAsset) -> Dict[str, object]:
    """Produce a JSON-serializable dict for a stored asset."""

    uid_str = str(uuid.UUID(bytes=asset.uid))
    raw_properties = {
        "uid": uid_str,
        "collection_name": asset.collection_name,
        "original_name": asset.original_name,
        "title": asset.title,
        "name": asset.name,
        "model_type": asset.model_type,
        "folder": asset.folder,
        "mime_type": asset.mime_type,
        "extension": asset.extension,
        "disk": asset.disk,
        "size": asset.size,
        "status": asset.status,
        "manipulations": asset.manipulations,
        "custom_properties": asset.custom_properties,
        "responsive_images": asset.responsive_images,
        "order_column": asset.order_column,
        "created_by": asset.created_by,
        "updated_by": asset.updated_by,
        "deleted_by": asset.deleted_by,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "deleted_at": asset.deleted_at,
        "aspect_ratio": asset.aspect_ratio,
    }
    return {key: _serialize_value(value) for key, value in raw_properties.items()}


def build_asset_payload(asset: MediaAsset) -> Dict[str, object]:
    """Combine asset metadata with its set of responsive links."""

    properties = _build_properties_payload(asset)
    links = asset.responsive_images or {}
    enriched_links = {
        key: {"url": url, "properties": properties} for key, url in links.items()
    }
    return {"asset": properties, "links": enriched_links}


async def persist_asset_metadata(
    original_name: str,
    mime_type: str,
    file_size: int,
    variant_payload: VariantPayload,
) -> MediaAsset:
    """Store metadata for an uploaded asset."""

    uid = uuid.uuid4()
    width = variant_payload["width"]
    height = variant_payload["height"]
    aspect_ratio = (width / height) if height else None
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
        order_column=None,
        created_by=None,
        updated_by=None,
        deleted_by=None,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )

    async with AsyncSessionLocal() as session:
        session.add(asset)
        await session.commit()
        await session.refresh(asset)

    return asset


async def get_asset_by_base_name(base_name: str) -> MediaAsset | None:
    """Fetch an asset row by its generated base filename."""

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MediaAsset).where(MediaAsset.name == base_name)
        )
        return result.scalar_one_or_none()

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    token: str = Header(..., alias="X-Secret-Token"),
):
    """Handle uploads for all supported asset categories."""

    if token != SECRET_TOKEN:
        raise HTTPException(401, "Invalid token")

    if not file.filename:
        raise HTTPException(400, "No file selected")

    temp_path = _get_temp_file_path(file.filename)
    await _write_upload_to_temp(file, temp_path)

    mime_type = get_mime_type(temp_path)
    if not await scan_file_with_clamav(temp_path):
        _remove_file_if_exists(temp_path)
        raise HTTPException(400, "File failed security scan")

    category = classify_file(mime_type, file.filename)

    if category == "image":
        file_size = os.path.getsize(temp_path)
        variant_payload = await asyncio.to_thread(
            generate_image_variants, temp_path, file.filename
        )
        _remove_file_if_exists(temp_path)
        asset = await persist_asset_metadata(
            original_name=file.filename,
            mime_type=mime_type,
            file_size=file_size,
            variant_payload=variant_payload,
        )
        return JSONResponse(build_asset_payload(asset))
    else:
        unique_name = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
        final_path = os.path.join(DIRS[category], unique_name)
        shutil.move(temp_path, final_path)
        return JSONResponse({"url": _build_public_file_url(category, unique_name)})


@app.get("/files/images/{variant}/{filename}")
async def retrieve_image_metadata(
    variant: str, filename: str, raw: bool = False
):
    """Return metadata (default) or raw bytes for a stored image."""

    _validate_variant_name(variant)
    base_name, _ = os.path.splitext(filename)
    asset = await get_asset_by_base_name(base_name)

    if not asset:
        raise HTTPException(404, "Asset not found")

    file_path = os.path.join(DIRS["image"], variant, filename)

    if raw:
        if not os.path.exists(file_path):
            raise HTTPException(404, "File not found")
        media_type = asset.mime_type or "application/octet-stream"
        return FileResponse(file_path, media_type=media_type)

    return JSONResponse(build_asset_payload(asset))

@app.get("/test")
async def test():
    """Kitchensink placeholder endpoint."""

    return {"Message": "Hi mom"}

# Serve static files (fallback/raw access)
app.mount("/files", StaticFiles(directory=BASE_PATH), name="files")