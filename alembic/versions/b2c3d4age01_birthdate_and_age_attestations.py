"""birthdate + age_attestations + birthdate_change_requests

Age-verification hardening (AGE_VERIFICATION_SPEC.md). Replaces the bare
`users.age` integer with a stored `birthdate` (age derived on read), enforces
18+ at the DB layer via a CHECK constraint, and adds an append-only
`age_attestations` audit trail plus an admin-reviewed `birthdate_change_requests`
flow.

AS-BUILT DEVIATION FROM SPEC: `users.birthdate` is NULLABLE, not NOT NULL. The
app bootstraps a bare user row (firebase_uid + email/phone only) on the first
authenticated request, *before* onboarding collects the date of birth (see
dependencies.get_current_user / users.get_my_profile). A NOT NULL birthdate
would 500 every first login. Compliance is instead enforced by:
  (a) app-level validate_birthdate() rejecting sub-18 on every write,
  (b) the CHECK constraint below, which allows NULL but requires 18+/sane when set,
  (c) matchmaking/discovery already filtering out users without a birthdate.
The `age` column is intentionally KEPT here; it is dropped in a follow-up
migration once all readers have switched to the computed property.

Revision ID: b2c3d4age01
Revises: a1b2c3scjf01
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4age01'
down_revision: Union[str, None] = 'a1b2c3scjf01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add birthdate column (nullable — see module docstring).
    op.add_column('users', sa.Column('birthdate', sa.Date(), nullable=True))

    # 2. Backfill existing users from their stored age. Jan 1 is deliberate: it
    #    is the most conservative (oldest) DOB for a given age, so a backfill can
    #    never accidentally push an existing user under 18 (DD-8).
    #
    #    Only backfill SANE ages (18..120). Junk/sub-18 ages are left with a NULL
    #    birthdate (which the CHECK below permits) — backfilling them would either
    #    overflow make_date (e.g. age 9999 -> year -7973) or produce a birthdate
    #    that violates the 18+ CHECK, aborting the whole migration. Those accounts
    #    simply re-enter their DOB; pre-launch this is harmless, and it makes the
    #    migration robust against bad existing rows.
    op.execute(
        """
        UPDATE users
        SET birthdate = make_date(EXTRACT(YEAR FROM CURRENT_DATE)::int - age, 1, 1)
        WHERE age IS NOT NULL AND age BETWEEN 18 AND 120 AND birthdate IS NULL
        """
    )

    # 3. CHECK constraint: NULL is allowed (pre-onboarding rows); when present the
    #    birthdate must be 18+ and sane (not in the future, not >120y ago).
    op.create_check_constraint(
        'users_birthdate_18_plus_or_null',
        'users',
        "birthdate IS NULL OR ("
        "birthdate <= CURRENT_DATE - INTERVAL '18 years' "
        "AND birthdate >= CURRENT_DATE - INTERVAL '120 years')",
    )
    op.create_index('ix_users_birthdate', 'users', ['birthdate'])

    # 4. birthdate_change_requests — created BEFORE age_attestations because the
    #    latter has an FK to it.
    op.create_table(
        'birthdate_change_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('current_birthdate', sa.Date(), nullable=False),
        sa.Column('proposed_birthdate', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('admin_note', sa.String(length=500), nullable=True),
        sa.Column('reviewed_by_admin_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "proposed_birthdate <= CURRENT_DATE - INTERVAL '18 years'",
            name='birthdate_change_requests_proposed_18_plus',
        ),
    )
    op.create_index('ix_birthdate_change_requests_status',
                    'birthdate_change_requests', ['status'])
    op.create_index('ix_birthdate_change_requests_user_id',
                    'birthdate_change_requests', ['user_id'])

    # 5. age_attestations — append-only audit trail, one row per birthdate ever
    #    persisted (signup + each admin-approved change + this backfill).
    op.create_table(
        'age_attestations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('birthdate', sa.Date(), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('admin_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('change_request_id', sa.Integer(),
                  sa.ForeignKey('birthdate_change_requests.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_age_attestations_user_id', 'age_attestations', ['user_id'])
    op.create_index('ix_age_attestations_created_at', 'age_attestations', ['created_at'])

    # 6. Backfill an attestation for every user that now has a birthdate.
    op.execute(
        """
        INSERT INTO age_attestations (user_id, birthdate, source, created_at)
        SELECT id, birthdate, 'backfill', now()
        FROM users
        WHERE birthdate IS NOT NULL
        """
    )

    # NOTE: users.age is intentionally NOT dropped here. A follow-up migration
    # drops it after all code readers have switched to the computed property.


def downgrade() -> None:
    op.drop_table('age_attestations')
    op.drop_index('ix_birthdate_change_requests_user_id', table_name='birthdate_change_requests')
    op.drop_index('ix_birthdate_change_requests_status', table_name='birthdate_change_requests')
    op.drop_table('birthdate_change_requests')
    op.drop_index('ix_users_birthdate', table_name='users')
    op.drop_constraint('users_birthdate_18_plus_or_null', 'users', type_='check')
    op.drop_column('users', 'birthdate')
