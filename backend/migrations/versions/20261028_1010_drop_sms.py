"""drop sms

Removes SMS notifications. `phone` existed only to hold the SMS number and
`notify_sms` only switched the channel on, so both go.

Revision ID: b3d9f0c61e22
Revises: a7c1e4d20b11
Create Date: 2026-10-28 10:10:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d9f0c61e22'
down_revision: Union[str, None] = 'a7c1e4d20b11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('users', 'phone')
    op.drop_column('users', 'notify_sms')


def downgrade() -> None:
    op.add_column('users', sa.Column('phone', sa.String(), nullable=True))
    op.add_column('users', sa.Column(
        'notify_sms', sa.Boolean(), nullable=False, server_default=sa.false()))
