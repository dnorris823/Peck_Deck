"""device pi health

Five device columns from the Pi's heartbeat, all nullable. A Pi on older code
sends none of them.

- `devices.queued_sightings`: sightings in the Pi's offline queue.
- `devices.oldest_queued_at`: when the oldest of them was captured.
- `devices.dropped_since_boot`: sightings the Pi lost since it started.
- `devices.disk_free_bytes`: free space where the Pi keeps its cache.
- `devices.cpu_temp_c`: the Pi's CPU temperature.

Revision ID: 5c1e8a3f9d27
Revises: 7a2d9e4b1c60
Create Date: 2026-11-01 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5c1e8a3f9d27'
down_revision: Union[str, None] = '7a2d9e4b1c60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('devices', sa.Column('queued_sightings', sa.Integer(), nullable=True))
    op.add_column('devices', sa.Column('oldest_queued_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('devices', sa.Column('dropped_since_boot', sa.Integer(), nullable=True))
    op.add_column('devices', sa.Column('disk_free_bytes', sa.BigInteger(), nullable=True))
    op.add_column('devices', sa.Column('cpu_temp_c', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('devices', 'cpu_temp_c')
    op.drop_column('devices', 'disk_free_bytes')
    op.drop_column('devices', 'dropped_since_boot')
    op.drop_column('devices', 'oldest_queued_at')
    op.drop_column('devices', 'queued_sightings')
