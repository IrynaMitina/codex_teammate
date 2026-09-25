"""add shared link revocation

Revision ID: c2d4e6f8a010
Revises: 9b7e3d41a2c0
"""

from alembic import op
import sqlalchemy as sa


revision = "c2d4e6f8a010"
down_revision = "9b7e3d41a2c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shared_links",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shared_links", "revoked_at")
