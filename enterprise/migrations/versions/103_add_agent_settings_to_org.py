"""Add agent_settings column to org table.

Revision ID: 103
Revises: 102
Create Date: 2026-03-23 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '103'
down_revision: Union[str, None] = '102'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EMPTY_JSON = sa.text("'{}'::json")


def upgrade() -> None:
    op.add_column(
        'org',
        sa.Column(
            'agent_settings', sa.JSON(), nullable=False, server_default=_EMPTY_JSON
        ),
    )

    op.execute(
        sa.text(
            """
            UPDATE org
            SET agent_settings = jsonb_strip_nulls(
                jsonb_build_object(
                    'schema_version', 1,
                    'agent', agent,
                    'llm.model', default_llm_model,
                    'llm.base_url', default_llm_base_url,
                    'verification.confirmation_mode', confirmation_mode,
                    'verification.security_analyzer', security_analyzer,
                    'condenser.enabled', enable_default_condenser,
                    'condenser.max_size', condenser_max_size,
                    'max_iterations', default_max_iterations,
                    'mcp_config', mcp_config
                )
            )::json
            """
        )
    )

    op.alter_column('org', 'agent_settings', server_default=None)


def downgrade() -> None:
    op.drop_column('org', 'agent_settings')
