"""
handlers/admin_handler.py

Admin commands:
  /report      — daily summary (team_leader, manager, developer)
  /leaderboard — top agents this week (team_leader, manager, developer)
  /missed      — unhandled alerts today (team_leader, manager, developer)
"""

import logging
from collections import defaultdict
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import TelegramError

from storage.case_store import get_cases_today, get_cases_this_week, get_user_role
from shift_manager import is_super_admin, is_known_user
from roles import can_view_reports

logger  = logging.getLogger(__name__)
BOT_NAME = "Kurtex Alert Bot"


def _is_main_admin(user_id: int) -> bool:
    """True for team_leader, manager, developer."""
    try:
        return can_view_reports(get_user_role(user_id))
    except Exception:
        return is_super_admin(user_id)


def _is_admin(user_id: int) -> bool:
    return is_known_user(user_id)


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M")
    except Exception:
        return iso[:16]


def _build_daily_report(cases: list[dict], title: str) -> str:
    total    = len(cases)
    assigned = [c for c in cases if c["status"] in ("assigned", "done")]
    done     = [c for c in cases if c["status"] == "done"]
    missed   = [c for c in cases if c["status"] == "missed"]
    open_    = [c for c in cases if c["status"] == "open"]

    agent_counts = defaultdict(int)
    for c in assigned:
        if c.get("agent_name"):
            agent_counts[c["agent_name"]] += 1

    lines = [
        f"*{title}*\n",
        f"Total Alerts: {total}",
        f"Assigned: {len(assigned)}",
        f"Resolved: {len(done)}",
        f"Missed: {len(missed)}",
        f"Open: {len(open_)}",
    ]

    if agent_counts:
        lines.append("\n*Agent Activity:*")
        for agent, count in sorted(agent_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {agent}: {count} case(s)")

    if missed:
        lines.append("\n*Unresolved Alerts:*")
        for c in missed:
            lines.append(f"  {_fmt_dt(c.get('opened_at'))} — {c['driver_name']} ({c['group_name']})")

    return "\n".join(lines)


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_main_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    cases  = get_cases_today()
    today  = datetime.now().strftime("%B %d, %Y")
    report = _build_daily_report(cases, f"Daily Report — {today}")
    await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)


async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_main_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    cases = get_cases_this_week()
    if not cases:
        await update.message.reply_text("No activity recorded this week yet.")
        return
    agent_stats = defaultdict(lambda: {"count": 0})
    for c in cases:
        if c.get("agent_name") and c["status"] in ("assigned", "done"):
            agent_stats[c["agent_name"]]["count"] += 1
    if not agent_stats:
        await update.message.reply_text("No assigned cases this week.")
        return
    sorted_agents = sorted(agent_stats.items(), key=lambda x: -x[1]["count"])
    medals = ["🥇", "🥈", "🥉"]
    lines  = ["*Weekly Leaderboard*\n"]
    for i, (name, stats) in enumerate(sorted_agents):
        medal = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{medal} {name}: {stats['count']} cases")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_missed(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_main_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    cases  = get_cases_today()
    missed = [c for c in cases if c["status"] == "missed"]
    if not missed:
        await update.message.reply_text("All alerts handled today. Great job!")
        return
    lines = [f"*Missed Alerts — {len(missed)} today*\n"]
    for c in missed:
        lines.append(f"{_fmt_dt(c.get('opened_at'))} — {c['driver_name']}")
        lines.append(f"   {c['group_name']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def send_daily_report(bot, chat_id: int) -> None:
    cases  = get_cases_today()
    today  = datetime.now().strftime("%B %d, %Y")
    report = _build_daily_report(cases, f"End of Day Report — {today}")
    try:
        await bot.send_message(chat_id, report, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Daily report sent to {chat_id}")
    except TelegramError as e:
        logger.error(f"Failed to send daily report: {e}")
