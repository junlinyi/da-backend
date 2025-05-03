from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '374616024b01'
down_revision = '9c1f6a29a96e'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('username', sa.String, nullable=False),
        sa.Column('email', sa.String, nullable=False, unique=True),
        sa.Column('hashed_password', sa.String, nullable=False),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('bio', sa.String),
        sa.Column('age', sa.Integer),
        sa.Column('gender', sa.String),
        sa.Column('interests', sa.String),
        sa.Column('location', sa.String),
    )

def downgrade():
    op.drop_table('users')
