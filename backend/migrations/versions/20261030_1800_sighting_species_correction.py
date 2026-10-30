"""sighting species correction

Adds what PATCH /sightings/{id} records when a person corrects a species:
`original_species_id` keeps the Pi's answer, and `corrected_by` and
`corrected_at` say who changed it and when. All nullable, because no existing
sighting has been corrected.

Revision ID: 67d2b2042099
Revises: 0d25a81712db
Create Date: 2026-10-30 18:00:25.202538+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '67d2b2042099'
down_revision: Union[str, None] = '0d25a81712db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sightings', sa.Column('original_species_id', sa.Integer(), nullable=True))
    op.add_column('sightings', sa.Column('corrected_by', sa.Integer(), nullable=True))
    op.add_column('sightings', sa.Column('corrected_at', sa.DateTime(timezone=True), nullable=True))
    # Named as Postgres would name them, so downgrade can drop them by name.
    op.create_foreign_key(
        'sightings_corrected_by_fkey', 'sightings', 'users', ['corrected_by'], ['id']
    )
    op.create_foreign_key(
        'sightings_original_species_id_fkey', 'sightings', 'species',
        ['original_species_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('sightings_original_species_id_fkey', 'sightings', type_='foreignkey')
    op.drop_constraint('sightings_corrected_by_fkey', 'sightings', type_='foreignkey')
    op.drop_column('sightings', 'corrected_at')
    op.drop_column('sightings', 'corrected_by')
    op.drop_column('sightings', 'original_species_id')
