# APP_API_CONTRACT_SHORT_DRAMA

This document is the Flutter-facing API contract aligned to the **current backend implementation**.

## Naming and currency rules (authoritative)

- Platform credit name: **Meow Points**
- Payment token symbol: **THB-LTT**
- Payment token full name: **LTT Thai Baht Stablecoin**
- Blockchain: **LTT**
- Peg: **1 THB-LTT = 1 THB**

Rules:

- Flutter must not hardcode exchange rates.
- Exchange rate/package snapshots are backend-controlled.
- Flutter should display THB-LTT only in purchase/payment contexts.

---

## A. Drama read APIs

### 1) GET /api/dramas/

- **Auth**: Optional
- **Request**: `?page=&page_size=&category=` optional
- **Response shape**: paginated series list with personalized fields (`is_favorited`, `continue_episode_no`, `continue_progress_seconds`) when authenticated.
- **Frontend notes**:
  - Anonymous users should treat personalized fields as defaults.
- **Errors**: standard paginated endpoint errors (400 for invalid params).
- **Idempotency**: read-only.

### 2) GET /api/dramas/{id}/

- **Auth**: Optional
- **Request**: path param `id`
- **Response shape**: single series with same personalized fields as list.
- **Frontend notes**: same default handling for anonymous users.
- **Errors**: `404` if series not active/published/not found.
- **Idempotency**: read-only.

### 3) GET /api/dramas/{id}/episodes/

- **Auth**: Optional (recommended authenticated)
- **Request**: path param `id`
- **Response shape**:
  - `series_id`
  - `episodes[]` containing:
    - `id`, `series_id`, `episode_no`, `title`, `duration_seconds`
    - `unlock_type`, `is_free`, `meow_points_price`, `points_price`
    - `can_watch`, `is_unlocked`, `is_locked`
    - `playback_url`, `video_url`, `hls_url`
- **Frontend notes**:
  - Use `can_watch` as playback gate.
  - `playback_url` is only valid when `can_watch=true`.
  - Locked episodes should show unlock UI.
- **Errors**: `404` for unavailable series.
- **Idempotency**: read-only.

### 4) GET /api/dramas/{id}/episodes/{episode_no}/

- **Auth**: Optional
- **Request**: path params `id`, `episode_no`
- **Response shape**: single episode with same access fields as episode list.
- **Frontend notes**: same as episode list.
- **Errors**: `404` if series/episode not accessible.
- **Idempotency**: read-only.

---

## B. Drama retention APIs

### 1) POST /api/dramas/{id}/progress/

- **Auth**: Required
- **Request**:

```json
{
  "episode_id": 101,
  "progress_seconds": 85,
  "completed": false
}
```

- **Response shape**:

```json
{
  "series_id": 10,
  "episode_id": 101,
  "episode_no": 1,
  "progress_seconds": 85,
  "completed": false,
  "updated_at": "2026-04-28T00:00:00Z"
}
```

- **Frontend notes**: call repeatedly while watching; latest values overwrite by series context.
- **Errors**: `400` invalid payload; `404` invalid series/episode relation.
- **Idempotency**: upsert-style (same series can be updated repeatedly).

### 2) POST /api/dramas/{id}/favorite/

- **Auth**: Required
- **Request**: empty body
- **Response shape**:

```json
{
  "series_id": 10,
  "is_favorited": true,
  "favorite_count": 8801
}
```

- **Frontend notes**: safe to call even if already favorited.
- **Errors**: `404` invalid series.
- **Idempotency**: idempotent target state (`is_favorited=true`).

### 3) DELETE /api/dramas/{id}/favorite/

- **Auth**: Required
- **Request**: empty body
- **Response shape**:

```json
{
  "series_id": 10,
  "is_favorited": false,
  "favorite_count": 8800
}
```

- **Frontend notes**: safe to call even if already unfavorited.
- **Errors**: `404` invalid series.
- **Idempotency**: idempotent target state (`is_favorited=false`).

### 4) GET /api/account/drama-progress/

- **Auth**: Required
- **Request**: pagination query optional
- **Response shape**: paginated continue-watching list:
  - `series_id`, `series_title`, `cover_url`
  - `episode_id`, `episode_no`, `progress_seconds`, `duration_seconds`, `updated_at`
- **Frontend notes**: display continue cards ordered by recency.
- **Errors**: `401` unauthenticated.
- **Idempotency**: read-only.

### 5) GET /api/account/drama-favorites/

- **Auth**: Required
- **Request**: pagination query optional
- **Response shape**: paginated favorite series list:
  - `id`, `title`, `cover_url`, `total_episodes`, `favorited_at`
- **Frontend notes**: user-scoped list only.
- **Errors**: `401` unauthenticated.
- **Idempotency**: read-only.

---

## C. Drama unlock API

### POST /api/dramas/episodes/{episode_id}/unlock/

- **Auth**: Required
- **Request**: empty body
- **Response shape**:

```json
{
  "episode_id": 102,
  "series_id": 10,
  "is_unlocked": true,
  "points_charged": 30
}
```

- **Frontend notes**:
  - If already unlocked, `points_charged` returns `0`.
  - After success, refresh episode list/detail to get `can_watch` + `playback_url`.
- **Errors**:
  - `400` with code `insufficient_balance`:

```json
{
  "code": "insufficient_balance",
  "detail": "Insufficient Meow Points balance."
}
```

  - `401` unauthenticated
  - `404` episode not available
- **Idempotency**: idempotent for already-unlocked episode (no double charge).

---

## D. Meow Points wallet/package/ledger APIs

### 1) GET /api/meow-points/wallet/

- **Auth**: Required
- **Request**: none
- **Response shape**:

```json
{
  "balance": 1200,
  "total_earned": 1400,
  "total_spent": 200,
  "total_purchased": 1300,
  "total_bonus": 100,
  "created_at": "...",
  "updated_at": "..."
}
```

- **Frontend notes**: wallet is auto-created if missing.
- **Errors**: `401` unauthenticated.
- **Idempotency**: read-only.

### 2) GET /api/meow-points/packages/

- **Auth**: Required
- **Request**: none
- **Response shape**: active package array with:
  - `code`, `name`, `points_amount`, `bonus_points`, `total_points`
  - `price_amount`, `price_currency`, `status`, `sort_order`, `description`
- **Frontend notes**: display THB-LTT pricing in purchase context only.
- **Errors**: `401` unauthenticated.
- **Idempotency**: read-only.

### 3) GET /api/meow-points/ledger/

- **Auth**: Required
- **Request**: pagination query optional
- **Response shape**: paginated user-scoped ledger entries with:
  - `entry_type`, signed `amount`, `balance_before`, `balance_after`, targets, note, timestamps
- **Frontend notes**: use signed `amount` for credit/debit UI.
- **Errors**: `401` unauthenticated.
- **Idempotency**: read-only.

---

## E. Meow Points order APIs

### 1) POST /api/meow-points/orders/

- **Auth**: Required
- **Request**:

```json
{
  "package_code": "starter_100"
}
```

- **Response shape**: created `MeowPointPurchase` snapshot payload:
  - `order_no`, package snapshots, points snapshots, price snapshots
  - purchase `status`
  - `payment_order_status`, `txid`, timestamps
- **Frontend notes**:
  - order amount/currency shown from response snapshot.
  - then proceed to payment UX.
- **Errors**:
  - `400` invalid/empty package code
  - `400` inactive/nonexistent package
  - `401` unauthenticated
- **Idempotency**: non-idempotent creation (each call creates a new order).

### 2) GET /api/meow-points/orders/

- **Auth**: Required
- **Request**: pagination query optional
- **Response shape**: paginated current-user purchase orders.
- **Frontend notes**: use for order history and pending payments.
- **Errors**: `401` unauthenticated.
- **Idempotency**: read-only.

### 3) GET /api/meow-points/orders/{order_no}/

- **Auth**: Required
- **Request**: path param `order_no`
- **Response shape**: one purchase order snapshot payload.
- **Frontend notes**: poll detail after payment submission.
- **Errors**: `401`, `404`.
- **Idempotency**: read-only.

### 4) POST /api/meow-points/orders/{order_no}/tx-hint/

- **Auth**: Required
- **Request**:

```json
{
  "txid": "abc123..."
}
```

- **Response shape**:

```json
{
  "order_no": "MP20260428ABCD1234",
  "txid_hint": "abc123...",
  "status": "pending",
  "detail": "txid hint recorded; payment confirmation is still required."
}
```

- **Frontend notes**:
  - tx-hint only records txid on eligible payment-order states.
  - it does not guarantee immediate credit.
- **Errors**: `400` invalid txid, `401`, `404`.
- **Idempotency**: idempotent-like for repeated same txid hint; no direct double-credit behavior.

---

## F. Gift APIs

### 1) GET /api/gifts/

- **Auth**: Optional
- **Request**: none
- **Response shape**: active gift array:
  - `code`, `name`, `icon_url`, `animation_url`, `points_price`, `is_active`, `sort_order`
- **Frontend notes**: render gifting panel from this list.
- **Errors**: standard read endpoint errors.
- **Idempotency**: read-only.

### 2) POST /api/live/{live_id}/gifts/send/

- **Auth**: Required
- **Request**:

```json
{
  "gift_code": "rose",
  "quantity": 3
}
```

- **Response shape**:

```json
{
  "id": 1,
  "gift_name_snapshot": "Rose",
  "points_price_snapshot": 10,
  "quantity": 3,
  "total_points": 30,
  "created_at": "..."
}
```

- **Frontend notes**:
  - deduct preview = `points_price * quantity` before submit.
  - refresh wallet after successful send.
- **Errors**:
  - `400` inactive gift
  - `400` invalid quantity
  - `400` insufficient balance (code `insufficient_balance`)
  - `401` unauthenticated
  - `404` live stream or gift not found
- **Idempotency**: non-idempotent (each successful call is a new spend/send action).

---

## Episode access field usage (Flutter)

- `can_watch` controls playback availability.
- `playback_url` is only usable when `can_watch=true`.
- `points_price` is Meow Points price for point-based locked episodes.
- `is_unlocked` means user currently has access.
- Membership episodes can become watchable via active membership.
- If locked, show unlock UI instead of starting player.

---

## Current implementation status

### Implemented

- Drama read APIs
- Progress/favorites APIs
- Drama unlock spending API
- Meow Points wallet/packages/ledger APIs
- Meow Points purchase orders with THB-LTT `PaymentOrder` linkage
- Gifts and gift spending APIs

### Deferred / pending (still true)

- Production-grade payment confirmation automation and ops workflow hardening
- Real mobile wallet UX polish and end-to-end production settlement UX
- Video player/CDN production hardening and full playback QoS handling
- Flutter full integration rollout and UX iteration
