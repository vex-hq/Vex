"""Database engine and session factory for the storage worker.

Uses SQLAlchemy to manage PostgreSQL connections. Configuration is
driven by the DATABASE_URL environment variable, falling back to
local development defaults.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentguard:agentguard_dev@localhost:5432/agentguard",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
