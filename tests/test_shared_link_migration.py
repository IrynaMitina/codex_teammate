import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_expiration_migration_preserves_existing_links(monkeypatch):
    migration = importlib.import_module(
        "migrations.versions.d3e5f7a9b011_add_shared_link_expiration"
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE shared_links (id INTEGER PRIMARY KEY, token VARCHAR(128))"
        ))
        connection.execute(sa.text(
            "INSERT INTO shared_links (id, token) VALUES (1, 'existing-link')"
        ))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        row = connection.execute(sa.text(
            "SELECT token, expires_at FROM shared_links WHERE id = 1"
        )).one()
        assert row == ("existing-link", None)
        migration.downgrade()
        assert "expires_at" not in {
            column["name"] for column in sa.inspect(connection).get_columns("shared_links")
        }
        assert connection.scalar(sa.text(
            "SELECT token FROM shared_links WHERE id = 1"
        )) == "existing-link"
    engine.dispose()
