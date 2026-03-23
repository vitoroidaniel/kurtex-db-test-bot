"""
roles.py — Central role definitions for Kurtex Alert Bot.

Hierarchy (highest → lowest):
  developer   — god mode: manages everyone, all commands
  manager     — manages team_leaders + agents, views reports
  team_leader — manages agents only, views reports
  agent       — receives alerts, handles cases

"super_admin" (legacy DB value) is treated as developer.

Who can add/remove whom:
  developer   → can manage: manager, team_leader, agent
  manager     → can manage: team_leader, agent
  team_leader → can manage: agent
  agent       → cannot manage anyone
"""

ROLE_DEVELOPER   = "developer"
ROLE_MANAGER     = "manager"
ROLE_TEAM_LEADER = "team_leader"
ROLE_AGENT       = "agent"
ROLE_SUPER_ADMIN = "super_admin"   # legacy alias → treated as developer

# Ordered from highest to lowest power
ROLE_HIERARCHY = [ROLE_DEVELOPER, ROLE_MANAGER, ROLE_TEAM_LEADER, ROLE_AGENT]

ROLE_LABELS = {
    ROLE_DEVELOPER:   "Developer",
    ROLE_MANAGER:     "Manager",
    ROLE_TEAM_LEADER: "Team Leader",
    ROLE_AGENT:       "Agent",
    ROLE_SUPER_ADMIN: "Developer",   # legacy display
}

ROLE_ICONS = {
    ROLE_DEVELOPER:   "⚙️",
    ROLE_MANAGER:     "👑",
    ROLE_TEAM_LEADER: "🎯",
    ROLE_AGENT:       "👤",
    ROLE_SUPER_ADMIN: "⚙️",
}

# Which roles each role can assign to new users
MANAGEABLE_ROLES: dict[str, list[str]] = {
    ROLE_DEVELOPER:   [ROLE_MANAGER, ROLE_TEAM_LEADER, ROLE_AGENT],
    ROLE_SUPER_ADMIN: [ROLE_MANAGER, ROLE_TEAM_LEADER, ROLE_AGENT],   # legacy
    ROLE_MANAGER:     [ROLE_TEAM_LEADER, ROLE_AGENT],
    ROLE_TEAM_LEADER: [ROLE_AGENT],
    ROLE_AGENT:       [],
}

# Roles that can add/remove users at all
CAN_MANAGE_USERS = {ROLE_DEVELOPER, ROLE_SUPER_ADMIN, ROLE_MANAGER, ROLE_TEAM_LEADER}

# Roles that can view /report, /leaderboard, /missed
CAN_VIEW_REPORTS = {ROLE_DEVELOPER, ROLE_SUPER_ADMIN, ROLE_MANAGER, ROLE_TEAM_LEADER}

# Roles that see the super-admin Telegram command menu
SUPER_MENU_ROLES = {ROLE_DEVELOPER, ROLE_SUPER_ADMIN, ROLE_MANAGER, ROLE_TEAM_LEADER}


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, "Agent")


def role_icon(role: str) -> str:
    return ROLE_ICONS.get(role, "👤")


def get_manageable_roles(actor_role: str) -> list[str]:
    """Return the list of roles this actor is allowed to assign to others."""
    return MANAGEABLE_ROLES.get(actor_role, [])


def can_manage_users(role: str) -> bool:
    return role in CAN_MANAGE_USERS


def can_view_reports(role: str) -> bool:
    return role in CAN_VIEW_REPORTS


def role_rank(role: str) -> int:
    """Lower number = more powerful. Used for permission comparisons."""
    try:
        return ROLE_HIERARCHY.index(role)
    except ValueError:
        return 99  # unknown role = least powerful


def actor_outranks(actor_role: str, target_role: str) -> bool:
    """True if actor is strictly more powerful than target."""
    return role_rank(actor_role) < role_rank(target_role)
