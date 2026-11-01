"""animal measures, animal alerts, capture trigger

- `feeder_measures`: anti-animal measures an owner logs on a feeder, such as a
  baffle. `ended_at` is null while the measure lasts.
- `sightings.trigger`: "detector" or "motion", what made the Pi capture. Null
  for rows from older Pi builds.
- `user_preferences.animal_alerts`: a JSON map from animal group to on or off.
  Null means the defaults in backend/animals/groups.py.
- `user_preferences.animal_quiet_interval_seconds`: the animal push throttle
  per (user, feeder, group), default 1800.

It also seeds one species row per feeder animal, so a person can correct a
sighting to a squirrel before any squirrel upload exists. The rows are inline
because the backend image does not hold machine_learning/. They match
machine_learning/feeder_animals.csv at this revision. An animal added to that
file later gets its row on its first upload. The seed skips a row that already
exists, and the downgrade deletes only seeded rows no sighting uses.

Revision ID: 7a2d9e4b1c60
Revises: 3f8b1c6d2e95
Create Date: 2026-11-01 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a2d9e4b1c60'
down_revision: Union[str, None] = '3f8b1c6d2e95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (common_name, genus, species_name, animal_group)
FEEDER_ANIMALS = [
    ("Eastern Gray Squirrel", "Sciurus", "carolinensis", "squirrel"),
    ("Fox Squirrel", "Sciurus", "niger", "squirrel"),
    ("Western Gray Squirrel", "Sciurus", "griseus", "squirrel"),
    ("Abert's Squirrel", "Sciurus", "aberti", "squirrel"),
    ("American Red Squirrel", "Tamiasciurus", "hudsonicus", "squirrel"),
    ("Douglas's Squirrel", "Tamiasciurus", "douglasii", "squirrel"),
    ("Southern Flying Squirrel", "Glaucomys", "volans", "squirrel"),
    ("Eastern Chipmunk", "Tamias", "striatus", "chipmunk"),
    ("Least Chipmunk", "Neotamias", "minimus", "chipmunk"),
    ("Yellow-pine Chipmunk", "Neotamias", "amoenus", "chipmunk"),
    ("Townsend's Chipmunk", "Neotamias", "townsendii", "chipmunk"),
    ("Raccoon", "Procyon", "lotor", "raccoon"),
    ("Virginia Opossum", "Didelphis", "virginiana", "opossum"),
    ("White-tailed Deer", "Odocoileus", "virginianus", "deer"),
    ("Mule Deer", "Odocoileus", "hemionus", "deer"),
    ("American Black Bear", "Ursus", "americanus", "bear"),
    ("Brown Bear", "Ursus", "arctos", "bear"),
    ("Domestic Cat", "Felis", "catus", "cat"),
    ("Brown Rat", "Rattus", "norvegicus", "rat"),
    ("Black Rat", "Rattus", "rattus", "rat"),
    ("Eastern Cottontail", "Sylvilagus", "floridanus", "rabbit"),
    ("Desert Cottontail", "Sylvilagus", "audubonii", "rabbit"),
    ("Mountain Cottontail", "Sylvilagus", "nuttallii", "rabbit"),
]

_species = sa.table(
    'species',
    sa.column('id', sa.Integer),
    sa.column('common_name', sa.String),
    sa.column('genus', sa.String),
    sa.column('species_name', sa.String),
    sa.column('kind', sa.String),
    sa.column('animal_group', sa.String),
)


def upgrade() -> None:
    op.create_table(
        'feeder_measures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('note', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_feeder_measures_device_id'), 'feeder_measures', ['device_id'], unique=False
    )
    op.add_column('sightings', sa.Column('trigger', sa.String(), nullable=True))
    op.add_column('user_preferences', sa.Column('animal_alerts', sa.JSON(), nullable=True))
    op.add_column(
        'user_preferences',
        sa.Column(
            'animal_quiet_interval_seconds', sa.Integer(), nullable=False,
            server_default='1800',
        ),
    )

    conn = op.get_bind()
    for common, genus, name, group in FEEDER_ANIMALS:
        existing = conn.execute(
            sa.select(_species.c.id).where(
                _species.c.common_name == common,
                _species.c.genus == genus,
                _species.c.species_name == name,
            )
        ).first()
        if existing is None:
            conn.execute(
                _species.insert().values(
                    common_name=common, genus=genus, species_name=name,
                    kind='animal', animal_group=group,
                )
            )
        else:
            conn.execute(
                _species.update()
                .where(_species.c.id == existing.id)
                .values(kind='animal', animal_group=group)
            )


def downgrade() -> None:
    sightings = sa.table(
        'sightings',
        sa.column('species_id', sa.Integer),
        sa.column('original_species_id', sa.Integer),
        sa.column('provisional_species_id', sa.Integer),
    )
    conn = op.get_bind()
    for common, genus, name, _group in FEEDER_ANIMALS:
        row = conn.execute(
            sa.select(_species.c.id).where(
                _species.c.common_name == common,
                _species.c.genus == genus,
                _species.c.species_name == name,
            )
        ).first()
        if row is None:
            continue
        used = conn.execute(
            sa.select(sa.func.count()).select_from(sightings).where(
                sa.or_(
                    sightings.c.species_id == row.id,
                    sightings.c.original_species_id == row.id,
                    sightings.c.provisional_species_id == row.id,
                )
            )
        ).scalar()
        if not used:
            conn.execute(_species.delete().where(_species.c.id == row.id))

    op.drop_column('user_preferences', 'animal_quiet_interval_seconds')
    op.drop_column('user_preferences', 'animal_alerts')
    op.drop_column('sightings', 'trigger')
    op.drop_index(op.f('ix_feeder_measures_device_id'), table_name='feeder_measures')
    op.drop_table('feeder_measures')
