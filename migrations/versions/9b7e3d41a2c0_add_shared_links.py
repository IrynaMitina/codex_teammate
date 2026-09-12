"""add shared links

Revision ID: 9b7e3d41a2c0
Revises: 487512d812fd
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b7e3d41a2c0"
down_revision: Union[str, Sequence[str], None] = "487512d812fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shared_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shared_links_file_id"), "shared_links", ["file_id"])
    op.create_index(op.f("ix_shared_links_token"), "shared_links", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_shared_links_token"), table_name="shared_links")
    op.drop_index(op.f("ix_shared_links_file_id"), table_name="shared_links")
    op.drop_table("shared_links")
