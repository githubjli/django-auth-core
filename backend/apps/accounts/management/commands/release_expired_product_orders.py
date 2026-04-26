from django.core.management.base import BaseCommand

from apps.accounts.services import ProductOrderService


class Command(BaseCommand):
    help = 'Release expired pending product orders and restore reserved stock.'

    def handle(self, *args, **options):
        result = ProductOrderService().release_expired_pending_orders()
        self.stdout.write(
            self.style.SUCCESS(
                'Expired product orders release complete: '
                f"scanned_orders={result['scanned_orders']} "
                f"released_orders={result['released_orders']} "
                f"restored_stock_quantity={result['restored_stock_quantity']}"
            )
        )
