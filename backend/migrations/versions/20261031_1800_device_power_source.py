"""device power source

Adds `power_source`, "mains" or "battery", from the Pi's POWER_SOURCE. The Pi
sends it in each heartbeat, so the column needs no backfill. A mains heartbeat
also clears the stale seed battery level on the same row.

Revision ID: 9d4c2b7e6a10
Revises: 5e2a7d9c4f13
Create Date: 2026-10-31 18:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9d4c2b7e6a10'
down_revision: Union[str, None] = '5e2a7d9c4f13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('devices', sa.Column('power_source', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('devices', 'power_source')
