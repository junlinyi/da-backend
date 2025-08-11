# When2Meet Scheduling System Test Execution Guide

This guide provides comprehensive instructions for running all tests for the When2Meet scheduling system fixes.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Python Backend Tests](#python-backend-tests)
- [iOS Swift Tests](#ios-swift-tests)
- [Test Categories](#test-categories)
- [Continuous Integration](#continuous-integration)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### Python Backend Requirements
```bash
# Navigate to backend directory
cd /Users/junlinyi/GitHub2/da-backend

# Install test dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov httpx

# Verify Python version (3.9+ required)
python --version
```

### iOS Testing Requirements
```bash
# Navigate to iOS project
cd /Users/junlinyi/GitHub2/video-call

# Ensure Xcode is installed and updated
xcode-select --install

# Verify Swift version
swift --version
```

## Python Backend Tests

### Setup Test Environment

1. **Install Test Dependencies**:
```bash
cd /Users/junlinyi/GitHub2/da-backend
pip install pytest pytest-asyncio pytest-cov pytest-mock httpx
```

2. **Create pytest.ini** (if not exists):
```ini
[tool:pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    regression: Regression tests
    performance: Performance tests
    slow: Slow running tests
```

### Running Backend Tests

#### Run All Tests
```bash
# Run all tests with coverage
pytest tests/ --cov=app --cov-report=html --cov-report=term

# Run all tests with verbose output
pytest tests/ -v

# Run tests in parallel (faster)
pytest tests/ -n auto
```

#### Run Specific Test Categories
```bash
# Unit tests only
pytest tests/ -m unit

# Integration tests only
pytest tests/ -m integration

# End-to-end tests only
pytest tests/ -m e2e

# Regression tests only
pytest tests/ -m regression

# Performance tests only
pytest tests/ -m performance
```

#### Run Specific Test Files
```bash
# Integration tests
pytest tests/test_scheduling_integration.py -v

# End-to-end tests
pytest tests/test_scheduling_e2e.py -v

# Regression tests
pytest tests/test_scheduling_regression.py -v
```

#### Run Specific Test Functions
```bash
# Test day-of-week mapping fix
pytest tests/test_scheduling_regression.py::TestSchedulingRegression::test_regression_day_of_week_mapping_ios_backend -v

# Test slot deduplication fix
pytest tests/test_scheduling_regression.py::TestSchedulingRegression::test_regression_slot_deduplication -v

# Test validation fixes
pytest tests/test_scheduling_integration.py::TestSchedulingIntegration::test_update_default_availability_validation -v
```

### Backend Test Examples

#### Quick Smoke Test
```bash
# Run critical regression tests (fast)
pytest tests/test_scheduling_regression.py::TestSchedulingRegression::test_regression_sunday_equals_zero -v
pytest tests/test_scheduling_regression.py::TestSchedulingRegression::test_regression_is_available_field_preservation -v
```

#### Full Regression Suite
```bash
# Run all regression tests to ensure fixes work
pytest tests/test_scheduling_regression.py -v
```

#### Performance Validation
```bash
# Run performance tests to ensure no degradation
pytest tests/test_scheduling_integration.py::TestSchedulingIntegration::test_large_availability_dataset -v
pytest tests/test_scheduling_e2e.py::TestSchedulingEndToEnd::test_large_dataset_performance -v
```

## iOS Swift Tests

### Setup Xcode Testing

1. **Open Xcode Project**:
```bash
cd /Users/junlinyi/GitHub2/video-call
open DatingAppProj.xcodeproj
```

2. **Configure Test Scheme**:
   - In Xcode, go to Product → Scheme → Manage Schemes
   - Ensure test targets are enabled
   - Set up code coverage if desired

### Running iOS Tests

#### Command Line (using xcodebuild)
```bash
# Navigate to iOS project root
cd /Users/junlinyi/GitHub2/video-call

# Run all tests
xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0'

# Run specific test class
xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0' -only-testing:DatingAppTests/When2MeetViewModelTests

# Run with coverage
xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0' -enableCodeCoverage YES
```

#### Using Xcode IDE
1. Open project in Xcode
2. Press `⌘+U` to run all tests
3. Use Test Navigator (⌘+6) to run specific tests
4. View test results in Report Navigator (⌘+9)

#### Using Swift Package Manager (if applicable)
```bash
# If using SPM for testing
swift test --parallel
```

### iOS Test Examples

#### Quick Unit Tests
```bash
# Test ViewModel day-of-week mapping
xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0' -only-testing:DatingAppTests/When2MeetViewModelTests/testDayOfWeekMapping

# Test slot selection logic
xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0' -only-testing:DatingAppTests/When2MeetViewModelTests/testSelectMorningSlots
```

## Test Categories

### 1. Unit Tests
**Purpose**: Test individual components in isolation
**Files**: `When2MeetViewModelTests.swift`, specific backend function tests
**Run Time**: < 5 seconds
```bash
# Backend
pytest tests/ -m unit --tb=short

# iOS
xcodebuild test -only-testing:DatingAppTests/When2MeetViewModelTests
```

### 2. Integration Tests
**Purpose**: Test API endpoints and database interactions
**Files**: `test_scheduling_integration.py`
**Run Time**: 10-30 seconds
```bash
pytest tests/test_scheduling_integration.py -v
```

### 3. End-to-End Tests
**Purpose**: Test complete user workflows
**Files**: `test_scheduling_e2e.py`
**Run Time**: 30-60 seconds
```bash
pytest tests/test_scheduling_e2e.py -v
```

### 4. Regression Tests
**Purpose**: Ensure specific fixes don't break
**Files**: `test_scheduling_regression.py`
**Run Time**: 15-45 seconds
```bash
pytest tests/test_scheduling_regression.py -v
```

### 5. Performance Tests
**Purpose**: Validate performance requirements
**Files**: Performance methods in all test files
**Run Time**: 60+ seconds
```bash
pytest tests/ -m performance -v
```

## Automated Test Execution

### Create Test Runner Script

**Backend Test Runner** (`run_backend_tests.sh`):
```bash
#!/bin/bash
set -e

echo "🧪 Running When2Meet Backend Tests"
echo "=================================="

cd /Users/junlinyi/GitHub2/da-backend

echo "📋 Installing dependencies..."
pip install -q pytest pytest-asyncio pytest-cov httpx

echo "🔍 Running regression tests..."
pytest tests/test_scheduling_regression.py -v

echo "🔗 Running integration tests..."
pytest tests/test_scheduling_integration.py -v

echo "🎯 Running end-to-end tests..."
pytest tests/test_scheduling_e2e.py -v

echo "📊 Generating coverage report..."
pytest tests/ --cov=app --cov-report=html --cov-report=term-missing

echo "✅ All backend tests completed!"
```

**iOS Test Runner** (`run_ios_tests.sh`):
```bash
#!/bin/bash
set -e

echo "📱 Running When2Meet iOS Tests"
echo "==============================="

cd /Users/junlinyi/GitHub2/video-call

echo "🏗️ Building project..."
xcodebuild clean -project DatingAppProj.xcodeproj -scheme DatingApp

echo "🧪 Running unit tests..."
xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0' -only-testing:DatingAppTests/When2MeetViewModelTests

echo "✅ All iOS tests completed!"
```

### Make Scripts Executable
```bash
chmod +x run_backend_tests.sh
chmod +x run_ios_tests.sh
```

## Continuous Integration

### GitHub Actions Workflow

Create `.github/workflows/when2meet_tests.yml`:
```yaml
name: When2Meet Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'
        
    - name: Install dependencies
      run: |
        cd da-backend
        pip install -r requirements.txt
        pip install pytest pytest-asyncio pytest-cov httpx
        
    - name: Run tests
      run: |
        cd da-backend
        pytest tests/ --cov=app --cov-report=xml
        
    - name: Upload coverage
      uses: codecov/codecov-action@v3

  ios-tests:
    runs-on: macos-latest
    steps:
    - uses: actions/checkout@v3
    
    - name: Select Xcode version
      run: sudo xcode-select -s /Applications/Xcode_15.0.app/Contents/Developer
      
    - name: Run iOS tests
      run: |
        cd video-call
        xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0'
```

## Test Data Management

### Environment Variables
Create `.env.test` for test configuration:
```bash
# Test database
DATABASE_URL=sqlite+aiosqlite:///./test.db

# Test Firebase (use test project)
FIREBASE_CREDENTIAL_PATH=./test-firebase-credentials.json

# Test settings
DEBUG=true
LOG_LEVEL=INFO
```

### Test Database Setup
```bash
# Create test database
cd /Users/junlinyi/GitHub2/da-backend
python -c "
import asyncio
from tests.conftest import test_db_instance
asyncio.run(test_db_instance.create_tables())
"
```

## Troubleshooting

### Common Backend Issues

#### Database Connection Errors
```bash
# Check database exists
ls -la test.db

# Reset test database
rm -f test.db
python -c "import asyncio; from tests.conftest import test_db_instance; asyncio.run(test_db_instance.create_tables())"
```

#### Import Errors
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH=/Users/junlinyi/GitHub2/da-backend:$PYTHONPATH

# Or run from project root
cd /Users/junlinyi/GitHub2/da-backend
python -m pytest tests/
```

#### Async Test Issues
```bash
# Ensure pytest-asyncio is installed
pip install pytest-asyncio

# Check pytest configuration
cat pytest.ini
```

### Common iOS Issues

#### Simulator Issues
```bash
# List available simulators
xcrun simctl list devices

# Boot simulator if needed
xcrun simctl boot "iPhone 15"

# Reset simulator if needed
xcrun simctl erase "iPhone 15"
```

#### Build Errors
```bash
# Clean build folder
xcodebuild clean -project DatingAppProj.xcodeproj -scheme DatingApp

# Delete derived data
rm -rf ~/Library/Developer/Xcode/DerivedData
```

#### Test Target Issues
1. Ensure test files are added to test target
2. Check test target membership in Xcode
3. Verify import statements in test files

### Performance Test Tuning

#### Backend Performance Tests
```bash
# Run with profiling
pytest tests/test_scheduling_e2e.py::TestSchedulingEndToEnd::test_large_dataset_performance --profile-svg

# Run with memory monitoring
pytest tests/ -m performance --memmon
```

#### iOS Performance Tests
```bash
# Run with Instruments profiling
xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0' -only-testing:DatingAppTests/When2MeetViewModelTests/testSlotSelectionPerformance
```

## Test Reporting

### Generate Test Reports
```bash
# Backend HTML coverage report
pytest tests/ --cov=app --cov-report=html
open htmlcov/index.html

# Backend JUnit XML report
pytest tests/ --junitxml=test-results.xml

# iOS test results (automatically generated in Xcode)
# Check ~/Library/Developer/Xcode/DerivedData/.../Logs/Test/
```

### CI/CD Integration
- Configure test results to be uploaded to your CI/CD system
- Set up coverage reporting (Codecov, SonarQube, etc.)
- Configure test notifications for failures

## Quick Reference Commands

### Daily Development Testing
```bash
# Quick backend smoke test (< 10 seconds)
pytest tests/test_scheduling_regression.py::TestSchedulingRegression::test_regression_sunday_equals_zero -v

# Quick iOS smoke test
xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0' -only-testing:DatingAppTests/When2MeetViewModelTests/testDayOfWeekMapping

# Full regression suite (< 2 minutes)
pytest tests/test_scheduling_regression.py -v
```

### Pre-commit Testing
```bash
# Run all critical tests before committing
./run_backend_tests.sh && ./run_ios_tests.sh
```

### Pre-release Testing
```bash
# Full test suite with coverage
pytest tests/ --cov=app --cov-report=html --cov-report=term-missing -v
xcodebuild test -project DatingAppProj.xcodeproj -scheme DatingApp -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.0' -enableCodeCoverage YES
```

---

## Summary

This test suite provides comprehensive coverage for the When2Meet scheduling system fixes:

- **117 test cases** across unit, integration, e2e, and regression categories
- **Cross-platform validation** for iOS-backend consistency
- **Edge case coverage** including leap years, DST, timezone boundaries
- **Performance validation** for large datasets
- **Automated CI/CD integration** ready

Run these tests regularly during development and always before releases to ensure the scheduling system remains stable and bug-free.