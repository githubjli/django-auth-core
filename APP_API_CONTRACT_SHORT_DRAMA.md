# APP_API_CONTRACT_SHORT_DRAMA

This document defines the initial backend-frontend API contract between Django backend and Flutter app for short-drama and Meow Points features.

## Naming and currency rules

- Platform credit name in all app-credit contexts: **Meow Points**
- Payment token symbol in payment contexts only: **THB-LTT**
- Payment token full name: **LTT Thai Baht Stablecoin**
- Blockchain: **LTT**
- Peg reference: **1 THB-LTT = 1 THB**
- Flutter must not hardcode conversion rate.
- Flutter should render backend-provided `exchange_rate_label`.

---

## A. Short drama APIs

### 1) GET /api/dramas/

**Purpose**: List drama series for home sections.

**Auth**: Optional JWT Bearer (recommended authenticated; when anonymous, user-personalized fields default safely).

**Request example**:

```http
GET /api/dramas/?page=1&page_size=20
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 10,
      "title": "Bangkok Hearts",
      "description": "A fast-paced city romance.",
      "cover_url": "https://cdn.example.com/dramas/10/cover.jpg",
      "tags": ["romance", "urban"],
      "total_episodes": 24,
      "free_episode_count": 3,
      "locked_episode_count": 21,
      "view_count": 156900,
      "favorite_count": 8490,
      "is_favorited": true,
      "continue_episode_no": 7,
      "continue_progress_seconds": 85
    }
  ]
}
```

**Frontend notes**:

- Use `continue_episode_no` and `continue_progress_seconds` to show “Continue Watching”.
- For anonymous users, backend may return `is_favorited=false` and null/0 continue fields.

---

### 2) GET /api/dramas/{id}/

**Purpose**: Get drama series detail.

**Auth**: Optional JWT Bearer.

**Request example**:

```http
GET /api/dramas/10/
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "id": 10,
  "title": "Bangkok Hearts",
  "description": "A fast-paced city romance.",
  "cover_url": "https://cdn.example.com/dramas/10/cover.jpg",
  "tags": ["romance", "urban"],
  "total_episodes": 24,
  "free_episode_count": 3,
  "locked_episode_count": 21,
  "view_count": 156900,
  "favorite_count": 8490,
  "is_favorited": true,
  "continue_episode_no": 7,
  "continue_progress_seconds": 85
}
```

---

### 3) GET /api/dramas/{id}/episodes/

**Purpose**: List episodes for one drama series.

**Auth**: Optional JWT Bearer.

**Request example**:

```http
GET /api/dramas/10/episodes/
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "series_id": 10,
  "episodes": [
    {
      "id": 101,
      "series_id": 10,
      "episode_no": 1,
      "title": "Episode 1",
      "duration_seconds": 95,
      "video_url": "https://cdn.example.com/dramas/10/e01.mp4",
      "hls_url": "https://cdn.example.com/dramas/10/e01.m3u8",
      "is_free": true,
      "unlock_type": "free",
      "meow_points_price": 0,
      "is_locked": false,
      "is_unlocked": true
    },
    {
      "id": 102,
      "series_id": 10,
      "episode_no": 2,
      "title": "Episode 2",
      "duration_seconds": 99,
      "video_url": "https://cdn.example.com/dramas/10/e02.mp4",
      "hls_url": "https://cdn.example.com/dramas/10/e02.m3u8",
      "is_free": false,
      "unlock_type": "meow_points",
      "meow_points_price": 30,
      "is_locked": true,
      "is_unlocked": false
    }
  ]
}
```

**Frontend notes**:

- Treat `is_locked` as canonical gating flag.
- `unlock_type` may be `free`, `meow_points`, `membership`, or `ad_reward`.

---

### 4) GET /api/dramas/{id}/episodes/{episode_no}/

**Purpose**: Get one episode detail.

**Auth**: Optional JWT Bearer.

**Request example**:

```http
GET /api/dramas/10/episodes/2/
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "id": 102,
  "series_id": 10,
  "episode_no": 2,
  "title": "Episode 2",
  "duration_seconds": 99,
  "video_url": "https://cdn.example.com/dramas/10/e02.mp4",
  "hls_url": "https://cdn.example.com/dramas/10/e02.m3u8",
  "is_free": false,
  "unlock_type": "meow_points",
  "meow_points_price": 30,
  "is_locked": true,
  "is_unlocked": false
}
```

---

### 5) POST /api/dramas/{id}/progress/

**Purpose**: Save watch progress.

**Auth**: Required JWT Bearer.

**Request example**:

```http
POST /api/dramas/10/progress/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "episode_id": 101,
  "progress_seconds": 85,
  "completed": false
}
```

**Response example**:

```json
{
  "ok": true,
  "series_id": 10,
  "episode_id": 101,
  "progress_seconds": 85,
  "completed": false,
  "updated_at": "2026-04-27T08:00:00Z"
}
```

---

### 6) POST /api/dramas/{id}/favorite/

**Purpose**: Favorite drama.

**Auth**: Required JWT Bearer.

**Request example**:

```http
POST /api/dramas/10/favorite/
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "series_id": 10,
  "is_favorited": true
}
```

---

### 7) DELETE /api/dramas/{id}/favorite/

**Purpose**: Unfavorite drama.

**Auth**: Required JWT Bearer.

**Request example**:

```http
DELETE /api/dramas/10/favorite/
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "series_id": 10,
  "is_favorited": false
}
```

---

### 8) GET /api/account/drama-progress/

**Purpose**: Continue watching list.

**Auth**: Required JWT Bearer.

**Request example**:

```http
GET /api/account/drama-progress/?page=1&page_size=20
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "series_id": 10,
      "series_title": "Bangkok Hearts",
      "cover_url": "https://cdn.example.com/dramas/10/cover.jpg",
      "episode_id": 107,
      "episode_no": 7,
      "progress_seconds": 85,
      "duration_seconds": 102,
      "updated_at": "2026-04-27T08:00:00Z"
    }
  ]
}
```

---

### 9) GET /api/account/drama-favorites/

**Purpose**: User favorite drama list.

**Auth**: Required JWT Bearer.

**Request example**:

```http
GET /api/account/drama-favorites/?page=1&page_size=20
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 10,
      "title": "Bangkok Hearts",
      "cover_url": "https://cdn.example.com/dramas/10/cover.jpg",
      "total_episodes": 24,
      "favorited_at": "2026-04-20T10:00:00Z"
    }
  ]
}
```

---

## B. Meow Points APIs

### 1) GET /api/meow-points/me/

**Purpose**: Get current user Meow Points balance.

**Auth**: Required JWT Bearer.

**Request example**:

```http
GET /api/meow-points/me/
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "balance": 1250,
  "display_name": "Meow Points",
  "unit": "points"
}
```

---

### 2) GET /api/meow-points/packages/

**Purpose**: List packages purchasable with THB-LTT.

**Auth**: Required JWT Bearer.

**Request example**:

```http
GET /api/meow-points/packages/
Authorization: Bearer <access_token>
```

**Response example**:

```json
[
  {
    "id": 1,
    "name": "Starter Pack",
    "points_amount": 1000,
    "bonus_points": 0,
    "total_points": 1000,
    "payment_amount": "100.00",
    "payment_currency": "THB-LTT",
    "blockchain": "LTT",
    "token_name": "LTT Thai Baht Stablecoin",
    "exchange_rate": "10.00000000",
    "exchange_rate_label": "1 THB-LTT = 10 Meow Points",
    "is_active": true
  }
]
```

**Frontend notes**:

- Purchase UI should show `payment_amount` + `payment_currency`.
- Rate text should come from `exchange_rate_label`; do not format from hardcoded constants.

---

### 3) GET /api/meow-points/transactions/

**Purpose**: List Meow Points transaction history.

**Auth**: Required JWT Bearer.

**Supported `tx_type` values**:

- `purchase`
- `spend_episode_unlock`
- `spend_live_gift`
- `spend_membership_exchange`
- `reward_checkin`
- `reward_watch`
- `reward_ad`
- `admin_adjust`
- `refund`

**Request example**:

```http
GET /api/meow-points/transactions/?page=1&page_size=20
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 9002,
      "tx_type": "spend_episode_unlock",
      "direction": "debit",
      "amount": 30,
      "balance_after": 1220,
      "remark": "Unlock episode 2",
      "created_at": "2026-04-27T08:20:00Z"
    },
    {
      "id": 9001,
      "tx_type": "purchase",
      "direction": "credit",
      "amount": 1000,
      "balance_after": 1250,
      "remark": "Purchase order MP202604270001",
      "created_at": "2026-04-27T08:00:00Z"
    }
  ]
}
```

---

### 4) POST /api/meow-points/purchase-orders/

**Purpose**: Create a Meow Points purchase order.

**Auth**: Required JWT Bearer.

**Idempotency**: Required (`idempotency_key` must be unique per user+operation intent).

**Request example**:

```http
POST /api/meow-points/purchase-orders/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "package_id": 1,
  "idempotency_key": "client-generated-key"
}
```

**Response example**:

```json
{
  "order_no": "MP202604270001",
  "status": "pending",
  "total_points": 1000,
  "payment_amount": "100.00",
  "payment_currency": "THB-LTT",
  "blockchain": "LTT",
  "token_name": "LTT Thai Baht Stablecoin",
  "pay_to_address": "ltt1qexampleaddress",
  "exchange_rate_snapshot": "10.00000000",
  "exchange_rate_label": "1 THB-LTT = 10 Meow Points",
  "expires_at": "2026-04-27T08:30:00Z"
}
```

---

### 5) GET /api/meow-points/purchase-orders/{order_no}/

**Purpose**: Get purchase order status.

**Auth**: Required JWT Bearer.

**Request example**:

```http
GET /api/meow-points/purchase-orders/MP202604270001/
Authorization: Bearer <access_token>
```

**Response example**:

```json
{
  "order_no": "MP202604270001",
  "status": "paid",
  "total_points": 1000,
  "payment_amount": "100.00",
  "payment_currency": "THB-LTT",
  "paid_at": "2026-04-27T08:02:10Z"
}
```

---

## C. Episode unlock API

### 1) POST /api/episodes/{id}/unlock/

**Purpose**: Unlock a locked drama episode using Meow Points.

**Auth**: Required JWT Bearer.

**Idempotency**: Required.

**Request example**:

```http
POST /api/episodes/101/unlock/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "idempotency_key": "client-generated-key"
}
```

**Response example**:

```json
{
  "episode_id": 101,
  "is_unlocked": true,
  "spent_points": 30,
  "balance_after": 1220
}
```

---

## D. Membership exchange APIs

### 1) GET /api/meow-points/membership-exchange-rules/

**Purpose**: List rules for exchanging Meow Points for membership.

**Auth**: Required JWT Bearer.

**Request example**:

```http
GET /api/meow-points/membership-exchange-rules/
Authorization: Bearer <access_token>
```

**Response example**:

```json
[
  {
    "id": 1,
    "membership_plan": "monthly",
    "required_points": 300,
    "duration_days": 30,
    "is_active": true
  }
]
```

### 2) POST /api/meow-points/exchange-membership/

**Purpose**: Exchange Meow Points for membership.

**Auth**: Required JWT Bearer.

**Idempotency**: Required.

**Request example**:

```http
POST /api/meow-points/exchange-membership/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "rule_id": 1,
  "idempotency_key": "client-generated-key"
}
```

**Response example**:

```json
{
  "ok": true,
  "membership_plan": "monthly",
  "spent_points": 300,
  "balance_after": 920,
  "membership_expire_at": "2026-05-27T09:00:00Z"
}
```

---

## E. Live gift APIs

### 1) GET /api/live-gifts/

**Purpose**: List available gifts.

**Auth**: Required JWT Bearer.

**Request example**:

```http
GET /api/live-gifts/
Authorization: Bearer <access_token>
```

**Response example**:

```json
[
  {
    "id": 1,
    "name": "Meow Rose",
    "icon_url": "https://cdn.example.com/gifts/rose.png",
    "meow_points_price": 10,
    "animation_type": "basic",
    "is_active": true,
    "sort_order": 1
  }
]
```

### 2) POST /api/live/{id}/gifts/

**Purpose**: Send gift in live room using Meow Points.

**Auth**: Required JWT Bearer.

**Idempotency**: Required.

**Request example**:

```http
POST /api/live/88/gifts/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "gift_id": 1,
  "quantity": 3,
  "idempotency_key": "client-generated-key"
}
```

**Response example**:

```json
{
  "gift_order_id": 70012,
  "spent_points": 30,
  "balance_after": 1190,
  "live_event": {
    "type": "gift_sent",
    "placeholder": true
  }
}
```

---

## F. Common API behavior

### Authentication

- Protected endpoints require `Authorization: Bearer <JWT access token>`.
- Unauthenticated access to protected endpoints returns `401 Unauthorized`.

### Pagination recommendation

Recommended list response shape:

```json
{
  "count": 0,
  "next": null,
  "previous": null,
  "results": []
}
```

### Error format recommendation

Recommended error shape:

```json
{
  "error": {
    "code": "insufficient_meow_points",
    "message": "Insufficient Meow Points balance.",
    "details": {}
  }
}
```

### Idempotency requirement

These operations should require `idempotency_key`:

- Create Meow Points purchase order
- Episode unlock spend
- Membership exchange
- Live gift send

On duplicate key with same semantic request, backend should return existing successful result (or current operation state), not double-charge.

### Locked episode behavior

- Locked episode response should clearly expose `is_locked=true` and `unlock_type`.
- Playback endpoints (if separated later) should deny stream for locked/unentitled users.

### Insufficient balance behavior

- For spend endpoints, return `400` or `409` with stable error code such as `insufficient_meow_points`.

### Expired purchase order behavior

- If `expires_at` passed before valid payment confirmation, order transitions to `expired`.
- Expired order cannot be paid/credited unless explicitly reopened by backend policy.

### Duplicate unlock behavior

- Unlocking an already unlocked episode should be idempotent:
  - Return `is_unlocked=true`
  - `spent_points=0` or original spend reference (backend policy consistent)
  - Must not deduct points twice

### Purchase order status values

Recommended canonical statuses:

- `pending`
- `paid`
- `expired`
- `cancelled`
- `failed`

### Frontend display notes

- Flutter should display **Meow Points** for balance and spending UI.
- Flutter should display **THB-LTT** only in purchase/payment UI.
- Flutter must not hardcode exchange rates.
- Flutter should rely on backend `exchange_rate_label` for display text.
