"""Tests for asset deletion functionality."""
import pytest
from fastapi import status


def test_delete_asset_by_name(client, test_token, sample_image):
    """Test deleting an asset by base name."""
    # First upload an asset
    upload_response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": test_token},
    )
    assert upload_response.status_code == status.HTTP_200_OK
    asset_data = upload_response.json()["asset"]
    base_name = asset_data["name"]
    
    # Delete it
    response = client.delete(
        f"/delete/name/{base_name}",
        headers={"X-Secret-Token": test_token},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "deleted"
    assert response.json()["name"] == base_name
    
    # Verify it's deleted
    get_response = client.get(f"/asset/{base_name}")
    assert get_response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_asset_by_uid(client, test_token, sample_image):
    """Test deleting an asset by UID."""
    # First upload an asset
    upload_response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": test_token},
    )
    assert upload_response.status_code == status.HTTP_200_OK
    asset_data = upload_response.json()["asset"]
    uid = asset_data["uid"]
    base_name = asset_data["name"]
    
    # Delete it
    response = client.delete(
        f"/delete/uid/{uid}",
        headers={"X-Secret-Token": test_token},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "deleted"
    assert response.json()["uid"] == uid
    
    # Verify it's deleted
    get_response = client.get(f"/asset/{base_name}")
    assert get_response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_asset_with_folder(client, test_token, sample_image):
    """Test deleting an asset that was uploaded with a folder."""
    # Upload with folder
    upload_response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "test_folder"},
        headers={"X-Secret-Token": test_token},
    )
    assert upload_response.status_code == status.HTTP_200_OK
    asset_data = upload_response.json()["asset"]
    base_name = asset_data["name"]
    
    # Delete it
    response = client.delete(
        f"/delete/name/{base_name}",
        headers={"X-Secret-Token": test_token},
    )
    assert response.status_code == status.HTTP_200_OK
    
    # Verify it's deleted
    get_response = client.get(f"/asset/{base_name}")
    assert get_response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_nonexistent_asset_by_name(client, test_token):
    """Test deleting a non-existent asset by name."""
    response = client.delete(
        "/delete/name/nonexistent123",
        headers={"X-Secret-Token": test_token},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_nonexistent_asset_by_uid(client, test_token):
    """Test deleting a non-existent asset by UID."""
    import uuid
    fake_uid = str(uuid.uuid4())
    response = client.delete(
        f"/delete/uid/{fake_uid}",
        headers={"X-Secret-Token": test_token},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_with_invalid_token(client, test_token, sample_image):
    """Test deleting with invalid token."""
    # First upload an asset
    upload_response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        headers={"X-Secret-Token": test_token},
    )
    assert upload_response.status_code == status.HTTP_200_OK
    asset_data = upload_response.json()["asset"]
    base_name = asset_data["name"]
    
    # Try to delete with wrong token
    response = client.delete(
        f"/delete/name/{base_name}",
        headers={"X-Secret-Token": "wrong_token"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_delete_pdf_with_folder(client, test_token, sample_pdf):
    """Test deleting a PDF that was uploaded with a folder."""
    # Upload PDF with folder
    upload_response = client.post(
        "/upload",
        files={"file": ("test.pdf", sample_pdf, "application/pdf")},
        data={"folder": "documents/contracts"},
        headers={"X-Secret-Token": test_token},
    )
    assert upload_response.status_code == status.HTTP_200_OK
    asset_data = upload_response.json()["asset"]
    base_name = asset_data["name"]
    
    # Delete it
    response = client.delete(
        f"/delete/name/{base_name}",
        headers={"X-Secret-Token": test_token},
    )
    assert response.status_code == status.HTTP_200_OK
    
    # Verify it's deleted
    get_response = client.get(f"/asset/{base_name}")
    assert get_response.status_code == status.HTTP_404_NOT_FOUND

