"""Tests specifically for the folder feature."""
import pytest
import os
from fastapi import status


def test_folder_creates_directory_structure(client, test_token, sample_image, test_storage_dir):
    """Test that folder parameter creates proper directory structure."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "products/2024/january"},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    
    # Check that directories were created
    expected_path = os.path.join(test_storage_dir, "images", "products", "2024", "january")
    assert os.path.exists(expected_path)
    
    # Check that subdirectories for image variants exist
    for variant in ["small", "medium", "high", "original", "placeholder"]:
        variant_path = os.path.join(expected_path, variant)
        assert os.path.exists(variant_path)


def test_multiple_uploads_same_folder(client, test_token, sample_image):
    """Test uploading multiple files to the same folder."""
    folder = "shared_folder"
    
    # Upload first file
    response1 = client.post(
        "/upload",
        files={"file": ("test1.png", sample_image, "image/png")},
        data={"folder": folder},
        headers={"X-Secret-Token": test_token},
    )
    assert response1.status_code == status.HTTP_200_OK
    asset1 = response1.json()["asset"]
    
    # Upload second file
    response2 = client.post(
        "/upload",
        files={"file": ("test2.png", sample_image, "image/png")},
        data={"folder": folder},
        headers={"X-Secret-Token": test_token},
    )
    assert response2.status_code == status.HTTP_200_OK
    asset2 = response2.json()["asset"]
    
    # Both should have the same folder
    assert asset1["folder"] == asset2["folder"] == f"images/{folder}"
    # But different names
    assert asset1["name"] != asset2["name"]


def test_folder_path_normalization(client, test_token, sample_image):
    """Test that various folder path formats are normalized correctly."""
    test_cases = [
        ("/folder", "images/folder"),
        ("folder/", "images/folder"),
        ("/folder/", "images/folder"),
        ("folder//subfolder", "images/folder/subfolder"),
        ("folder\\subfolder", "images/folder/subfolder"),
        ("  folder  ", "images/folder"),
    ]
    
    for input_folder, expected_folder in test_cases:
        response = client.post(
            "/upload",
            files={"file": ("test.png", sample_image, "image/png")},
            data={"folder": input_folder},
            headers={"X-Secret-Token": test_token},
        )
        assert response.status_code == status.HTTP_200_OK
        asset = response.json()["asset"]
        assert asset["folder"] == expected_folder


def test_folder_with_special_characters(client, test_token, sample_image):
    """Test folder paths with special characters."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "folder-name_with.123"},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    asset = response.json()["asset"]
    assert asset["folder"] == "images/folder-name_with.123"


def test_folder_affects_file_paths(client, test_token, sample_image):
    """Test that folder affects the file paths in responses."""
    response = client.post(
        "/upload",
        files={"file": ("test.png", sample_image, "image/png")},
        data={"folder": "test_folder"},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response.status_code == status.HTTP_200_OK
    asset = response.json()["asset"]
    
    # Check original path includes folder
    assert "/test_folder/" in asset["original"] or asset["original"].endswith("/test_folder/original/")
    
    # Check responsive images paths include folder
    if asset.get("responsive_images"):
        for variant_info in asset["responsive_images"].values():
            assert "/test_folder/" in variant_info["path"]


def test_empty_folder_parameter(client, test_token, sample_image):
    """Test that empty folder parameter works the same as no folder."""
    # Upload without folder
    response1 = client.post(
        "/upload",
        files={"file": ("test1.png", sample_image, "image/png")},
        headers={"X-Secret-Token": test_token},
    )
    
    # Upload with empty folder
    response2 = client.post(
        "/upload",
        files={"file": ("test2.png", sample_image, "image/png")},
        data={"folder": ""},
        headers={"X-Secret-Token": test_token},
    )
    
    assert response1.status_code == status.HTTP_200_OK
    assert response2.status_code == status.HTTP_200_OK
    
    asset1 = response1.json()["asset"]
    asset2 = response2.json()["asset"]
    
    # Both should have the same folder (just "images")
    assert asset1["folder"] == asset2["folder"] == "images"

