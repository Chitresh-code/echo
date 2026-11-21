import os

from alembic import context
from sqlalchemy import create_engine

# The api passes the url; the alembic command line falls back to the data directory.
url = context.config.get_main_option("sqlalchemy.url") or f"sqlite:///{os.environ.get('ECHO_DATA_DIR', '/data')}/echo.db"

with create_engine(url).connect() as connection:
    # Batch mode lets later migrations alter tables, which SQLite cannot do in place.
    context.configure(connection=connection, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
