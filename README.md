# Django Auth Core API Starter

API-first Django starter for front-end/back-end separation. The Django project root remains in `backend/`, and domain apps live under `backend/apps/`.

## Requirements

- macOS (recommended)
- Python 3.11+
- Homebrew

## Quick start

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

Minimum fields:

- `DEBUG`
- `SECRET_KEY`
- `ALLOWED_HOSTS`
- `DATABASE_URL` or `DB_ENGINE`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`
- `REDIS_URL`

Optional API fields:

- `CORS_ALLOWED_ORIGINS`
- `CORS_ALLOW_ALL_ORIGINS` (defaults to `DEBUG` behavior)
- `JWT_ACCESS_MINUTES`
- `JWT_REFRESH_DAYS`

By default SQLite is used. Set `DATABASE_URL` (or `DB_*`) to switch to Postgres.

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

## Auth Core APIs (JWT)

Base path: `/api/auth`

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `GET /api/auth/me` (Bearer access token required)

### Curl examples

Register:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"strong-pass-123","first_name":"Demo","last_name":"User"}'
```

Login (get access + refresh):

```bash
curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"strong-pass-123"}'
```

Refresh access token:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh":"<refresh_token>"}'
```

Current user profile:

```bash
curl http://127.0.0.1:8000/api/auth/me \
  -H 'Authorization: Bearer <access_token>'
```

## Project structure

```text
backend/
  manage.py
  config/
  apps/
    accounts/
```

## Notes

- `.venv/` and `.env` are ignored by git and must stay local.
- Starter stack includes DRF, SimpleJWT, CORS, dotenv, and psycopg.
