# How to Run Tests

## Quick Commands

### Run Integration Tests (Recommended)
These tests work against the running API and are the most reliable:

```bash
# Simple way - run all integration tests
docker compose exec assets-bucket python -m pytest tests/test_integration.py -v

# Or use the helper script
./run_tests.sh
```

### Run All Tests
```bash
docker compose exec assets-bucket python -m pytest tests/ -v
```

### Run Specific Test File
```bash
# Integration tests
docker compose exec assets-bucket python -m pytest tests/test_integration.py -v

# Upload tests
docker compose exec assets-bucket python -m pytest tests/test_upload.py -v

# Deletion tests
docker compose exec assets-bucket python -m pytest tests/test_deletion.py -v

# Folder feature tests
docker compose exec assets-bucket python -m pytest tests/test_folder_feature.py -v
```

### Run Specific Test
```bash
docker compose exec assets-bucket python -m pytest tests/test_integration.py::test_health_endpoint -v
```

## Test Options

### Verbose Output
```bash
docker compose exec assets-bucket python -m pytest tests/ -v
```

### Show Print Statements
```bash
docker compose exec assets-bucket python -m pytest tests/ -v -s
```

### Stop on First Failure
```bash
docker compose exec assets-bucket python -m pytest tests/ -v -x
```

### Show Test Coverage
```bash
docker compose exec assets-bucket python -m pytest tests/ --cov=main --cov-report=html
```

## Note About Token

Some tests require the `SECRET_TOKEN`. The integration tests will try to read it from the `.env` file automatically. If tests fail with 401 errors, make sure:

1. The `.env` file exists
2. It contains `SECRET_TOKEN=your_token_here`
3. The Docker container has access to it

## Test Files Overview

- **test_integration.py** - Tests against running API (most reliable, recommended)
- **test_upload.py** - Upload functionality tests
- **test_retrieval.py** - Asset retrieval and serving tests  
- **test_deletion.py** - Deletion by name and UID tests
- **test_folder_feature.py** - Folder feature specific tests

## Example Output

```
============================= test session starts ==============================
platform linux -- Python 3.12.12, pytest-9.0.1
collected 10 items

tests/test_integration.py::test_health_endpoint PASSED
tests/test_integration.py::test_upload_image_without_folder PASSED
tests/test_integration.py::test_upload_image_with_folder PASSED
...

======================== 10 passed in 2.34s =========================
```

