"""reset unflattened feed_body so the backfill retries it

Revision ID: c4d8e1f2a3b5
Revises: b7e2f4a9c1d3
Create Date: 2026-09-24 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4d8e1f2a3b5'
down_revision: Union[str, Sequence[str], None] = 'b7e2f4a9c1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Null feed_body where flattening fell back to the raw body."""
    op.execute("UPDATE entries SET feed_body = NULL WHERE feed_body = body")


def downgrade() -> None:
    """Nothing to undo: the backfill refills feed_body."""
