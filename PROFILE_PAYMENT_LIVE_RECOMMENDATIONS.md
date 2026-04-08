# Profile & Payment Management Integration Recommendations (Backend-Focused)

## Scope
- Read first-pass contract/design docs:
  - `API_CONTRACT_SUMMARY.md`
  - `CONTENT_LAYER_NEXT_STEP.md`
- Reviewed backend implementation for profile, live, and payment flows in:
  - `backend/apps/accounts/views.py`
  - `backend/apps/accounts/serializers.py`
  - `backend/apps/accounts/models.py`
  - `backend/apps/accounts/live_urls.py`
  - `backend/apps/accounts/account_urls.py`

> Note: this repository snapshot does not include a frontend source tree, so “frontend usage” is inferred from API contract/docs and endpoint design.

---

## Key findings (focused on profile + payment management)

## 1) Profile API shape is too minimal for common frontend account pages
Current `GET /api/account/profile` returns display fields only (`display_name`, names, avatar, bio), while identity/role fields are on `/api/auth/me`.

**Integration impact**
- Frontend often needs to render account header + role gating in one fetch.
- Causes extra request orchestration (`/api/auth/me` + `/api/account/profile`).

**Suggestion**
- Add a lightweight unified account endpoint (or extend profile response) with read-only identity fields: `id`, `email`, `is_creator`.
- Keep profile-editable fields unchanged to avoid migration risk.

---

## 2) Profile update validation for avatar/bio is currently weak
`AccountProfileSerializer` relies mostly on model defaults for `avatar` and `bio` and does not enforce explicit constraints such as max file size, allowed mime/extensions, or bio length policy.

**Integration impact**
- Frontend may accept uploads that backend rejects late (or stores unexpectedly large files), leading to inconsistent UX.

**Suggestion**
- Add serializer-level validation (`validate_avatar`, `validate_bio`) and publish limits in contract docs.
- Return consistent, field-level validation errors so frontend can map directly to form hints.

---

## 3) Payment order creation lacks key consistency checks
`LivePaymentOrderCreateAPIView` + `PaymentOrderCreateSerializer` currently validate only that product orders include `product`.
Missing checks include:
- `payment_method` belongs to the same stream (`payment_method.stream_id == pk`)
- `payment_method.is_active == true`
- product-stream/store consistency rule (if required by product strategy)
- stream visibility/availability constraints for payer actions

**Integration impact**
- Frontend can submit technically valid payloads that are semantically wrong, then fail later in fulfillment/reconciliation.

**Suggestion**
- Add cross-entity validation in create serializer/view:
  - bind `stream` early
  - verify payment method ownership/activity
  - enforce product constraints explicitly by order type
- Return structured error codes (e.g., `payment_method_invalid_for_stream`, `product_not_sellable`).

---

## 4) Payment order creation has no idempotency protection
Repeated client retries (network retry, double-click) can create duplicate `pending` orders.

**Integration impact**
- Common mobile/web retry behavior can over-create orders and complicate finance ops.

**Suggestion**
- Support `Idempotency-Key` header (or deterministic `client_order_id`) for `POST /api/live/{id}/payments/orders/`.
- Persist request fingerprint + response snapshot for safe replay.

---

## 5) “Mark paid” is operationally useful but not auditable enough
`POST /mark-paid/` updates status and optionally emits payment chat message, but there is no explicit paid operator/timestamp/reference lifecycle beyond generic `updated_at`.

**Integration impact**
- Frontend admin dashboards and customer support views lack clear settlement provenance.

**Suggestion**
- Add optional fields to `PaymentOrder` lifecycle (e.g., `paid_at`, `paid_by`, `status_reason`).
- Keep endpoint additive and backward compatible.

---

## 6) Account payment history is unpaginated and filterless
`GET /api/account/payment-orders/` returns full list with `pagination_class = None` and no filters.

**Integration impact**
- As order volume grows, account page performance and mobile payload size degrade.

**Suggestion**
- Add pagination (`page`, `page_size`) and optional filters (`status`, `order_type`, `stream_id`, date range).
- Default sort is already suitable (`-created_at`, `-id`).

---

## 7) Public payment methods are readable but missing explicit client semantics
Public endpoint already trims fields, which is good. But method semantics are implicit (e.g., when to show `qr_text` vs `wallet_address`).

**Integration impact**
- Frontend has to hardcode display logic per `method_type`, which is brittle across clients.

**Suggestion**
- Add response hints such as `display_mode` / `cta_label` per `method_type`, or publish a strict enum-to-UI mapping in contract docs.

---

## 8) Live stream detail/status and payment panels still need capability-aware flags
The live review already identified `can_start/can_end` are state-based and not viewer-capability based.

**Integration impact**
- For profile/payment management surfaces embedded in live room UI, frontend can accidentally expose owner actions to non-owners unless it joins extra identity checks.

**Suggestion**
- Add viewer-aware booleans: `viewer_can_manage_stream`, `viewer_can_manage_payments`, `viewer_can_mark_paid`.

---

## Priority implementation order (smallest safe path)
1. **P0 Security/consistency**: payment order cross-entity validation + stream/payment method checks.
2. **P0 Reliability**: idempotency for order creation.
3. **P1 Frontend efficiency**: profile identity merge (or aggregate endpoint).
4. **P1 Scalability**: paginate/filter account payment orders.
5. **P2 Operations**: auditable payment settlement fields.
6. **P2 UX consistency**: capability-aware live/payment flags + payment method UI hints.

---

## Suggested contract additions (additive, non-breaking)
- `GET /api/account/profile` add: `id`, `email`, `is_creator` (read-only)
- `POST /api/live/{id}/payments/orders/`:
  - request header: `Idempotency-Key`
  - error code taxonomy for semantic validation
- `GET /api/account/payment-orders/`:
  - `page`, `page_size`, `status`, `order_type`, `stream_id`, `date_from`, `date_to`
- `PaymentOrder` response add (optional): `paid_at`, `paid_by`, `status_reason`
- Live status/detail add: `viewer_can_manage_payments`, `viewer_can_mark_paid`

