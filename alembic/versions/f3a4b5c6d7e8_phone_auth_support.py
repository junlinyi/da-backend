"""phone auth support: phone_number column + email nullable

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-05-13 00:00:00.000000

Adds the `phone_number` column to `users` (nullable, UNIQUE, indexed) and
makes the existing `email` column nullable so that phone-only users can be
persisted alongside email-only and dual (linked) accounts.

Application-level invariant: at least one of email/phone_number must be
non-null for an active user. Enforced in `app/schemas.py` validators and the
six lazy-create paths — not via a DB CHECK constraint (would conflict with
the migration window where Andrew/Lena temporarily have email set and phone
set lazily on first phone-token request).

Part of `PHONE_AUTH_MIGRATION_PLAN.md` Phase A.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add phone_number column (nullable initially — backfill on link)
    op.add_column(
        'users',
        sa.Column('phone_number', sa.String(), nullable=True)
    )
    op.create_unique_constraint('uq_users_phone_number', 'users', ['phone_number'])
    op.create_index('ix_users_phone_number', 'users', ['phone_number'])

    # 2. Make email nullable (phone-only users have no email)
    op.alter_column('users', 'email', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.alter_column('users', 'email', existing_type=sa.String(), nullable=False)
    op.drop_index('ix_users_phone_number', table_name='users')
    op.drop_constraint('uq_users_phone_number', 'users', type_='unique')
    op.drop_column('users', 'phone_number')
