"""drop unused tier settings

Drops four columns that the Pi never read. The Pi takes its tier order and
thresholds from its own `.env` (`TIER_PREFERENCE`, `TIER*_CONFIDENCE_THRESHOLD`,
and a pipeline debounce), so the per-device tier and the three per-user preferences
changed nothing.

Revision ID: a7c1e4d20b11
Revises: 233452d81bee
Create Date: 2026-10-28 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c1e4d20b11'
down_revision: Union[str, None] = '233452d81bee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('devices', 'classification_tier')
    op.drop_column('user_preferences', 'default_tier')
    op.drop_column('user_preferences', 'escalation_threshold')
    op.drop_column('user_preferences', 'debounce_seconds')


def downgrade() -> None:
    op.add_column('devices', sa.Column(
        'classification_tier', sa.String(), nullable=False, server_default='auto'))
    op.add_column('user_preferences', sa.Column(
        'default_tier', sa.String(), nullable=False, server_default='auto'))
    op.add_column('user_preferences', sa.Column(
        'escalation_threshold', sa.Integer(), nullable=False, server_default='70'))
    op.add_column('user_preferences', sa.Column(
        'debounce_seconds', sa.Integer(), nullable=False, server_default='30'))
