"""sighting thumbnail

Adds `thumbnail_data`, a small JPEG of the capture for the gallery grids.
Nullable, because rows from before this migration have none until
`python -m backend.backfill_thumbnails` runs. The migration does not backfill,
since decoding every image would hold up the container's start.

Revision ID: 7c41e9a2d5b3
Revises: 0d25a81712db
Create Date: 2026-10-30 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7c41e9a2d5b3'
down_revision: Union[str, None] = '0d25a81712db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sightings', sa.Column('thumbnail_data', sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column('sightings', 'thumbnail_data')
