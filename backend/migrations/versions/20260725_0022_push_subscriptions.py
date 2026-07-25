"""push subscriptions

Adds the web-push subscription table (FLEDGE Phase 7). One row per (user,
browser); the row's existence *is* the push opt-in, so no matching flag is added
to `users`.

`endpoint` is unique on purpose: it identifies the browser installation, so a
re-subscribe has to replace the row rather than add a second one that would
deliver every alert twice.

Revision ID: 233452d81bee
Revises: 40b75dcf0b75
Create Date: 2026-07-25 00:22:17.768382+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '233452d81bee'
down_revision: Union[str, None] = '40b75dcf0b75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'push_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('p256dh', sa.String(), nullable=False),
        sa.Column('auth', sa.String(), nullable=False),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint'),
    )
    # Every dispatch loads subscriptions by recipient, never by endpoint.
    op.create_index(
        op.f('ix_push_subscriptions_user_id'),
        'push_subscriptions',
        ['user_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_push_subscriptions_user_id'), table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
