"""species kind and animal group

Adds `kind`, "bird" or "animal", and `animal_group` for animal rows, such as
"squirrel". Every existing row is a bird, so the server default fills them.
Bird counts and bird stats filter on `kind = 'bird'`.

Revision ID: 3b8e1f6a2c47
Revises: c5e8a1f3b2d7
Create Date: 2026-10-31 21:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3b8e1f6a2c47'
down_revision: Union[str, None] = 'c5e8a1f3b2d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'species',
        sa.Column('kind', sa.String(), nullable=False, server_default='bird'),
    )
    op.add_column('species', sa.Column('animal_group', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('species', 'animal_group')
    op.drop_column('species', 'kind')
