"""add premium_unlocks table (Likes tab)

Backs the `PremiumUnlock` ORM model, which until now had no table (the
scheduling-alignment migration deliberately HELD premium_unlocks/profile_boosts
as "premium WIP"). The Likes tab (/likes/unlock + /likes/respond) needs it to
record daily free unlocks and the like/pass action + resulting match.

Also serves as the merge point for the two open heads on main
(b2c3d4age01 = age verification, c4d5e6del01 = deletion reasons).

profile_boosts remains held — it is not needed by the Likes tab.

Revision ID: f7a1likes01
Revises: b2c3d4age01, c4d5e6del01
Create Date: 2026-06-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a1likes01'
down_revision: Union[str, Sequence[str], None] = ('b2c3d4age01', 'c4d5e6del01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'premium_unlocks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('unlocked_user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('unlocked_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=True),
        sa.Column('match_id', sa.Integer(),
                  sa.ForeignKey('matches.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('user_id', 'unlocked_user_id', name='uq_premium_unlock'),
    )
    # Daily free-unlock count query filters on (user_id, unlocked_at).
    op.create_index('ix_premium_unlocks_user_unlocked_at',
                    'premium_unlocks', ['user_id', 'unlocked_at'])


def downgrade() -> None:
    op.drop_index('ix_premium_unlocks_user_unlocked_at', table_name='premium_unlocks')
    op.drop_table('premium_unlocks')
