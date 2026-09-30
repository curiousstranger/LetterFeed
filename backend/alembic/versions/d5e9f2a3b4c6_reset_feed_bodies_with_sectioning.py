"""reset feed_body holding header/footer/nav/aside so the backfill redoes it

Revision ID: d5e9f2a3b4c6
Revises: c4d8e1f2a3b5
Create Date: 2026-09-30 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd5e9f2a3b4c6'
down_revision: Union[str, Sequence[str], None] = 'c4d8e1f2a3b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Null feed_body flattened before sectioning elements became divs."""
    op.execute(
        "UPDATE entries SET feed_body = NULL "
        "WHERE feed_body LIKE '%<header%' OR feed_body LIKE '%<footer%' "
        "OR feed_body LIKE '%<nav%' OR feed_body LIKE '%<aside%'"
    )


def downgrade() -> None:
    """Nothing to undo: the backfill refills feed_body."""
