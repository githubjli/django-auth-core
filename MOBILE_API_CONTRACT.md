# MOBILE_API_CONTRACT

## 1) Purpose

This contract defines how the Flutter mobile app should integrate with the existing Django backend APIs without copying web-only assumptions (browser routing, browser WebRTC setup details, web-specific field normalization, or frontend-only URL composition). It is intended to be practical for near-term Flutter delivery and explicit about what is already implemented vs what is proposed for mobile hardening.

Status legend used throughout:
- **Current**: implemented and documented in current backend contract docs.
- **Current but needs mobile review**: implemented, but mobile-specific behavior/shape/constraints should be validated before relying on it in production Flutter.
- **Proposed**: not currently guaranteed by backend contract; listed for roadmap and alignment.

---

## 2) Global API conventions

### Base URL strategy
- **Current**: API paths are rooted under `/api/...` and should be composed by Flutter from environment-specific host values (dev/staging/prod).
- **Mobile guidance**: use one configurable `api_base_url` (e.g. `https://api.example.com`) and append paths exactly as documented.
- **Proposed**: optional dedicated namespace (for example `/api/mobile/*` or `/api/app/*`) after backend/mobile cleanup review.

### Auth header format
- **Current**: JWT Bearer token.
- Header format:
  - `Authorization: Bearer <access_token>`
- Refresh token is sent in JSON body to refresh endpoint, not in auth header.

### JSON request/response convention
- **Current**:
  - Most endpoints accept/return JSON.
  - Some update/create endpoints also accept `form-data` or `multipart/form-data` (profile avatar, video upload, some creator/live flows).
- **Mobile guidance**:
  - Default to JSON.
  - Use multipart only when uploading files.

### Pagination shape
- **Current but needs mobile review**:
  - DRF paginated endpoints are used across public videos/dramas/account lists.
  - Typical DRF page shape is expected (`count`, `next`, `previous`, `results`) but mobile should verify endpoint-by-endpoint.
- **Proposed mobile normalization**:
  - `count`, `next`, `previous`, `results` unchanged, plus optional additive `page` and `page_size` metadata for easier Flutter state handling.

### Error response shape
- **Current but needs mobile review**:
  - Error payloads are not fully uniform yet across all modules.
  - Some endpoints use `{ "detail": "..." }`.
  - Validation endpoints can return field-keyed errors.
  - Some domain endpoints return explicit `code` (for example `insufficient_balance`).
- **Proposed normalized mobile error shape**:
```json
{
  "code": "validation_error|auth_error|permission_denied|not_found|insufficient_balance|...",
  "message": "Human-readable message",
  "details": {
    "field_name": ["error1", "error2"]
  },
  "request_id": "optional-trace-id"
}
```

### Date/time format
- **Current**: ISO-8601 datetime strings are used in API responses.
- **Mobile guidance**: parse as UTC-capable ISO-8601 and convert in UI layer only.

### Absolute media URL requirement
- **Current but needs mobile review**:
  - `avatar_url` is documented as fully-qualified when present.
  - Playback/media URL fields across videos/live/drama should be treated as requiring absolute URLs for mobile reliability.
- **Proposed requirement**: all mobile-consumed media fields (`avatar_url`, `thumbnail_url`, `video_url`, `playback_url`, `hls_url`, etc.) must be absolute HTTPS URLs.

### Field naming convention
- **Current**: many endpoints already expose snake_case fields.
- **Mobile preference**: snake_case should be the backend response standard for mobile-facing APIs.
- **Proposed**: resolve remaining inconsistent/web-normalized naming to snake_case additive fields (without breaking existing clients).

---

## 3) Auth endpoints

### POST `/api/auth/register`
- **Status**: Current
- **Auth**: Public
- **Request body**:
```json
{
  "email": "user@example.com",
  "password": "strong-pass-123",
  "first_name": "Demo",
  "last_name": "User"
}
```
- **Response fields**: `id`, `email`, `first_name`, `last_name`
- **Mobile notes**:
  - Store nothing except immediate UX state; token pair is not returned by register.
  - After register, call login.

### POST `/api/auth/login`
- **Status**: Current
- **Auth**: Public
- **Request body**:
```json
{
  "email": "user@example.com",
  "password": "strong-pass-123"
}
```
- **Response fields**: `access`, `refresh`
- **Mobile notes**:
  - Persist `refresh` in secure storage.
  - Keep `access` in memory + secure fallback as needed.

### POST `/api/auth/refresh`
- **Status**: Current
- **Auth**: Public (token-based)
- **Request body**:
```json
{
  "refresh": "<refresh_token>"
}
```
- **Response fields**: `access`
- **Mobile notes**:
  - Implement interceptor-based retry once on 401.
  - If refresh fails, force logout.

### GET `/api/auth/me`
- **Status**: Current
- **Auth**: Bearer access token required
- **Request body**: none
- **Response fields**: `id`, `email`, `first_name`, `last_name`, `is_creator`, `display_name`, `avatar`, `avatar_url`, `is_admin`
- **Mobile notes**:
  - Prefer `avatar_url` for display.
  - `is_admin` is additive; mobile app should not assume admin UI unless product requires it.

---

## 4) Account / Profile endpoints

### GET `/api/account/profile`
- **Status**: Current
- **Auth**: Bearer access token required
- **Response fields** include:
  - Identity/profile: `id`, `email`, `display_name`, `first_name`, `last_name`, `bio`, `avatar`, `avatar_url`
  - Role flags: `is_creator`, `is_seller`, `is_admin`
  - Capability flags: `can_create_live`, `can_manage_store`, `can_accept_payments`
  - Optional summaries: `seller_store`, `counts`
  - Content aggregates: `video_count`, `drama_count`, `live_count`, `video_total_views`, `drama_total_views`, `live_total_views`, `total_views`, `view_count`, `video_total_likes`, `drama_total_likes`, `live_total_likes`, `total_likes`, `like_count`
- **Aggregate semantics**:
  - `video_total_views` = total playback count for public active videos.
  - `drama_total_views` = total playback count for active published dramas/short series.
  - `live_total_views` = total live replay/history playback count; currently `0` until a stable live replay view-count field exists.
  - `total_views` = `video_total_views + drama_total_views + live_total_views`.
  - `view_count` is a deprecated backward-compatible alias for `total_views` in profile payloads (`profile.view_count == profile.total_views`).
  - `total_likes` = `video_total_likes + drama_total_likes + live_total_likes`; drama/live likes are `0` until first-class like models/fields exist.
  - `like_count` is a deprecated backward-compatible alias for `total_likes` in profile payloads (`profile.like_count == profile.total_likes`).
- **Recommended display**:
  - My Profile / Creator Profile first screen should prioritize: `Followers / Videos / Total Views / Total Likes`.
  - If showing breakdowns, use explicit split fields: `video_total_views`, `drama_total_views`, `live_total_views`.
  - Do not directly display compatibility fields `view_count` / `like_count` in new UI; use `total_views` / `total_likes` to avoid confusion with single-content detail payloads.
- **Mobile notes**:
  - Flutter should prefer capability booleans (`can_*`) over hardcoded role string logic.
  - Keep role labels/UI derived from booleans and explicit backend flags.

### PATCH `/api/account/profile`
- **Status**: Current but needs mobile review
- **Auth**: Bearer access token required
- **Request body** (partial update; JSON/form/multipart supported):
  - editable: `display_name`, `bio`, `avatar`, `avatar_clear`
  - backward-compatible: `first_name`, `last_name`
- **Response fields**: same shape as `GET /api/account/profile`
- **Mobile notes**:
  - Use multipart when sending `avatar` file.
  - Validate avatar size/type constraints in backend docs or follow-up testing.

---

## 5) Public content endpoints

### GET `/api/public/categories/`
- **Status**: Current
- **Auth**: Public
- **Mobile notes**:
  - Cache categories locally with periodic refresh.

### GET `/api/public/videos/`
- **Status**: Current but needs mobile review
- **Auth**: Public
- **Current assumptions**:
  - Paginated list endpoint.
  - Supports ordering/filter patterns documented in backend contracts (verify exact query params for public route in integration test).
- **Current canonical public fields (as currently documented/expected for app feed)**:
  - playback: `file_url`
  - thumbnail: `thumbnail_url`
  - owner: `owner_id`, `owner_name`, `owner_avatar_url`
  - category: `category`, `category_name`, `category_slug`
  - gating: `access_type`, `preview_seconds`, `can_watch`, `is_locked`, `lock_reason`
- **Additional mobile-required fields**:
  - `id`, `title`, `description`, `created_at`
- **Mobile review needed**:
  - Confirm absolute URL guarantees for `file_url`, `thumbnail_url`, `owner_avatar_url`.
  - Confirm `duration` field existence, semantics/units, and nullability before adding to Current mobile DTO.

### GET `/api/public/videos/{id}/`
- **Status**: Current but needs mobile review
- **Reason**:
  - Public video detail route should be confirmed/standardized for Flutter detail page deep-linking.
- **Proposed response**:
  - Same core fields as list item with richer creator/category/playback metadata.
  - `view_count` is the single video's playback/view count, not the creator's total views.
- **UX note**:
  - Do not show `video.view_count` in the video detail author row; it can be misunderstood as creator total views. Use explicit labels near video stats only.


### GET `/api/public/users/{id}/`
- **Status**: Current; preferred public profile endpoint for all user profile pages.
- **Auth**: Public; when authenticated, `viewer_is_following` reflects the request user.
- **Purpose**: unified public user profile for both creators and non-creators. New frontend profile pages should use this endpoint instead of `/api/public/creators/{id}/` for stats.
- **Core public fields**: `id`, `display_name`, `username`, `email`, `avatar_url`, `bio`, `is_creator`, `is_seller`.
- **Relationship fields**:
  - `follower_count`: number of users following this profile user.
  - `following_count`: number of users this profile user follows.
  - `viewer_is_following`: `false` when anonymous; otherwise whether the viewer follows this user.
- **Unified stats fields**:
  - `video_count`, `drama_count`, `live_count`
  - `video_total_views`, `drama_total_views`, `live_total_views`, `total_views`
  - `video_total_likes`, `drama_total_likes`, `live_total_likes`, `total_likes`
  - `total_gifts`: current backend gift value total received by this user's public creator content.
  - Deprecated aliases are retained for compatibility: `view_count == total_views`, `like_count == total_likes`. New code should prefer `total_views` / `total_likes`.
- **Non-creator users**: return `is_creator=false`; content stats such as `video_count`, `total_views`, `total_likes`, and `total_gifts` are `0`.
- **Recommended display**: My Profile / Creator Profile first screen should prioritize `Followers / Videos / Total Views / Total Likes`; use split fields only for detailed breakdowns.

### GET `/api/public/creators/{id}/`
- **Status**: Current but compatibility-oriented; new public profile UI should prefer `GET /api/public/users/{id}/`.
- **Auth**: Public
- **Creator aggregate fields**:
  - `video_count`: number of the creator's videos where `visibility=public` and `status=active`.
  - `drama_count`: number of active published dramas/short series.
  - `live_count`: number of non-private live streams (`public` or `unlisted`).
  - `video_total_views`: total playback count for public active videos.
  - `drama_total_views`: total playback count for active published dramas/short series.
  - `live_total_views`: total live replay/history playback count; currently `0` until a stable live replay view-count field exists.
  - `total_views`: `video_total_views + drama_total_views + live_total_views`.
  - `view_count`: deprecated backward-compatible alias for `total_views` (`creator.view_count == creator.total_views`); do not interpret as one video's view count in creator payloads.
  - `video_total_likes`: total likes for public active videos.
  - `drama_total_likes`: `0` until a first-class drama like model/field exists.
  - `live_total_likes`: `0` until a first-class live like model/field exists.
  - `total_likes`: `video_total_likes + drama_total_likes + live_total_likes`.
  - `total_gifts`: current backend gift value total received by this creator's content.
  - `like_count`: deprecated backward-compatible alias for `total_likes` (`creator.like_count == creator.total_likes`).
- **Consistency**:
  - `creator.video_count` should match the `count` returned by `GET /api/public/creators/{id}/videos/` with no filters.
  - `video.view_count` remains single-video playback count in video list/detail payloads.
  - `drama.view_count` remains single-drama/series playback count in drama detail payloads.
  - `live.viewer_count` remains current realtime viewers; `live.view_count`, if added later, should mean live replay/history playback count.
  - Single-video `like_count` remains current-video likes in video payloads.
- **UX note**:
  - My Profile / Creator Profile first screen should prioritize clearly labeled `Followers / Videos / Total Views / Total Likes`.
  - If displaying detailed playback breakdowns, use `video_total_views`, `drama_total_views`, and `live_total_views`.
  - New frontend code should read `total_views` / `total_likes`; avoid directly displaying deprecated compatibility aliases `view_count` / `like_count`.

### GET `/api/public/creators/{id}/videos/`
- **Status**: Current but needs mobile review
- **Auth**: Public
- **Semantics**:
  - Returns only creator videos with `visibility=public` and `status=active`.
  - Paginated `count` is the same public active video count exposed as `creator.video_count` on creator detail.

---

## 6) Shorts / short drama feed

Based on current short-drama contract:

### Vertical shorts feed
- **Status**: Current but needs mobile review
- **Current candidates**:
  - `GET /api/dramas/`
  - `GET /api/dramas/{id}/episodes/`
  - `GET /api/dramas/{id}/episodes/{episode_no}/`
- **Mobile target feed item fields**:
  - `series_id`, `episode_id`, `episode_no`, `title`, `duration_seconds`, `thumbnail/cover_url`, `can_watch`, `is_locked`, `is_unlocked`, `playback_url`/`video_url`/`hls_url`
- **Mobile review needed**:
  - Align a single mobile feed DTO for vertical scrolling.

### Series
- **Status**: Current
- `GET /api/dramas/` (paginated list), `GET /api/dramas/{id}/` (detail)

### Episodes
- **Status**: Current
- `GET /api/dramas/{id}/episodes/`, `GET /api/dramas/{id}/episodes/{episode_no}/`

### Locked / member-only content
- **Status**: Current
- Gating fields currently include `can_watch`, `is_locked`, `is_unlocked`, pricing fields.
- Unlock flow currently available via `POST /api/dramas/episodes/{episode_id}/unlock/`.

### Watch progress
- **Status**: Current
- `POST /api/dramas/{id}/progress/`
- Account history endpoints exist for continue watching/favorites.
- **Proposed additive**: batch progress sync endpoint for intermittent mobile connectivity.

---

## 7) Membership endpoints

### GET `/api/membership/plans/`
- **Status**: Current
- **Auth**: typically authenticated flow context
- **Mobile notes**:
  - Render plan code/name/price and backend-controlled payment metadata.

### POST `/api/membership/orders/`
- **Status**: Current
- **Auth**: Required
- **Request**:
```json
{
  "plan_code": "monthly"
}
```
- **Mobile notes**:
  - Verify whether backend currently accepts `plan_code`, `plan_id`, or both; treat this as required integration check before Flutter release.
  - Use returned order snapshot as source of truth for amount/address/expiry.

### GET `/api/membership/orders/{order_no}/`
- **Status**: Current
- **Auth**: Required (owner-scoped)
- **Mobile notes**:
  - Poll this endpoint after order creation.
  - Handle states: `paid`, `underpaid`, `overpaid`, `expired` (exact enum/value mapping must be confirmed against backend output).

### GET `/api/membership/me/`
- **Status**: Current
- **Auth**: Required
- **Mobile notes**:
  - Drive membership badge/entitlement from this endpoint, not local assumptions.

### Membership payment display notes (LBC/LTT)
- **Status**: Current but needs mobile review
- Show backend-provided:
  - payment address (`pay_to_address` when provided)
  - expected amount (`expected_amount_lbc` naming may remain internal)
- **QR display fields**:
  - **Current**: not explicitly standardized in contract docs.
  - **Proposed**: additive `payment_uri` and/or explicit `qr_payload` field for consistent Flutter QR rendering.

---

## 8) Live watching endpoints

### Live list/detail/status
- **GET `/api/live/`** — **Status**: Current
- **GET `/api/live/{id}/`** — **Status**: Current
- **GET `/api/live/{id}/status/`** — **Status**: Current but needs mobile review (currently similar to detail payload; optimize later)
- **Field semantics**:
  - `viewer_count` is realtime/current audience.
  - `view_count`, if introduced later, should mean replay/history playback count, not realtime viewers.

### Live products
- **Status**: Current but needs mobile review
- Product linkage/listing for live sessions should be validated in payload shape before Flutter UI hard-depends on it.

### Live payment methods
- **Status**: Current but needs mobile review
- Confirm exact endpoint/shape used to expose creator payment methods in live room context.

### Live chat REST/WebSocket
- **REST**: `/api/live/{live_id}/chat/messages/` — **Status**: Current but needs mobile review (exact route placeholder verification required)
- **WebSocket**: `/ws/live/{live_id}/chat/?token=<jwt_access_token>` — **Status**: Current but needs mobile review (exact route placeholder verification required)
- **Mobile notes**:
  - Use JWT query token for websocket auth.
  - Implement reconnect/backoff and dedupe by message id.

### Mobile live scope boundary
- **Phase 1 Flutter live**: watching only (list/detail/status/playback/chat/product display).
- **Later phase**: mobile live publishing.
- **Important**: do not assume browser WebRTC `prepare` payload is directly usable in Flutter SDK pipelines without adapter work.

---

## 9) Upload / creator endpoints

### Video upload/create
- **POST `/api/videos/`** — **Status**: Current but needs mobile review
- **GET `/api/videos/`** — **Status**: Current (owner scope)
- **GET/PATCH/DELETE `/api/videos/{id}/`** — **Status**: Current (owner scope)

### Mobile notes
- Multipart upload is currently supported.
- Large file strategy is **Proposed** for hardening:
  - resumable/chunked upload support or explicit size/time/network retry policy.
- Thumbnail handling exists via upload/update fields and regenerate endpoint.
- Creator permission requirement:
  - Validate creator-gated flows from capability/profile fields for upload/live creation UX.

---

## 10) Seller / store / product endpoints

- **Status**: Current but needs mobile review
- Profile currently exposes seller/capability fields (`is_seller`, `can_manage_store`, `can_accept_payments`, `seller_store`).
- `SellerStore` remains the source of truth for seller capability; approved applications create a `SellerStore` automatically.
- Related store/product/order surfaces are present in backend route inventory but mobile contract shape needs consolidation.

### Seller application endpoints

#### POST `/api/seller-applications/`
- **Status**: Current
- **Auth**: Bearer access token required
- **Purpose**: submit an application to become a seller without directly creating a store.
- **Request body**:
  ```json
  {
    "store_name": "Alice Handmade",
    "business_type": "individual",
    "business_description": "Handmade goods and accessories.",
    "contact_phone": "+15551234567",
    "contact_email": "alice@example.com",
    "business_license_url": ""
  }
  ```
- **Validation**:
  - `business_type` must be `individual` or `company`.
  - `business_license_url` is required when `business_type=company`.
  - A user with an existing pending application receives `409`.
  - A user who already has a `SellerStore` receives `409` (`already seller`).
- **Success response**: `201`
  ```json
  {
    "id": 12,
    "store_name": "Alice Handmade",
    "business_type": "individual",
    "business_description": "Handmade goods and accessories.",
    "contact_phone": "+15551234567",
    "contact_email": "alice@example.com",
    "business_license_url": "",
    "status": "pending",
    "rejection_reason": "",
    "submitted_at": "2026-05-31T12:00:00Z",
    "reviewed_at": null
  }
  ```

#### GET `/api/seller-applications/me/`
- **Status**: Current
- **Auth**: Bearer access token required
- **Purpose**: return the current user's latest seller application.
- **Success response**: `200`, same fields as `POST /api/seller-applications/`.
- **No application response**: `404` with `{ "detail": "Seller application not found." }`.

#### GET `/api/admin/seller-applications/`
- **Status**: Current
- **Auth**: staff/superuser only
- **Purpose**: list seller applications for review. Optional query param: `status=pending|approved|rejected`.

#### POST `/api/admin/seller-applications/{id}/approve/`
- **Status**: Current
- **Auth**: staff/superuser only
- **Purpose**: approve an application and create the user's `SellerStore` if one does not already exist.
- **Success response**: `200`
  ```json
  {
    "application": { "id": 12, "status": "approved", "reviewed_at": "2026-05-31T12:05:00Z" },
    "store": { "id": 7, "name": "Alice Handmade", "slug": "alice-handmade" }
  }
  ```

#### POST `/api/admin/seller-applications/{id}/reject/`
- **Status**: Current
- **Auth**: staff/superuser only
- **Request body**: `{ "rejection_reason": "Please provide a valid business license." }`
- **Success response**: `200`, application fields with `status=rejected` and `rejection_reason`.

### Store endpoint protection

#### POST `/api/store/me/`
- **Status**: Current with seller-application gate
- **Auth**: Bearer access token required
- **Behavior**:
  - Users with an existing `SellerStore` still receive `409`.
  - Users without an approved seller application receive `403`.
  - Approved applications normally create the store during staff approval, so mobile should treat `/api/store/me/` primarily as read/edit for the current store.

### Mobile ACCOUNT block logic
- `is_seller=true`: show Seller Studio.
- `is_seller=false` and `GET /api/seller-applications/me/` returns `404`: show "Apply to open a store".
- Latest application `status=pending`: show "Under review".
- Latest application `status=rejected`: show "Application rejected, apply again" and display `rejection_reason`.
- Latest application `status=approved` but profile still has no `seller_store`: refresh profile, then retry/show a transient retry prompt.

### Mobile notes
- First mobile phase can keep seller management hidden/read-only.
- Seller tooling can be added later.
- Gate seller UI from `can_manage_store` rather than hardcoded role names.

---

## 11) Recommended mobile integration phases

1. **M1**: Auth + API client foundation (token lifecycle, retry, error mapping)
2. **M2**: Public home feed + shorts feed
3. **M3**: Profile
4. **M4**: Membership
5. **M5**: Live watching
6. **M6**: Upload / creator tools
7. **M7**: Seller tools
8. **M8**: Mobile live publishing

---

## 12) Open questions / backend cleanup checklist

1. Confirm all media URLs are absolute HTTPS in mobile-consumed responses.
2. Confirm pagination shape consistency (`count/next/previous/results`) across all list endpoints.
3. Standardize mobile error format rules for common APIs (`detail` / `message` / `code`) and document exact fallback order.
4. Add a stable public-video mobile DTO so Flutter does not guess between `file_url` / `video_url` / `playback_url`.
5. Confirm `duration` field existence; if unavailable, do not keep it in Current mobile target DTO.
6. Write and freeze membership order create request serializer contract (`plan_code`, `plan_id`, or both; required/optional rules).
7. Publish official mobile live chat routes for REST and WebSocket (path params, auth token placement, and examples).
8. Confirm live playback URL field for Flutter player.
9. Confirm CORS remains web concern, while mobile still requires correct HTTPS domains and allowed hosts config.
10. Confirm token refresh behavior (timing, invalid refresh handling, concurrent refresh race strategy).
11. Confirm whether app home feed should reuse `/api/public/videos/` or introduce dedicated feed endpoint.
12. If Shorts is a vertical-first experience, evaluate dedicated feed endpoint such as `/api/app/shorts/` or `/api/mobile/feed/`.
13. Confirm whether to create broader dedicated `/api/mobile/*` or `/api/app/*` namespace.
14. Confirm mobile-safe live publish contract separate from browser WebRTC adaptor assumptions.

