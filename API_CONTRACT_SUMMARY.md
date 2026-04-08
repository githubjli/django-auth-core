# Backend API Contract (Extracted from Django REST Framework code)

This document captures the currently implemented API contract used by the frontend.
It is **analysis-only** and reflects current behavior; no contract redesign is proposed here.
The internal unified content mapping layer is not part of this public contract yet.

## Base Routes

- Django admin site: `/admin/`
- API auth routes: `/api/auth/`
- API account routes: `/api/account/`
- API admin routes: `/api/admin/`
- API video routes: `/api/videos/`
- API channel routes: `/api/channels/`
- API live routes: `/api/live/`
- API public category routes: `/api/public/categories/`
- API public video routes: `/api/public/videos/`

---

## 1) Endpoint Inventory + Contract

## A. Auth endpoints (`/api/auth`)

### `POST /api/auth/register`
- Auth: public
- Request body (JSON/form):
  - **required**: `email`, `password`
  - **optional**: `first_name`, `last_name`
- Validation:
  - `password` min length 8
- Response (201):
  - `id`, `email`, `first_name`, `last_name`

### `POST /api/auth/login`
- Auth: public
- Request body (JWT SimpleJWT pair):
  - **required**: `email`, `password`
- Response (200):
  - `refresh`, `access`

### `POST /api/auth/refresh`
- Auth: public
- Request body:
  - **required**: `refresh`
- Response (200):
  - `access`

### `GET /api/auth/me`
- Auth: required
- Response (200):
  - `id`, `email`, `first_name`, `last_name`, `is_creator`

---

## B. Account endpoints (`/api/account`)

### `GET /api/account/profile`
- Auth: required
- Response:
  - `display_name`, `first_name`, `last_name`, `avatar`, `avatar_url`, `bio`

### `PATCH /api/account/profile`
- Auth: required
- Content types: JSON/form/multipart
- Body (partial update):
  - **optional**: `first_name`, `last_name`, `avatar`, `bio`
- Response:
  - same shape as `GET /profile`

### `GET /api/account/preferences`
- Auth: required
- Response:
  - `language`, `theme`, `timezone`

### `PATCH /api/account/preferences`
- Auth: required
- Body (partial update):
  - **optional**: `language` (`en-US|zh-CN|th-TH|my-MM`)
  - **optional**: `theme` (`light|dark|system`)
  - **optional**: `timezone`
- Response:
  - `language`, `theme`, `timezone`

---

## C. Video owner endpoints (`/api/videos`)

### `GET /api/videos`
- Auth: required
- Query params:
  - optional: `category` (slug; supports legacy alias `tech -> technology`)
  - optional: `search`
  - optional: `ordering` (`created_at` or `-created_at`)
  - optional: `page`, `page_size` (default 10, max 100)
- Response: paginated list of video objects.

### `POST /api/videos`
- Auth: required
- Content types: JSON/form/multipart
- Request fields:
  - **required**: `title`, `file`
  - **optional**: `description`, `category` (slug or null), `thumbnail`, `visibility` (`public|private`)
- Response (201): full video object.

### `GET /api/videos/{id}/`
- Auth: required (owner only)
- Response: full video object.

### `PATCH|PUT|DELETE /api/videos/{id}/`
- Auth: required (owner only)
- Update serializer is metadata-only:
  - writable: `title`, `description`, `category`, `thumbnail`, `visibility` (`public|private`)
  - read-only: includes `file` (cannot replace video file through this route)
- Response: video object (for update)

### `POST /api/videos/{id}/regenerate-thumbnail/`
- Auth: required (owner only)
- Body:
  - optional: `time_offset` (numeric, default 1)
- Response (200): updated full video object
- Error (400): `{ "detail": "time_offset must be a number." }`

### `POST /api/videos/{id}/like/`
- Auth: required
- Response (200): interaction summary object
  - `video_id`, `like_count`, `comment_count`, `viewer_has_liked`, `viewer_is_subscribed`, `channel_id`, `subscriber_count`

### `DELETE /api/videos/{id}/like/`
- Auth: required
- Response: same interaction summary object

### `POST /api/videos/{id}/comments/`
- Auth: required
- Body:
  - **required**: `content` (non-blank after trim; max 500)
  - **optional**: `parent_id` (null or integer)
- Response (201): comment object
  - `id`, `video_id`, `parent_id`, `content`, `created_at`, `updated_at`, `like_count`, `reply_count`, `viewer_has_liked`, `user`

---

## D. Channel endpoint (`/api/channels`)

### `POST /api/channels/{channelUserId}/subscribe/`
- Auth: required
- Response:
  - `channel_id`, `subscriber_count`, `viewer_is_subscribed: true`
- Error 400 when subscribing to self.

### `DELETE /api/channels/{channelUserId}/subscribe/`
- Auth: required
- Response:
  - `channel_id`, `subscriber_count`, `viewer_is_subscribed: false`

---

## E. Live endpoints (`/api/live`)

### `GET /api/live/`
- Auth: optional
- Returns list (non-paginated)
- Visibility filter:
  - anonymous: only `public`
  - authenticated: `public` + own streams

### `POST /api/live/create/`
- Auth: required + creator role (`is_creator=true`)
- Content types: JSON/form/multipart
- Request fields:
  - **required**: `title`
  - **optional**: `description`, `payment_address`, `category`, `visibility`
  - read-only server fields include `status`, `viewer_count`, timestamps
- Response (201): live stream object

### `GET /api/live/{id}/`
- Auth: optional
- Visibility behavior same as list.
- Response: live stream object

### `GET /api/live/{id}/status/`
- Auth: optional
- Visibility behavior same as list/detail (public streams are public, non-public streams are owner-only)
- Response: live stream object (status-focused contract fields included)

### `PATCH /api/live/{id}/update/`
- Auth: required (owner only)
- Body (partial):
  - writable fields same as create writable set
- Response: live stream object

### `POST /api/live/{id}/start/`
- Auth: required + creator role (owner only)
- Allowed transition: `idle -> live`
- Invalid transitions return `409 Conflict`
- Sets stream to live, sets `started_at=now`, `ended_at=null`
- Response: live stream object
- Note: this is a Django-side control action; it does not guarantee direct media-server ingest control.

### `POST /api/live/{id}/prepare/`
- Auth: required + creator role (owner only)
- Allowed lifecycle state: `idle` only
- Invalid lifecycle states return `409 Conflict`
- Rotates/regenerates stream publish credential (`stream_key`) per successful prepare
- Response (owner-only compact payload):
  - `id`
  - `rtmp_base`
  - `stream_key`
  - `playback_url`
  - `watch_url`
  - `status`
  - `message`

### `POST /api/live/{id}/end/`
- Auth: required + creator role (owner only)
- Allowed transition: `live -> ended`
- Invalid transitions return `409 Conflict`
- Sets stream to ended, sets `ended_at=now`
- Response: live stream object
- Note: this is a Django-side control action; it does not guarantee direct media-server ingest control.

Live stream object fields:
- `id`, `owner_id`, `owner_name`, `title`, `description`, `payment_address`, `category`, `category_name`, `visibility`,
- `status`, `django_status`, `effective_status`, `status_source`, `raw_ant_media_status`,
- `rtmp_url`, `playback_url`, `watch_url`, `thumbnail_url`, `preview_image_url`, `snapshot_url`,
- `viewer_count`, `can_start`, `can_end`, `sync_ok`, `sync_error`, `message`,
- `started_at`, `ended_at`, `created_at`

Status field meanings:
- `status`: backward-compatible effective status (same as `effective_status`)
- `django_status`: stored Django DB control status
- `effective_status`: final status shown to clients after optional Ant Media normalization
- `status_source`: `ant_media` when derived from Ant Media payload, otherwise `django_control`
- `raw_ant_media_status`: raw status string from Ant Media payload, or `null`
- `watch_url`: canonical frontend watch/share URL for this live room (viewer-facing route)
- `playback_url`: media playback URL (HLS `.m3u8`), intentionally separate from `watch_url`
- `stream_key` is intentionally excluded from list/detail/status/update live object responses and is only returned by owner-only `prepare`.

`effective_status` is computed:
- if Ant Media synced status = `broadcasting` => `live`
- if Ant Media synced status = `finished` => `ended`
- if Ant Media returns other status => `waiting_for_signal`
- else fallback from Django DB status:
  - db `live` => `live`
  - db `ended` => `ended`
  - db `idle` => `ready`

---

## F. Live Commerce / Payments endpoints (`/api/live` + `/api/account`)

### `GET /api/live/{id}/payment-methods/`
- Auth: public (private stream remains owner-only visibility)
- Response: active payment methods only (viewer-safe trimmed fields):
  - `id`, `method_type`, `title`, `qr_image_url`, `qr_text`, `wallet_address`, `sort_order`

### `POST /api/live/{id}/payments/orders/`
- Auth: required
- Request body:
  - required: `order_type`, `amount`
  - optional: `currency`, `product`, `payment_method`, `external_reference`
  - optional idempotency: `client_request_id` or `idempotency_key`
- Validation hardening:
  - private streams are not orderable by non-owners
  - `payment_method` (if provided) must belong to the target live stream and be active
  - `product` required when `order_type=product`
  - `product` (if provided) must be active, store-active, and currently active for the target stream binding
- Idempotency behavior:
  - if same authenticated user repeats the same payload for the same stream and same request key, server reuses prior order and returns `200`
  - if same key is reused with a different payload, returns `409`
- Response:
  - `201` for newly created order, `200` for idempotent replay
  - order object fields listed below

### `GET /api/live/{id}/payments/orders/{order_id}/`
- Auth: required
- Access: buyer, stream owner, or staff
- Response: payment order object

### `POST /api/live/{id}/payments/orders/{order_id}/mark-paid/`
- Auth: required
- Access: stream owner or staff
- Body:
  - optional: `note` (<=1000 chars)
- Behavior:
  - transition `pending -> paid` sets `paid_at`, `paid_by`, optional `paid_note`
  - repeated calls remain idempotent for `status`; optional note can be backfilled if currently empty
- Response: payment order object

### `GET /api/account/payment-orders/`
- Auth: required
- Response: **paginated** payment order list
- Query params (optional):
  - `status`: `pending|paid|failed|cancelled`
  - `live_stream`: integer stream id
  - `product`: integer product id
  - `date_from`: `YYYY-MM-DD`
  - `date_to`: `YYYY-MM-DD`
  - `page`, `page_size`

Payment order object fields:
- `id`, `user_id`, `stream_id`, `product_id`, `payment_method_id`,
- `order_type`, `amount`, `currency`, `status`,
- `client_request_id`, `external_reference`,
- `paid_at`, `paid_by_id`, `paid_note`,
- `created_at`, `updated_at`

---

## G. Admin endpoints (`/api/admin`)

Auth: staff/superuser required.

### Users
- `GET /api/admin/users/` (paginated by DRF default if global pagination is configured; no custom paginator here)
- `GET /api/admin/users/{id}/`
- `PUT|PATCH /api/admin/users/{id}/`
- `POST /api/admin/users/{id}/activate/`
- `POST /api/admin/users/{id}/deactivate/`

Admin user object fields:
- `id`, `email`, `first_name`, `last_name`, `is_active`, `is_staff`, `is_superuser`, `date_joined`

### Videos
- `GET /api/admin/videos/`
  - query params:
    - `search`, `owner`, `category`, `status`, `visibility`, `ordering`, `page`, `page_size`
  - allowed ordering values:
    - `created_at`, `-created_at`, `updated_at`, `-updated_at`, `like_count`, `-like_count`, `comment_count`, `-comment_count`
- `GET /api/admin/videos/{id}/`
- `PATCH|PUT /api/admin/videos/{id}/`
- `DELETE /api/admin/videos/{id}/`

Admin video object fields:
- `id`, `title`, `thumbnail_url`, `owner_id`, `owner_name`, `owner_email`, `category`, `status`, `visibility`,
- `like_count`, `comment_count`, `created_at`, `updated_at`

---

## H. Public endpoints (`/api/public/...`)

### Categories
#### `GET /api/public/categories/`
- Auth: public
- Response: non-paginated list
- Category object:
  - `name`, `slug`, `description`, `sort_order`, `show_on_homepage`
- Note: legacy alias category slugs (e.g. `tech`) are excluded from this list.

### Videos
#### `GET /api/public/videos/`
- Auth: public
- Query params:
  - optional: `category`, `search`, `ordering`, `page`, `page_size`
- Response: paginated video list.

#### `GET /api/public/videos/{id}/`
- Auth: public
- Response: full video object.

#### `GET /api/public/videos/{id}/related/?limit=8`
- Auth: public
- Query:
  - optional `limit` (int clamped 1..20; default 8)
- Response: non-paginated video array.

#### `GET /api/public/videos/{id}/interaction-summary/`
- Auth: public/optional
- Response: interaction summary object
  - `video_id`, `like_count`, `comment_count`, `viewer_has_liked`, `viewer_is_subscribed`, `channel_id`, `subscriber_count`

#### `GET /api/public/videos/{id}/comments/?parent_id=...`
- Auth: public/optional
- Query:
  - if `parent_id` omitted => top-level comments
  - if provided => replies for that parent
  - paginated (default 20, max 100)
- Response: comment list objects.

#### `POST /api/public/videos/{id}/view/`
- Auth: public/optional
- Side effect: creates a view row; includes authenticated viewer when available.
- Response: full video object with updated counts.

Common public video object fields:
- `id`, `owner_id`, `owner_name`, `owner_avatar_url`, `title`, `description`, `description_preview`, `category`, `category_name`, `category_slug`,
- `like_count`, `comment_count`, `view_count`, `is_liked`, `file`, `file_url`, `thumbnail`, `thumbnail_url`, `created_at`

---

## 2) Stable vs Optional/Unstable Fields

## Likely Stable (safe for frontend assumptions)
- Primary ids: `id`, `video_id`, `channel_id`, `owner_id`
- Core identities: `email`, `first_name`, `last_name`, `owner_name`
- Core counters: `like_count`, `comment_count`, `subscriber_count`
- Core timestamps: `created_at` (videos/live/comments), `updated_at` (comments/videos where exposed)
- Core auth token keys from SimpleJWT: `access`, `refresh`

## Optional / Nullable / Environment-dependent
- User profile: `avatar`, `avatar_url`, `bio`
- Video media URLs: `thumbnail`, `thumbnail_url`, sometimes missing if generation failed/unset
- Live URLs: `rtmp_url`, `playback_url`, `thumbnail_url`, `preview_image_url`, `snapshot_url` (all can be `null` when Ant Media config is absent)
- Live time fields: `started_at`, `ended_at` nullable
- Video/category relation: `category` may be null
- Viewer-dependent booleans:
  - `is_liked`, `viewer_has_liked`, `viewer_is_subscribed` depend on auth context and default false for anonymous

## Semantically Unstable / derived
- `live.status` is not raw DB status; it is computed and can emit values beyond model enum (`ready`, `waiting_for_signal`), and can be mutated during serialization due to Ant Media sync.
- `status_source` changes between `django_control` and `ant_media` depending on runtime network/config availability.

---

## 3) Inconsistencies / Frontend Risks

1. **Status vocabulary mismatch risk (live):**
   - DB stores `idle|live|ended`, but API returns `ready|live|ended|waiting_for_signal`.
   - Frontend expecting only model choices may mis-handle `ready` or `waiting_for_signal`.

2. **Visibility filtering gap on public videos:**
   - Public video endpoints currently query all videos and do not enforce `visibility='public'` at query layer.
   - If frontend assumes all returned videos are public-safe, this is a data exposure risk.

3. **Category representation inconsistency:**
   - video `category` is slug in API payloads for writable/readable serializer, while admin/public/category list may use additional fields (`category_name`, `category_slug`).
   - Frontend may confuse `category` (slug) with full object.

4. **Mixed status naming conventions across domains:**
   - Video status uses `active|flagged|archived`; live status externally uses `ready|live|ended|waiting_for_signal`.
   - Reusable status UI components may wrongly share assumptions.

5. **snake_case only contract but frontend might expect camelCase:**
   - Backend uses snake_case consistently (`viewer_has_liked`, `description_preview`, `payment_address`).
   - Any frontend camelCase mapping not centralized can cause silent bugs.

6. **Owner avatar fields are structurally present but effectively null in some serializers:**
   - `owner_avatar_url` and comment user `avatar_url` currently return `None` from serializer method.
   - Frontend expecting actual URLs may show broken image logic unless null-safe.

7. **Trailing slash behavior split:**
   - several auth/account endpoints are defined without trailing slash (`/api/auth/login`, `/api/account/profile`) while others include slashes in path definitions.
   - Depending on APPEND_SLASH/client behavior, frontend URL builders can drift.

8. **File field echo risk:**
   - video payload includes both `file` and `file_url`; frontend may depend on one and break in multipart vs serialized contexts.

---

## 4) Minimal Safe Improvements (Non-breaking)

1. **Document status contract explicitly**
   - Publish allowed API `live.status` values (`ready|live|ended|waiting_for_signal`) and clarify they are API-facing computed values.

2. **Add response examples in backend docs/tests**
   - Include canonical JSON examples for video object, interaction summary, comment object, live object.

3. **Explicit optionality notes in docs**
   - Mark nullable/env-dependent fields (`avatar_url`, stream URLs, timestamps, category).

4. **Frontend-safe guardrails in docs**
   - Recommend null-safe rendering for avatar/thumbnail/live URLs.
   - Recommend default handling for unknown `status` values.

5. **Contract tests (no behavior change)**
   - Add API tests that assert field presence and type (including nullable fields), plus auth-dependent booleans.

6. **Clarify category field meaning**
   - Document that `category` in video/live payloads is a slug string (or null), not nested object.

7. **Clarify public visibility expectation**
   - Add a documented warning that frontend should not assume privacy-filter semantics beyond what endpoint currently enforces.
   - (No code change in this analysis doc.)
