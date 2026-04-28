# SHORT_DRAMA_AND_MEOW_POINTS_PROPOSAL

## 1. Product direction

The mobile app should prioritize a short-drama-first experience before expanding other content/business layers.

Core journey:

- Drama series as the main content container
- Ordered episodes within each series
- Vertical episode player optimized for mobile short-form viewing
- Continue watching across sessions/devices
- User favorites
- Episode access control (free / Meow Points / membership)
- Meow Points purchase and spend flows
- Live gift spending with Meow Points

## 2. Naming and currency terminology (authoritative)

- **Meow Points** = platform credit name (frontend + backend)
- **THB-LTT** = payment token used to purchase Meow Points
- **LTT** = blockchain network
- **LTT Thai Baht Stablecoin** = THB-LTT token full name
- **1 THB-LTT = 1 THB**

Rules:

- Flutter must not hardcode exchange rates.
- Package pricing and snapshots are backend-controlled.
- Flutter should display **THB-LTT** only in purchase/payment contexts.

## 3. Short-drama model layer (current implementation-aligned)

### DramaSeries

- Main drama container.
- One-to-many with `DramaEpisode`.
- One-to-many with `DramaFavorite`.
- One-to-many with `DramaWatchProgress` and `DramaUnlock`.

### DramaEpisode

- Episode metadata, ordering, and access strategy.
- `unlock_type` supports: `free`, `meow_points`, `membership`, `ad_reward`.

### DramaWatchProgress

- Per-user progress for continue watching.
- Current implementation semantics support continue-by-series.

### DramaFavorite

- Per-user favorite relation at series level.

### DramaUnlock

- Stores user entitlement at episode level.
- Fields include `source` (`meow_points` / `membership` / `free` / `admin` / `ad_reward`), `points_amount`, optional `ledger_entry`, and `unlocked_at`.
- Unique by `(user, episode)`.

## 4. Meow Points model layer (current implementation-aligned)

### MeowPointWallet

- One wallet per user.
- Tracks `balance`, `total_earned`, `total_spent`, `total_purchased`, `total_bonus`.

### MeowPointPackage

- Backend-managed package catalog for recharge.
- Includes points/bonus and THB-LTT price snapshot source.

### MeowPointLedger

- Signed ledger entries for all balance changes.
- Stores before/after balance, target linkage, and optional `payment_order`.

### MeowPointPurchase

- Recharge order domain model.
- Linked to `PaymentOrder` (OneToOne nullable).
- Stores package snapshots, price snapshots, status lifecycle, paid/credited timestamps.

### PaymentOrder integration

- `PaymentOrder.order_type` includes `meow_points_recharge`.
- `PaymentOrder.target_type = meow_point_purchase`.
- `PaymentOrder.target_id` points to `MeowPointPurchase.id`.
- `tx-hint` writes to `PaymentOrder.txid`.
- `credit_paid_purchase` is idempotent and credits wallet exactly once.

## 5. Gift model layer (current implementation-aligned)

### Gift

- Gift catalog (`code`, `name`, `icon`, `animation`, `points_price`, `is_active`, `sort_order`).

### GiftTransaction

- Spending record for sending gifts in live rooms.
- Includes sender/receiver/stream, gift snapshots, quantity, total points, optional ledger link.

## 6. API endpoints (implemented paths)

### Drama APIs

- `GET /api/dramas/`
- `GET /api/dramas/{id}/`
- `GET /api/dramas/{id}/episodes/`
- `GET /api/dramas/{id}/episodes/{episode_no}/`
- `POST /api/dramas/{id}/progress/`
- `POST /api/dramas/{id}/favorite/`
- `DELETE /api/dramas/{id}/favorite/`
- `GET /api/account/drama-progress/`
- `GET /api/account/drama-favorites/`
- `POST /api/dramas/episodes/{episode_id}/unlock/`

### Meow Points APIs

- `GET /api/meow-points/wallet/`
- `GET /api/meow-points/packages/`
- `GET /api/meow-points/ledger/`
- `POST /api/meow-points/orders/`
- `GET /api/meow-points/orders/`
- `GET /api/meow-points/orders/{order_no}/`
- `POST /api/meow-points/orders/{order_no}/tx-hint/`

### Gift APIs

- `GET /api/gifts/`
- `POST /api/live/{live_id}/gifts/send/`

## 7. Episode access contract notes (Flutter)

Episode payload includes:

- `can_watch`: playback permission gate
- `is_unlocked`: user has access
- `points_price`: Meow Points required for point-based locked episodes
- `playback_url`: only usable when `can_watch=true`

UI guidance:

- If `can_watch=false`, do not start player.
- If `can_watch=false` and episode is point-based, show unlock CTA with `points_price`.
- Membership episodes may become watchable when membership is active.
