"""Root conftest.

Ensures the repo root is importable (so `import app...` works regardless of
the directory pytest is invoked from) and registers the Postgres-backed
Scheduling V2 harness as a plugin so its fixtures (db, make_user, make_match,
client_as) are discoverable by tests under tests/.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

pytest_plugins = ["tests.conftest_pg"]
