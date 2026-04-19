"""create conversations and messages tables

These tables were created manually on local dev and never included in the
migration chain. This migration inserts them into the chain so fresh
deployments (e.g. Railway) have the correct schema before
ad434d509367 runs and modifies constraints/indexes.

Revision ID: b1a2c3d4e5f6
Revises: c2b5beb307a7
Create Date: 2026-04-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1a2c3d4e5f6'
down_revision: Union[str, None] = 'c2b5beb307a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create conversations table with the schema that existed before
    # ad434d509367 modified it (named FKs, named unique constraint, named indexes).
    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user1_id', sa.Integer(), nullable=False),
        sa.Column('user2_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_message', sa.Text(), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('user1_unread_count', sa.Integer(), server_default='0'),
        sa.Column('user2_unread_count', sa.Integer(), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['user1_id'], ['users.id'],
            name='conversations_user1_id_fkey', ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['user2_id'], ['users.id'],
            name='conversations_user2_id_fkey', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user1_id', 'user2_id', name='conversations_user1_id_user2_id_key'),
    )
    op.create_index('idx_conversations_user1', 'conversations', ['user1_id'])
    op.create_index('idx_conversations_user2', 'conversations', ['user2_id'])
    op.create_index(
        'idx_conversations_last_message', 'conversations',
        [sa.literal_column('last_message_at DESC')]
    )

    # Create messages table (no firebase_id yet — ad434d509367 adds it)
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('sender_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('message_type', sa.String(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('is_read', sa.Boolean(), server_default='false'),
        sa.ForeignKeyConstraint(
            ['conversation_id'], ['conversations.id'],
            name='messages_conversation_id_fkey', ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['sender_id'], ['users.id'],
            name='messages_sender_id_fkey', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_messages_conversation', 'messages', ['conversation_id'])
    op.create_index('idx_messages_sender', 'messages', ['sender_id'])
    op.create_index(
        'idx_messages_timestamp', 'messages',
        [sa.literal_column('timestamp DESC')]
    )

    # Create the users name index that ad434d509367 will drop
    op.create_index('idx_users_name', 'users', ['name'])


def downgrade() -> None:
    op.drop_index('idx_users_name', table_name='users')
    op.drop_table('messages')
    op.drop_table('conversations')
