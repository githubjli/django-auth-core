# LBC Membership Phase 2B (Payment Detection + Activation)

This phase adds:

1. Transaction detection via `LbryDaemonClient.transaction_list` + `transaction_show`.
2. Output-level matching (`transaction_show.outputs`) against `PaymentOrder.pay_to_address`.
3. Receipt persistence in `ChainReceipt` / `OrderPayment`.
4. Membership activation/extension via `MembershipActivationService`.
5. Operational polling command: `python manage.py sync_lbc_membership_payments`.

## Matching source of truth

Payment matching is performed from transaction output details, not wallet summary totals.

Matching order:
1. output address equals order `pay_to_address`
2. output amount compared to `expected_amount_lbc`
3. confirmations compared to `LBC_MIN_CONFIRMATIONS`

## Deferred

Real-time listener/webhook infrastructure remains deferred; current mode is poll-by-command/service.
