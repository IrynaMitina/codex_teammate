import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_expiration_migration_preserves_existing_links():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/d3e5f7a9b011_add_shared_link_expiration.py"
    spec = importlib.util.spec_from_file_location("expiration_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE shared_links (id INTEGER PRIMARY KEY, token VARCHAR(128))"))
        connection.execute(text("INSERT INTO shared_links (id, token) VALUES (1, 'existing-token')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            row = connection.execute(text("SELECT token, expires_at FROM shared_links")).one()
            assert row == ("existing-token", None)
            assert next(c for c in inspect(connection).get_columns("shared_links") if c["name"] == "expires_at")["nullable"]
            migration.downgrade()
            assert "expires_at" not in {c["name"] for c in inspect(connection).get_columns("shared_links")}
            assert connection.execute(text("SELECT token FROM shared_links")).scalar_one() == "existing-token"
    engine.dispose()
