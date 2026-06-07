"""drop reports.reason column (structured reporting Migration B)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-06 01:00:00.000000

Migration B of REPORTING_CATEGORIES_SPEC.md. Migration A replaced the free-text
`reports.reason` with `category` + `context` and made `reason` nullable
(vestigial). No code reads or writes `reason` anymore, so this drops the column.

Pre-launch: there are no real reports, so no data is lost. Rollback re-adds the
column as nullable (original data is unrecoverable — acceptable per spec).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('reports', 'reason')


def downgrade() -> None:
    # Re-add as nullable — the original NOT NULL constraint can't be restored
    # without data, and old free-text values are gone.
    op.add_column('reports', sa.Column('reason', sa.String(length=100), nullable=True))
