#!/usr/bin/env python3
"""
backup.py — Kurtex Alert Bot local backup tool
===============================================
Exports cases + users from MongoDB to JSON files on your PC.

Usage:
    python backup.py              # one-time backup
    python backup.py --watch      # auto-backup every 6 hours
    python backup.py --restore backup_cases_2026-03-23.json  # restore from file

Output: ./backups/backup_<date>.json

Requires the same env vars as the bot:
    MONGODB_URI  (or falls back to mongodb://localhost:27017/)
    MONGODB_DB   (defaults to kurtex)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("backup")

BACKUP_DIR      = Path(__file__).parent / "backups"
AUTO_INTERVAL_H = 6          # hours between auto-backups in --watch mode
KEEP_BACKUPS    = 30         # keep only the last N backup files


# ── Core backup ───────────────────────────────────────────────────────────────

def run_backup() -> Path:
    from storage.case_store import get_all_cases, get_all_users, health_check

    if not health_check():
        logger.error("MongoDB is not reachable. Backup aborted.")
        sys.exit(1)

    cases = get_all_cases()
    users = get_all_users()

    BACKUP_DIR.mkdir(exist_ok=True)

    stamp    = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_path = BACKUP_DIR / f"backup_{stamp}.json"

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "cases_count": len(cases),
        "users_count": len(users),
        "cases":       cases,
        "users":       users,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"✅  Backup saved → {out_path}  ({len(cases)} cases, {len(users)} users)")
    _prune_old_backups()
    return out_path


def _prune_old_backups():
    files = sorted(BACKUP_DIR.glob("backup_*.json"), key=lambda p: p.stat().st_mtime)
    while len(files) > KEEP_BACKUPS:
        old = files.pop(0)
        old.unlink()
        logger.info(f"Pruned old backup: {old.name}")


# ── Restore ───────────────────────────────────────────────────────────────────

def run_restore(filepath: str):
    from storage.case_store import _get_col, _get_users_col, health_check

    if not health_check():
        logger.error("MongoDB is not reachable. Restore aborted.")
        sys.exit(1)

    path = Path(filepath)
    if not path.exists():
        logger.error(f"File not found: {filepath}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        payload = json.load(f)

    cases = payload.get("cases", [])
    users = payload.get("users", [])

    confirm = input(
        f"\n⚠️  This will UPSERT {len(cases)} cases and {len(users)} users into MongoDB.\n"
        "Existing records with matching IDs will be overwritten.\n"
        "Type YES to continue: "
    ).strip()

    if confirm != "YES":
        logger.info("Restore cancelled.")
        return

    col       = _get_col()
    users_col = _get_users_col()
    restored_cases = 0
    restored_users = 0

    for case in cases:
        if not case.get("id"):
            continue
        col.update_one({"id": case["id"]}, {"$set": case}, upsert=True)
        restored_cases += 1

    for user in users:
        if not user.get("telegram_id"):
            continue
        users_col.update_one({"telegram_id": user["telegram_id"]}, {"$set": user}, upsert=True)
        restored_users += 1

    logger.info(f"✅  Restore complete: {restored_cases} cases, {restored_users} users upserted.")


# ── Summary of latest backup ──────────────────────────────────────────────────

def show_latest():
    files = sorted(BACKUP_DIR.glob("backup_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("No backups found in ./backups/")
        return
    latest = files[0]
    with open(latest, encoding="utf-8") as f:
        data = json.load(f)
    print(f"\nLatest backup: {latest.name}")
    print(f"  Exported at : {data.get('exported_at', '?')}")
    print(f"  Cases       : {data.get('cases_count', '?')}")
    print(f"  Users       : {data.get('users_count', '?')}")
    print(f"  File size   : {latest.stat().st_size / 1024:.1f} KB\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Kurtex Bot — MongoDB backup tool")
    parser.add_argument("--watch",   action="store_true", help=f"Auto-backup every {AUTO_INTERVAL_H}h")
    parser.add_argument("--restore", metavar="FILE",      help="Restore from a backup JSON file")
    parser.add_argument("--latest",  action="store_true", help="Show info about the latest backup")
    args = parser.parse_args()

    if args.latest:
        show_latest()
        return

    if args.restore:
        run_restore(args.restore)
        return

    if args.watch:
        logger.info(f"Watch mode: backing up every {AUTO_INTERVAL_H} hours. Ctrl+C to stop.")
        while True:
            try:
                run_backup()
            except Exception as e:
                logger.error(f"Backup failed: {e}")
            time.sleep(AUTO_INTERVAL_H * 3600)
    else:
        run_backup()


if __name__ == "__main__":
    main()
