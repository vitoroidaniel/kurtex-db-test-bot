"""
storage/case_store.py  —  MongoDB backend

Collections:
  cases  — alert/case records
  users  — registered users with roles
"""

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger(__name__)

_client: Optional[MongoClient] = None
_db     = None
_lock   = threading.Lock()


def _get_db():
    global _client, _db
    if _db is not None:
        return _db
    with _lock:
        if _db is not None:
            return _db
        uri     = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        db_name = os.getenv("MONGODB_DB", "kurtex")
        _client = MongoClient(
            uri,
            maxPoolSize=10,
            minPoolSize=1,
            serverSelectionTimeoutMS=8_000,
            connectTimeoutMS=8_000,
            socketTimeoutMS=15_000,
            retryWrites=True,
            retryReads=True,
        )
        try:
            _client.admin.command("ping")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"MongoDB connection failed: {e}")
            raise
        database = _client[db_name]

        # Create indexes on first connect
        cases_col = database["cases"]
        cases_col.create_index("id",        unique=True)
        cases_col.create_index("status")
        cases_col.create_index("agent_id")
        cases_col.create_index([("opened_at",   DESCENDING)])
        cases_col.create_index([("agent_id",    ASCENDING), ("assigned_at", DESCENDING)])

        users_col = database["users"]
        users_col.create_index("telegram_id", unique=True)
        users_col.create_index("role")

        _db = database
        logger.info(f"MongoDB connected → {db_name}")
        return _db


def _cases() -> Collection:
    return _get_db()["cases"]


def _users() -> Collection:
    return _get_db()["users"]


def health_check() -> bool:
    try:
        _get_db().client.admin.command("ping")
        return True
    except Exception as e:
        logger.warning(f"MongoDB health check failed: {e}")
        return False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip(doc: Optional[dict]) -> Optional[dict]:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


# ── Cases ─────────────────────────────────────────────────────────────────────

def create_case(case_id, driver_name, driver_username, group_name, description) -> dict:
    case = {
        "id":              case_id,
        "driver_name":     driver_name,
        "driver_username": driver_username,
        "group_name":      group_name,
        "description":     description,
        "opened_at":       now_iso(),
        "assigned_at":     None,
        "closed_at":       None,
        "agent_id":        None,
        "agent_name":      None,
        "agent_username":  None,
        "status":          "open",
        "notes":           None,
        "resolution_secs": None,
    }
    _cases().insert_one(case)
    case.pop("_id", None)
    logger.info(f"Case {case_id} created")
    return case


def assign_case(case_id, agent_id, agent_name, agent_username) -> Optional[dict]:
    col  = _cases()
    case = _strip(col.find_one({"id": case_id}))
    if not case:
        logger.warning(f"assign_case: case {case_id} not found")
        return None
    assigned_at = now_iso()
    update = {
        "assigned_at":    assigned_at,
        "agent_id":       agent_id,
        "agent_name":     agent_name,
        "agent_username": agent_username,
        "status":         "assigned",
    }
    col.update_one({"id": case_id}, {"$set": update})
    case.update(update)
    logger.info(f"Case {case_id} assigned to {agent_name}")
    return case


def report_case(case_id, notes="case reported") -> Optional[dict]:
    result = _cases().find_one_and_update(
        {"id": case_id},
        {"$set": {"status": "reported", "notes": notes}},
        return_document=True,
    )
    if result is None:
        logger.warning(f"report_case: case {case_id} not found")
        return None
    logger.info(f"Case {case_id} marked as reported")
    return _strip(result)


def close_case(case_id, notes=None) -> Optional[dict]:
    col  = _cases()
    case = _strip(col.find_one({"id": case_id}))
    if not case:
        logger.warning(f"close_case: case {case_id} not found")
        return None
    closed_at       = now_iso()
    resolution_secs = None
    if case.get("assigned_at"):
        try:
            a = datetime.fromisoformat(case["assigned_at"])
            c = datetime.fromisoformat(closed_at)
            if a.tzinfo is None:
                a = a.replace(tzinfo=timezone.utc)
            if c.tzinfo is None:
                c = c.replace(tzinfo=timezone.utc)
            resolution_secs = int((c - a).total_seconds())
        except Exception:
            pass
    update = {
        "closed_at":       closed_at,
        "status":          "done",
        "notes":           notes,
        "resolution_secs": resolution_secs,
    }
    col.update_one({"id": case_id}, {"$set": update})
    case.update(update)
    logger.info(f"Case {case_id} closed")
    return case


def mark_missed(case_id) -> None:
    result = _cases().update_one(
        {"id": case_id, "status": "open"},
        {"$set": {"status": "missed"}},
    )
    if result.modified_count:
        logger.info(f"Case {case_id} marked missed")


def delete_case(case_id) -> bool:
    result = _cases().delete_one({"id": case_id})
    if result.deleted_count:
        logger.info(f"Case {case_id} permanently deleted")
        return True
    return False


def get_case(case_id) -> Optional[dict]:
    return _strip(_cases().find_one({"id": case_id}))


def get_cases_for_agent_today(agent_id) -> list:
    today  = datetime.now(timezone.utc).date().isoformat()
    cursor = _cases().find(
        {"agent_id": agent_id, "assigned_at": {"$gte": today}},
        sort=[("assigned_at", DESCENDING)],
    )
    return [_strip(c) for c in cursor]


def get_all_cases_for_agent(agent_id) -> list:
    cursor = _cases().find(
        {"agent_id": agent_id},
        sort=[("assigned_at", DESCENDING)],
    )
    return [_strip(c) for c in cursor]


def get_active_case_for_agent(agent_id) -> Optional[dict]:
    doc = _cases().find_one(
        {"agent_id": agent_id, "status": {"$in": ["assigned", "reported"]}},
        sort=[("assigned_at", DESCENDING)],
    )
    return _strip(doc)


def get_cases_today() -> list:
    today  = datetime.now(timezone.utc).date().isoformat()
    cursor = _cases().find(
        {"opened_at": {"$gte": today}},
        sort=[("opened_at", DESCENDING)],
    )
    return [_strip(c) for c in cursor]


def get_cases_this_week() -> list:
    from datetime import timedelta
    now   = datetime.now(timezone.utc)
    start = (now - timedelta(days=now.weekday())).date().isoformat()
    cursor = _cases().find(
        {"opened_at": {"$gte": start}},
        sort=[("opened_at", DESCENDING)],
    )
    return [_strip(c) for c in cursor]


def get_all_cases(limit: int = 0) -> list:
    cursor = _cases().find({}, sort=[("opened_at", DESCENDING)])
    if limit:
        cursor = cursor.limit(limit)
    return [_strip(c) for c in cursor]


# ── Users ─────────────────────────────────────────────────────────────────────

def get_all_users() -> list:
    return [_strip(u) for u in _users().find({}, sort=[("name", 1)])]


def get_user(telegram_id) -> Optional[dict]:
    return _strip(_users().find_one({"telegram_id": telegram_id}))


def get_users_by_role(role) -> list:
    return [_strip(u) for u in _users().find({"role": role}, sort=[("name", 1)])]


def upsert_user(telegram_id, name, username, role="agent") -> dict:
    doc = {
        "telegram_id": telegram_id,
        "name":        name,
        "username":    username or "",
        "role":        role,
        "added_at":    now_iso(),
    }
    _users().update_one(
        {"telegram_id": telegram_id},
        {"$set": doc},
        upsert=True,
    )
    logger.info(f"User upserted: {name} ({telegram_id}) role={role}")
    return doc


def remove_user(telegram_id) -> bool:
    result = _users().delete_one({"telegram_id": telegram_id})
    return result.deleted_count > 0


def get_user_role(telegram_id) -> str:
    u = get_user(telegram_id)
    return u.get("role", "agent") if u else "agent"


def is_agent(telegram_id) -> bool:
    return get_user(telegram_id) is not None


def is_super_admin(telegram_id) -> bool:
    from roles import CAN_VIEW_REPORTS
    u = get_user(telegram_id)
    if not u:
        return False
    return u.get("role") in CAN_VIEW_REPORTS


def mark_user_started(telegram_id) -> None:
    """Mark that a user has sent /start — tracked in DB, no file needed."""
    _users().update_one(
        {"telegram_id": telegram_id},
        {"$set": {"started": True}},
    )
