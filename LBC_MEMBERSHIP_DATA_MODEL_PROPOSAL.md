# LBC Membership Data Model Proposal (Additive)

## A) Model definitions proposal

This proposal is implemented as additive models plus additive fields on existing `PaymentOrder`:

1. `MembershipPlan`
   - `code`: enum (`monthly`, `quarterly`, `yearly`), unique
   - `name`, `description`
   - `price_lbc` (decimal)
   - `duration_days` (int)
   - `is_active`, `sort_order`
   - `created_at`, `updated_at`

2. `WalletAddress`
   - `address` (unique)
   - `label`
   - `usage_type`: enum (`membership`, `tip`, `deposit`, `general`)
   - `status`: enum (`available`, `assigned`, `retired`)
   - `assigned_order` (nullable FK to `PaymentOrder`)
   - `assigned_at`
   - `created_at`, `updated_at`

3. `PaymentOrder` (existing model, additive fields)
   - Existing live/store order fields remain unchanged
   - Added membership-ready fields:
     - `order_no`
     - `order_type` extended with `membership`
     - `target_type`, `target_id`
     - `plan_code_snapshot`, `plan_name_snapshot`
     - `expected_amount_lbc`, `actual_amount_lbc`
     - `pay_to_address`
     - `wallet_address` (nullable FK to `WalletAddress`)
     - `status` extended with `expired`, `underpaid`, `overpaid`
     - `expires_at`, `paid_at`, `txid`, `confirmations`

4. `ChainReceipt`
   - `currency` (`LBC`)
   - `address`, `txid`, `vout`
   - `amount_lbc`, `block_height`, `confirmations`
   - `seen_at`, `confirmed_at`
   - `raw_payload` (JSON)
   - `matched_order` (nullable FK)
   - `match_status`: enum (`unmatched`, `matched`, `ignored`)
   - `created_at`, `updated_at`

5. `OrderPayment`
   - `order` FK
   - `receipt` FK
   - `txid`
   - `amount_lbc`
   - `confirmations`
   - `payment_status` (`pending`, `confirmed`, `failed`)
   - `matched_at`
   - `created_at`, `updated_at`

6. `UserMembership`
   - `user`
   - `source_order`
   - `plan`
   - `status`: enum (`active`, `expired`, `cancelled`)
   - `starts_at`, `ends_at`
   - `created_at`, `updated_at`

---

## B) Field rationale

- Snapshot fields on order (`plan_code_snapshot`, `plan_name_snapshot`, `expected_amount_lbc`) preserve billing truth even if plan data changes.
- `pay_to_address` + `wallet_address` allows both denormalized read speed and FK traceability.
- `target_type` + `target_id` supports generic commerce targets while keeping membership additive.
- `ChainReceipt` stores chain observations independently from matching logic/listener lifecycle.
- `OrderPayment` provides explicit many-receipt linkage for split/partial/duplicate chain events.
- `UserMembership` validity relies on `starts_at`/`ends_at`; no `is_subscriber` source-of-truth flag.

---

## C) Suggested indexes / unique constraints

- `MembershipPlan.code` unique.
- `WalletAddress.address` unique.
- `WalletAddress.assigned_order` unique when not null (enforces one order -> one receiving address).
- `PaymentOrder.order_no` unique when not empty.
- `ChainReceipt(currency, txid, vout)` unique.
- `OrderPayment(order, receipt)` unique.
- Indexes:
  - `ChainReceipt(address, seen_at)`
  - `ChainReceipt(match_status, seen_at)`
  - `OrderPayment(order, payment_status)`
  - `OrderPayment(txid)`
  - `UserMembership(user, status, ends_at)`
  - `UserMembership(starts_at, ends_at)`

---

## D) Admin registration proposal

Add admin entries for:
- `MembershipPlanAdmin`
- `WalletAddressAdmin`
- `ChainReceiptAdmin`
- `OrderPaymentAdmin`
- `UserMembershipAdmin`

Update `PaymentOrderAdmin` list/search/filter to include new membership and on-chain fields (`order_no`, `pay_to_address`, `txid`, snapshots, LBC amounts).

---

## E) Serializer/API shape proposal (no implementation yet)

### Suggested serializers

- `MembershipPlanSerializer`
  - read: `code`, `name`, `description`, `price_lbc`, `duration_days`, `is_active`

- `CreateMembershipOrderSerializer` (input)
  - `plan_code`

- `PaymentOrderMembershipSerializer` (output)
  - `order_no`, `status`, `plan_code_snapshot`, `plan_name_snapshot`, `expected_amount_lbc`, `actual_amount_lbc`, `pay_to_address`, `expires_at`, `paid_at`, `confirmations`, `txid`

- `UserMembershipSerializer`
  - `status`, `starts_at`, `ends_at`, `plan` (nested summary), `source_order_no`

### Suggested API contract

1. `GET /api/billing/membership/plans/`
   - response: active plans ordered by `sort_order`

2. `POST /api/billing/membership/orders/`
   - request: `{ "plan_code": "monthly" }`
   - response: created pending order with assigned `pay_to_address`, `order_no`, `expires_at`

3. `GET /api/billing/membership/orders/{order_no}/`
   - response: latest order payment status

4. `GET /api/billing/membership/me/`
   - response: current active membership + timeline

5. (future internal/admin) `POST /api/internal/chain/receipts/`
   - listener callback ingestion endpoint (deferred in this phase)

---

## F) Migration plan

1. Create schema migration for new models:
   - `MembershipPlan`, `WalletAddress`, `ChainReceipt`, `OrderPayment`, `UserMembership`
2. Create additive migration on existing `PaymentOrder` fields/choices/indexes.
3. Optional data migration:
   - seed plans: monthly / quarterly / yearly with agreed LBC pricing/durations.
4. No destructive changes, no existing API removal.

---

## G) Reuse for future LBC video unlock / tipping

- Keep creating `PaymentOrder` with different `order_type` and `target_type` (`video_unlock`, `tip`, etc.).
- Reuse `WalletAddress` pool assignment and lifecycle statuses.
- Reuse `ChainReceipt` + `OrderPayment` matching pipeline for all on-chain inflows.
- Add new entitlement tables analogous to `UserMembership` for content unlock windows.
