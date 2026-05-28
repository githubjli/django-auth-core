from django.core.management.base import BaseCommand
from apps.accounts.models import ProductOrder, ProductRefundRequest, SellerPayout


class Command(BaseCommand):
    help = 'Read-only check for asset consistency across product orders, payouts, and refunds.'

    def handle(self, *args, **options):
        inconsistencies = []

        orders = ProductOrder.objects.select_related('seller_payout').all()
        for order in orders:
            if order.payment_method != ProductOrder.PAYMENT_METHOD_PLATFORM_ASSET:
                continue
            if order.payment_asset not in {ProductOrder.ASSET_MEOW_POINTS, ProductOrder.ASSET_MEOW_CREDIT}:
                inconsistencies.append(
                    f'ORDER_ASSET_INVALID order_no={order.order_no} payment_asset={order.payment_asset!r}'
                )
                continue

            payout = getattr(order, 'seller_payout', None)
            if payout and payout.asset_type and payout.asset_type != order.payment_asset:
                inconsistencies.append(
                    f'PAYOUT_ASSET_MISMATCH order_no={order.order_no} order_asset={order.payment_asset} payout_asset={payout.asset_type}'
                )

            refunds = order.refund_requests.all()
            for refund in refunds:
                tx = refund.refunded_asset_transaction
                if tx and tx.asset_type != order.payment_asset:
                    inconsistencies.append(
                        f'REFUND_TX_ASSET_MISMATCH order_no={order.order_no} refund_id={refund.id} order_asset={order.payment_asset} tx_asset={tx.asset_type}'
                    )

        payout_orphans = SellerPayout.objects.select_related('product_order').exclude(product_order__isnull=True)
        for payout in payout_orphans:
            if payout.asset_type and payout.product_order.payment_asset and payout.asset_type != payout.product_order.payment_asset:
                inconsistencies.append(
                    f'PAYOUT_ORPHAN_MISMATCH payout_id={payout.id} order_no={payout.product_order.order_no} payout_asset={payout.asset_type} order_asset={payout.product_order.payment_asset}'
                )

        refunds = ProductRefundRequest.objects.select_related('product_order', 'refunded_asset_transaction').all()
        for refund in refunds:
            order = refund.product_order
            tx = refund.refunded_asset_transaction
            if order.payment_method != ProductOrder.PAYMENT_METHOD_PLATFORM_ASSET:
                continue
            if tx and tx.asset_type != order.payment_asset:
                inconsistencies.append(
                    f'REFUND_TX_ASSET_MISMATCH_GLOBAL order_no={order.order_no} refund_id={refund.id} order_asset={order.payment_asset} tx_asset={tx.asset_type}'
                )

        if inconsistencies:
            self.stdout.write(self.style.WARNING('Asset consistency check found issues:'))
            for line in inconsistencies:
                self.stdout.write(f'- {line}')
            self.stdout.write(self.style.ERROR(f'Total issues: {len(inconsistencies)}'))
        else:
            self.stdout.write(self.style.SUCCESS('Asset consistency check passed with 0 issues.'))
