"""add tournament_simulations table

Revision ID: 56a015708c89
Revises: b7c8d9e0f1a2
Create Date: 2026-04-24 16:03:10.229816

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '56a015708c89'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tournament_simulations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_at', sa.DateTime(), nullable=False),
        sa.Column('n_sims', sa.Integer(), nullable=False),
        sa.Column('result_json', sa.Text(), nullable=False),
        sa.Column('model_version', sa.String(length=30), nullable=False),
        sa.Column('elo_model_version', sa.String(length=30), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_tournament_simulations_run_at',
        'tournament_simulations',
        [sa.text('run_at DESC')],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_tournament_simulations_run_at', table_name='tournament_simulations')
    op.drop_table('tournament_simulations')
