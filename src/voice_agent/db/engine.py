"""Database engine and session factory."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://voice_agent:voice_agent@localhost:5432/voice_agent",
)


def get_engine(url: str | None = None):
    return create_engine(url or DATABASE_URL, echo=False, pool_pre_ping=True)


def get_session(url: str | None = None) -> Session:
    engine = get_engine(url)
    factory = sessionmaker(bind=engine)
    return factory()
