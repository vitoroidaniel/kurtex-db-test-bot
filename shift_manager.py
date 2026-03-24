"""
shift_manager.py — User and shift helpers backed entirely by MongoDB.

shifts.py has been removed. All user data lives in the DB.
MAIN_ADMIN_ID / SUPER_ADMINS are only used as fallback when DB is unreachable.
"""

from datetime import datetime, time
import zoneinfo

# ── Constants (formerly in shifts.py) ────────────────────────────────────────

TIMEZONE = "America/New_York"

MAIN_ADMIN_ID = (8422260316, 7808593054, 7769230456, 1401145589, )
SUPER_ADMINS = {1615926408}

SHIFTS = [
    {"name": "Morning",   "start": time(6, 0),  "end": time(14, 0), "days": [0,1,2,3,4]},
    {"name": "Afternoon", "start": time(14, 0), "end": time(22, 0), "days": [0,1,2,3,4]},
    {"name": "Night",     "start": time(22, 0), "end": time(6, 0),  "days": [0,1,2,3,4,5,6]},
    {"name": "Weekend",   "start": time(8, 0),  "end": time(20, 0), "days": [5,6]},
]


def _now_in_tz():
    try:
        tz = zoneinfo.ZoneInfo(TIMEZONE)
    except Exception:
        tz = zoneinfo.ZoneInfo("America/New_York")
    return datetime.now(tz)


def _in_shift(shift: dict, weekday: int, now_time: time) -> bool:
    if weekday not in shift["days"]:
        return False
    s, e = shift["start"], shift["end"]
    if s <= e:
        return s <= now_time < e
    return now_time >= s or now_time < e


def get_current_shift_name() -> str:
    now     = _now_in_tz()
    t       = now.time().replace(second=0, microsecond=0)
    weekday = now.weekday()
    for shift in SHIFTS:
        if _in_shift(shift, weekday, t):
            return shift["name"]
    return "Off Hours"


def _all_users() -> list:
    try:
        from storage.case_store import get_all_users
        return get_all_users()
    except Exception:
        return []


def get_on_shift_admins() -> list:
    return [
        {"id": u["telegram_id"], "name": u.get("name", f"User {u['telegram_id']}"), "username": u.get("username", "")}
        for u in _all_users()
    ]


def get_all_admins() -> list:
    return get_on_shift_admins()


def is_known_user(telegram_id: int) -> bool:
    try:
        from storage.case_store import is_agent
        return is_agent(telegram_id)
    except Exception:
        return telegram_id in SUPER_ADMINS or telegram_id in MAIN_ADMIN_ID


def is_super_admin(telegram_id: int) -> bool:
    try:
        from storage.case_store import get_user_role
        from roles import CAN_VIEW_REPORTS
        return get_user_role(telegram_id) in CAN_VIEW_REPORTS
    except Exception:
        return telegram_id in SUPER_ADMINS


def get_user_role(telegram_id: int) -> str:
    if telegram_id in SUPER_ADMINS:
        return "developer"
    try:
        from storage.case_store import get_user_role as db_role
        return db_role(telegram_id)
    except Exception:
        return "agent"