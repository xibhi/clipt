import contextlib
import os
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path


DATA_DIR = Path.home() / ".local" / "share" / "clipt"
DB_PATH = DATA_DIR / "history.db"
VALID_SOURCES = {"manual", "file", "pipe", "ocopy", "share"}


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    item_id: str
    content: str
    source: str
    created_at: str
    pinned: bool
    pinned_at: str | None = None

    @property
    def created_on(self) -> str:
        return self.pinned_at if self.pinned and self.pinned_at else self.created_at


def _generate_item_id() -> str:
    """Generate a random 10-digit item ID (first digit 1-9, no leading zero)."""
    first_digit = str(random.randint(1, 9))
    remaining = "".join(str(random.randint(0, 9)) for _ in range(9))
    return first_digit + remaining


@contextlib.contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if DB_PATH.exists():
            os.chmod(DB_PATH, 0o600)
    except OSError:
        pass
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    try:
        if DB_PATH.exists():
            os.chmod(DB_PATH, 0o600)
    except OSError:
        pass
    table_info = conn.execute("PRAGMA table_info(history)").fetchall()
    if not table_info:
        conn.executescript(
            """
            CREATE TABLE history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL CHECK (source IN ('manual', 'file', 'pipe', 'ocopy', 'share')),
                pinned INTEGER NOT NULL DEFAULT 0,
                pinned_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_history_source ON history(source);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_history_item_id ON history(item_id);
            """
        )
        conn.commit()
        return

    # Migration for existing databases
    existing_cols = {row["name"] for row in table_info}
    if "item_id" not in existing_cols:
        conn.execute("ALTER TABLE history ADD COLUMN item_id TEXT")
        rows = conn.execute("SELECT id FROM history WHERE item_id IS NULL OR item_id = ''").fetchall()
        for row in rows:
            while True:
                new_id = _generate_item_id()
                if not conn.execute("SELECT 1 FROM history WHERE item_id = ?", (new_id,)).fetchone():
                    break
            conn.execute("UPDATE history SET item_id = ? WHERE id = ?", (new_id, row["id"]))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_history_item_id ON history(item_id)")

    if "pinned_at" not in existing_cols:
        conn.execute("ALTER TABLE history ADD COLUMN pinned_at TEXT")
        conn.execute("UPDATE history SET pinned_at = created_at WHERE pinned = 1 AND pinned_at IS NULL")

    schema_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='history'").fetchone()
    schema_sql = str(schema_row["sql"]) if schema_row and schema_row["sql"] else ""
    if "copyp" in schema_sql:
        # Recreate table to update CHECK constraint cleanly
        conn.executescript(
            """
            CREATE TABLE history_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL CHECK (source IN ('manual', 'file', 'pipe', 'ocopy', 'share')),
                pinned INTEGER NOT NULL DEFAULT 0,
                pinned_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            """
        )
        rows = conn.execute("SELECT id, item_id, content, source, pinned, pinned_at, created_at FROM history").fetchall()
        for r in rows:
            src = "ocopy" if r["source"] == "copyp" else r["source"]
            if src not in VALID_SOURCES:
                src = "manual"
            item_id_val = r["item_id"] if r["item_id"] else _generate_item_id()
            conn.execute(
                "INSERT INTO history_v2 (id, item_id, content, source, pinned, pinned_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["id"], item_id_val, r["content"], src, r["pinned"], r["pinned_at"], r["created_at"]),
            )
        conn.executescript(
            """
            DROP TABLE history;
            ALTER TABLE history_v2 RENAME TO history;
            CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_history_source ON history(source);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_history_item_id ON history(item_id);
            """
        )

    conn.commit()


def add_history(
    content: str,
    source: str,
    *,
    max_entries: int,
    deduplicate_consecutive: bool,
) -> int | None:
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid history source: {source!r}. Must be one of: {VALID_SOURCES}")
    with connect() as conn:
        if deduplicate_consecutive:
            row = conn.execute("SELECT content FROM history ORDER BY id DESC LIMIT 1").fetchone()
            if row and row["content"] == content:
                return None

        # Retry on rare item_id collision
        for _ in range(10):
            item_id = _generate_item_id()
            try:
                cur = conn.execute(
                    "INSERT INTO history (item_id, content, source) VALUES (?, ?, ?)",
                    (item_id, content, source),
                )
                break
            except sqlite3.IntegrityError:
                continue
        else:
            raise RuntimeError("Failed to generate unique 10-digit item_id after retries")

        prune_history(conn, max_entries)
        conn.commit()
        return int(cur.lastrowid)


def prune_history(conn: sqlite3.Connection, max_entries: int) -> int:
    rows = conn.execute(
        """
        SELECT id FROM history
        WHERE pinned = 0
        ORDER BY created_at DESC, id DESC
        LIMIT -1 OFFSET ?
        """,
        (max_entries,),
    ).fetchall()
    ids = [row["id"] for row in rows]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    conn.execute(f"DELETE FROM history WHERE id IN ({placeholders})", ids)
    return len(ids)


def _entry_from_row(row: sqlite3.Row) -> HistoryEntry:
    return HistoryEntry(
        id=int(row["id"]),
        item_id=str(row["item_id"]),
        content=str(row["content"]),
        source=str(row["source"]),
        created_at=str(row["created_at"]),
        pinned=bool(row["pinned"]),
        pinned_at=str(row["pinned_at"]) if row["pinned_at"] else None,
    )


def list_history(limit: int | None = None, *, pinned_only: bool = False) -> list[HistoryEntry]:
    sql = "SELECT id, item_id, content, source, created_at, pinned, pinned_at FROM history"
    params: list[int] = []
    if pinned_only:
        sql += " WHERE pinned = 1"
    sql += " ORDER BY created_at DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with connect() as conn:
        return [_entry_from_row(row) for row in conn.execute(sql, params).fetchall()]


def get_entry_by_index(index: int) -> tuple[int, HistoryEntry] | None:
    if index < 1:
        return None
    entries = list_history()
    if index > len(entries):
        return None
    return index, entries[index - 1]


def get_entry_by_item_id(item_id: str) -> tuple[int, HistoryEntry] | None:
    all_entries = list_history()
    for idx, entry in enumerate(all_entries, start=1):
        if entry.item_id == item_id:
            return idx, entry
    return None


def search_history(query: str, limit: int = 50) -> list[HistoryEntry]:
    like = f"%{query}%"
    with connect() as conn:
        return [
            _entry_from_row(row)
            for row in conn.execute(
                """
                SELECT id, item_id, content, source, created_at, pinned, pinned_at
                FROM history
                WHERE content LIKE ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (like, limit),
            ).fetchall()
        ]


def set_pinned(entry_id: int, pinned: bool = True) -> None:
    with connect() as conn:
        if pinned:
            conn.execute("UPDATE history SET pinned = 1, pinned_at = datetime('now', 'localtime') WHERE id = ?", (entry_id,))
        else:
            conn.execute("UPDATE history SET pinned = 0, pinned_at = NULL WHERE id = ?", (entry_id,))
        conn.commit()


def delete_history_entry(entry_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM history WHERE id = ?", (entry_id,))
        conn.commit()


def wipe_unpinned() -> int:
    with connect() as conn:
        cur = conn.execute("DELETE FROM history WHERE pinned = 0")
        conn.commit()
        return int(cur.rowcount)


def wipe_all() -> int:
    with connect() as conn:
        cur = conn.execute("DELETE FROM history")
        conn.commit()
        return int(cur.rowcount)


def count_history(*, pinned_only: bool = False, unpinned_only: bool = False) -> int:
    sql = "SELECT COUNT(*) AS count FROM history"
    if pinned_only:
        sql += " WHERE pinned = 1"
    elif unpinned_only:
        sql += " WHERE pinned = 0"
    with connect() as conn:
        row = conn.execute(sql).fetchone()
        return int(row["count"])


def latest_entry() -> HistoryEntry | None:
    entries = list_history(1)
    return entries[0] if entries else None


def stats() -> dict[str, object]:
    with connect() as conn:
        total = int(conn.execute("SELECT COUNT(*) AS count FROM history").fetchone()["count"])
        pinned = int(conn.execute("SELECT COUNT(*) AS count FROM history WHERE pinned = 1").fetchone()["count"])
        avg_row = conn.execute("SELECT AVG(LENGTH(content)) AS avg_len FROM history").fetchone()
        avg_len = float(avg_row["avg_len"] or 0)
        by_source = {
            str(row["source"]): int(row["count"])
            for row in conn.execute(
                "SELECT source, COUNT(*) AS count FROM history GROUP BY source ORDER BY source"
            ).fetchall()
        }
        busy_row = conn.execute(
            """
            SELECT strftime('%w', created_at) AS weekday, COUNT(*) AS count
            FROM history
            GROUP BY weekday
            ORDER BY count DESC
            LIMIT 1
            """
        ).fetchone()
        contents = [str(row["content"]) for row in conn.execute("SELECT content FROM history").fetchall()]

    return {
        "total": total,
        "pinned": pinned,
        "avg_len": avg_len,
        "by_source": by_source,
        "busiest_day": str(busy_row["weekday"]) if busy_row else "",
        "contents": contents,
    }

