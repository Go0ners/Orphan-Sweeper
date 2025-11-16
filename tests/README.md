# Orphan Sweeper Tests

This directory contains unit tests for the Orphan Sweeper project.

## Running Tests

### Run all tests
```bash
python3 -m unittest discover tests
```

### Run specific test file
```bash
python3 -m unittest tests.test_config
python3 -m unittest tests.test_file_info
python3 -m unittest tests.test_orphan_sweeper
```

### Run with verbose output
```bash
python3 -m unittest discover tests -v
```

## Test Coverage

- `test_config.py` - Tests for Config class and configuration loading
- `test_file_info.py` - Tests for FileInfo data class
- `test_orphan_sweeper.py` - Tests for OrphanSweeper main functionality

## Test Structure

Each test file includes:
- Setup and teardown methods for test fixtures
- Individual test methods for specific functionality
- Cleanup of temporary files and resources

## Requirements

Tests use only Python standard library modules:
- `unittest` - Test framework
- `tempfile` - Temporary file/directory creation
- `pathlib` - Path operations
- `json` - JSON parsing

No additional dependencies required.
