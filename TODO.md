# TODO

- [x] Refactor `storage/case_store.py` to strict DB-only mode for Railway (`DATABASE_URL` required).
- [x] Add one-time migration script `scripts/migrate_cases_json_to_postgres.py`.
- [x] Review references and remove legacy entrypoints (`bot_old.py`, `bot_new.py`, `bot_simple.py`) if unused.
- [x] Review/update `railway.json` for clean production startup.
- [x] Add deployment guide `docs/DEPLOYMENT.md` with env vars + migration/run steps.
- [ ] Run critical-path verification commands and fix any issues.
- [ ] Final cleanup pass and summary.
