from django.core.management.base import BaseCommand, CommandError

from apps.accounts.constants import TOKEN_NAME, TOKEN_SYMBOL
from apps.accounts.services import LbryDaemonError, PaymentDetectionService


class Command(BaseCommand):
    help = f'Sync {TOKEN_SYMBOL} ({TOKEN_NAME}) membership payments and activate memberships for paid orders.'

    def handle(self, *args, **options):
        service = PaymentDetectionService()
        try:
            result = service.sync_membership_orders()
        except LbryDaemonError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'{TOKEN_SYMBOL} membership sync complete: '
                f"orders={result['scanned_orders']} "
                f"receipts={result['matched_receipts']} "
                f"paid={result['paid_orders']} "
                f"activated={result['activated_memberships']}"
            )
        )
