"""sighting tier trace

Adds `tier_trace`, the Pi's record of what each tier in its chain did with the
capture. Nullable, because older rows and older Pi builds have no trace.

Revision ID: 0d25a81712db
Revises: b3d9f0c61e22
Create Date: 2026-10-29 22:02:06.601686+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0d25a81712db'
down_revision: Union[str, None] = 'b3d9f0c61e22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sightings', sa.Column(
        'tier_trace',
        sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_column('sightings', 'tier_trace')
