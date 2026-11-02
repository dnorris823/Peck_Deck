"""digests

- `user_preferences.time_zone`: the user's IANA time zone. Null reads as UTC.
- `digest_push` and `digest_email`: the evening push and the weekly email. Both
  default off.
- `digest_push_time`: local time of the evening push, default 19:00.
- `digest_push_sent_at` and `digest_email_sent_at`: the last send of each, so a
  restart never sends a period's digest twice.

Revision ID: 8d4b2f6a1e93
Revises: 5c1e8a3f7b24
Create Date: 2026-11-01 14:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8d4b2f6a1e93'
down_revision: Union[str, None] = '5c1e8a3f7b24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_preferences', sa.Column('time_zone', sa.String(), nullable=True))
    op.add_column(
        'user_preferences',
        sa.Column('digest_push', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'user_preferences',
        sa.Column('digest_push_time', sa.String(length=5), nullable=False, server_default='19:00'),
    )
    op.add_column(
        'user_preferences',
        sa.Column('digest_email', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'user_preferences',
        sa.Column('digest_push_sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'user_preferences',
        sa.Column('digest_email_sent_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    for name in (
        'digest_email_sent_at', 'digest_push_sent_at', 'digest_email',
        'digest_push_time', 'digest_push', 'time_zone',
    ):
        op.drop_column('user_preferences', name)
