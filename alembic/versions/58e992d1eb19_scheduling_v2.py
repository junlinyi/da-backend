"""scheduling_v2

Revision ID: 58e992d1eb19
Revises: b2c3d4e5f6a7
Create Date: 2026-06-16 13:52:10.534216

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '58e992d1eb19'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Scheduling V2 schema (curated; autogen drift removed — see migration notes) ===

    # --- New V2 tables ---
    op.create_table('video_call_proposals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('proposer_user_id', sa.Integer(), nullable=False),
    sa.Column('proposed_start_utc', sa.DateTime(timezone=True), nullable=False),
    sa.Column('proposed_end_utc', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending','accepted','superseded')", name='chk_vcp_status'),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['proposer_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_one_pending_proposal_per_match', 'video_call_proposals', ['match_id'], unique=True, postgresql_where=sa.text("status = 'pending'"))
    op.create_index('idx_video_call_proposals_match', 'video_call_proposals', ['match_id'], unique=False)
    op.create_index('idx_video_call_proposals_proposer', 'video_call_proposals', ['proposer_user_id'], unique=False)
    op.create_index('idx_video_call_proposals_status', 'video_call_proposals', ['status'], unique=False)

    op.create_table('no_show_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('scheduled_call_id', sa.Integer(), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('event_type', sa.String(length=20), nullable=False),
    sa.CheckConstraint("event_type IN ('no_show','partial')", name='chk_nse_type'),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['scheduled_call_id'], ['scheduled_calls.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_no_show_events_call', 'no_show_events', ['scheduled_call_id'], unique=False)
    op.create_index('idx_no_show_events_match', 'no_show_events', ['match_id'], unique=False)
    op.create_index('idx_no_show_events_user', 'no_show_events', ['user_id', sa.literal_column('detected_at DESC')], unique=False)
    op.create_index('idx_no_show_events_user_match', 'no_show_events', ['user_id', 'match_id'], unique=False)

    # --- matches: V2 columns ---
    # NOT NULL columns get a temporary server_default to backfill existing rows,
    # then the server_default is dropped to match the ORM (Python-side default only).
    op.add_column('matches', sa.Column('text_state', sa.String(length=20), nullable=False, server_default='open'))
    op.add_column('matches', sa.Column('call_status', sa.String(length=30), nullable=False, server_default='none'))
    op.add_column('matches', sa.Column('lifecycle', sa.String(length=20), nullable=False, server_default='active'))
    op.add_column('matches', sa.Column('text_locked_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('matches', sa.Column('text_unlocked_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('matches', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('matches', sa.Column('exit_survey_user_a_response', sa.Boolean(), nullable=True))
    op.add_column('matches', sa.Column('exit_survey_user_a_responded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('matches', sa.Column('exit_survey_user_b_response', sa.Boolean(), nullable=True))
    op.add_column('matches', sa.Column('exit_survey_user_b_responded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('matches', sa.Column('contact_reveal_unlocked', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('matches', sa.Column('contact_revealed_to_user_a_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('matches', sa.Column('contact_revealed_to_user_b_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('matches', 'text_state', server_default=None)
    op.alter_column('matches', 'call_status', server_default=None)
    op.alter_column('matches', 'lifecycle', server_default=None)
    op.alter_column('matches', 'contact_reveal_unlocked', server_default=None)

    # --- matches: V2 CHECK constraints (autogen does not emit table-level CHECKs) ---
    op.create_check_constraint('chk_text_state', 'matches', "text_state IN ('open','locked','archived')")
    op.create_check_constraint('chk_call_status', 'matches', "call_status IN ('none','proposal_pending','scheduled','in_progress','pending_survey','completed','no_show')")
    op.create_check_constraint('chk_lifecycle', 'matches', "lifecycle IN ('active','terminated','expired')")

    # --- matches: V2 indexes ---
    op.create_index('idx_matches_text_state', 'matches', ['text_state'], unique=False)
    op.create_index('idx_matches_call_status', 'matches', ['call_status'], unique=False)
    op.create_index('idx_matches_lifecycle', 'matches', ['lifecycle'], unique=False)
    op.create_index('idx_matches_text_locked_at', 'matches', ['text_locked_at'], unique=False, postgresql_where=sa.text('text_locked_at IS NOT NULL'))
    op.create_index('idx_matches_active_needs_action', 'matches', ['lifecycle', 'text_state', 'call_status'], unique=False, postgresql_where=sa.text("lifecycle = 'active'"))

    # --- messages: V2 columns ---
    op.add_column('messages', sa.Column('has_masked_content', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('messages', sa.Column('system_message_type', sa.String(length=40), nullable=True))
    op.alter_column('messages', 'has_masked_content', server_default=None)
    op.alter_column('messages', 'sender_id',
               existing_type=sa.INTEGER(),
               nullable=True)

    # --- users: V2 columns + partial index ---
    op.add_column('users', sa.Column('total_calls_scheduled', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('users', sa.Column('total_calls_completed', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('users', sa.Column('phone_country_code', sa.String(length=8), nullable=True))
    op.alter_column('users', 'total_calls_scheduled', server_default=None)
    op.alter_column('users', 'total_calls_completed', server_default=None)
    op.create_index('idx_users_no_show_count', 'users', ['no_show_count'], unique=False, postgresql_where=sa.text('no_show_count > 0'))

    # --- Drop the 5 legacy scheduling tables (children before parents; CASCADE for safety) ---
    op.execute("DROP TABLE IF EXISTS counter_proposal_time_slots CASCADE")
    op.execute("DROP TABLE IF EXISTS proposal_responses CASCADE")
    op.execute("DROP TABLE IF EXISTS proposal_time_slots CASCADE")
    op.execute("DROP TABLE IF EXISTS scheduling_proposals CASCADE")
    op.execute("DROP TABLE IF EXISTS call_requests CASCADE")

    # --- Drop broken legacy trigger + function on scheduled_calls ---
    op.execute("DROP TRIGGER IF EXISTS trigger_update_call_preferences ON scheduled_calls")
    op.execute("DROP FUNCTION IF EXISTS update_call_preferences() CASCADE")
    # === end curated V2 migration ===


def downgrade() -> None:
    raise NotImplementedError("Pre-launch; forward-only V2 migration. Use seed scripts to reset.")
