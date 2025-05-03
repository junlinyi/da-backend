import sys
import os
from logging.config import fileConfig

# Add the parent directory (where app/ lives) to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import your SQLAlchemy Base and models so Alembic sees them
from app.models import Base, User  # 👈 this is key — it registers the User model with Base.metadata

# Load Alembic config
config = context.config
fileConfig(config.config_file_name)

# Database URLs (sync for Alembic)
DATABASE_URL = "postgresql+asyncpg://dating_user:securepassword@localhost/dating_app"
SYNC_DATABASE_URL = "postgresql+psycopg2://dating_user:securepassword@localhost/dating_app"

# Set target metadata
target_metadata = Base.metadata

# Run migrations in offline mode
def run_migrations_offline():
    context.configure(
        url=SYNC_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()

# Run migrations in online mode
def run_migrations_online():
    connectable = engine_from_config(
        {"sqlalchemy.url": SYNC_DATABASE_URL},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

# Entry point
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
