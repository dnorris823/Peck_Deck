"""feed alerts

Adds the three tables behind the low and out of feed alerts, and two device
columns.

- `feeder_refills`: one row per "Refilled" tap.
- `feed_spells`: times the feed was low or out. The open row is the state.
- `device_outages`: times the backend heard nothing from a device for 30 min.
- `devices.trigger_tick_at`: the camera trigger's last analysis tick.
- `devices.feed_drop_armed`: false from a refill until visits look normal.

No backfill. Outages and spells start from this release.

Revision ID: 3f8b1c6d2e95
Revises: 3b8e1f6a2c47
Create Date: 2026-10-31 22:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3f8b1c6d2e95'
down_revision: Union[str, None] = '3b8e1f6a2c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('devices', sa.Column('trigger_tick_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'devices',
        sa.Column('feed_drop_armed', sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        'feeder_refills',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('refilled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('feed_type', sa.String(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feeder_refills_device_id', 'feeder_refills', ['device_id'])

    op.create_table(
        'feed_spells',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feed_spells_device_id', 'feed_spells', ['device_id'])

    op.create_table(
        'device_outages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_device_outages_device_id', 'device_outages', ['device_id'])


def downgrade() -> None:
    op.drop_index('ix_device_outages_device_id', table_name='device_outages')
    op.drop_table('device_outages')
    op.drop_index('ix_feed_spells_device_id', table_name='feed_spells')
    op.drop_table('feed_spells')
    op.drop_index('ix_feeder_refills_device_id', table_name='feeder_refills')
    op.drop_table('feeder_refills')
    op.drop_column('devices', 'feed_drop_armed')
    op.drop_column('devices', 'trigger_tick_at')
