"""
One-time migration utility:
- Reads local JSON cases from data/cases.json
- Upserts into PostgreSQL cases table (DATABASE_URL required)

Usage:
  python scripts/migrate_cases_json_to_postgres.py
"""

import json
import os
from pathlib import Path

from psycopg_pool import ConnectionPool

BASE_DIR = Path(__file__).resolve().parent.parent
CASES_FILE = BASE_DIR / "data" / "cases.json"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required for migration.")


def main() -> None:
    if not CASES_FILE.exists():
        print(f"No file found at {CASES_FILE}. Nothing to migrate.")
        return

    raw = CASES_FILE.read_text()
    cases = json.loads(raw)
    if not isinstance(cases, list):
        raise RuntimeError("Invalid JSON format: expected a list of case objects.")

    conninfo = DATABASE_URL
    if "sslmode=" not in conninfo:
        sep = "&" if "?" in conninfo else "?"
        conninfo = f"{conninfo}{sep}sslmode=require"

    pool = ConnectionPool(conninfo=conninfo, min_size=1, max_size=3, timeout=15)

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

    insert_sql = """
    INSERT INTO cases (
        id, driver_name, driver_username, group_name, description,
        opened_at, assigned_at, closed_at,
        agent_id, agent_name, agent_username,
        status, notes, response_secs, resolution_secs
    )
    VALUES (
        %(id)s, %(driver_name)s, %(driver_username)s, %(group_name)s, %(description)s,
        %(opened_at)s::timestamptz, %(assigned_at)s::timestamptz, %(closed_at)s::timestamptz,
        %(agent_id)s, %(agent_name)s, %(agent_username)s,
        %(status)s, %(notes)s, %(response_secs)s, %(resolution_secs)s
    )
    ON CONFLICT (id) DO UPDATE SET
        driver_name = EXCLUDED.driver_name,
        driver_username = EXCLUDED.driver_username,
        group_name = EXCLUDED.group_name,
        description = EXCLUDED.description,
        opened_at = EXCLUDED.opened_at,
        assigned_at = EXCLUDED.assigned_at,
        closed_at = EXCLUDED.closed_at,
        agent_id = EXCLUDED.agent_id,
        agent_name = EXCLUDED.agent_name,
        agent_username = EXCLUDED.agent_username,
        status = EXCLUDED.status,
        notes = EXCLUDED.notes,
        response_secs = EXCLUDED.response_secs,
        resolution_secs = EXCLUDED.resolution_secs
    """

    migrated = 0
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
            for case in cases:
                payload = {
                    "id": case.get("id"),
                    "driver_name": case.get("driver_name"),
                    "driver_username": case.get("driver_username"),
                    "group_name": case.get("group_name"),
                    "description": case.get("description"),
                    "opened_at": case.get("opened_at"),
                    "assigned_at": case.get("assigned_at"),
                    "closed_at": case.get("closed_at"),
                    "agent_id": case.get("agent_id"),
                    "agent_name": case.get("agent_name"),
                    "agent_username": case.get("agent_username"),
                    "status": case.get("status") or "open",
                    "notes": case.get("notes"),
                    "response_secs": case.get("response_secs"),
                    "resolution_secs": case.get("resolution_secs"),
                }
                if not payload["id"] or not payload["driver_name"] or not payload["group_name"] or not payload["description"] or not payload["opened_at"]:
                    continue
                cur.execute(insert_sql, payload)
                migrated += 1
        conn.commit()

    print(f"Migration finished. Upserted {migrated} case(s).")


if __name__ == "__main__":
    main()
