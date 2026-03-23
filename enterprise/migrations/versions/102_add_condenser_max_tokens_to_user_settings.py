"""add condenser_max_tokens to user_settings and orgs

Revision ID: 102
Revises: 101
Create Date: 2025-03-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '102'
down_revision: Union[str, None] = '101'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user_settings', sa.Column('condenser_max_tokens', sa.Integer(), nullable=True)
    )
    op.add_column(
        'orgs', sa.Column('condenser_max_tokens', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('user_settings', 'condenser_max_tokens')
    op.drop_column('orgs', 'condenser_max_tokens')
