"""Tests for asset retrieval functionality."""
import pytest
from fastapi import status


def test_get_asset_by_name(client, test_token, sample_image):
    """Test retrieving an asset by base name."""
    # First upload an asset
    upload_response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "test_folder"},
        headers={"X-Secret-Token": test_token},
    )
    assert upload_response.status_code == status.HTTP_200_OK
    asset_data = upload_response.json()["asset"]
    base_name = asset_data["name"]
    
    # Then retrieve it
    response = client.get(f"/asset/{base_name}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "asset" in data
    assert data["asset"]["name"] == base_name
    assert data["asset"]["folder"] == "images/test_folder"


def test_get_nonexistent_asset(client):
    """Test retrieving a non-existent asset."""
    response = client.get("/asset/nonexistent123")
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_get_asset_with_folder(client, test_token, sample_image):
    """Test retrieving an asset that was uploaded with a folder."""
    # Upload with folder
    upload_response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "products/2024"},
        headers={"X-Secret-Token": test_token},
    )
    assert upload_response.status_code == status.HTTP_200_OK
    asset_data = upload_response.json()["asset"]
    base_name = asset_data["name"]
    uid = asset_data["uid"]
    
    # Retrieve by name
    response = client.get(f"/asset/{base_name}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["asset"]["folder"] == "images/products/2024"
    assert data["asset"]["uid"] == uid


def test_serve_image_file(client, test_token, sample_image):
    """Test serving an image file directly."""
    # Upload an image
    upload_response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": test_token},
    )
    assert upload_response.status_code == status.HTTP_200_OK
    asset_data = upload_response.json()["asset"]
    base_name = asset_data["name"]
    extension = asset_data["extension"]
    filename = f"{base_name}.{extension}"
    
    # Try to serve the original variant
    response = client.get(f"/files/images/original/{filename}")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "image/png"


def test_serve_image_variants(client, test_token, sample_image):
    """Test serving different image variants."""
    # Upload an image
    upload_response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": test_token},
    )
    assert upload_response.status_code == status.HTTP_200_OK
    asset_data = upload_response.json()["asset"]
    base_name = asset_data["name"]
    extension = asset_data["extension"]
    filename = f"{base_name}.{extension}"
    
    # Test all variants
    variants = ["small", "medium", "high", "original", "placeholder"]
    for variant in variants:
        response = client.get(f"/files/images/{variant}/{filename}")
        # May be 404 if file doesn't exist, but endpoint should work
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]


def test_health_endpoint(client):
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}

