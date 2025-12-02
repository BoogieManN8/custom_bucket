import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime
from typing import Any, Dict, Literal, TypedDict

import aiofiles
import magic
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, Path
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


class VariantInfo(TypedDict):
    path: str
    size: int
    width: int
    height: int


class VariantPayload(TypedDict):
    base_name: str
    extension: str
    width: int  # Original width
    height: int  # Original height
    variants: Dict[str, VariantInfo]  # Key: "image_high", "image_small", etc.


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
CLAMAV_HOST = os.getenv("CLAMAV_HOST", "clamav")
CLAMAV_PORT = int(os.getenv("CLAMAV_PORT", "3310"))
CLAMAV_ENABLED = os.getenv("CLAMAV_ENABLED", "false").lower() == "true"

IMAGE_SUBDIRECTORIES = ("small", "medium", "high", "original", "placeholder")
IMAGE_VARIANT_SET = set(IMAGE_SUBDIRECTORIES)

IMAGE_VARIANTS: Dict[VariantKey, VariantConfig] = {
    "image_url_original": {"folder": "original", "max_size": None},
    "image_url_small": {"folder": "small", "max_size": (320, 320)},
    "image_url_medium": {"folder": "medium", "max_size": (800, 800)},
    "image_url_high": {"folder": "high", "max_size": (1600, 1600), "quality": 70},
    "image_url_placeholder": {"folder": "placeholder", "max_size": (20, 20), "blur_radius": 2},
}

DEFAULT_MANIPULATIONS = {
    "small": {"max_dimension": 320},
    "medium": {"max_dimension": 800},
    "high": {"max_dimension": 1600},
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


def _normalize_folder_path(folder: str | None) -> str | None:
    """Normalize folder path: remove leading/trailing slashes, handle empty strings."""
    if not folder or not folder.strip():
        return None
    # Remove leading and trailing slashes, normalize path separators
    normalized = folder.strip().strip("/").strip("\\")
    if not normalized:
        return None
    # Replace backslashes with forward slashes for consistency
    normalized = normalized.replace("\\", "/")
    # Remove any double slashes
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


def _get_folder_storage_path(base_dir: str, folder: str | None) -> str:
    """Get the full storage path including folder subdirectory."""
    if folder:
        return os.path.join(base_dir, folder)
    return base_dir


def _ensure_folder_directories(category: str, folder: str | None) -> None:
    """Ensure all necessary directories exist for a given category and folder."""
    base_dir = DIRS[category]
    folder_path = _get_folder_storage_path(base_dir, folder)
    os.makedirs(folder_path, exist_ok=True)
    
    if category == "image":
        for sub_dir in IMAGE_SUBDIRECTORIES:
            os.makedirs(os.path.join(folder_path, sub_dir), exist_ok=True)


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
    """Scan file with ClamAV if enabled, otherwise allow upload."""
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
    except Exception as exc:
        logger.warning("ClamAV scan failed (upload allowed due to fallback): %s", exc)
        return True


def generate_image_variants(file_path: str, filename: str, folder: str | None = None) -> VariantPayload:
    """Generate all image variants and return their actual dimensions and file sizes."""
    base_name = f"{uuid.uuid4()}"
    extension = os.path.splitext(filename)[1].lower()
    if not extension:
        extension = ".jpg"
    filename_with_ext = f"{base_name}{extension}"
    variants: Dict[str, VariantInfo] = {}
    
    # Ensure folder directories exist
    _ensure_folder_directories("image", folder)
    
    # Build base path with folder
    base_image_dir = _get_folder_storage_path(DIRS["image"], folder)
    
    # Build path prefix for responses
    path_prefix = f"/files/images"
    if folder:
        path_prefix = f"{path_prefix}/{folder}"

    with Image.open(file_path) as img:
        image_format = img.format or "JPEG"
        original_width, original_height = img.size

        for variant_key, config in IMAGE_VARIANTS.items():
            variant_image = img.copy()
            variant_width, variant_height = original_width, original_height

            if config.get("max_size"):
                variant_image.thumbnail(config["max_size"], Image.Resampling.LANCZOS)
                variant_width, variant_height = variant_image.size

            if config.get("blur_radius"):
                variant_image = variant_image.filter(ImageFilter.GaussianBlur(config["blur_radius"]))

            variant_path = os.path.join(base_image_dir, config["folder"], filename_with_ext)

            save_kwargs: Dict[str, Any] = {"format": image_format}
            if config.get("quality") is not None:
                save_kwargs["quality"] = config["quality"]
                save_kwargs["optimize"] = True
                if image_format.upper() == "JPEG":
                    save_kwargs["subsampling"] = 1

            variant_image.save(variant_path, **save_kwargs)
            
            # Get actual file size after saving
            variant_file_size = os.path.getsize(variant_path)
            
            # Convert variant_key to response key (e.g., "image_url_high" -> "image_high")
            response_key = variant_key.replace("image_url_", "image_")
            variants[response_key] = {
                "path": f"{path_prefix}/{config['folder']}/{filename_with_ext}",
                "size": variant_file_size,
                "width": variant_width,
                "height": variant_height,
            }

    return {
        "base_name": base_name,
        "extension": extension.lstrip("."),
        "width": original_width,
        "height": original_height,
        "variants": variants,
    }


def extract_file_metadata(file_path: str, mime_type: str, category: str) -> Dict[str, Any]:
    """Extract metadata for non-image files (audio, video, pdf, etc.)."""
    metadata: Dict[str, Any] = {}
    
    if category == "audio":
        try:
            # Try to extract audio metadata using ffprobe if available
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                import json
                probe_data = json.loads(result.stdout)
                if "format" in probe_data:
                    format_info = probe_data["format"]
                    if "duration" in format_info:
                        metadata["duration"] = float(format_info["duration"])
                    if "bit_rate" in format_info:
                        metadata["bitrate"] = int(format_info["bit_rate"])
                if "streams" in probe_data and len(probe_data["streams"]) > 0:
                    stream = probe_data["streams"][0]
                    if "codec_name" in stream:
                        metadata["codec"] = stream["codec_name"]
                    if "sample_rate" in stream:
                        metadata["sample_rate"] = int(stream["sample_rate"])
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, Exception) as e:
            logger.debug("Could not extract audio metadata: %s", e)
    
    elif category == "video":
        try:
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                import json
                probe_data = json.loads(result.stdout)
                if "format" in probe_data:
                    format_info = probe_data["format"]
                    if "duration" in format_info:
                        metadata["duration"] = float(format_info["duration"])
                    if "bit_rate" in format_info:
                        metadata["bitrate"] = int(format_info["bit_rate"])
                if "streams" in probe_data:
                    video_stream = next((s for s in probe_data["streams"] if s.get("codec_type") == "video"), None)
                    if video_stream:
                        if "width" in video_stream and "height" in video_stream:
                            metadata["width"] = int(video_stream["width"])
                            metadata["height"] = int(video_stream["height"])
                        if "codec_name" in video_stream:
                            metadata["codec"] = video_stream["codec_name"]
                        if "r_frame_rate" in video_stream:
                            metadata["frame_rate"] = video_stream["r_frame_rate"]
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, Exception) as e:
            logger.debug("Could not extract video metadata: %s", e)
    
    elif category == "pdf":
        try:
            # Try to extract PDF metadata using pdfinfo if available
            import subprocess
            result = subprocess.run(
                ["pdfinfo", file_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "Pages:" in line:
                        try:
                            metadata["pages"] = int(line.split(":")[1].strip())
                        except (ValueError, IndexError):
                            pass
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug("Could not extract PDF metadata: %s", e)
    
    return metadata


async def persist_non_image_metadata(
    original_name: str,
    mime_type: str,
    file_size: int,
    category: str,
    base_name: str,
    extension: str,
    file_path: str,
    folder: str | None = None,
) -> MediaAsset:
    """Store metadata for non-image files in the database."""
    uid = uuid.uuid4()
    now = datetime.utcnow()
    
    # Extract additional metadata
    custom_properties = extract_file_metadata(file_path, mime_type, category)
    
    # Build folder path: category or "category/folder/subfolder"
    folder_path = category
    if folder:
        folder_path = f"{category}/{folder}"
    
    asset = MediaAsset(
        uid=uid.bytes,
        aspect_ratio=None,
        collection_name=None,
        original_name=original_name,
        title=None,
        name=base_name,
        model_type=category,
        folder=folder_path,
        mime_type=mime_type,
        extension=extension,
        disk="local",
        size=file_size,
        status=0,
        manipulations=None,
        custom_properties=custom_properties,
        responsive_images=None,
        order_column=None,
        created_by=None,
        updated_by=None,
        deleted_by=None,
        is_paragraph=None,
        created_at=now,
        updated_at=now,
    )

    async with AsyncSessionLocal() as session:
        session.add(asset)
        await session.commit()
        await session.refresh(asset)

    return asset


async def persist_asset_metadata(
    original_name: str,
    mime_type: str,
    file_size: int,
    variant_payload: VariantPayload,
    folder: str | None = None,
) -> MediaAsset:
    """Store asset metadata in the database."""
    uid = uuid.uuid4()
    width = variant_payload["width"]
    height = variant_payload["height"]
    aspect_ratio = width / height if height else None
    now = datetime.utcnow()
    
    # Build folder path: "images" or "images/folder/subfolder"
    folder_path = "images"
    if folder:
        folder_path = f"images/{folder}"

    # Store variants info in responsive_images
    asset = MediaAsset(
        uid=uid.bytes,
        aspect_ratio=aspect_ratio,
        collection_name=None,
        original_name=original_name,
        title=None,
        name=variant_payload["base_name"],
        model_type="image",
        folder=folder_path,
        mime_type=mime_type,
        extension=variant_payload["extension"],
        disk="local",
        size=file_size,
        status=0,
        manipulations=DEFAULT_MANIPULATIONS,
        custom_properties={"width": width, "height": height},
        responsive_images=variant_payload["variants"],
        is_paragraph=None,
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


async def get_asset_by_uid(uid_str: str) -> MediaAsset | None:
    """Get asset by UID string."""
    try:
        uid_bytes = uuid.UUID(uid_str).bytes
    except ValueError:
        return None
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(MediaAsset).where(MediaAsset.uid == uid_bytes))
        return result.scalar_one_or_none()


def delete_asset_files(asset: MediaAsset) -> None:
    """Delete all physical files associated with an asset."""
    filename_with_ext = f"{asset.name}.{asset.extension}"
    
    if asset.model_type == "image":
        # Parse folder from asset.folder (format: "images" or "images/folder/subfolder")
        folder = None
        if asset.folder and asset.folder.startswith("images/"):
            folder_part = asset.folder[7:]  # Remove "images/" prefix
            if folder_part:
                folder = folder_part
        
        # Build base path with folder
        base_image_dir = _get_folder_storage_path(DIRS["image"], folder)
        
        # Delete all image variants
        for variant_folder in IMAGE_SUBDIRECTORIES:
            # Standard variant path
            variant_path = os.path.join(base_image_dir, variant_folder, filename_with_ext)
            if os.path.exists(variant_path):
                try:
                    os.remove(variant_path)
                except OSError as e:
                    logger.warning("Failed to delete file %s: %s", variant_path, e)
            
            # High variant might have .jpg extension
            if variant_folder == "high":
                high_filename = f"{asset.name}.jpg"
                high_path = os.path.join(base_image_dir, variant_folder, high_filename)
                if os.path.exists(high_path):
                    try:
                        os.remove(high_path)
                    except OSError as e:
                        logger.warning("Failed to delete file %s: %s", high_path, e)
    else:
        # Parse folder from asset.folder (format: "category" or "category/folder/subfolder")
        folder = None
        category = asset.model_type or "unknown"
        if asset.folder and asset.folder.startswith(f"{category}/"):
            folder_part = asset.folder[len(category) + 1:]  # Remove "category/" prefix
            if folder_part:
                folder = folder_part
        
        # Build path with folder
        base_dir = DIRS.get(category, DIRS["image"])  # fallback to image if unknown
        file_path = os.path.join(_get_folder_storage_path(base_dir, folder), filename_with_ext)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                logger.warning("Failed to delete file %s: %s", file_path, e)


async def delete_asset_from_db(asset: MediaAsset) -> None:
    """Delete asset record from database."""
    async with AsyncSessionLocal() as session:
        await session.delete(asset)
        await session.commit()


def build_asset_payload(asset: MediaAsset) -> Dict[str, object]:
    """Build the exact JSON structure as specified by the user."""
    uid_str = str(uuid.UUID(bytes=asset.uid))
    filename_with_ext = f"{asset.name}.{asset.extension}"
    
    # Get original path based on file type
    if asset.model_type == "image":
        # Parse folder from asset.folder (format: "images" or "images/folder/subfolder")
        folder = None
        if asset.folder and asset.folder.startswith("images/"):
            folder_part = asset.folder[7:]  # Remove "images/" prefix
            if folder_part:
                folder = folder_part
        
        path_prefix = "/files/images"
        if folder:
            path_prefix = f"{path_prefix}/{folder}"
        original_path = f"{path_prefix}/original/{filename_with_ext}"
        responsive_images = asset.responsive_images or {}
        manipulations = asset.manipulations or DEFAULT_MANIPULATIONS
    else:
        original_path = f"/files/{asset.folder}/{filename_with_ext}"
        responsive_images = None
        manipulations = None
    
    # Build the exact structure
    asset_payload = {
        "uid": uid_str,
        "original_name": asset.original_name,
        "title": asset.title,
        "name": asset.name,
        "folder": asset.folder,
        "mime_type": asset.mime_type,
        "extension": asset.extension,
        "disk": asset.disk,
        "size": asset.size,
        "status": asset.status,
        "original": original_path,
        "manipulations": manipulations,
        "custom_properties": asset.custom_properties or {},
        "responsive_images": responsive_images,
        "is_paragraph": asset.is_paragraph,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }
    
    return {"asset": asset_payload}


# ==================== ROUTES ====================

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    token: str = Header(..., alias="X-Secret-Token"),
    folder: str | None = Form(None),
):
    """Upload a file with optional folder organization."""
    if token != SECRET_TOKEN:
        raise HTTPException(401, "Invalid token")

    # Normalize folder path
    normalized_folder = _normalize_folder_path(folder)

    temp_path = _get_temp_file_path(file.filename or "unknown")
    await _write_upload_to_temp(file, temp_path)

    mime_type = get_mime_type(temp_path)
    if not await scan_file_with_clamav(temp_path):
        _remove_file_if_exists(temp_path)
        raise HTTPException(400, "File failed security scan")

    category = classify_file(mime_type, file.filename or "unknown")

    if category == "image":
        file_size = os.path.getsize(temp_path)
        variant_payload = await asyncio.to_thread(
            generate_image_variants, temp_path, file.filename or "image", normalized_folder
        )
        _remove_file_if_exists(temp_path)
        asset = await persist_asset_metadata(
            file.filename or "unknown", mime_type, file_size, variant_payload, normalized_folder
        )
        return JSONResponse(build_asset_payload(asset))
    else:
        # Handle non-image files (audio, video, pdf, etc.)
        file_size = os.path.getsize(temp_path)
        extension = os.path.splitext(file.filename or "file")[1].lstrip(".")
        if not extension:
            # Try to guess extension from mime type
            if mime_type == "application/pdf":
                extension = "pdf"
            elif mime_type.startswith("audio/"):
                extension = "mp3"  # default
            elif mime_type.startswith("video/"):
                extension = "mp4"  # default
        
        base_name = f"{uuid.uuid4()}"
        unique_name = f"{base_name}.{extension}"
        
        # Ensure folder directories exist
        _ensure_folder_directories(category, normalized_folder)
        
        # Build final path with folder
        base_dir = _get_folder_storage_path(DIRS[category], normalized_folder)
        final_path = os.path.join(base_dir, unique_name)
        
        # Move file first, then extract metadata (some tools need the file in place)
        shutil.move(temp_path, final_path)
        
        # Persist metadata
        asset = await persist_non_image_metadata(
            original_name=file.filename or "unknown",
            mime_type=mime_type,
            file_size=file_size,
            category=category,
            base_name=base_name,
            extension=extension,
            file_path=final_path,
            folder=normalized_folder,
        )
        
        return JSONResponse(build_asset_payload(asset))


# NEW: Clean endpoint to get full asset info
@app.get("/asset/{base_name}")
async def get_asset_info(base_name: str = Path(..., description="Base name without extension")):
    """Return full JSON with all variants and metadata"""
    asset = await get_asset_by_base_name(base_name)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return build_asset_payload(asset)


# FIXED: Raw image URLs now serve actual images (not JSON!)
@app.get("/files/images/{variant}/{filename:path}")
async def serve_image_file(variant: str, filename: str):
    """Serve raw image files directly (for <img src="">, previews, etc.)
    
    Supports folder paths: /files/images/{variant}/{folder}/{filename}
    or /files/images/{variant}/{filename}
    """
    if variant not in IMAGE_VARIANT_SET:
        raise HTTPException(404, "Unknown variant")

    # Try to get asset from DB first to determine folder
    base_name, _ = os.path.splitext(os.path.basename(filename))
    asset = await get_asset_by_base_name(base_name)
    
    # Parse folder from filename path (filename might be "folder/subfolder/file.ext")
    folder = None
    if "/" in filename:
        folder_part = os.path.dirname(filename)
        if folder_part:
            folder = folder_part
    
    # If we have asset, use its folder info
    if asset and asset.folder and asset.folder.startswith("images/"):
        folder_part = asset.folder[7:]  # Remove "images/" prefix
        if folder_part:
            folder = folder_part
    
    # Build file path
    base_image_dir = _get_folder_storage_path(DIRS["image"], folder)
    file_path = os.path.join(base_image_dir, variant, os.path.basename(filename))
    
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found")

    media_type = asset.mime_type if asset else "application/octet-stream"
    
    # Handle high variant which might be .jpg
    if variant == "high" and not os.path.exists(file_path):
        high_filename = f"{base_name}.jpg"
        file_path = os.path.join(base_image_dir, variant, high_filename)
        if not os.path.exists(file_path):
            raise HTTPException(404, "File not found")

    return FileResponse(file_path, media_type=media_type)


@app.delete("/delete/name/{base_name}")
async def delete_asset_by_name(
    base_name: str,
    token: str = Header(..., alias="X-Secret-Token"),
):
    """Delete asset by base name (without extension)."""
    if token != SECRET_TOKEN:
        raise HTTPException(401, "Invalid token")
    
    asset = await get_asset_by_base_name(base_name)
    if not asset:
        raise HTTPException(404, "Asset not found")
    
    # Delete physical files
    delete_asset_files(asset)
    
    # Delete from database
    await delete_asset_from_db(asset)
    
    return JSONResponse({"status": "deleted", "name": base_name})


@app.delete("/delete/uid/{uid}")
async def delete_asset_by_uid(
    uid: str,
    token: str = Header(..., alias="X-Secret-Token"),
):
    """Delete asset by UID."""
    if token != SECRET_TOKEN:
        raise HTTPException(401, "Invalid token")
    
    asset = await get_asset_by_uid(uid)
    if not asset:
        raise HTTPException(404, "Asset not found")
    
    # Delete physical files
    delete_asset_files(asset)
    
    # Delete from database
    await delete_asset_from_db(asset)
    
    return JSONResponse({"status": "deleted", "uid": uid})


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