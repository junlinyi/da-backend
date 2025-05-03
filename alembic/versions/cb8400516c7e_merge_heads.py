"""Merge heads

Revision ID: cb8400516c7e
Revises: 0ccaab485b9f, 374616024b01
Create Date: 2025-04-12 15:23:16.327821

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb8400516c7e'
down_revision: Union[str, None] = ('0ccaab485b9f', '374616024b01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
