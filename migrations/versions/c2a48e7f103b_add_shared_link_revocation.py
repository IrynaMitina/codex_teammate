"""add shared link revocation

Revision ID: c2a48e7f103b
Revises: 9b7e3d41a2c0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2a48e7f103b"
down_revision: Union[str, Sequence[str], None] = "9b7e3d41a2c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("shared_links", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("shared_links", "revoked_at")
