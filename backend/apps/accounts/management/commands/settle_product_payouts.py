from django.core.management.base import BaseCommand, CommandError

from apps.accounts.services import LbryDaemonError, ProductPayoutService


class Command(BaseCommand):
    help = 'Auto-settle eligible pending seller payouts for completed product orders.'

    def handle(self, *args, **options):
        try:
            result = ProductPayoutService().settle_pending_payouts()
        except LbryDaemonError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                'Product payout settlement complete: '
                f"scanned_payouts={result['scanned_payouts']} "
                f"eligible_payouts={result['eligible_payouts']} "
                f"settled_payouts={result['settled_payouts']} "
                f"skipped_payouts={result['skipped_payouts']} "
                f"failed_payouts={result['failed_payouts']}"
            )
        )
