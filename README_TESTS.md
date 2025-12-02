# Running Tests

## Quick Start

### Run Integration Tests (Recommended)
These tests run against the actual running API and don't require database setup:

```bash
# Make sure Docker containers are running
docker compose up -d

# Run integration tests
docker compose exec assets-bucket python -m pytest tests/test_integration.py -v
```

### Run All Tests (Requires Database Connection)
To run all tests, you need the database to be accessible. The unit tests require a database connection:

```bash
# Run all tests
docker compose exec assets-bucket python -m pytest tests/ -v

# Run specific test file
docker compose exec assets-bucket python -m pytest tests/test_upload.py -v

# Run specific test
docker compose exec assets-bucket python -m pytest tests/test_integration.py::test_upload_image_with_folder -v
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

### Run Only Passing Tests
```bash
docker compose exec assets-bucket python -m pytest tests/ -v -x
```

### Show Coverage
```bash
docker compose exec assets-bucket python -m pytest tests/ --cov=main --cov-report=html
```

## Test Files

- `test_integration.py` - Integration tests against running API (recommended)
- `test_upload.py` - Upload functionality tests
- `test_retrieval.py` - Asset retrieval tests
- `test_deletion.py` - Deletion tests
- `test_folder_feature.py` - Folder feature specific tests

## Running Tests Locally (Outside Docker)

If you have Python and dependencies installed locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export SECRET_TOKEN=$(grep SECRET_TOKEN .env | cut -d'=' -f2)
export API_URL=http://localhost:8088

# Run integration tests
pytest tests/test_integration.py -v
```

## Note

Most unit tests require a database connection. The integration tests (`test_integration.py`) are the most reliable as they test against the actual running API and don't require database mocking.

