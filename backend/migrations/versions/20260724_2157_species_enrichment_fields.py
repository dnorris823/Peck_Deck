"""species enrichment fields

Adds the cached field-guide data (FLEDGE Phase 6): `description` (Wikipedia
summary extract) and `family` (GBIF taxonomy match). Both nullable — they are
populated lazily by a background task on first sighting of a species, and an
unenriched species must still render.

Revision ID: 40b75dcf0b75
Revises: 25d65b9ab024
Create Date: 2026-07-24 21:57:07.742494+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '40b75dcf0b75'
down_revision: Union[str, None] = '25d65b9ab024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('species', sa.Column('description', sa.String(), nullable=True))
    op.add_column('species', sa.Column('family', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('species', 'family')
    op.drop_column('species', 'description')
