from alembic import context

from backend.db import Base, get_engine
from backend import models

target_metadata = Base.metadata


def run_migrations():
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
