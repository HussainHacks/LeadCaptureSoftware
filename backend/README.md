# Backend

FastAPI backend for the HVAC Lead Conversion Platform. See the
[root README](../README.md) for the full quick start.

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir src --reload --port 8000
uv run pytest   # needs Postgres and Redis running (see docker-compose)
```

Layout: `src/app/` holds the application (`api`, `core`, `models`, `schemas`,
`repositories`, `services`), `alembic/` the database migrations, and `tests/`
the pytest suite.
