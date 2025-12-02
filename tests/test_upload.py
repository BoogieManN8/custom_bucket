"""Tests for file upload functionality."""
import pytest
from fastapi import status


def test_upload_image_without_folder(client, test_token, sample_image):
    """Test uploading an image without folder parameter."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "asset" in data
    asset = data["asset"]
    assert asset["model_type"] == "image"
    assert asset["folder"] == "images"
    assert asset["name"] is not None
    assert asset["uid"] is not None
    assert "responsive_images" in asset
    assert asset["responsive_images"] is not None


def test_upload_image_with_folder(client, test_token, sample_image):
    """Test uploading an image with folder parameter."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "products/2024"},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "asset" in data
    asset = data["asset"]
    assert asset["model_type"] == "image"
    assert asset["folder"] == "images/products/2024"
    assert asset["name"] is not None
    assert "responsive_images" in asset
    
    # Check that paths include folder
    responsive_images = asset["responsive_images"]
    if responsive_images:
        first_variant = list(responsive_images.values())[0]
        assert "/products/2024/" in first_variant["path"]


def test_upload_image_with_empty_folder(client, test_token, sample_image):
    """Test uploading an image with empty folder parameter."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": ""},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "asset" in data
    asset = data["asset"]
    assert asset["folder"] == "images"  # Should default to "images"


def test_upload_image_with_nested_folder(client, test_token, sample_image):
    """Test uploading an image with nested folder path."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "users/123/photos"},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "asset" in data
    asset = data["asset"]
    assert asset["folder"] == "images/users/123/photos"


def test_upload_pdf_without_folder(client, test_token, sample_pdf):
    """Test uploading a PDF without folder parameter."""
    response = client.post(
        "/upload",
        files={"file": ("test.pdf", sample_pdf, "application/pdf")},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "asset" in data
    asset = data["asset"]
    assert asset["model_type"] == "pdf"
    assert asset["folder"] == "pdf"


def test_upload_pdf_with_folder(client, test_token, sample_pdf):
    """Test uploading a PDF with folder parameter."""
    response = client.post(
        "/upload",
        files={"file": ("test.pdf", sample_pdf, "application/pdf")},
        data={"folder": "documents/contracts"},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "asset" in data
    asset = data["asset"]
    assert asset["model_type"] == "pdf"
    assert asset["folder"] == "pdf/documents/contracts"


def test_upload_invalid_token(client, sample_image):
    """Test uploading with invalid token."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": "wrong_token"},
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_upload_missing_token(client, sample_image):
    """Test uploading without token."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
    )
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_upload_folder_with_slashes(client, test_token, sample_image):
    """Test that folder paths with leading/trailing slashes are normalized."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "/products/2024/"},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    asset = data["asset"]
    assert asset["folder"] == "images/products/2024"  # Should be normalized


def test_upload_folder_with_backslashes(client, test_token, sample_image):
    """Test that folder paths with backslashes are normalized."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "products\\2024"},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    asset = data["asset"]
    assert asset["folder"] == "images/products/2024"  # Should be normalized

