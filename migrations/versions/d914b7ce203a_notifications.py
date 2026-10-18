"""Login-derived admin membership and persistent notification/outbox foundation.

Revision ID: d914b7ce203a
Revises: c7d2a960e148
Existing users must log in again to establish admin membership.
"""
from alembic import op
import sqlalchemy as sa
revision = 'd914b7ce203a'
down_revision = 'c7d2a960e148'
branch_labels = depends_on = None


def upgrade():
    for name in ('is_admin', 'backup_success_in_app', 'backup_success_email'):
        op.add_column('users', sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('system_settings', sa.Column('key',sa.String(80),primary_key=True), sa.Column('value',sa.JSON(),nullable=False))
    op.create_table('notification_events',
        sa.Column('id',sa.UUID(),primary_key=True), sa.Column('event_key',sa.String(160),nullable=False,unique=True),
        sa.Column('kind',sa.String(40),nullable=False), sa.Column('scope',sa.String(20),nullable=False),
        sa.Column('severity',sa.String(20),nullable=False), sa.Column('title',sa.String(200),nullable=False),
        sa.Column('message',sa.Text(),nullable=False), sa.Column('action',sa.String(200),nullable=False),
        sa.Column('occurrences',sa.Integer(),nullable=False), sa.Column('resolved',sa.Boolean(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_table('notification_recipients',
        sa.Column('id',sa.UUID(),primary_key=True),
        sa.Column('event_id',sa.UUID(),sa.ForeignKey('notification_events.id',ondelete='CASCADE'),nullable=False),
        sa.Column('user_id',sa.UUID(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('in_app',sa.Boolean(),nullable=False), sa.Column('read_at',sa.DateTime(timezone=True)),
        sa.Column('email_state',sa.String(30),nullable=False), sa.Column('attempts',sa.Integer(),nullable=False),
        sa.Column('next_attempt',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('test_recipient',sa.String(320)), sa.Column('diagnostic',sa.String(200)), sa.Column('sent_at',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('event_id','user_id',name='uq_notification_recipient'))
    for column in ('event_id','user_id','email_state'):
        op.create_index('ix_notification_recipients_'+column,'notification_recipients',[column])


def downgrade():
    op.drop_table('notification_recipients')
    op.drop_table('notification_events')
    op.drop_table('system_settings')
    for name in ('backup_success_email','backup_success_in_app','is_admin'):
        op.drop_column('users',name)
