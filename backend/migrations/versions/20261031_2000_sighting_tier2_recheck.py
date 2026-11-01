"""sighting tier2 recheck

Adds what the backend's Tier 2 re-check needs. `tier2_recheck` is null,
"pending" or "done". `provisional_species_id` keeps the Pi's species when a
re-check replaced it, and `rechecked_at` says when. `crop_box` holds the square
the Pi classified. A partial index covers only the pending rows.

Existing rows stay null, so nothing re-checks the history. Only uploads from
this build on are marked.

Revision ID: c5e8a1f3b2d7
Revises: 9d4c2b7e6a10
Create Date: 2026-10-31 20:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c5e8a1f3b2d7'
down_revision: Union[str, None] = '9d4c2b7e6a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sightings', sa.Column('tier2_recheck', sa.String(), nullable=True))
    op.add_column(
        'sightings', sa.Column('provisional_species_id', sa.Integer(), nullable=True)
    )
    op.add_column(
        'sightings', sa.Column('rechecked_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'sightings',
        sa.Column(
            'crop_box',
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=True,
        ),
    )
    # Named as Postgres would name it, so downgrade can drop it by name.
    op.create_foreign_key(
        'sightings_provisional_species_id_fkey', 'sightings', 'species',
        ['provisional_species_id'], ['id'],
    )
    op.create_index(
        'ix_sightings_tier2_recheck_pending',
        'sightings',
        ['datetime'],
        postgresql_where=sa.text("tier2_recheck = 'pending'"),
        sqlite_where=sa.text("tier2_recheck = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index('ix_sightings_tier2_recheck_pending', table_name='sightings')
    op.drop_constraint(
        'sightings_provisional_species_id_fkey', 'sightings', type_='foreignkey'
    )
    op.drop_column('sightings', 'crop_box')
    op.drop_column('sightings', 'rechecked_at')
    op.drop_column('sightings', 'provisional_species_id')
    op.drop_column('sightings', 'tier2_recheck')
