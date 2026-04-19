"""scheduling alignment cleanup: drop deprecated When2Meet tables, create all remaining live tables, patch missing columns

Revision ID: e1f2a3b4c5d6
Revises: ad434d509367
Create Date: 2026-04-19 00:00:00.000000

This is an alignment checkpoint migration. It brings a fresh Railway database
(currently at head ad434d509367) to match the cleaned-up ORM models in
app/models.py. It is designed to be idempotent — safe to re-run on local DBs
that may already contain some of these tables/columns.

Operations:
  1. Patch missing columns on `users` and `matches` (ADD COLUMN IF NOT EXISTS).
  2. Create all remaining live tables that have no prior migration:
       scheduling_proposals, proposal_time_slots, proposal_responses,
       counter_proposal_time_slots, scheduled_calls, call_ratings,
       user_scheduling_preferences, reports, call_requests, user_values,
       user_feature_vectors, behavioral_events, match_outcomes,
       video_call_rooms
     (HOLD: premium_unlocks, profile_boosts — premium feature WIP.)
  3. Drop deprecated When2Meet-era tables and SQL functions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'ad434d509367'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_missing(name: str) -> bool:
    """Return True if `name` is not already a table in the current DB."""
    return name not in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) Patch missing columns on existing tables
    #    Use Postgres `ADD COLUMN IF NOT EXISTS` so this is idempotent.
    # ------------------------------------------------------------------

    # --- users ---
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone VARCHAR DEFAULT 'UTC'")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS prompts JSON")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS no_show_count INTEGER DEFAULT 0 NOT NULL")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_no_show_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS device_token VARCHAR")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS strikes INTEGER DEFAULT 0")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_completed BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP WITH TIME ZONE DEFAULT NOW()")
    # Premium columns — safe to add now; premium routers not yet wired in.
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_expires_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_weekly_boost_granted DATE")

    # --- matches ---
    op.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE")

    # ------------------------------------------------------------------
    # 2) Create new tables (dependency-ordered). Each wrapped in
    #    `if _table_missing(...)` so local DBs that already have some
    #    tables won't error out.
    # ------------------------------------------------------------------

    # --- scheduling_proposals ---
    if _table_missing('scheduling_proposals'):
        op.create_table(
            'scheduling_proposals',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('match_id', sa.Integer(), nullable=False),
            sa.Column('proposer_id', sa.Integer(), nullable=False),
            sa.Column('receiver_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['proposer_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['receiver_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_scheduling_proposals_id'), 'scheduling_proposals', ['id'], unique=False)

    # --- proposal_time_slots (depends on scheduling_proposals) ---
    if _table_missing('proposal_time_slots'):
        op.create_table(
            'proposal_time_slots',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('proposal_id', sa.Integer(), nullable=False),
            sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
            sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
            sa.Column('is_selected', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['proposal_id'], ['scheduling_proposals.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_proposal_time_slots_id'), 'proposal_time_slots', ['id'], unique=False)

    # --- proposal_responses (depends on scheduling_proposals, proposal_time_slots) ---
    if _table_missing('proposal_responses'):
        op.create_table(
            'proposal_responses',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('proposal_id', sa.Integer(), nullable=False),
            sa.Column('response_type', sa.String(length=20), nullable=False),
            sa.Column('selected_slot_id', sa.Integer(), nullable=True),
            sa.Column('counter_proposal_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['proposal_id'], ['scheduling_proposals.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['selected_slot_id'], ['proposal_time_slots.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_proposal_responses_id'), 'proposal_responses', ['id'], unique=False)

    # --- counter_proposal_time_slots (depends on proposal_responses) ---
    if _table_missing('counter_proposal_time_slots'):
        op.create_table(
            'counter_proposal_time_slots',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('response_id', sa.Integer(), nullable=False),
            sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
            sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['response_id'], ['proposal_responses.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_counter_proposal_time_slots_id'), 'counter_proposal_time_slots', ['id'], unique=False)

    # --- scheduled_calls (self-referencing via original_call_id) ---
    if _table_missing('scheduled_calls'):
        op.create_table(
            'scheduled_calls',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('match_id', sa.Integer(), nullable=False),
            sa.Column('user1_id', sa.Integer(), nullable=False),
            sa.Column('user2_id', sa.Integer(), nullable=False),
            sa.Column('scheduled_start_utc', sa.DateTime(timezone=True), nullable=False),
            sa.Column('scheduled_end_utc', sa.DateTime(timezone=True), nullable=False),
            sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='15'),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='scheduled'),
            sa.Column('user1_confirmed', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('user2_confirmed', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('user1_confirmed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('user2_confirmed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('call_room_id', sa.String(length=255), nullable=True),
            sa.Column('call_started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('call_ended_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('actual_duration_minutes', sa.Integer(), nullable=True),
            sa.Column('original_call_id', sa.Integer(), nullable=True),
            sa.Column('reschedule_count', sa.Integer(), server_default='0'),
            sa.Column('cancelled_by_id', sa.Integer(), nullable=True),
            sa.Column('cancellation_reason', sa.String(length=50), nullable=True),
            sa.Column('user1_notified', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('user2_notified', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('reminder_sent', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user1_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user2_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['original_call_id'], ['scheduled_calls.id']),
            sa.ForeignKeyConstraint(['cancelled_by_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_scheduled_calls_id'), 'scheduled_calls', ['id'], unique=False)

    # --- call_ratings (depends on scheduled_calls) ---
    if _table_missing('call_ratings'):
        op.create_table(
            'call_ratings',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('call_id', sa.Integer(), nullable=False),
            sa.Column('rater_id', sa.Integer(), nullable=False),
            sa.Column('rated_user_id', sa.Integer(), nullable=False),
            sa.Column('rating', sa.Integer(), nullable=False),
            sa.Column('feedback', sa.Text(), nullable=True),
            sa.Column('categories', sa.ARRAY(sa.String()), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['call_id'], ['scheduled_calls.id']),
            sa.ForeignKeyConstraint(['rater_id'], ['users.id']),
            sa.ForeignKeyConstraint(['rated_user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('call_id', 'rater_id', name='uq_call_rater'),
        )
        op.create_index(op.f('ix_call_ratings_id'), 'call_ratings', ['id'], unique=False)

    # --- user_scheduling_preferences ---
    if _table_missing('user_scheduling_preferences'):
        op.create_table(
            'user_scheduling_preferences',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('max_calls_per_week', sa.Integer(), server_default='5'),
            sa.Column('min_notice_hours', sa.Integer(), server_default='2'),
            sa.Column('max_advance_days', sa.Integer(), server_default='7'),
            sa.Column('preferred_start_time', sa.Time(), server_default=sa.text("'18:00:00'")),
            sa.Column('preferred_end_time', sa.Time(), server_default=sa.text("'22:00:00'")),
            sa.Column('email_notifications', sa.Boolean(), server_default=sa.text('true')),
            sa.Column('push_notifications', sa.Boolean(), server_default=sa.text('true')),
            sa.Column('reminder_hours_before', sa.Integer(), server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
        )
        op.create_index(op.f('ix_user_scheduling_preferences_id'), 'user_scheduling_preferences', ['id'], unique=False)

    # --- reports ---
    if _table_missing('reports'):
        op.create_table(
            'reports',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('reporter_id', sa.Integer(), nullable=False),
            sa.Column('reported_user_id', sa.Integer(), nullable=False),
            sa.Column('reason', sa.String(length=100), nullable=False),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('reviewed_by', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['reporter_id'], ['users.id']),
            sa.ForeignKeyConstraint(['reported_user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint(
                "status IN ('pending', 'reviewed', 'dismissed')",
                name='valid_report_status',
            ),
        )
        op.create_index(op.f('ix_reports_id'), 'reports', ['id'], unique=False)

    # --- call_requests ---
    if _table_missing('call_requests'):
        op.create_table(
            'call_requests',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('match_id', sa.Integer(), nullable=False),
            sa.Column('requester_id', sa.Integer(), nullable=False),
            sa.Column('recipient_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('room_name', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['match_id'], ['matches.id']),
            sa.ForeignKeyConstraint(['requester_id'], ['users.id']),
            sa.ForeignKeyConstraint(['recipient_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint(
                "status IN ('pending','accepted','declined','expired')",
                name='valid_call_request_status',
            ),
        )
        op.create_index(op.f('ix_call_requests_id'), 'call_requests', ['id'], unique=False)

    # --- user_values ---
    if _table_missing('user_values'):
        op.create_table(
            'user_values',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('relationship_goal', sa.String(length=30), nullable=False, server_default='long_term'),
            sa.Column('wants_children', sa.String(length=20), nullable=False, server_default='open'),
            sa.Column('children_timeline_years', sa.Integer(), nullable=True),
            sa.Column('activity_level', sa.Integer(), nullable=True),
            sa.Column('social_energy', sa.Integer(), nullable=True),
            sa.Column('night_owl_score', sa.Integer(), nullable=True),
            sa.Column('travel_importance', sa.Integer(), nullable=True),
            sa.Column('religious_importance', sa.Integer(), nullable=True),
            sa.Column('religion', sa.String(length=50), nullable=True),
            sa.Column('political_leaning', sa.Integer(), nullable=True),
            sa.Column('financial_priority', sa.Integer(), nullable=True),
            sa.Column('career_ambition', sa.Integer(), nullable=True),
            sa.Column('environmental_concern', sa.Integer(), nullable=True),
            sa.Column('big5_openness', sa.Float(), nullable=True),
            sa.Column('big5_conscientiousness', sa.Float(), nullable=True),
            sa.Column('big5_extraversion', sa.Float(), nullable=True),
            sa.Column('big5_agreeableness', sa.Float(), nullable=True),
            sa.Column('big5_neuroticism', sa.Float(), nullable=True),
            sa.Column('communication_directness', sa.Integer(), nullable=True),
            sa.Column('conflict_style', sa.String(length=30), nullable=True, server_default='discuss'),
            sa.Column('dealbreaker_smoking', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('dealbreaker_drugs', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('dealbreaker_drinking', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('dealbreaker_diff_religion', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('dealbreaker_diff_politics', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('dealbreaker_no_children', sa.Boolean(), server_default=sa.text('false')),
            sa.Column('completed_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
        )
        op.create_index(op.f('ix_user_values_id'), 'user_values', ['id'], unique=False)

    # --- user_feature_vectors ---
    if _table_missing('user_feature_vectors'):
        op.create_table(
            'user_feature_vectors',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('features', sa.JSON(), nullable=False),
            sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
        )
        op.create_index(op.f('ix_user_feature_vectors_id'), 'user_feature_vectors', ['id'], unique=False)

    # --- behavioral_events ---
    if _table_missing('behavioral_events'):
        op.create_table(
            'behavioral_events',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('target_user_id', sa.Integer(), nullable=True),
            sa.Column('event_type', sa.String(length=50), nullable=False),
            sa.Column('event_value', sa.Float(), nullable=True),
            sa.Column('event_meta', sa.JSON(), nullable=True),
            sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_behavioral_events_id'), 'behavioral_events', ['id'], unique=False)

    # --- match_outcomes ---
    if _table_missing('match_outcomes'):
        op.create_table(
            'match_outcomes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('match_id', sa.Integer(), nullable=False),
            sa.Column('user1_id', sa.Integer(), nullable=False),
            sa.Column('user2_id', sa.Integer(), nullable=False),
            sa.Column('matched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('first_message_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('reciprocal_msg_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('call_scheduled_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('call_completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('second_call_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('user1_call_rating', sa.Integer(), nullable=True),
            sa.Column('user2_call_rating', sa.Integer(), nullable=True),
            sa.Column('avg_call_rating', sa.Float(), nullable=True),
            sa.Column('still_talking_30d', sa.Boolean(), nullable=True),
            sa.Column('relationship_formed', sa.Boolean(), nullable=True),
            sa.Column('survey_responded_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('compatibility_label', sa.Float(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user1_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user2_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('match_id'),
        )
        op.create_index(op.f('ix_match_outcomes_id'), 'match_outcomes', ['id'], unique=False)

    # --- video_call_rooms (depends on scheduled_calls) ---
    if _table_missing('video_call_rooms'):
        op.create_table(
            'video_call_rooms',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('scheduled_call_id', sa.Integer(), nullable=False),
            sa.Column('room_name', sa.String(length=255), nullable=False),
            sa.Column('room_sid', sa.String(length=255), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['scheduled_call_id'], ['scheduled_calls.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('room_name'),
            sa.CheckConstraint(
                "status IN ('active', 'ended', 'expired')",
                name='valid_status',
            ),
        )
        op.create_index(op.f('ix_video_call_rooms_id'), 'video_call_rooms', ['id'], unique=False)
        op.create_index(op.f('ix_video_call_rooms_room_name'), 'video_call_rooms', ['room_name'], unique=True)

    # ------------------------------------------------------------------
    # 3) Drop deprecated When2Meet-era tables and SQL functions.
    #    CASCADE handles any lingering FKs from removed routers.
    # ------------------------------------------------------------------
    op.execute("DROP TABLE IF EXISTS user_override_availability CASCADE")
    op.execute("DROP TABLE IF EXISTS user_default_availability CASCADE")
    op.execute("DROP TABLE IF EXISTS user_availability_overrides CASCADE")
    op.execute("DROP TABLE IF EXISTS user_weekly_availability CASCADE")
    op.execute("DROP TABLE IF EXISTS user_timezones CASCADE")
    op.execute("DROP TABLE IF EXISTS user_match_call_preferences CASCADE")

    op.execute("DROP FUNCTION IF EXISTS find_common_availability CASCADE")
    op.execute("DROP FUNCTION IF EXISTS find_immediate_common_availability CASCADE")
    op.execute("DROP FUNCTION IF EXISTS find_immediate_common_availability_utc CASCADE")
    op.execute("DROP FUNCTION IF EXISTS check_scheduling_conflict CASCADE")


def downgrade() -> None:
    raise NotImplementedError("cleanup migration is not reversible")
