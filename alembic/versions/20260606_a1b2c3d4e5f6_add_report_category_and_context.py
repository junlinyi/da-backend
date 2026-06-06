"""add report category + context (structured reporting)

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-06-06 00:00:00.000000

Migration A of REPORTING_CATEGORIES_SPEC.md. Replaces the free-text
`reports.reason` with a machine-readable `category` enum + a `context` enum
(where the report was filed). Pre-launch, so existing test rows are deleted
rather than backfilled — there are no real user reports yet.

`reason` is kept but made nullable here so the column is vestigial during the
A→B coexistence window; follow-up migration B drops it once no code reads it.

CHECK constraints mirror the Pydantic enums for defense-in-depth.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CATEGORY_VALUES = (
    "'harassment', 'inappropriate_photos', 'explicit_on_video_call', "
    "'underage', 'impersonation', 'scam_spam', 'hate_speech', "
    "'violence_threat', 'off_platform_solicitation', 'other'"
)
_CONTEXT_VALUES = "'chat', 'video_call', 'profile'"


def upgrade() -> None:
    # Pre-launch: drop any free-text test reports; they have no `category`/
    # `context` and can't be meaningfully backfilled (acceptable per spec).
    op.execute("DELETE FROM reports")

    # New structured columns. Table is now empty, so NOT NULL is safe without a
    # backfill. `context` carries a server_default so any stray legacy insert
    # path still satisfies NOT NULL.
    op.add_column('reports', sa.Column('category', sa.String(length=40), nullable=False))
    op.add_column('reports', sa.Column('context', sa.String(length=20), nullable=False, server_default='chat'))

    # `reason` becomes vestigial — nullable so code can stop writing it before
    # migration B drops the column entirely.
    op.alter_column('reports', 'reason', existing_type=sa.String(length=100), nullable=True)

    op.create_check_constraint(
        'reports_category_valid', 'reports',
        f"category IN ({_CATEGORY_VALUES})"
    )
    op.create_check_constraint(
        'reports_context_valid', 'reports',
        f"context IN ({_CONTEXT_VALUES})"
    )

    op.create_index('ix_reports_category', 'reports', ['category'])
    op.create_index('ix_reports_status_category', 'reports', ['status', 'category'])

    # Drop the server_default now that the column exists — app always supplies
    # context explicitly going forward.
    op.alter_column('reports', 'context', server_default=None)


def downgrade() -> None:
    op.drop_index('ix_reports_status_category', table_name='reports')
    op.drop_index('ix_reports_category', table_name='reports')
    op.drop_constraint('reports_context_valid', 'reports', type_='check')
    op.drop_constraint('reports_category_valid', 'reports', type_='check')
    op.alter_column('reports', 'reason', existing_type=sa.String(length=100), nullable=False)
    op.drop_column('reports', 'context')
    op.drop_column('reports', 'category')
