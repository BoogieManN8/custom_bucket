# API Documentation

Base URL: `http://localhost:8088` (or your server URL)

All endpoints that require authentication use the `X-Secret-Token` header with the value from your `.env` file.

---

## 1. Upload File

**POST** `/upload`

Upload a file (image, PDF, audio, video) with optional folder organization.

### Headers
- `X-Secret-Token` (required): Authentication token

### Form Data
- `file` (required): The file to upload
- `folder` (optional): Folder path for organization (e.g., `"products/2024"`, `"users/123/photos"`)
  - Empty string or omitted = default location
  - Leading/trailing slashes are normalized
  - Backslashes are converted to forward slashes

### Supported File Types
- **Images**: PNG, JPEG, GIF, WebP, etc. (generates variants: small, medium, high, original, placeholder)
- **PDF**: PDF documents
- **Audio**: MP3, WAV, etc.
- **Video**: MP4, AVI, etc.

### Response (200 OK)
```json
{
  "asset": {
    "uid": "uuid-string",
    "original_name": "filename.png",
    "title": null,
    "name": "generated-uuid-base-name",
    "folder": "images/products/2024",
    "mime_type": "image/png",
    "extension": "png",
    "disk": "local",
    "size": 12345,
    "status": 0,
    "original": "/files/images/products/2024/original/filename.png",
    "manipulations": {
      "small": {"max_dimension": 320},
      "medium": {"max_dimension": 800},
      "high": {"max_dimension": 1600},
      "placeholder": {"max_dimension": 20, "blur": 2}
    },
    "custom_properties": {
      "width": 1920,
      "height": 1080
    },
    "responsive_images": {
      "image_small": {
        "path": "/files/images/products/2024/small/filename.png",
        "size": 5000,
        "width": 320,
        "height": 180
      },
      "image_medium": {
        "path": "/files/images/products/2024/medium/filename.png",
        "size": 15000,
        "width": 800,
        "height": 450
      },
      "image_high": {
        "path": "/files/images/products/2024/high/filename.png",
        "size": 80000,
        "width": 1600,
        "height": 900
      },
      "image_original": {
        "path": "/files/images/products/2024/original/filename.png",
        "size": 200000,
        "width": 1920,
        "height": 1080
      },
      "image_placeholder": {
        "path": "/files/images/products/2024/placeholder/filename.png",
        "size": 200,
        "width": 20,
        "height": 20
      }
    },
    "is_paragraph": null,
    "created_at": "2025-12-02T10:30:00.123456",
    "updated_at": "2025-12-02T10:30:00.123456"
  }
}
```

### Error Responses
- `401 Unauthorized`: Invalid or missing token
- `400 Bad Request`: Unsupported file type or failed security scan

### Example (cURL)
```bash
# Upload without folder
curl -X POST http://localhost:8088/upload \
  -H "X-Secret-Token: your_token_here" \
  -F "file=@image.png"

# Upload with folder
curl -X POST http://localhost:8088/upload \
  -H "X-Secret-Token: your_token_here" \
  -F "file=@image.png" \
  -F "folder=products/2024"

# Upload PDF with folder
curl -X POST http://localhost:8088/upload \
  -H "X-Secret-Token: your_token_here" \
  -F "file=@document.pdf" \
  -F "folder=documents/contracts"
```

---

## 2. Get Asset Metadata

**GET** `/asset/{base_name}`

Retrieve full metadata for an asset by its base name (UUID without extension).

### Path Parameters
- `base_name` (required): The base name (UUID) of the asset without extension

### Response (200 OK)
Same structure as upload response.

### Error Responses
- `404 Not Found`: Asset not found

### Example
```bash
curl http://localhost:8088/asset/82125263-45f9-4d7d-ab3f-3e49faaf3511
```

---

## 3. Serve Image File

**GET** `/files/images/{variant}/{filename:path}`

Serve raw image files directly. Supports folder paths in filename.

### Path Parameters
- `variant` (required): Image variant - one of: `small`, `medium`, `high`, `original`, `placeholder`
- `filename:path` (required): Filename with optional folder path
  - Simple: `filename.png`
  - With folder: `products/2024/filename.png`

### Response (200 OK)
- Content-Type: Image MIME type (e.g., `image/png`, `image/jpeg`)
- Body: Binary image data

### Error Responses
- `404 Not Found`: Unknown variant or file not found

### Example
```bash
# Serve original image
curl http://localhost:8088/files/images/original/filename.png

# Serve small variant
curl http://localhost:8088/files/images/small/filename.png

# Serve from folder
curl http://localhost:8088/files/images/original/products/2024/filename.png
```

### HTML Usage
```html
<img src="http://localhost:8088/files/images/medium/filename.png" alt="Image">
```

---

## 4. Delete Asset by Name

**DELETE** `/delete/name/{base_name}`

Delete an asset and all its files by base name.

### Headers
- `X-Secret-Token` (required): Authentication token

### Path Parameters
- `base_name` (required): The base name (UUID) of the asset without extension

### Response (200 OK)
```json
{
  "status": "deleted",
  "name": "82125263-45f9-4d7d-ab3f-3e49faaf3511"
}
```

### Error Responses
- `401 Unauthorized`: Invalid or missing token
- `404 Not Found`: Asset not found

### Example
```bash
curl -X DELETE http://localhost:8088/delete/name/82125263-45f9-4d7d-ab3f-3e49faaf3511 \
  -H "X-Secret-Token: your_token_here"
```

---

## 5. Delete Asset by UID

**DELETE** `/delete/uid/{uid}`

Delete an asset and all its files by UID.

### Headers
- `X-Secret-Token` (required): Authentication token

### Path Parameters
- `uid` (required): The full UUID string of the asset

### Response (200 OK)
```json
{
  "status": "deleted",
  "uid": "e7dad70b-81f7-44f1-8aa2-83726ce9e8a2"
}
```

### Error Responses
- `401 Unauthorized`: Invalid or missing token
- `404 Not Found`: Asset not found

### Example
```bash
curl -X DELETE http://localhost:8088/delete/uid/e7dad70b-81f7-44f1-8aa2-83726ce9e8a2 \
  -H "X-Secret-Token: your_token_here"
```

---

## 6. Health Check

**GET** `/health`

Check if the API is running.

### Response (200 OK)
```json
{
  "status": "ok"
}
```

### Example
```bash
curl http://localhost:8088/health
```

---

## 7. Test Endpoint

**GET** `/test`

Simple test endpoint.

### Response (200 OK)
```json
{
  "Message": "Direct image URLs now work!"
}
```

---

## Image Variants

When uploading images, the following variants are automatically generated:

| Variant | Max Size | Quality | Description |
|---------|----------|---------|-------------|
| `small` | 320×320 | Original | Thumbnail for lists |
| `medium` | 800×800 | Original | Standard display |
| `high` | 1600×1600 | 70% | Compressed high-res |
| `original` | Original | 95% (JPEG) | Full quality original |
| `placeholder` | 20×20 | Original + Blur | Blurred placeholder |

All variants maintain aspect ratio. The `high` variant is always saved as JPEG for better compression.

---

## Folder Organization

The optional `folder` parameter allows organizing files in subdirectories:

- **Format**: `"path/to/folder"` (no leading/trailing slashes needed)
- **Normalization**: 
  - `/folder/` → `folder`
  - `folder\subfolder` → `folder/subfolder`
  - `folder//subfolder` → `folder/subfolder`
- **Storage**: Files are stored in `storage/{category}/{folder}/`
- **Database**: Folder path stored as `"{category}/{folder}"` (e.g., `"images/products/2024"`)

### Examples
- `folder="products"` → stored in `storage/images/products/`
- `folder="users/123/photos"` → stored in `storage/images/users/123/photos/`
- `folder=""` or omitted → stored in `storage/images/` (default)

---

## Response Fields

### Asset Object
- `uid`: Unique identifier (UUID string)
- `original_name`: Original filename from upload
- `name`: Generated base name (UUID without extension)
- `folder`: Storage folder path (e.g., `"images/products/2024"`)
- `mime_type`: File MIME type
- `extension`: File extension
- `size`: File size in bytes
- `original`: URL path to original file
- `responsive_images`: Object with variant info (images only)
- `manipulations`: Processing settings (images only)
- `custom_properties`: Extracted metadata (dimensions, duration, etc.)
- `is_paragraph`: Boolean flag (default: `null`)
- `created_at`: ISO 8601 timestamp
- `updated_at`: ISO 8601 timestamp

### Responsive Images Object (Images Only)
Each variant contains:
- `path`: URL path to variant
- `size`: File size in bytes
- `width`: Image width in pixels
- `height`: Image height in pixels

---

## Error Codes

| Code | Description |
|------|-------------|
| `200` | Success |
| `400` | Bad Request (unsupported file type, failed security scan) |
| `401` | Unauthorized (invalid or missing token) |
| `404` | Not Found (asset/file doesn't exist) |
| `422` | Unprocessable Entity (validation error) |

---

## Notes

- All timestamps are in ISO 8601 format (UTC)
- File paths in responses are relative to the base URL
- Image variants are generated asynchronously during upload
- Non-image files (PDF, audio, video) store metadata in `custom_properties`
- Deletion removes both physical files and database records
- The `high` variant for images is always JPEG format for compression

