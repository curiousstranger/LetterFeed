"""reset feed_body holding classes or comments so the backfill redoes it

Revision ID: e6f1a2b3c4d5
Revises: d5e9f2a3b4c6
Create Date: 2026-10-22 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e6f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'd5e9f2a3b4c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Null feed_body flattened before classes and comments were removed."""
    op.execute(
        "UPDATE entries SET feed_body = NULL "
        "WHERE feed_body LIKE '%class=%' OR feed_body LIKE '%<!--%'"
    )


def downgrade() -> None:
    """Nothing to undo: the backfill refills feed_body."""
