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
Uploaded videos also receive a default thumbnail automatically. The backend will try to extract a frame around 1 second using `ffmpeg` when available, and fall back to a minimal placeholder thumbnail when extraction is not possible.

- `POST /api/videos/` - upload a video file for the current user
- `GET /api/videos/` - list the current user's videos with optional filtering/search/sorting/pagination
- `GET /api/videos/<id>/` - retrieve one of the current user's videos
- `PATCH /api/videos/<id>/` - update the owner's `title`, `description`, `category`, or manually replace `thumbnail`
- `DELETE /api/videos/<id>/` - delete one of the current user's videos
- `POST /api/videos/<id>/regenerate-thumbnail/` - regenerate the thumbnail from the stored video file
- `POST /api/videos/<id>/like/` - like a video as the current authenticated user
- `DELETE /api/videos/<id>/like/` - remove the current user's like from a video
- `POST /api/videos/<id>/comments/` - create a comment on a video as the current authenticated user

Optional upload/list fields and query params:

- Upload fields: `title`, optional `description`, optional `category`, `file`
- Detail/PATCH response fields also include `thumbnail` and `thumbnail_url`
- Categories: `technology`, `education`, `gaming`, `news`, `entertainment`, `other`
- List query params:
  - `category=technology`
  - `search=demo`
  - `ordering=created_at` or `ordering=-created_at`
  - `page=1`
  - `page_size=10`

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

Filter/search/paginate your own videos:

```bash
curl "http://127.0.0.1:8001/api/videos/?category=technology&search=demo&ordering=-created_at&page=1&page_size=10" \
  -H 'Authorization: Bearer <access_token>'
```

Update metadata or manually replace the thumbnail:

```bash
curl -X PATCH http://127.0.0.1:8001/api/videos/1/ \
  -H 'Authorization: Bearer <access_token>' \
  -F 'title=Better title' \
  -F 'description=Updated description' \
  -F 'category=education' \
  -F 'thumbnail=@/path/to/manual-thumbnail.png'
```

Regenerate the thumbnail from the uploaded video:

```bash
curl -X POST http://127.0.0.1:8001/api/videos/1/regenerate-thumbnail/ \
  -H 'Authorization: Bearer <access_token>' \
  -H 'Content-Type: application/json' \
  -d '{"time_offset": 1.0}'
```

## Public Video API

These endpoints are read-only and do not require authentication.

- `GET /api/public/videos/`
- `GET /api/public/videos/<id>/`
- `GET /api/public/videos/<id>/related/`
- `GET /api/public/videos/<id>/interaction-summary/`
- `GET /api/public/videos/<id>/comments/`
- `POST /api/public/videos/<id>/view/` - record a lightweight view event and return the updated video payload

The public list also supports the same `category`, `search`, `ordering`, `page`, and `page_size` query params.
Public video responses also include presentation-friendly fields such as `owner_id`, `owner_name`, `description_preview`, `category_name`, `category_slug`, `thumbnail_url`, `like_count`, `comment_count`, `view_count`, and `is_liked`.

```bash
curl "http://127.0.0.1:8001/api/public/videos/?category=education&search=tutorial&ordering=-created_at"
```

```bash
curl http://127.0.0.1:8001/api/public/videos/1/
```

```bash
curl http://127.0.0.1:8001/api/public/videos/1/related/
```


```bash
curl -X POST http://127.0.0.1:8001/api/public/videos/1/view/
```


## Channel Subscription API

These endpoints are for authenticated users and provide a first-pass channel follow skeleton.

- `POST /api/channels/<id>/subscribe/`
- `DELETE /api/channels/<id>/subscribe/`

```bash
curl -X POST http://127.0.0.1:8001/api/channels/2/subscribe/ \
  -H 'Authorization: Bearer <access_token>'
```

## Public Categories API

This backend now exposes frontend-ready categories so a separate UI can render dynamic sidebar links, homepage chips, and category browse pages from backend-managed data instead of hardcoded labels.

- `GET /api/public/categories/`

Response fields:

- `name` - display label for the UI
- `slug` - stable routing/filtering key
- `description`
- `sort_order`
- `show_on_homepage`

Notes:

- only active categories are returned
- legacy duplicate variants such as `tech` are normalized to the canonical `technology` channel
- categories with zero videos are still returned so the frontend can render empty states cleanly
- videos continue to store and filter by category slug

```bash
curl http://127.0.0.1:8001/api/public/categories/
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
