from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    url = get_settings().database_url.get_secret_value()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    if not url.startswith("postgresql"):
        raise RuntimeError("PostgreSQL DATABASE_URL is required")
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def ping_database():
    with get_engine().connect() as connection:
        if connection.scalar(text("SELECT 1")) != 1:
            raise RuntimeError("Database health query failed")


def session_factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def database_session():
    with session_factory()() as session:
        yield session
