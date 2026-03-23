"""
handlers/user_handler.py

User management commands — available to developer, manager, team_leader.
Each role can only add/remove users of lower rank than themselves.

Commands:
  /manageusers  — show all users + management menu
  /adduser      — add a user (forward msg or type ID)
  /removeuser   — remove user by Telegram ID
  /listusers    — list all users
  /changerole   — change an existing user's role
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from storage.case_store import get_all_users, get_user, upsert_user, remove_user, get_user_role
from roles import (
    role_label, role_icon, get_manageable_roles, can_manage_users,
    ROLE_HIERARCHY, ROLE_LABELS, ROLE_ICONS,
)

logger = logging.getLogger(__name__)


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_actor_role(user_id: int) -> str:
    return get_user_role(user_id)


def _can_manage(user_id: int) -> bool:
    return can_manage_users(_get_actor_role(user_id))


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_user(u: dict) -> str:
    role     = u.get("role", "agent")
    icon     = role_icon(role)
    name     = u.get("name", "—")
    username = f"@{u['username']}" if u.get("username") else "no username"
    tid      = u.get("telegram_id", "?")
    label    = role_label(role)
    return f"{icon} *{name}* ({username})\n   ID: `{tid}` · {label}"


def _build_user_list() -> str:
    users = get_all_users()
    if not users:
        return "No users in database yet."

    sections = {}
    for role in ROLE_HIERARCHY:
        sections[role] = []

    for u in users:
        role = u.get("role", "agent")
        # legacy super_admin → show under developer
        if role == "super_admin":
            role = "developer"
        bucket = sections.get(role, sections["agent"])
        bucket.append(u)

    lines = []
    for role in ROLE_HIERARCHY:
        bucket = sections[role]
        if bucket:
            lines.append(f"\n*{role_icon(role)} {role_label(role)}s*")
            for u in bucket:
                lines.append(_fmt_user(u))

    return "\n".join(lines).strip()


def _manage_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add User",     callback_data="mu_add")],
        [InlineKeyboardButton("🔄 Change Role",  callback_data="mu_changerole_list")],
        [InlineKeyboardButton("🗑 Remove User",  callback_data="mu_remove_list")],
        [InlineKeyboardButton("🔃 Refresh",      callback_data="mu_refresh")],
    ])


def _role_kb(actor_role: str) -> InlineKeyboardMarkup:
    """Show only roles this actor is allowed to assign."""
    assignable = get_manageable_roles(actor_role)
    rows = []
    for role in assignable:
        rows.append([InlineKeyboardButton(
            f"{role_icon(role)} {role_label(role)}",
            callback_data=f"mu_role|{role}"
        )])
    return InlineKeyboardMarkup(rows)


def _changerole_kb(actor_role: str, target_id: int) -> InlineKeyboardMarkup:
    """Show role options when changing an existing user's role."""
    assignable = get_manageable_roles(actor_role)
    rows = []
    for role in assignable:
        rows.append([InlineKeyboardButton(
            f"{role_icon(role)} {role_label(role)}",
            callback_data=f"mu_setrole|{target_id}|{role}"
        )])
    rows.append([InlineKeyboardButton("↩️ Back", callback_data="mu_back")])
    return InlineKeyboardMarkup(rows)


def _pick_user_kb(users: list[dict], action_prefix: str) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        label = f"{role_icon(u.get('role','agent'))} {u['name']} · {role_label(u.get('role','agent'))}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{action_prefix}|{u['telegram_id']}")])
    rows.append([InlineKeyboardButton("↩️ Back", callback_data="mu_back")])
    return InlineKeyboardMarkup(rows)


def _confirm_remove_kb(tid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, remove", callback_data=f"mu_rm_confirm|{tid}"),
        InlineKeyboardButton("❌ Cancel",      callback_data="mu_back"),
    ]])


def _manageable_users(actor_role: str) -> list[dict]:
    """Return only users whose role is lower than the actor's."""
    from roles import role_rank
    actor_rank = role_rank(actor_role)
    return [
        u for u in get_all_users()
        if role_rank(u.get("role", "agent")) > actor_rank
    ]


# ── /manageusers ──────────────────────────────────────────────────────────────

async def cmd_manageusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _can_manage(update.effective_user.id):
        await update.message.reply_text("⛔ You don't have permission to manage users.")
        return
    text = _build_user_list()
    await update.message.reply_text(
        f"{text}\n\n*What would you like to do?*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_manage_kb(),
    )


# ── /listusers ────────────────────────────────────────────────────────────────

async def cmd_listusers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _can_manage(update.effective_user.id):
        await update.message.reply_text("⛔ You don't have permission to view users.")
        return
    await update.message.reply_text(_build_user_list(), parse_mode=ParseMode.MARKDOWN)


# ── /removeuser <id> ──────────────────────────────────────────────────────────

async def cmd_removeuser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    actor_role = _get_actor_role(update.effective_user.id)
    if not can_manage_users(actor_role):
        await update.message.reply_text("⛔ You don't have permission to remove users.")
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: /removeuser <telegram_id>")
        return
    try:
        tid = int(args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID.")
        return
    u = get_user(tid)
    if not u:
        await update.message.reply_text(f"No user with ID `{tid}` found.", parse_mode=ParseMode.MARKDOWN)
        return
    from roles import role_rank
    if role_rank(u.get("role", "agent")) <= role_rank(actor_role):
        await update.message.reply_text("⛔ You can only remove users with a lower role than yours.")
        return
    await update.message.reply_text(
        f"Remove *{u['name']}* ({role_label(u.get('role','agent'))})?\n\nThis will revoke their bot access.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_confirm_remove_kb(tid),
    )


# ── /adduser shortcut ─────────────────────────────────────────────────────────

async def cmd_adduser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _can_manage(update.effective_user.id):
        await update.message.reply_text("⛔ You don't have permission to add users.")
        return
    ctx.user_data["adding_user"] = {}
    ctx.user_data["mu_adding"]   = True
    await update.message.reply_text(
        "➕ *Add User*\n\n"
        "Forward a message from the user, or type their Telegram ID.\n\n"
        "Send /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /changerole shortcut ──────────────────────────────────────────────────────

async def cmd_changerole(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    actor_role = _get_actor_role(update.effective_user.id)
    if not can_manage_users(actor_role):
        await update.message.reply_text("⛔ You don't have permission to change roles.")
        return
    targets = _manageable_users(actor_role)
    if not targets:
        await update.message.reply_text("No users available to change role.")
        return
    await update.message.reply_text(
        "🔄 *Change Role*\n\nSelect a user:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_pick_user_kb(targets, "mu_changerole"),
    )


# ── Callback handler ──────────────────────────────────────────────────────────

async def cb_manage(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query      = update.callback_query
    await query.answer()
    actor_id   = update.effective_user.id
    actor_role = _get_actor_role(actor_id)

    if not can_manage_users(actor_role):
        await query.answer("⛔ No permission.", show_alert=True)
        return

    data = query.data

    # ── Refresh / Back ────────────────────────────────────────────────────────
    if data in ("mu_refresh", "mu_back"):
        text = _build_user_list()
        await query.edit_message_text(
            f"{text}\n\n*What would you like to do?*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_manage_kb(),
        )
        return

    # ── Start add-user flow ───────────────────────────────────────────────────
    if data == "mu_add":
        ctx.user_data["adding_user"] = {}
        ctx.user_data["mu_adding"]   = True
        await query.edit_message_text(
            "➕ *Add User*\n\n"
            "Forward a message from the user you want to add, "
            "or type their Telegram ID manually.\n\n"
            "Send /cancel to abort.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── Remove — show list ────────────────────────────────────────────────────
    if data == "mu_remove_list":
        targets = _manageable_users(actor_role)
        if not targets:
            await query.edit_message_text("No users available to remove.", reply_markup=_manage_kb())
            return
        await query.edit_message_text(
            "🗑 *Remove User*\n\nSelect a user:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_pick_user_kb(targets, "mu_rm"),
        )
        return

    # ── Remove — confirm ──────────────────────────────────────────────────────
    if data.startswith("mu_rm|"):
        from roles import role_rank
        tid = int(data.split("|")[1])
        u   = get_user(tid)
        if not u:
            await query.edit_message_text("User not found.", reply_markup=_manage_kb())
            return
        if role_rank(u.get("role", "agent")) <= role_rank(actor_role):
            await query.answer("⛔ Can't remove a user with equal or higher role.", show_alert=True)
            return
        await query.edit_message_text(
            f"Remove *{u['name']}* ({role_label(u.get('role','agent'))})?\n\nThis will revoke their bot access.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_confirm_remove_kb(tid),
        )
        return

    # ── Remove — confirmed ────────────────────────────────────────────────────
    if data.startswith("mu_rm_confirm|"):
        from roles import role_rank
        tid  = int(data.split("|")[1])
        u    = get_user(tid)
        name = u["name"] if u else str(tid)
        if u and role_rank(u.get("role", "agent")) <= role_rank(actor_role):
            await query.answer("⛔ Can't remove a user with equal or higher role.", show_alert=True)
            return
        removed = remove_user(tid)
        text    = _build_user_list()
        if removed:
            await query.edit_message_text(
                f"✅ *{name}* removed.\n\n{text}\n\n*What would you like to do?*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_manage_kb(),
            )
        else:
            await query.edit_message_text("User not found.", reply_markup=_manage_kb())
        return

    # ── Change role — show user list ──────────────────────────────────────────
    if data == "mu_changerole_list":
        targets = _manageable_users(actor_role)
        if not targets:
            await query.edit_message_text("No users available to change.", reply_markup=_manage_kb())
            return
        await query.edit_message_text(
            "🔄 *Change Role*\n\nSelect a user:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_pick_user_kb(targets, "mu_changerole"),
        )
        return

    # ── Change role — pick user, then show role options ───────────────────────
    if data.startswith("mu_changerole|"):
        tid = int(data.split("|")[1])
        u   = get_user(tid)
        if not u:
            await query.edit_message_text("User not found.", reply_markup=_manage_kb())
            return
        await query.edit_message_text(
            f"🔄 *Change role for {u['name']}*\n\nCurrent: {role_label(u.get('role','agent'))}\n\nSelect new role:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_changerole_kb(actor_role, tid),
        )
        return

    # ── Change role — apply ───────────────────────────────────────────────────
    if data.startswith("mu_setrole|"):
        from roles import role_rank
        _, tid_str, new_role = data.split("|")
        tid = int(tid_str)
        u   = get_user(tid)
        if not u:
            await query.edit_message_text("User not found.", reply_markup=_manage_kb())
            return
        if new_role not in get_manageable_roles(actor_role):
            await query.answer("⛔ You can't assign that role.", show_alert=True)
            return
        upsert_user(tid, u["name"], u.get("username"), new_role)
        text = _build_user_list()
        await query.edit_message_text(
            f"✅ *{u['name']}* is now *{role_label(new_role)}*.\n\n{text}\n\n*What would you like to do?*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_manage_kb(),
        )
        return

    # ── Role selection (during add flow) ─────────────────────────────────────
    if data.startswith("mu_role|"):
        new_role = data.split("|")[1]
        if new_role not in get_manageable_roles(actor_role):
            await query.answer("⛔ You can't assign that role.", show_alert=True)
            return
        info = ctx.user_data.get("adding_user", {})
        info["role"] = new_role
        tid      = info.get("telegram_id")
        name     = info.get("name", "Unknown")
        username = info.get("username")
        upsert_user(tid, name, username, new_role)
        ctx.user_data.pop("adding_user", None)
        ctx.user_data.pop("mu_adding",   None)
        text = _build_user_list()
        await query.edit_message_text(
            f"✅ *{name}* added as *{role_label(new_role)}*.\n\n{text}\n\n*What would you like to do?*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_manage_kb(),
        )
        return


# ── Message handlers (used during add-user flow) ──────────────────────────────

async def recv_add_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("mu_adding"):
        return
    actor_role = _get_actor_role(update.effective_user.id)
    if not can_manage_users(actor_role):
        return

    msg  = update.message
    info = ctx.user_data.setdefault("adding_user", {})

    if msg.forward_origin:
        origin = msg.forward_origin
        if hasattr(origin, "sender_user") and origin.sender_user:
            u = origin.sender_user
            info["telegram_id"] = u.id
            info["name"]        = f"{u.first_name} {u.last_name or ''}".strip()
            info["username"]    = u.username or ""
        else:
            await msg.reply_text(
                "⚠️ Couldn't extract user from that forward (private account?). "
                "Please send their Telegram ID as a number instead."
            )
            return
    elif msg.text and msg.text.strip().lstrip("-").isdigit():
        tid      = int(msg.text.strip())
        existing = get_user(tid)
        info["telegram_id"] = tid
        if existing:
            info["name"]     = existing["name"]
            info["username"] = existing.get("username", "")
        else:
            info["name"]     = f"User {tid}"
            info["username"] = ""
    else:
        await msg.reply_text(
            "Please forward a message from the user or send their numeric Telegram ID.\n"
            "Send /cancel to abort."
        )
        return

    if not info.get("name") or info["name"].startswith("User "):
        ctx.user_data["mu_await_name"] = True
        await msg.reply_text(
            f"Got ID `{info['telegram_id']}`. What's their name?",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Show only roles this actor can assign
    assignable = get_manageable_roles(actor_role)
    if not assignable:
        await msg.reply_text("⛔ You have no roles available to assign.")
        ctx.user_data.pop("adding_user", None)
        ctx.user_data.pop("mu_adding",   None)
        return

    await msg.reply_text(
        f"Adding *{info['name']}* (ID: `{info['telegram_id']}`)\n\nSelect their role:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_role_kb(actor_role),
    )


async def recv_add_user_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("mu_adding") or not ctx.user_data.get("mu_await_name"):
        return
    actor_role = _get_actor_role(update.effective_user.id)
    if not can_manage_users(actor_role):
        return
    name = update.message.text.strip()
    ctx.user_data["adding_user"]["name"] = name
    ctx.user_data.pop("mu_await_name", None)
    info = ctx.user_data["adding_user"]
    await update.message.reply_text(
        f"Adding *{name}* (ID: `{info['telegram_id']}`)\n\nSelect their role:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_role_kb(actor_role),
    )


async def cmd_cancel_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("adding_user",   None)
    ctx.user_data.pop("mu_adding",     None)
    ctx.user_data.pop("mu_await_name", None)
    await update.message.reply_text("Cancelled.")
