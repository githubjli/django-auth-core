# SHORT_DRAMA_AND_MEOW_POINTS_PROPOSAL

## 1. Product direction

The mobile app should prioritize a short-drama-first experience before expanding other content/business layers. The initial user journey should center around:

- Drama series as the main content container
- Ordered episodes within each series
- Vertical episode player optimized for mobile short-form viewing
- Continue watching capability across sessions/devices
- User favorites for quick return and personalization
- Mixed locked/free episode strategy
- Meow Points-based paid unlocks
- Membership-based unlocks for selected episodes
- Future extension to live room gifting scenarios

This direction keeps product scope focused while building reusable account, entitlement, and monetization foundations.

## 2. Currency and credit model

To avoid ambiguity between blockchain payment and app credits, backend and Flutter should align on the following terms:

- **LTT** is the blockchain network.
- **THB-LTT** is the payment token symbol.
- **LTT Thai Baht Stablecoin** is the payment token full name.
- **1 THB-LTT = 1 THB** (peg definition).
- **Meow Points** are internal platform credits.
- **THB-LTT is used only to purchase Meow Points** in the wallet prototype flow.
- **Meow Points are used only inside the app** (episode unlock, membership exchange, gifts, rewards).
- Example conversion: **1 THB-LTT = 10 Meow Points**.
- Exchange rates must be backend-configurable (database/admin/config driven), not client-hardcoded.
- Flutter should display backend-returned labels (for example, `exchange_rate_label`) rather than deriving rate text locally.

## 3. Why the existing Video model is not enough

The existing generic video domain is not sufficient for short-drama product requirements because short-drama introduces structured narrative and monetization behaviors:

- Single video object != multi-episode drama series hierarchy
- Requires strict episode ordering and continuity semantics
- Needs per-user watch progress at episode granularity
- Needs locked/free logic per episode
- Needs episode-level Meow Points pricing
- Needs membership-only episode options
- Needs continue-watching aggregation by user
- Needs user favorites at series level
- Needs recommendation/ranking signals combining series, episode completion, favorites, and unlock behavior

In short: the drama experience needs content metadata + entitlement + engagement features that exceed a flat video model.

## 4. Proposed short-drama models

### DramaSeries

Suggested fields:

- `id`
- `title`
- `description`
- `cover_url`
- `poster_url` (optional)
- `tags` (array/json)
- `status` (draft/published/archived)
- `is_active`
- `publish_at`
- `view_count`
- `favorite_count`
- `created_at`, `updated_at`

Relationships:

- One-to-many with `DramaEpisode`
- One-to-many with `DramaFavorite`
- One-to-many with `DramaWatchProgress` (through episodes/series scoping)

### DramaEpisode

Suggested fields:

- `id`
- `series` (FK -> `DramaSeries`)
- `episode_no` (unique within series)
- `title`
- `description`
- `duration_seconds`
- `video_url`
- `hls_url`
- `thumbnail_url`
- `unlock_type` enum:
  - `free`
  - `meow_points`
  - `membership`
  - `ad_reward`
- `meow_points_price` (for `meow_points`)
- `is_active`
- `publish_at`
- `created_at`, `updated_at`

Relationships:

- Many-to-one with `DramaSeries`
- One-to-many with `DramaWatchProgress`
- One-to-many with `DramaEpisodeUnlock`

### DramaWatchProgress

Suggested fields:

- `id`
- `user` (FK)
- `series` (FK -> `DramaSeries`)
- `episode` (FK -> `DramaEpisode`)
- `progress_seconds`
- `completed` (bool)
- `last_watched_at`
- `created_at`, `updated_at`

Constraints:

- Unique (`user`, `episode`) for latest progress row semantics

### DramaFavorite

Suggested fields:

- `id`
- `user` (FK)
- `series` (FK -> `DramaSeries`)
- `created_at`

Constraints:

- Unique (`user`, `series`)

### DramaEpisodeUnlock

Suggested fields:

- `id`
- `user` (FK)
- `episode` (FK -> `DramaEpisode`)
- `unlock_source` (meow_points/membership/ad_reward/admin)
- `unlock_txn_id` (optional pointer to transaction/order)
- `unlocked_at`
- `expires_at` (nullable, if temporary unlock is ever needed)

Constraints:

- Unique (`user`, `episode`) for effective entitlement record

## 5. Proposed Meow Points models

### MeowPointAccount

Suggested fields:

- `id`
- `user` (OneToOne FK)
- `balance` (integer, stores **Meow Points**)
- `status`
- `created_at`, `updated_at`

### MeowPointTransaction

Suggested fields:

- `id`
- `user` (FK)
- `account` (FK -> `MeowPointAccount`)
- `tx_type` (purchase/spend/reward/refund/admin_adjust, etc.)
- `direction` (credit/debit)
- `amount` (positive integer points)
- `balance_before`
- `balance_after`
- `related_order_no` / `related_entity_type` / `related_entity_id`
- `idempotency_key` (nullable)
- `remark`
- `created_at`

Purpose:

- Ledger of every increase/decrease; no balance changes without a corresponding transaction row

### MeowPointPackage

Suggested fields:

- `id`
- `name`
- `points_amount`
- `bonus_points`
- `total_points`
- `payment_amount` (THB-LTT amount)
- `is_active`
- `sort_order`
- `created_at`, `updated_at`

Purpose:

- Defines purchasable packages shown to Flutter

### MeowPointExchangeRate

Suggested fields:

- `id`
- `payment_currency` (default `THB-LTT`)
- `blockchain` (default `LTT`)
- `rate` (Meow Points per 1 THB-LTT)
- `label_template` / computed label
- `effective_from`
- `effective_to` (nullable)
- `is_active`
- `created_at`

Purpose:

- Controls THB-LTT -> Meow Points conversion rate via backend config

### MeowPointPurchaseOrder

Suggested fields:

- `id`
- `order_no`
- `user` (FK)
- `package` (FK -> `MeowPointPackage`)
- `status` (pending/paid/expired/cancelled/failed)
- `payment_amount` (snapshot in THB-LTT)
- `payment_currency` (snapshot: `THB-LTT`)
- `blockchain` (snapshot: `LTT`)
- `token_name` (snapshot: `LTT Thai Baht Stablecoin`)
- `exchange_rate_snapshot`
- `exchange_rate_label_snapshot`
- `total_points` (snapshot)
- `pay_to_address`
- `wallet_payment_ref` (nullable)
- `idempotency_key`
- `expires_at`
- `paid_at` (nullable)
- `created_at`, `updated_at`

Clarifications:

- `MeowPointAccount.balance` stores Meow Points only.
- `MeowPointTransaction` records every credit/debit.
- `MeowPointPackage` defines what can be bought.
- `MeowPointExchangeRate` controls THB-LTT conversion.
- `MeowPointPurchaseOrder` stores THB-LTT payment values and credited Meow Points snapshot.

## 6. THB-LTT wallet prototype purchase flow

Intended flow:

1. User selects a Meow Points package.
2. Backend creates `MeowPointPurchaseOrder`.
3. Backend snapshots all payment context at creation time:
   - payment token: `THB-LTT`
   - blockchain: `LTT`
   - exchange rate
   - total Meow Points
   - payment amount
4. User pays with THB-LTT through existing wallet prototype payment flow.
5. Backend receives/validates payment confirmation.
6. Backend marks purchase order as `paid`.
7. Backend credits `MeowPointAccount`.
8. Backend writes `MeowPointTransaction` with `tx_type = purchase`.

Critical clarifications:

- Wallet prototype is only a payment mechanism.
- THB-LTT and Meow Points are different assets/domains.
- Meow Points are non-withdrawable.
- Meow Points are internal application credits.

## 7. Meow Points spending use cases

Primary and planned uses:

- Unlock short-drama episodes
- Exchange points for membership benefits
- Send live room gifts
- Future rewards/engagement systems:
  - daily check-in rewards
  - ad watch rewards
  - watch-time rewards
  - invite rewards

## 8. Proposed live gift models

### LiveGift

Suggested fields:

- `id`
- `name`
- `icon_url`
- `meow_points_price`
- `animation_type`
- `is_active`
- `sort_order`
- `created_at`, `updated_at`

### LiveGiftOrder

Suggested fields:

- `id`
- `order_no`
- `sender` (FK user)
- `receiver` / `stream_owner` (FK user)
- `stream` (FK live room/stream)
- `gift` (FK -> `LiveGift`)
- `quantity`
- `unit_points`
- `total_points`
- `status`
- `idempotency_key`
- `created_at`

Expected side effects for send gift flow:

1. Deduct Meow Points from sender account.
2. Write a debit `MeowPointTransaction`.
3. Create `LiveGiftOrder`.
4. Create/broadcast live chat message payload through Channels/WebSocket layer.

## 9. Implementation phases

### Phase 1

- `DramaSeries`
- `DramaEpisode`
- Read-only drama APIs
- Admin registration
- Seed/demo data support

### Phase 2

- `DramaWatchProgress`
- `DramaFavorite`
- Continue watching APIs
- Favorite/unfavorite APIs

### Phase 3

- `MeowPointAccount`
- `MeowPointTransaction`
- `MeowPointPackage`
- `MeowPointExchangeRate`
- Balance/package/transaction APIs

### Phase 4

- `MeowPointPurchaseOrder`
- THB-LTT wallet prototype payment integration
- Idempotent purchase order creation
- Payment confirmation
- Meow Points crediting

### Phase 5

- `DramaEpisodeUnlock`
- Membership exchange
- `LiveGift`
- `LiveGiftOrder`
- Meow Points spending APIs

## 10. Risks and decisions

Key risks and decisions to resolve early:

- Virtual credit regulatory/compliance requirements by jurisdiction
- App Store / Google Play in-app purchase policy review risk
- Refund policy and how refunded purchases reverse points/entitlements
- Double spending prevention on spend endpoints
- Transaction atomicity (`select_for_update`, DB transaction boundaries)
- Idempotency for order creation, unlock, gifting, and exchange flows
- Copyright/content licensing ownership for drama assets
- Content moderation process for uploaded/published episodes
- Data model decision: episode references existing `Video` vs standalone media fields
- HLS/CDN/object storage strategy and signed URL policy
- Payment failure, timeout, and expired order cleanup behavior

Recommended safest minimal approach for first backend implementation:

- Start with `DramaEpisode` storing its own media fields (`video_url`, `hls_url`, `duration_seconds`) to decouple short-drama delivery from existing video-domain assumptions.
- Reference existing `Video` only if integration is already simple and does not introduce coupling/refactor risk.

Tradeoff summary:

- **Standalone media fields first**: faster isolation, lower risk to existing code, but possible future duplication.
- **Reference existing Video immediately**: less duplication, but higher coupling and potential behavior conflicts with existing video workflows.
