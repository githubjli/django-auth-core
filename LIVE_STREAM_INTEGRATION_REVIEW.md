# Live Streaming Integration Review (Backend ↔ Frontend)

## Scope reviewed
- `API_CONTRACT_SUMMARY.md`
- `CONTENT_LAYER_NEXT_STEP.md`
- Django live-stream model/view/serializer/service/test code

This review focuses on the current live-stream flow (`create -> prepare -> start -> poll status/detail -> end`) and highlights likely integration mismatches or improvement opportunities for frontend reliability.

---

## Current flow (as implemented)
1. Frontend creates a stream via `POST /api/live/create/`.
2. Frontend calls `POST /api/live/{id}/prepare/` to get browser publish config (`publish_session.ant_media`).
3. Frontend starts publishing media directly to Ant Media (WebRTC adaptor) using returned config.
4. Frontend reads stream state via `GET /api/live/{id}/` or `GET /api/live/{id}/status/`.
5. Owner can call `POST /api/live/{id}/start/` and `POST /api/live/{id}/end/` as Django control actions.

---

## Potential mismatches / risks

### 1) `stream_key` is exposed to anonymous/public responses
`LiveStreamSerializer` always includes `stream_key`, and public users can fetch public stream detail/list. This effectively exposes the broadcast credential-like identifier in public API payloads.

**Why this matters for frontend integration:**
- The frontend may unknowingly leak `stream_key` into logs/client telemetry.
- Public viewers do not need publish credentials.

**Suggested backend improvement:**
- Split serializer output by role (owner vs viewer) or conditionally redact `stream_key` unless requester is owner/staff.

### 2) `watch_url` is backend-host-derived but intended as frontend route
`watch_url` is generated using `request.build_absolute_uri('/live/{id}')`. In a separated frontend/backend deployment, this can produce a backend-domain URL for a frontend page route.

**Why this matters for frontend integration:**
- Share links can point to the API host rather than web app host.
- Frontend may need to ignore or rewrite `watch_url`, creating inconsistent behavior across clients.

**Suggested backend improvement:**
- Introduce `FRONTEND_BASE_URL` setting and construct `watch_url` from it, or return `watch_path` separately and let frontend compose full URL.

### 3) Read endpoints have side effects on DB status
Status normalization (`normalize_stream_fields`) can update `LiveStream.status` during reads when Ant Media reports `broadcasting` or `finished`.

**Why this matters for frontend integration:**
- Polling detail/status endpoints can mutate server state, making debugging replay difficult.
- UI timeline events can look inconsistent (state changed by read, not explicit action).

**Suggested backend improvement:**
- Prefer explicit sync job/webhook/command path for state writes; keep read endpoints side-effect-free.

### 4) `can_start` / `can_end` are state-only, not capability-aware
`can_start` and `can_end` are derived from status only. They do not reflect permission/ownership even on public detail endpoints.

**Why this matters for frontend integration:**
- Non-owner viewers can see `can_start: true` or `can_end: true` and UI can incorrectly render controls unless frontend adds extra permission checks.

**Suggested backend improvement:**
- Add capability fields that include authz context (e.g., `viewer_can_start`, `viewer_can_end`) and keep current fields for backward compatibility if needed.

### 5) Start/end actions are not idempotency-guarded
- Repeated `start` calls can overwrite `started_at`.
- `end` can be called from idle and will backfill `started_at` at end-time.

**Why this matters for frontend integration:**
- Retries and double-clicks can corrupt stream lifecycle timestamps.
- Analytics/session duration can be distorted.

**Suggested backend improvement:**
- Enforce transition guards (idle->live->ended), return 409 on invalid transitions, and keep first `started_at`.

### 6) `/status/` endpoint is contract-duplicate of detail
`GET /api/live/{id}/status/` currently returns full serializer payload (same core shape as detail), including fields not required for high-frequency polling.

**Why this matters for frontend integration:**
- Higher payload size and compute cost during frequent polling.
- No explicit “poll-optimized” contract for frontend real-time loop.

**Suggested backend improvement:**
- Introduce a lightweight status serializer for `/status/` with only polling fields (`status`, `effective_status`, `viewer_count`, `message`, timestamps, maybe sync metadata).

### 7) Viewer count fallback path is effectively static unless external sync is enabled
`viewer_count` DB field is returned as fallback, but no viewer heartbeat/update endpoint is implemented in this backend.

**Why this matters for frontend integration:**
- Frontend may interpret `viewer_count` as real-time even when it is stale.

**Suggested backend improvement:**
- Clarify semantics in contract docs (`estimated`, `source`) and/or add a backend update mechanism when Ant Media sync is unavailable.

---

## Priority recommendations (smallest safe changes)
1. **Security first:** redact `stream_key` for non-owners.
2. **Link correctness:** make `watch_url` frontend-base aware.
3. **Lifecycle safety:** add start/end transition guards.
4. **Polling optimization:** slim `/status/` response contract.
5. **Capability clarity:** add permission-aware action flags.

---

## Frontend integration notes (actionable)
- Treat `status` as computed API status (`ready|live|ended|waiting_for_signal`), not DB enum.
- Do not rely on `watch_url` being correct cross-domain unless backend adds frontend-base support.
- Do not render owner controls from `can_start`/`can_end` alone; gate by ownership/auth.
- Prefer `/status/` for polling today, but expect future payload minimization.
