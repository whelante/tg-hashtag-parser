import sqlite3
import hashlib
import threading
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH = Path("data/posts.db")
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute("PRAGMA busy_timeout=30000")
        _conn.commit()
        log.info("SQLite connected (WAL): %s", DB_PATH.resolve())
    return _conn


def init_db():
    with _lock:
        conn = get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS hashtags (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                tag      TEXT UNIQUE NOT NULL,
                active   INTEGER NOT NULL DEFAULT 1,
                added_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id   INTEGER NOT NULL,
                channel_name TEXT,
                username     TEXT,
                message_id   INTEGER NOT NULL,
                post_link    TEXT,
                published_at TEXT,
                parsed_at    TEXT NOT NULL,
                hashtag      TEXT,
                text         TEXT,
                text_hash    TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(channel_id, message_id),
                UNIQUE(text_hash)
            );
            CREATE TABLE IF NOT EXISTS stats (
                key   TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            );
        """)
        for tag in ["#btc","#btcusdt","#eth","#ethusdt","#sol","#solusdt",
                    "#doge","#dogeusdt","#bnb","#bnbusdt"]:
            conn.execute(
                "INSERT OR IGNORE INTO hashtags (tag,active,added_at) VALUES(?,1,?)",
                (tag, datetime.utcnow().isoformat())
            )
        conn.commit()


def _norm(tag: str) -> str:
    tag = tag.strip().lower()
    return tag if tag.startswith("#") else f"#{tag}"


def add_tag(tag: str) -> bool:
    tag = _norm(tag)
    with _lock:
        conn = get_conn()
        try:
            conn.execute("INSERT INTO hashtags(tag,active,added_at) VALUES(?,1,?)",
                         (tag, datetime.utcnow().isoformat()))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            conn.execute("UPDATE hashtags SET active=1 WHERE tag=?", (tag,))
            conn.commit()
            return False


def remove_tag(tag: str) -> bool:
    tag = _norm(tag)
    with _lock:
        conn = get_conn()
        cur = conn.execute("UPDATE hashtags SET active=0 WHERE tag=?", (tag,))
        conn.commit()
        return cur.rowcount > 0


def list_tags() -> list[dict]:
    return [dict(r) for r in get_conn().execute(
        "SELECT tag,active,added_at FROM hashtags ORDER BY tag").fetchall()]


def get_active_tags() -> list[str]:
    return [r["tag"] for r in get_conn().execute(
        "SELECT tag FROM hashtags WHERE active=1").fetchall()]


def save_post(channel_id, channel_name, username, message_id,
              post_link, published_at, hashtag, text) -> int | None:
    th = hashlib.sha256((text or "").strip().lower().encode()).hexdigest()
    with _lock:
        conn = get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO posts(channel_id,channel_name,username,message_id,
                   post_link,published_at,parsed_at,hashtag,text,text_hash,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,'pending')""",
                (channel_id, channel_name, username, message_id,
                 post_link, published_at, datetime.utcnow().isoformat(),
                 hashtag, text, th))
            conn.commit()
            conn.execute("INSERT INTO stats(key,value) VALUES('total_parsed',1) "
                         "ON CONFLICT(key) DO UPDATE SET value=value+1")
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def update_status(post_id: int, status: str):
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE posts SET status=? WHERE id=?", (status, post_id))
        conn.execute(f"INSERT INTO stats(key,value) VALUES('total_{status}',1) "
                     "ON CONFLICT(key) DO UPDATE SET value=value+1")
        conn.commit()


def get_post(post_id: int) -> dict | None:
    row = get_conn().execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    return dict(row) if row else None


def get_stats() -> dict:
    conn = get_conn()
    s = {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM stats").fetchall()}
    s["pending"]   = conn.execute("SELECT COUNT(*) FROM posts WHERE status='pending'").fetchone()[0]
    s["published"] = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0]
    return s
