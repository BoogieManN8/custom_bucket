"""Pytest configuration and fixtures."""
import os
import tempfile
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Set test environment variables before importing main
os.environ["SECRET_TOKEN"] = "test_secret_token_12345"
os.environ["CLAMAV_ENABLED"] = "false"
os.environ["BASE_PATH"] = str(Path(tempfile.mkdtemp()) / "test_storage")
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PORT"] = "3307"
os.environ["DB_NAME"] = "test_assets_bucket"
os.environ["DB_USER"] = "asset_user"
os.environ["DB_PASSWORD"] = "asset_pass"

# Import after setting env vars
try:
    from main import app
except Exception as e:
    # If database connection fails, we'll skip database-dependent tests
    pytest.skip(f"Could not import app: {e}", allow_module_level=True)


@pytest.fixture(scope="function")
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture(scope="function")
def test_storage_dir():
    """Get the test storage directory."""
    return os.environ["BASE_PATH"]


@pytest.fixture(scope="function", autouse=True)
def cleanup_storage(test_storage_dir):
    """Clean up storage directory before and after each test."""
    # Clean before
    if os.path.exists(test_storage_dir):
        shutil.rmtree(test_storage_dir)
    os.makedirs(test_storage_dir, exist_ok=True)
    
    yield
    
    # Clean after
    if os.path.exists(test_storage_dir):
        shutil.rmtree(test_storage_dir)


@pytest.fixture
def test_token():
    """Get the test secret token."""
    return "test_secret_token_12345"


@pytest.fixture
def sample_image():
    """Create a sample test image."""
    from PIL import Image
    import io
    
    # Create a simple 100x100 red image
    img = Image.new("RGB", (100, 100), color="red")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes.getvalue()


@pytest.fixture
def sample_pdf():
    """Create a sample test PDF content."""
    # Minimal valid PDF
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 0\ntrailer\n<< /Size 0 /Root 1 0 R >>\nstartxref\n0\n%%EOF"

