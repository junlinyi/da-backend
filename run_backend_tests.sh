#!/bin/bash
set -e

echo "🧪 Running When2Meet Backend Tests"
echo "=================================="

# Check if we're in the correct directory
if [ ! -f "app/main.py" ]; then
    echo "❌ Error: Not in backend directory. Please run from /Users/junlinyi/GitHub2/da-backend"
    exit 1
fi

echo "📋 Installing test dependencies..."
pip install -q pytest pytest-asyncio pytest-cov httpx pytest-mock

echo "🧹 Cleaning up any existing test database..."
rm -f test.db

echo "🔍 Running regression tests (critical fixes)..."
echo "-----------------------------------------------"
pytest tests/test_scheduling_regression.py -v --tb=short

echo ""
echo "🔗 Running integration tests (API endpoints)..."
echo "-----------------------------------------------"
pytest tests/test_scheduling_integration.py -v --tb=short

echo ""
echo "🎯 Running end-to-end tests (complete workflows)..."
echo "---------------------------------------------------"
pytest tests/test_scheduling_e2e.py -v --tb=short

echo ""
echo "📊 Generating comprehensive test report with coverage..."
echo "------------------------------------------------------"
pytest tests/ --cov=app --cov-report=html --cov-report=term-missing --tb=short

echo ""
echo "✅ All backend tests completed successfully!"
echo ""
echo "📁 Coverage report generated in htmlcov/index.html"
echo "🔗 Open with: open htmlcov/index.html"

# Check if any tests failed
if [ $? -eq 0 ]; then
    echo "🎉 Test Status: PASSED"
else
    echo "❌ Test Status: FAILED"
    exit 1
fi