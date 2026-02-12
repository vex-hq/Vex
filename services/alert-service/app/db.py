"""Database engine and session factory for the alert service."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentguard:agentguard_dev@localhost:5432/agentguard",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
