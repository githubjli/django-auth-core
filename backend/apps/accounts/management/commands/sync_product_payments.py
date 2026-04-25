from django.core.management.base import BaseCommand, CommandError

from apps.accounts.services import LbryDaemonError, ProductPaymentDetectionService


class Command(BaseCommand):
    help = 'Sync product payment orders from chain transactions.'

    def handle(self, *args, **options):
        try:
            result = ProductPaymentDetectionService().sync_product_orders()
        except LbryDaemonError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                'Product payment sync complete: '
                f"scanned_orders={result['scanned_orders']} "
                f"matched_receipts={result['matched_receipts']} "
                f"paid_orders={result['paid_orders']} "
                f"underpaid_orders={result['underpaid_orders']} "
                f"overpaid_orders={result['overpaid_orders']}"
            )
        )
