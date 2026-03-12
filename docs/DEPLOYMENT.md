# Railway Production Deployment

## 1) Required environment variables

Set these in Railway service variables:

- `BOT_TOKEN`
- `DRIVER_GROUP_ID`
- `REPORTS_GROUP_ID`
- `DATABASE_URL` (from Railway PostgreSQL plugin)

Optional:
- `AI_ALERTS_CHANNEL_ID`
- `WEBHOOK_URL`
- `WEBHOOK_SECRET`
- `WEBHOOK_SECRET_TOKEN`
- `ALERT_SECRET`

## 2) Install dependencies

Dependencies are in `requirements.txt`, including PostgreSQL client libs:
- `psycopg[binary]`
- `psycopg-pool`

## 3) One-time migration (if you previously used JSON storage)

If `data/cases.json` contains historical cases, run once:

```bash
python scripts/migrate_cases_json_to_postgres.py
```

This upserts JSON cases into PostgreSQL `cases` table.

## 4) Start command

Railway uses:

```bash
python bot.py
```

(`railway.json` already points to this.)

## 5) Storage model

`storage/case_store.py` is PostgreSQL-only in production mode:
- requires `DATABASE_URL`
- initializes schema automatically
- all commands/handlers read/write the same DB source of truth

## 6) Operational notes

- Ensure Railway Postgres is attached and `DATABASE_URL` is present before deploy.
- If `DATABASE_URL` is missing, bot startup fails by design (prevents silent file fallback / split data).
