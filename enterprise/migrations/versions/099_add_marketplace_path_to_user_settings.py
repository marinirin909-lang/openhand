"""Add marketplace_path column to user_settings table.

Revision ID: 099
Revises: 098
Create Date: 2026-03-02
"""

import sqlalchemy as sa
from alembic import op

revision = '099'
down_revision = '098'


def upgrade() -> None:
    op.add_column(
        'user_settings',
        sa.Column('marketplace_path', sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_settings', 'marketplace_path')
