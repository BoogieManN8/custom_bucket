# How to Run Tests

## Quick Start

The easiest way to run all integration tests:

```bash
./run_tests.sh
```

Or directly:

```bash
docker compose exec assets-bucket python -m pytest tests/test_integration.py -v
```

## Test Commands

### Run All Integration Tests (Recommended)
```bash
docker compose exec assets-bucket python -m pytest tests/test_integration.py -v
```

### Run Specific Test
```bash
docker compose exec assets-bucket python -m pytest tests/test_integration.py::test_upload_image_without_folder -v
```

### Run All Tests
```bash
docker compose exec assets-bucket python -m pytest tests/ -v
```

### Run with Output
```bash
docker compose exec assets-bucket python -m pytest tests/test_integration.py -v -s
```

## Test Files

- **test_integration.py** - Integration tests against running API (✅ Recommended - all tests pass)
- test_upload.py - Upload functionality tests
- test_retrieval.py - Asset retrieval tests
- test_deletion.py - Deletion tests
- test_folder_feature.py - Folder feature tests

## Note

The integration tests automatically read the `SECRET_TOKEN` from `/app/.env` in the container, so no manual configuration is needed. Just make sure your `.env` file exists and contains `SECRET_TOKEN=your_token`.

## Expected Output

```
============================= test session starts ==============================
collected 9 items

tests/test_integration.py::test_health_endpoint PASSED
tests/test_integration.py::test_upload_image_without_folder PASSED
tests/test_integration.py::test_upload_image_with_folder PASSED
tests/test_integration.py::test_upload_image_with_empty_folder PASSED
tests/test_integration.py::test_get_asset_by_name PASSED
tests/test_integration.py::test_delete_asset_by_name PASSED
tests/test_integration.py::test_delete_asset_by_uid PASSED
tests/test_integration.py::test_folder_path_normalization PASSED
tests/test_integration.py::test_invalid_token PASSED

======================== 9 passed in 0.65s =========================
```

