"""add wc2026 tournament and elo schema

Revision ID: a1b2c3d4e5f6
Revises: 4922171d5711
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '4922171d5711'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### teams: add country_code for ISO-3166 alpha-2 + subdivision codes ###
    op.add_column('teams', sa.Column('country_code', sa.String(length=8), nullable=True))
    op.create_index('ix_teams_country_code', 'teams', ['country_code'], unique=False)

    # ### matches: add tournament bracket/stage columns ###
    op.add_column('matches', sa.Column('stage', sa.String(length=20), nullable=True))
    op.add_column('matches', sa.Column('group_label', sa.String(length=2), nullable=True))
    op.add_column('matches', sa.Column('bracket_position', sa.SmallInteger(), nullable=True))

    # ### team_elo: new table for per-team ELO ratings over time ###
    op.create_table('team_elo',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('rating', sa.Float(), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('source', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('team_id', 'as_of_date', 'source', name='uq_team_elo_team_date_source')
    )
    op.create_index('ix_team_elo_team_date', 'team_elo', ['team_id', 'as_of_date'], unique=False)


def downgrade() -> None:
    # ### team_elo ###
    op.drop_index('ix_team_elo_team_date', table_name='team_elo')
    op.drop_table('team_elo')

    # ### matches ###
    op.drop_column('matches', 'bracket_position')
    op.drop_column('matches', 'group_label')
    op.drop_column('matches', 'stage')

    # ### teams ###
    op.drop_index('ix_teams_country_code', table_name='teams')
    op.drop_column('teams', 'country_code')
