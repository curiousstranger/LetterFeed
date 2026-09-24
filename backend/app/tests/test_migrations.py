import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def _alembic(db: Path, *args: str) -> None:
    env = {**os.environ, "LETTERFEED_DATABASE_URL": f"sqlite:///{db}"}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        check=True,
        capture_output=True,
    )


def test_unflattened_feed_bodies_are_reset_for_the_backfill(tmp_path):
    """feed_body copies of body are nulled so the startup backfill redoes them."""
    db = tmp_path / "m.db"
    _alembic(db, "upgrade", "b7e2f4a9c1d3")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO newsletters (id, name) VALUES ('n1', 'N')")
    con.executemany(
        "INSERT INTO entries (id, newsletter_id, message_id, subject, body, feed_body) "
        "VALUES (?, 'n1', ?, 's', ?, ?)",
        [
            ("fallback", "m1", "<img>raw", "<img>raw"),
            ("flattened", "m2", "<table>x</table>", "<div>x</div>"),
            ("pending", "m3", "<p>y</p>", None),
        ],
    )
    con.commit()
    con.close()

    _alembic(db, "upgrade", "head")

    con = sqlite3.connect(db)
    rows = dict(con.execute("SELECT id, feed_body FROM entries"))
    con.close()
    assert rows == {"fallback": None, "flattened": "<div>x</div>", "pending": None}
