"""Database setup.

The catalog lives in a single SQLite file (filament.db) next to the project.
SQLite needs no server and is perfect for a personal homelab tool.
"""

import os
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

# Where the SQLite file lives.
# - Locally: filament.db in the project root (one level up from this folder).
# - In Docker: set FILAMENT_DB=/data/filament.db and mount /data as a volume so
#   your catalog survives image updates.
_default = Path(__file__).resolve().parent.parent / "filament.db"
DB_PATH = Path(os.environ.get("FILAMENT_DB", _default))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
SQLITE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False lets FastAPI's worker threads share the connection.
engine = create_engine(SQLITE_URL, echo=False, connect_args={"check_same_thread": False})


def init_db() -> None:
    """Create the table(s) if the database file is new."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: hand each request its own database session."""
    with Session(engine) as session:
        yield session
