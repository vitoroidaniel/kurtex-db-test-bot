"""
config.py — All secrets from environment variables (Railway / local .env).

Required env vars:
    BOT_TOKEN           — Telegram bot token
    MONGODB_URI         — MongoDB connection string (from Railway MongoDB plugin)
    DRIVER_GROUP_ID     — Telegram group ID where drivers report issues
    REPORTS_GROUP_ID    — Telegram group ID where daily reports are posted

Optional env vars:
    MONGODB_DB          — Database name (default: kurtex)
    AI_ALERTS_CHANNEL_ID — Channel ID for AI alert forwarding (default: 0)
    KURTEX_WEB_URL      — Crash reporter web URL
    ALERT_SECRET        — Crash reporter secret key
    BOT_NAME            — Bot identifier for crash reporter (default: kurtex-main-bot)
"""

import os
import sys


def _require(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        sys.exit(f"[FATAL] Environment variable '{name}' is not set. "
                 f"Add it in Railway → Variables.")
    return val


def _optional_int(name: str, default: int = 0) -> int:
    val = os.getenv(name, "").strip()
    try:
        return int(val) if val else default
    except ValueError:
        return default


class Config:
    TELEGRAM_TOKEN       = _require("BOT_TOKEN")
    MONGODB_URI          = _require("MONGODB_URI")
    MONGODB_DB           = os.getenv("MONGODB_DB", "kurtex").strip()
    DRIVER_GROUP_ID      = _optional_int("DRIVER_GROUP_ID")
    REPORTS_GROUP_ID     = _optional_int("REPORTS_GROUP_ID")
    AI_ALERTS_CHANNEL_ID = _optional_int("AI_ALERTS_CHANNEL_ID")


config = Config()
