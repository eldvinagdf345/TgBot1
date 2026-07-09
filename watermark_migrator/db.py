import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    message_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    watermark_found INTEGER,
    bbox_x INTEGER,
    bbox_y INTEGER,
    bbox_w INTEGER,
    bbox_h INTEGER,
    error TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# status values: pending -> downloading -> detecting -> cleaning -> uploading -> done
#                any stage can transition to 'error'; already-'done' rows are skipped on resume


class StateDB:
    def __init__(self, path: str):
        # check_same_thread=False: the GUI app creates this on the main
        # thread but drives all the actual work from a background asyncio
        # thread, one call at a time - never concurrently.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def get_status(self, message_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM jobs WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row[0] if row else None

    def upsert_status(self, message_id: int, status: str, **fields):
        existing = self.get_status(message_id)
        if existing is None:
            self.conn.execute(
                "INSERT INTO jobs (message_id, status) VALUES (?, ?)",
                (message_id, status),
            )
        cols = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        vals = [status]
        for k, v in fields.items():
            cols.append(f"{k} = ?")
            vals.append(v)
        vals.append(message_id)
        self.conn.execute(
            f"UPDATE jobs SET {', '.join(cols)} WHERE message_id = ?", vals
        )
        self.conn.commit()

    def is_done(self, message_id: int) -> bool:
        return self.get_status(message_id) == "done"

    def close(self):
        self.conn.close()


@contextmanager
def open_db(path: str):
    db = StateDB(path)
    try:
        yield db
    finally:
        db.close()
