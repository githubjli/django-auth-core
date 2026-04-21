# LBC Membership: Simplified Wallet-Linked Flow (Additive Redesign)

## 1) Exact proposed data model changes

### User wallet linkage (metadata only)
Additive fields on `User`:
- `linked_wallet_id` (nullable/blank string)
- `primary_user_address` (nullable/blank string)
- `wallet_link_status` (`linked` / `unlinked` / `pending`, nullable/blank)
- `linked_at` (nullable datetime)

### Membership orders
Reuse existing additive membership fields on `PaymentOrder`:
- `order_no`, `order_type`, `target_type`, `target_id`
- `expected_amount_lbc` (UI may display as LTT amount label)
- `pay_to_address` (platform receiving address)
- `status`, `expires_at`, `txid`, `actual_amount_lbc`, `confirmations`, `paid_at`

### Chain verification
Reuse `ChainReceipt` + `OrderPayment` + `UserMembership` with existing output-level persistence and order linkage.

## 2) Field-by-field rationale

- User linkage fields are metadata/context only; no wallet unlock password is stored.
- `linked_wallet_id` + `primary_user_address` help UX and optional tx lookup hints.
- `wallet_link_status` + `linked_at` help account state visibility/audit trails.
- Keep internal naming `*_lbc` for compatibility; UI can map token display label to LTT.
- `txid` on order remains a hint/index; final success still comes from backend chain verification.

## 3) Existing fields/models that remain unchanged

Kept as-is and still primary:
- `MembershipPlan`
- membership-related `PaymentOrder` extensions
- `ChainReceipt`
- `OrderPayment`
- `UserMembership`

## 4) Relaxed prior per-order-unique-address assumption

Previous assumption: one unique new platform receive address per order.

Now relaxed safely:
- If `LBRY_PLATFORM_RECEIVE_ADDRESS` is configured, order creation can reuse a stable platform receiving address.
- If not configured, existing per-order daemon `address_unused` behavior remains available.

Tradeoff:
- Shared address can make matching ambiguous; backend now prioritizes txid-hint matching when available.

## 5) Migration plan

1. Additive migration adding user wallet-link metadata fields to `User`.
2. No destructive schema changes.
3. Existing membership/order/receipt data remains valid.

## 6) Updated API shape proposal

Existing:
- `GET /api/membership/plans/`
- `POST /api/membership/orders/`
- `GET /api/membership/orders/{order_no}/`
- `GET /api/membership/me/`

Additive:
- `POST /api/membership/orders/{order_no}/tx-hint/`
  - request: `{ "txid": "..." }`
  - behavior: stores txid hint on order; does **not** mark order paid.

Wallet linkage:
- reuse account profile update fields (`linked_wallet_id`, `primary_user_address`, `wallet_link_status`).

## 7) Short developer note

- Platform wallet/address and user wallet/address are separate concerns.
- Backend never stores user unlock password.
- txid from frontend is only a hint; backend chain verification is authoritative.
- Payment validity requires backend verification that tx outputs include platform receive address, amount is sufficient, and confirmations meet threshold.

## Frontend prototype change

Frontend should stop calling remote wallet RPC directly from browser.

Use backend bridge endpoint instead:

- `POST /api/wallet-prototype/pay-order/`

Payload:

`{ "order_no": "...", "wallet_id": "...", "password": "..." }`

Backend performs unlock -> send -> lock server-side, returns txid hint, and frontend continues polling order status.
