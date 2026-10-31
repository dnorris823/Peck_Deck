"""device live url

Adds `live_url`, where the feeder's MediaMTX answers WHEP offers. The Pi sends
it in each heartbeat, so the column needs no backfill.

Revision ID: 3b8f0c6e1a94
Revises: 7c41e9a2d5b3
Create Date: 2026-10-30 20:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3b8f0c6e1a94'
down_revision: Union[str, None] = '7c41e9a2d5b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('devices', sa.Column('live_url', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('devices', 'live_url')
