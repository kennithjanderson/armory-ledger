"""Add per-admin restore-initiated notification preferences.

Revision ID: a47c91e2d563
Revises: d914b7ce203a
"""
from alembic import op
import sqlalchemy as sa

revision = 'a47c91e2d563'
down_revision = 'd914b7ce203a'
branch_labels = depends_on = None


def upgrade():
    op.add_column('users', sa.Column(
        'restore_initiated_in_app', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column(
        'restore_initiated_email', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('users', 'restore_initiated_email')
    op.drop_column('users', 'restore_initiated_in_app')
