"""new species alerts

- `user_preferences.notify_first_ever`, `notify_first_at_feeder` and
  `notify_first_this_year`: one switch per kind of new species push. All
  default on.

`notify_new_species_only` keeps its name. It now means "Only new species": send
the new species pushes and mute the normal alerts.

Revision ID: 5c1e8a3f7b24
Revises: 7a2d9e4b1c60
Create Date: 2026-11-01 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5c1e8a3f7b24'
down_revision: Union[str, None] = '7a2d9e4b1c60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ('notify_first_ever', 'notify_first_at_feeder', 'notify_first_this_year')


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column(
            'user_preferences',
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column('user_preferences', name)
