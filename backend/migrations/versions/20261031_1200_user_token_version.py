"""user token version

Adds `token_version`. Each user JWT carries the version it was issued at, and
the user guard rejects a token whose version no longer matches. Existing rows
start at 0, which matches tokens issued before this column existed.

Revision ID: 5e2a7d9c4f13
Revises: 3b8f0c6e1a94
Create Date: 2026-10-31 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5e2a7d9c4f13'
down_revision: Union[str, None] = '3b8f0c6e1a94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('users', 'token_version')
