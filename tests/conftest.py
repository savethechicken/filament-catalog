"""Shared pytest setup.

Every test runs against a temporary SQLite file, never the real filament.db.
FILAMENT_DB is set before the app modules are imported, so the engine binds to
that throwaway file; each test then starts from empty tables.
"""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

_TMP = Path(tempfile.mkdtemp(prefix="filament-tests-"))
os.environ["FILAMENT_DB"] = str(_TMP / "test.db")
os.environ["BUILD_SHA"] = "testsha1234567890"   # footer shows the first 7 chars

from app.database import engine, init_db  # noqa: E402  (after FILAMENT_DB is set)
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    """A TestClient pointed at an empty catalog, with startup hooks run."""
    SQLModel.metadata.drop_all(engine)
    init_db()
    with TestClient(app) as test_client:
        yield test_client
