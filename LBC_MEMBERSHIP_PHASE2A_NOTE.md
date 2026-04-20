# LBC Membership Phase 2A (Current Scope)

This phase intentionally implements only:

1. `lbry-sdk` daemon JSON-RPC client integration (`LbryDaemonClient`)
2. Membership order creation with backend-owned receiving address assignment
3. Membership APIs:
   - `GET /api/membership/plans/`
   - `POST /api/membership/orders/`
   - `GET /api/membership/orders/{order_no}/`
   - `GET /api/membership/me/`

## Not included in this phase

- Payment polling
- On-chain transaction matching/reconciliation
- Membership activation/extension on paid receipts

Those are deferred to the next phase.

## Environment-driven daemon configuration

Daemon/wallet behavior is configured by environment variables:

- `LBRY_DAEMON_URL`
- `LBRY_DAEMON_TIMEOUT`
- `LBRY_PLATFORM_WALLET_ID`
- `LBRY_PLATFORM_ACCOUNT_ID`
- `MEMBERSHIP_ORDER_EXPIRE_MINUTES`

No daemon URL/port is hardcoded in application logic.
