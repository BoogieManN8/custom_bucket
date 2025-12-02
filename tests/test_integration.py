"""Integration tests that test the actual running API."""
import pytest
import requests
import os
from PIL import Image
import io


@pytest.fixture
def api_url():
    """Get the API URL from environment or default."""
    return os.getenv("API_URL", "http://localhost:8088")


@pytest.fixture
def secret_token():
    """Get secret token from .env file (prioritized over environment variable for integration tests)."""
    token = None
    
    # For integration tests, always read from .env file first (ignore env var from conftest.py)
    env_paths = [
        "/app/.env",  # Container path (where tests run)
        os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),  # Local path
    ]
    
    for env_path in env_paths:
        try:
            if os.path.exists(env_path):
                with open(env_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("SECRET_TOKEN="):
                            token = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if token:
                                break
                if token:
                    break
        except (FileNotFoundError, Exception):
            continue
    
    # Fallback to environment variable only if .env file not found
    if not token:
        token = os.getenv("SECRET_TOKEN")
    
    if not token:
        pytest.skip("SECRET_TOKEN not found. Set it in .env file or as SECRET_TOKEN environment variable.")
    
    return token


@pytest.fixture
def sample_image():
    """Create a sample test image."""
    img = Image.new("RGB", (100, 100), color="red")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes.getvalue()


def test_health_endpoint(api_url):
    """Test the health check endpoint."""
    response = requests.get(f"{api_url}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_image_without_folder(api_url, secret_token, sample_image):
    """Test uploading an image without folder."""
    response = requests.post(
        f"{api_url}/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": secret_token},
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text[:500]}"
    data = response.json()
    assert "asset" in data, f"Response doesn't contain 'asset' key. Response: {data}"
    asset = data["asset"]
    # Check folder instead of model_type (model_type is not in response, but folder indicates type)
    assert asset["folder"] == "images", f"Expected folder='images', got: {asset.get('folder')}"
    assert asset["mime_type"].startswith("image/"), f"Expected image mime type, got: {asset.get('mime_type')}"
    assert asset["name"] is not None
    assert asset["uid"] is not None


def test_upload_image_with_folder(api_url, secret_token, sample_image):
    """Test uploading an image with folder."""
    response = requests.post(
        f"{api_url}/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "test/products/2024"},
        headers={"X-Secret-Token": secret_token},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "asset" in data
    asset = data["asset"]
    assert asset["folder"] == "images/test/products/2024"
    assert asset["mime_type"].startswith("image/")
    assert asset["name"] is not None
    
    # Check that paths include folder
    if asset.get("responsive_images"):
        first_variant = list(asset["responsive_images"].values())[0]
        assert "/test/products/2024/" in first_variant["path"]


def test_upload_image_with_empty_folder(api_url, secret_token, sample_image):
    """Test uploading with empty folder parameter."""
    response = requests.post(
        f"{api_url}/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": ""},
        headers={"X-Secret-Token": secret_token},
    )
    
    assert response.status_code == 200
    data = response.json()
    asset = data["asset"]
    assert asset["folder"] == "images"


def test_get_asset_by_name(api_url, secret_token, sample_image):
    """Test retrieving an asset by name."""
    # Upload first
    upload_response = requests.post(
        f"{api_url}/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "retrieval_test"},
        headers={"X-Secret-Token": secret_token},
    )
    assert upload_response.status_code == 200
    base_name = upload_response.json()["asset"]["name"]
    
    # Retrieve
    response = requests.get(f"{api_url}/asset/{base_name}")
    assert response.status_code == 200
    data = response.json()
    assert data["asset"]["name"] == base_name
    assert data["asset"]["folder"] == "images/retrieval_test"


def test_delete_asset_by_name(api_url, secret_token, sample_image):
    """Test deleting an asset by name."""
    # Upload first
    upload_response = requests.post(
        f"{api_url}/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": secret_token},
    )
    assert upload_response.status_code == 200
    base_name = upload_response.json()["asset"]["name"]
    
    # Delete
    delete_response = requests.delete(
        f"{api_url}/delete/name/{base_name}",
        headers={"X-Secret-Token": secret_token},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"
    
    # Verify deleted
    get_response = requests.get(f"{api_url}/asset/{base_name}")
    assert get_response.status_code == 404


def test_delete_asset_by_uid(api_url, secret_token, sample_image):
    """Test deleting an asset by UID."""
    # Upload first
    upload_response = requests.post(
        f"{api_url}/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "delete_test"},
        headers={"X-Secret-Token": secret_token},
    )
    assert upload_response.status_code == 200
    uid = upload_response.json()["asset"]["uid"]
    base_name = upload_response.json()["asset"]["name"]
    
    # Delete
    delete_response = requests.delete(
        f"{api_url}/delete/uid/{uid}",
        headers={"X-Secret-Token": secret_token},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"
    
    # Verify deleted
    get_response = requests.get(f"{api_url}/asset/{base_name}")
    assert get_response.status_code == 404


def test_folder_path_normalization(api_url, secret_token, sample_image):
    """Test folder path normalization."""
    test_cases = [
        ("/folder", "images/folder"),
        ("folder/", "images/folder"),
        ("/folder/", "images/folder"),
    ]
    
    for input_folder, expected_folder in test_cases:
        response = requests.post(
            f"{api_url}/upload",
            files={"file": ("test.png", sample_image, "image/png")},
            data={"folder": input_folder},
            headers={"X-Secret-Token": secret_token},
        )
        assert response.status_code == 200
        asset = response.json()["asset"]
        assert asset["folder"] == expected_folder


def test_invalid_token(api_url, sample_image):
    """Test with invalid token."""
    response = requests.post(
        f"{api_url}/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": "wrong_token"},
    )
    assert response.status_code == 401

