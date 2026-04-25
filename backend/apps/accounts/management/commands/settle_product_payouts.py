from django.core.management.base import BaseCommand, CommandError

from apps.accounts.services import LbryDaemonError, ProductPayoutSettlementService


class Command(BaseCommand):
    help = 'Settle pending seller payouts for completed product orders.'

    def handle(self, *args, **options):
        try:
            result = ProductPayoutSettlementService().settle_pending_payouts()
        except LbryDaemonError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                'Product payout settlement complete: '
                f"processed={result['processed']} "
                f"settled={result['settled']} "
                f"skipped={result['skipped']}"
            )
        )
