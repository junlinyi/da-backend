"""add deletion_reasons table

Append-only, anonymous churn-reason capture for in-app account deletion. The
table carries no user identifier (the user row is PII-scrubbed on delete), so it
stays GDPR retention-free. See ACCOUNT_DELETION_IOS_SPEC.md DD-5.

Revision ID: c4d5e6del01
Revises: a1b2c3scjf01
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6del01'
down_revision: Union[str, None] = 'a1b2c3scjf01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'deletion_reasons',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('reason', sa.String(length=32), nullable=False),
        sa.Column('free_text', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "reason IN ('found_someone','not_finding_matches','privacy','bugs','other')",
            name='deletion_reasons_valid_reason'),
        sa.CheckConstraint(
            "reason != 'other' OR (free_text IS NOT NULL AND LENGTH(TRIM(free_text)) >= 1)",
            name='deletion_reasons_other_requires_text'),
    )
    op.create_index('ix_deletion_reasons_created_at', 'deletion_reasons', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_deletion_reasons_created_at', table_name='deletion_reasons')
    op.drop_table('deletion_reasons')
