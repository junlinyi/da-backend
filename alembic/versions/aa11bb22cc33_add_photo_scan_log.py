"""add photo_scan_log (and merge age + deletion heads)

Revision ID: aa11bb22cc33
Revises: b2c3d4age01, c4d5e6del01
Create Date: 2026-06-18

Merges the two open heads (birthdate/age-attestations and deletion-reasons)
that both descend from a1b2c3scjf01, and adds the photo_scan_log audit table
for NSFW photo scanning.
"""
from alembic import op
import sqlalchemy as sa

revision = "aa11bb22cc33"
down_revision = ("b2c3d4age01", "c4d5e6del01")
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "photo_scan_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("image_url", sa.String(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_photo_scan_log_user_id", "photo_scan_log", ["user_id"])
    op.create_index("ix_photo_scan_log_created_at", "photo_scan_log", ["created_at"])


def downgrade():
    op.drop_index("ix_photo_scan_log_created_at", table_name="photo_scan_log")
    op.drop_index("ix_photo_scan_log_user_id", table_name="photo_scan_log")
    op.drop_table("photo_scan_log")
