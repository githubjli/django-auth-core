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

By default, `make run` starts the server at `http://127.0.0.1:8001/` so it does not collide with another process already using port 8000.

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
- `APP_HOST`
- `APP_PORT`

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
- Override the bind address if needed: `APP_PORT=8010 make run` or `APP_HOST=0.0.0.0 APP_PORT=8010 make run`
- `make test` - run the current auth/accounts test suite (`apps.accounts`)
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
curl -X POST http://127.0.0.1:8001/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"strong-pass-123","first_name":"Demo","last_name":"User"}'
```

Login (get access + refresh):

```bash
curl -X POST http://127.0.0.1:8001/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"strong-pass-123"}'
```

Refresh access token:

```bash
curl -X POST http://127.0.0.1:8001/api/auth/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh":"<refresh_token>"}'
```

Current user profile:

```bash
curl http://127.0.0.1:8001/api/auth/me \
  -H 'Authorization: Bearer <access_token>'
```

## Admin User Control API

These endpoints are for staff or superusers only and are intended for future frontend admin pages.
Deactivating a user sets `is_active=False`, which blocks that user from logging in via the existing JWT auth endpoint.

- `GET /api/admin/users/` - list users
- `GET /api/admin/users/<id>/` - retrieve a user
- `PATCH /api/admin/users/<id>/` - update user fields such as `first_name`, `last_name`, `is_staff`, or `is_active`
- `POST /api/admin/users/<id>/activate/` - set `is_active=true`
- `POST /api/admin/users/<id>/deactivate/` - set `is_active=false`

Example admin curl commands:

```bash
curl http://127.0.0.1:8001/api/admin/users/ \
  -H 'Authorization: Bearer <staff_access_token>'
```

```bash
curl http://127.0.0.1:8001/api/admin/users/2/ \
  -H 'Authorization: Bearer <staff_access_token>'
```

```bash
curl -X PATCH http://127.0.0.1:8001/api/admin/users/2/ \
  -H 'Authorization: Bearer <staff_access_token>' \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Updated","last_name":"User","is_staff":false}'
```

```bash
curl -X POST http://127.0.0.1:8001/api/admin/users/2/deactivate/ \
  -H 'Authorization: Bearer <staff_access_token>'
```

```bash
curl -X POST http://127.0.0.1:8001/api/admin/users/2/activate/ \
  -H 'Authorization: Bearer <staff_access_token>'
```

## Video Upload API

These endpoints are for authenticated users only. Each user can only list, view, and delete their own uploaded videos.
Files are stored locally for now under the Django media directory.

- `POST /api/videos/` - upload a video file for the current user
- `GET /api/videos/` - list the current user's videos
- `GET /api/videos/<id>/` - retrieve one of the current user's videos
- `DELETE /api/videos/<id>/` - delete one of the current user's videos

Example video curl commands:

```bash
curl -X POST http://127.0.0.1:8001/api/videos/ \
  -H 'Authorization: Bearer <access_token>' \
  -F 'title=My first video' \
  -F 'file=@/path/to/video.mp4'
```

```bash
curl http://127.0.0.1:8001/api/videos/ \
  -H 'Authorization: Bearer <access_token>'
```

```bash
curl http://127.0.0.1:8001/api/videos/1/ \
  -H 'Authorization: Bearer <access_token>'
```

```bash
curl -X DELETE http://127.0.0.1:8001/api/videos/1/ \
  -H 'Authorization: Bearer <access_token>'
```

## Django Admin

Admin is enabled at `/admin/` for local verification and ops tasks.

Create a superuser:

```bash
.venv/bin/python backend/manage.py createsuperuser
```

Then open:

```text
http://127.0.0.1:8001/admin/
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
