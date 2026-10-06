"""add shared link expiration

Revision ID: d3e5f7a9b011
Revises: c2d4e6f8a010
"""

from alembic import op
import sqlalchemy as sa


revision = "d3e5f7a9b011"
down_revision = "c2d4e6f8a010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shared_links",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shared_links", "expires_at")
