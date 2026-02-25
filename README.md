# Django Auth Core API Starter

API-first Django starter for front-end/back-end separation. The Django project root remains in `backend/`, and future domain apps can live under `backend/apps/`.

## Requirements

- macOS (recommended)
- Python 3.11+
- Homebrew

## Quick start (one command flow)

```bash
make install
cp .env.example .env
make migrate
make run
```

Server runs at `http://127.0.0.1:8000/`.

## Dependency management

Install dependencies via pinned requirements:

```bash
pip install -r requirements.txt
```

## Environment variables

1. Copy template:

```bash
cp .env.example .env
```

2. Adjust as needed.

Minimum supported fields:

- `DEBUG`
- `SECRET_KEY`
- `ALLOWED_HOSTS`
- `DATABASE_URL` or `DB_ENGINE`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`
- `REDIS_URL`

By default, SQLite is used for local bootstrapping. Set `DATABASE_URL` (or `DB_*`) to switch to Postgres.

## macOS + Homebrew: minimal Postgres/Redis setup

```bash
brew update
brew install postgresql@16 redis
brew services start postgresql@16
brew services start redis
createdb django_auth_core
```

Example `.env` Postgres setting:

```env
DATABASE_URL=postgresql://$USER@127.0.0.1:5432/django_auth_core
REDIS_URL=redis://127.0.0.1:6379/0
```

## Makefile commands

- `make venv` - create virtual environment in `.venv`
- `make install` - create venv and install dependencies
- `make migrate` - run migrations
- `make run` - start development server
- `make test` - run test suite
- `make check` - run Django system checks

## Project structure

```text
backend/
  manage.py
  config/
  apps/
```

## Notes

- `.venv/` and `.env` are ignored by git and must stay local only.
- This starter includes DRF, SimpleJWT, CORS, dotenv support, and psycopg for Postgres.
