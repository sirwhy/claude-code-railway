"""Database connection and initialization.

Supports both SQLite (development) and PostgreSQL (production/Railway).
Backend is selected automatically from DATABASE_URL:
  - postgres:// or postgresql://  → asyncpg (PostgreSQL)
  - sqlite:///                    → aiosqlite (SQLite, default)
"""

import asyncio
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, List, Optional

import structlog

logger = structlog.get_logger()


# ─── SQLite datetime adapters ───────────────────────────────────────────────
def _register_sqlite_adapters():
    import sqlite3
    sqlite3.register_adapter(datetime, lambda v: v.isoformat())
    sqlite3.register_converter("TIMESTAMP", lambda b: datetime.fromisoformat(b.decode()))
    sqlite3.register_converter("DATETIME", lambda b: datetime.fromisoformat(b.decode()))
    sqlite3.register_converter("DATE", lambda b: b.decode())


# ─── Schema ─────────────────────────────────────────────────────────────────

INITIAL_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    telegram_username TEXT,
    first_seen TIMESTAMP DEFAULT NOW(),
    last_active TIMESTAMP DEFAULT NOW(),
    is_allowed BOOLEAN DEFAULT FALSE,
    total_cost REAL DEFAULT 0.0,
    message_count INTEGER DEFAULT 0,
    session_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    project_path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    last_used TIMESTAMP DEFAULT NOW(),
    total_cost REAL DEFAULT 0.0,
    total_turns INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS messages (
    message_id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    timestamp TIMESTAMP DEFAULT NOW(),
    prompt TEXT NOT NULL,
    response TEXT,
    cost REAL DEFAULT 0.0,
    duration_ms INTEGER,
    error TEXT
);
CREATE TABLE IF NOT EXISTS tool_usage (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    message_id BIGINT REFERENCES messages(message_id),
    tool_name TEXT NOT NULL,
    tool_input JSONB,
    timestamp TIMESTAMP DEFAULT NOW(),
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    event_type TEXT NOT NULL,
    event_data JSONB,
    success BOOLEAN DEFAULT TRUE,
    timestamp TIMESTAMP DEFAULT NOW(),
    ip_address TEXT
);
CREATE TABLE IF NOT EXISTS user_tokens (
    token_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    last_used TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS cost_tracking (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    date DATE NOT NULL,
    daily_cost REAL DEFAULT 0.0,
    request_count INTEGER DEFAULT 0,
    UNIQUE(user_id, date)
);
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    job_id TEXT PRIMARY KEY,
    job_name TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    prompt TEXT NOT NULL,
    target_chat_ids TEXT DEFAULT '',
    working_directory TEXT NOT NULL,
    skill_name TEXT,
    created_by BIGINT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS webhook_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    event_type TEXT NOT NULL,
    delivery_id TEXT UNIQUE,
    payload JSONB,
    processed BOOLEAN DEFAULT FALSE,
    received_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS project_threads (
    id BIGSERIAL PRIMARY KEY,
    project_slug TEXT NOT NULL,
    chat_id BIGINT NOT NULL,
    message_thread_id BIGINT NOT NULL,
    topic_name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(chat_id, project_slug),
    UNIQUE(chat_id, message_thread_id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project_path ON sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_cost_tracking_user_date ON cost_tracking(user_id, date);
CREATE INDEX IF NOT EXISTS idx_webhook_events_delivery ON webhook_events(delivery_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_active ON scheduled_jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_project_threads_chat_active ON project_threads(chat_id, is_active);
CREATE INDEX IF NOT EXISTS idx_project_threads_slug ON project_threads(project_slug);
"""

INITIAL_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    telegram_username TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_allowed BOOLEAN DEFAULT FALSE,
    total_cost REAL DEFAULT 0.0,
    message_count INTEGER DEFAULT 0,
    session_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    project_path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_cost REAL DEFAULT 0.0,
    total_turns INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    prompt TEXT NOT NULL,
    response TEXT,
    cost REAL DEFAULT 0.0,
    duration_ms INTEGER,
    error TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE TABLE IF NOT EXISTS tool_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_id INTEGER,
    tool_name TEXT NOT NULL,
    tool_input JSON,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
    FOREIGN KEY (message_id) REFERENCES messages(message_id)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSON,
    success BOOLEAN DEFAULT TRUE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE TABLE IF NOT EXISTS user_tokens (
    token_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    last_used TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE TABLE IF NOT EXISTS cost_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date DATE NOT NULL,
    daily_cost REAL DEFAULT 0.0,
    request_count INTEGER DEFAULT 0,
    UNIQUE(user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    job_id TEXT PRIMARY KEY,
    job_name TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    prompt TEXT NOT NULL,
    target_chat_ids TEXT DEFAULT '',
    working_directory TEXT NOT NULL,
    skill_name TEXT,
    created_by INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    event_type TEXT NOT NULL,
    delivery_id TEXT UNIQUE,
    payload JSON,
    processed BOOLEAN DEFAULT FALSE,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS project_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    message_thread_id INTEGER NOT NULL,
    topic_name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, project_slug),
    UNIQUE(chat_id, message_thread_id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project_path ON sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_cost_tracking_user_date ON cost_tracking(user_id, date);
CREATE INDEX IF NOT EXISTS idx_webhook_events_delivery ON webhook_events(delivery_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_active ON scheduled_jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_project_threads_chat_active ON project_threads(chat_id, is_active);
CREATE INDEX IF NOT EXISTS idx_project_threads_slug ON project_threads(project_slug);
"""


# ─── PostgreSQL helpers ──────────────────────────────────────────────────────

def _ensure_aware(value):
    """Convert naive datetime to UTC-aware datetime for PostgreSQL compatibility."""
    from datetime import datetime as _dt, UTC as _UTC, timezone as _tz
    if isinstance(value, _dt) and value.tzinfo is None:
        return value.replace(tzinfo=_UTC)
    return value


def _sanitize_params(params):
    """Ensure all datetime parameters are timezone-aware before sending to asyncpg."""
    if not params:
        return params
    return [_ensure_aware(p) for p in params]


def _sqlite_to_pg(query: str, params=None):
    """Convert SQLite-style query (? placeholders, SQLite functions) to PostgreSQL."""
    if params is None:
        params = []
    # Replace ? with $1, $2, ...
    out, counter = [], 1
    for ch in query:
        if ch == "?":
            out.append(f"${counter}")
            counter += 1
        else:
            out.append(ch)
    query = "".join(out)

    # SQLite datetime expressions → PostgreSQL
    query = re.sub(
        r"datetime\('now',\s*'-'\s*\|\|\s*(\$\d+)\s*\|\|\s*' days'\)",
        r"NOW() - (\1 || ' days')::INTERVAL",
        query,
    )
    query = re.sub(
        r"datetime\('now',\s*'-'\s*\|\|\s*(\$\d+)\s*\|\|\s*' hours'\)",
        r"NOW() - (\1 || ' hours')::INTERVAL",
        query,
    )
    query = re.sub(r"datetime\('now',\s*'-30 days'\)", "NOW() - INTERVAL '30 days'", query)
    query = re.sub(r"datetime\('now',\s*'-7 days'\)", "NOW() - INTERVAL '7 days'", query)
    query = re.sub(r"date\('now',\s*'-'\s*\|\|\s*(\$\d+)\s*\|\|\s*' days'\)",
                   r"CURRENT_DATE - (\1 || ' days')::INTERVAL", query)
    # date(column) → DATE(column) - already compatible
    # CURRENT_TIMESTAMP → NOW()
    query = query.replace("CURRENT_TIMESTAMP", "NOW()")
    # ON CONFLICT ... DO UPDATE SET (compatible; just ensure no SQLite-isms)
    return query, list(params)


class _PGCursor:
    def __init__(self, rows=None, rowcount=0, lastrowid=None):
        self._rows = rows or []
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return list(self._rows)


class _DictRecord:
    """Wraps asyncpg Record to support both key and integer index access."""
    def __init__(self, record):
        self._r = record
        self._keys = list(record.keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._r[self._keys[key]]
        return self._r[key]

    def get(self, key, default=None):
        try:
            return self._r[key]
        except KeyError:
            return default

    def keys(self):
        return self._keys

    def __iter__(self):
        return iter(self._keys)

    def __contains__(self, key):
        return key in self._keys


class _PGConn:
    """asyncpg connection wrapper mimicking aiosqlite interface."""

    def __init__(self, conn):
        self._conn = conn

    async def execute(self, query: str, params=None) -> _PGCursor:
        query, params = _sqlite_to_pg(query, params)
        params = _sanitize_params(params)
        try:
            # Try with RETURNING to get lastrowid for INSERT
            if query.strip().upper().startswith("INSERT") and "RETURNING" not in query.upper():
                try:
                    ret_query = query.rstrip().rstrip(";") + " RETURNING *"
                    rows = await self._conn.fetch(ret_query, *params)
                    wrapped = [_DictRecord(r) for r in rows]
                    lastrowid = None
                    if wrapped:
                        for key in ("message_id", "id", "token_id"):
                            val = wrapped[0].get(key)
                            if val is not None:
                                lastrowid = val
                                break
                    return _PGCursor(rows=wrapped, rowcount=len(wrapped), lastrowid=lastrowid)
                except Exception:
                    pass  # Fall through to plain execute

            result = await self._conn.execute(query, *params)
            rowcount = 0
            if result and " " in str(result):
                try:
                    rowcount = int(str(result).split()[-1])
                except ValueError:
                    pass
            return _PGCursor(rowcount=rowcount)
        except Exception as e:
            logger.error("PG execute error", error=str(e), query=query[:120])
            raise

    async def executescript(self, script: str):
        for stmt in script.split(";"):
            stmt = stmt.strip()
            if stmt:
                pg_stmt, _ = _sqlite_to_pg(stmt)
                try:
                    await self._conn.execute(pg_stmt)
                except Exception as e:
                    msg = str(e).lower()
                    if "already exists" not in msg and "duplicate" not in msg:
                        logger.warning("Migration stmt warning", error=str(e), stmt=pg_stmt[:80])

    async def commit(self):
        pass  # asyncpg auto-commits by default

    async def close(self):
        await self._conn.close()


# ─── SQLite cursor/connection wrappers ──────────────────────────────────────

class _SQLiteCursorWrapper:
    def __init__(self, cur):
        self._cur = cur
        self.rowcount = getattr(cur, "rowcount", 0)
        self.lastrowid = getattr(cur, "lastrowid", None)

    async def fetchone(self):
        return await self._cur.fetchone()

    async def fetchall(self):
        return await self._cur.fetchall()


class _SQLiteConnWrapper:
    def __init__(self, conn):
        self._conn = conn

    async def execute(self, query: str, params=None) -> _SQLiteCursorWrapper:
        cur = await self._conn.execute(query, params or [])
        return _SQLiteCursorWrapper(cur)

    async def executescript(self, script: str):
        await self._conn.executescript(script)

    async def commit(self):
        await self._conn.commit()

    async def close(self):
        await self._conn.close()


# ─── DatabaseManager ────────────────────────────────────────────────────────

async def _setup_pg_connection(conn) -> None:
    """Initialize each asyncpg connection.

    asyncpg natively returns timezone-aware datetimes from PostgreSQL.
    We ensure naive datetimes are converted to UTC before queries via
    _sanitize_params — no custom codec needed here.
    """
    # Set the timezone to UTC for this connection so all timestamps
    # are interpreted as UTC by PostgreSQL
    await conn.execute("SET TIME ZONE 'UTC'")


class DatabaseManager:
    """Unified database manager: PostgreSQL or SQLite."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._use_postgres = database_url.startswith("postgres")
        self._pg_pool = None
        self._sqlite_path: Optional[Path] = None
        self._connection_pool: List = []
        self._pool_size = 5
        self._pool_lock = asyncio.Lock()

        if not self._use_postgres:
            _register_sqlite_adapters()
            if database_url.startswith("sqlite:///"):
                self._sqlite_path = Path(database_url[10:])
            elif database_url.startswith("sqlite://"):
                self._sqlite_path = Path(database_url[9:])
            else:
                self._sqlite_path = Path(database_url)

    async def initialize(self):
        logger.info(
            "Initializing database",
            backend="postgresql" if self._use_postgres else "sqlite",
        )
        if self._use_postgres:
            await self._init_postgres()
        else:
            await self._init_sqlite()
        logger.info("Database initialization complete")

    # ── PostgreSQL init ──────────────────────────────────────────────────────

    async def _init_postgres(self):
        try:
            import asyncpg
        except ImportError:
            raise RuntimeError("asyncpg package is required for PostgreSQL. pip install asyncpg")

        url = self.database_url.replace("postgres://", "postgresql://", 1)
        # Railway internal Postgres (*.railway.internal) doesn't use SSL
        # External/public Postgres URLs do require SSL
        use_ssl = "railway.internal" not in url

        self._pg_pool = await asyncpg.create_pool(
            url,
            min_size=2,
            max_size=self._pool_size,
            command_timeout=30,
            ssl="require" if use_ssl else None,
            init=_setup_pg_connection,
        )

        async with self._pg_pool.acquire() as raw:
            conn = _PGConn(raw)
            await self._run_pg_migrations(conn, raw)

    async def _run_pg_migrations(self, conn: _PGConn, raw_conn):
        await raw_conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        current = await raw_conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        logger.info("Current schema version", version=current)

        if current < 1:
            logger.info("Running PostgreSQL initial migration")
            for stmt in INITIAL_SCHEMA_PG.split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        await raw_conn.execute(stmt)
                    except Exception as e:
                        msg = str(e).lower()
                        if "already exists" not in msg:
                            logger.warning("Migration warning", error=str(e), stmt=stmt[:80])
            await raw_conn.execute(
                "INSERT INTO schema_version(version) VALUES(1) ON CONFLICT DO NOTHING"
            )

    # ── SQLite init ──────────────────────────────────────────────────────────

    async def _init_sqlite(self):
        import aiosqlite, sqlite3

        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(
            self._sqlite_path, detect_types=sqlite3.PARSE_DECLTYPES
        ) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
            )
            cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
            row = await cursor.fetchone()
            current = row[0] if row and row[0] else 0

            if current < 1:
                await conn.executescript(INITIAL_SCHEMA_SQLITE)
                await conn.execute(
                    "INSERT OR IGNORE INTO schema_version(version) VALUES(1)"
                )
                await conn.commit()

        await self._init_sqlite_pool()

    async def _init_sqlite_pool(self):
        import aiosqlite, sqlite3

        async with self._pool_lock:
            for _ in range(self._pool_size):
                conn = await aiosqlite.connect(
                    self._sqlite_path, detect_types=sqlite3.PARSE_DECLTYPES
                )
                conn.row_factory = aiosqlite.Row
                await conn.execute("PRAGMA foreign_keys = ON")
                self._connection_pool.append(_SQLiteConnWrapper(conn))

    # ── Connection context manager ───────────────────────────────────────────

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator:
        if self._use_postgres:
            async with self._pg_pool.acquire() as raw:
                yield _PGConn(raw)
        else:
            async with self._pool_lock:
                if self._connection_pool:
                    conn = self._connection_pool.pop()
                else:
                    import aiosqlite, sqlite3
                    raw = await aiosqlite.connect(
                        self._sqlite_path, detect_types=sqlite3.PARSE_DECLTYPES
                    )
                    raw.row_factory = aiosqlite.Row
                    await raw.execute("PRAGMA foreign_keys = ON")
                    conn = _SQLiteConnWrapper(raw)
            try:
                yield conn
            finally:
                async with self._pool_lock:
                    if len(self._connection_pool) < self._pool_size:
                        self._connection_pool.append(conn)
                    else:
                        await conn.close()

    async def close(self):
        logger.info("Closing database connections")
        if self._use_postgres and self._pg_pool:
            await self._pg_pool.close()
        else:
            async with self._pool_lock:
                for conn in self._connection_pool:
                    await conn.close()
                self._connection_pool.clear()

    async def health_check(self) -> bool:
        try:
            async with self.get_connection() as conn:
                await conn.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error("Database health check failed", error=str(e))
            return False
