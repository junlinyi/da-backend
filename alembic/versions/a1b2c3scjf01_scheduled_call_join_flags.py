"""scheduled_call join flags

Adds user1_joined / user2_joined to scheduled_calls (join signals that drive
no-show detection). NOT NULL columns get a temporary server_default to backfill
existing rows, then the server_default is dropped to match the ORM.

Revision ID: a1b2c3scjf01
Revises: 58e992d1eb19
Create Date: 2026-06-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3scjf01'
down_revision: Union[str, None] = '58e992d1eb19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scheduled_calls', sa.Column('user1_joined', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('scheduled_calls', sa.Column('user2_joined', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.alter_column('scheduled_calls', 'user1_joined', server_default=None)
    op.alter_column('scheduled_calls', 'user2_joined', server_default=None)


def downgrade() -> None:
    op.drop_column('scheduled_calls', 'user2_joined')
    op.drop_column('scheduled_calls', 'user1_joined')
