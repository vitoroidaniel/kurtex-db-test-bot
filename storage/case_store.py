"""
storage/case_store.py

PostgreSQL-only case storage for Railway production.
Requires DATABASE_URL to be set.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required for storage.case_store in production mode.")

_pool = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _init_postgres() -> None:
    global _pool
    if _pool is not None:
        return

    try:
        from psycopg_pool import ConnectionPool
    except Exception as e:
        logger.error(f"Failed to import psycopg_pool: {e}")
        raise

    conninfo = DATABASE_URL
    if "sslmode=" not in conninfo:
        sep = "&" if "?" in conninfo else "?"
        conninfo = f"{conninfo}{sep}sslmode=require"

    _pool = ConnectionPool(conninfo=conninfo, min_size=1, max_size=8, timeout=15)

    ddl = """
    CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        driver_name TEXT NOT NULL,
        driver_username TEXT,
        group_name TEXT NOT NULL,
        description TEXT NOT NULL,
        opened_at TIMESTAMPTZ NOT NULL,
        assigned_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ,
        agent_id BIGINT,
        agent_name TEXT,
        agent_username TEXT,
        status TEXT NOT NULL CHECK (status IN ('open', 'assigned', 'reported', 'done', 'missed')),
        notes TEXT,
        response_secs INTEGER,
        resolution_secs INTEGER
    );

    CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
    CREATE INDEX IF NOT EXISTS idx_cases_opened_at ON cases(opened_at DESC);
    CREATE INDEX IF NOT EXISTS idx_cases_agent_id ON cases(agent_id);
    CREATE INDEX IF NOT EXISTS idx_cases_assigned_at ON cases(assigned_at DESC);
    """

    with _pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()

    logger.info("PostgreSQL case storage initialized")


def _db_fetchall(query: str, params: tuple = ()) -> list[dict]:
    _init_postgres()
    with _pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def _db_fetchone(query: str, params: tuple = ()) -> Optional[dict]:
    _init_postgres()
    with _pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


def _db_execute(query: str, params: tuple = ()) -> None:
    _init_postgres()
    with _pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()


def _normalize_row(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    out = dict(row)
    for key in ("opened_at", "assigned_at", "closed_at"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = value.astimezone(timezone.utc).isoformat()
    return out


# ── Write operations ──────────────────────────────────────────────────────────

def create_case(
    case_id: str,
    driver_name: str,
    driver_username: Optional[str],
    group_name: str,
    description: str,
) -> dict:
    opened_at = now_iso()

    _db_execute(
        """
        INSERT INTO cases (
            id, driver_name, driver_username, group_name, description,
            opened_at, assigned_at, closed_at,
            agent_id, agent_name, agent_username,
            status, notes, response_secs, resolution_secs
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s::timestamptz, NULL, NULL,
            NULL, NULL, NULL,
            'open', NULL, NULL, NULL
        )
        ON CONFLICT (id) DO NOTHING
        """,
        (case_id, driver_name, driver_username, group_name, description, opened_at),
    )

    case = _db_fetchone("SELECT * FROM cases WHERE id = %s", (case_id,))
    logger.info(f"Case {case_id} created")
    return _normalize_row(case)


def assign_case(case_id: str, agent_id: int, agent_name: str, agent_username: Optional[str]) -> Optional[dict]:
    row = _db_fetchone("SELECT opened_at FROM cases WHERE id = %s", (case_id,))
    if not row:
        logger.warning(f"assign_case: case {case_id} not found")
        return None

    opened_dt = row["opened_at"]
    if isinstance(opened_dt, str):
        opened_dt = _parse_iso(opened_dt)

    assigned_at = now_iso()
    assigned_dt = _parse_iso(assigned_at)
    response_secs = int((assigned_dt - opened_dt).total_seconds()) if (assigned_dt and opened_dt) else None

    updated = _db_fetchone(
        """
        UPDATE cases
        SET assigned_at = %s::timestamptz,
            agent_id = %s,
            agent_name = %s,
            agent_username = %s,
            status = 'assigned',
            response_secs = %s
        WHERE id = %s
        RETURNING *
        """,
        (assigned_at, agent_id, agent_name, agent_username, response_secs, case_id),
    )
    if not updated:
        logger.warning(f"assign_case: case {case_id} not found")
        return None

    logger.info(f"Case {case_id} assigned to {agent_name} (response: {response_secs}s)")
    return _normalize_row(updated)


def report_case(case_id: str, notes: Optional[str] = "case reported") -> Optional[dict]:
    """Mark case as reported — stays active in /mycases until agent solves it."""
    updated = _db_fetchone(
        """
        UPDATE cases
        SET status = 'reported',
            notes = %s
        WHERE id = %s
        RETURNING *
        """,
        (notes, case_id),
    )
    if not updated:
        logger.warning(f"report_case: case {case_id} not found")
        return None

    logger.info(f"Case {case_id} marked as reported")
    return _normalize_row(updated)


def close_case(case_id: str, notes: Optional[str] = None) -> Optional[dict]:
    row = _db_fetchone("SELECT assigned_at FROM cases WHERE id = %s", (case_id,))
    if not row:
        logger.warning(f"close_case: case {case_id} not found")
        return None

    assigned_dt = row.get("assigned_at")
    if isinstance(assigned_dt, str):
        assigned_dt = _parse_iso(assigned_dt)

    closed_at = now_iso()
    closed_dt = _parse_iso(closed_at)
    resolution_secs = int((closed_dt - assigned_dt).total_seconds()) if (closed_dt and assigned_dt) else None

    updated = _db_fetchone(
        """
        UPDATE cases
        SET closed_at = %s::timestamptz,
            status = 'done',
            notes = %s,
            resolution_secs = %s
        WHERE id = %s
        RETURNING *
        """,
        (closed_at, notes, resolution_secs, case_id),
    )
    if not updated:
        logger.warning(f"close_case: case {case_id} not found")
        return None

    logger.info(f"Case {case_id} closed")
    return _normalize_row(updated)


def mark_missed(case_id: str) -> None:
    _db_execute(
        """
        UPDATE cases
        SET status = 'missed'
        WHERE id = %s AND status = 'open'
        """,
        (case_id,),
    )
    logger.info(f"Case {case_id} marked missed (if it was open)")


# ── Read operations ───────────────────────────────────────────────────────────

def get_case(case_id: str) -> Optional[dict]:
    return _normalize_row(_db_fetchone("SELECT * FROM cases WHERE id = %s", (case_id,)))


def get_cases_for_agent_today(agent_id: int) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)

    rows = _db_fetchall(
        """
        SELECT * FROM cases
        WHERE agent_id = %s
          AND assigned_at >= %s::date
          AND assigned_at < %s::date
        ORDER BY assigned_at ASC
        """,
        (agent_id, today.isoformat(), tomorrow.isoformat()),
    )
    return [_normalize_row(r) for r in rows]


def get_all_cases_for_agent(agent_id: int) -> list[dict]:
    rows = _db_fetchall(
        "SELECT * FROM cases WHERE agent_id = %s ORDER BY opened_at ASC",
        (agent_id,),
    )
    return [_normalize_row(r) for r in rows]


def get_active_case_for_agent(agent_id: int) -> Optional[dict]:
    """Returns the most recent active (assigned or reported) case for this agent."""
    row = _db_fetchone(
        """
        SELECT * FROM cases
        WHERE agent_id = %s
          AND status IN ('assigned', 'reported')
        ORDER BY opened_at DESC
        LIMIT 1
        """,
        (agent_id,),
    )
    return _normalize_row(row)


def get_cases_today() -> list[dict]:
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)

    rows = _db_fetchall(
        """
        SELECT * FROM cases
        WHERE opened_at >= %s::date
          AND opened_at < %s::date
        ORDER BY opened_at ASC
        """,
        (today.isoformat(), tomorrow.isoformat()),
    )
    return [_normalize_row(r) for r in rows]


def get_cases_this_week() -> list[dict]:
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).date()

    rows = _db_fetchall(
        """
        SELECT * FROM cases
        WHERE opened_at >= %s::date
        ORDER BY opened_at ASC
        """,
        (week_start.isoformat(),),
    )
    return [_normalize_row(r) for r in rows]
